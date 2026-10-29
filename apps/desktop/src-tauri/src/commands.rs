use crate::{
    client,
    secrets::redact,
    types::{
        can_restart_worker, worker_is_outdated, AccountProfile, AppError, CliInstall, ErrorCode,
        FoundLogin, HubInfo, LoginResult, Settings, WorkerStatus,
    },
    url::{normalize_hub_url, validate_engines, validate_worker_id},
    wsl,
};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use tauri::{Emitter, Manager, State};
use tauri_plugin_autostart::ManagerExt as AutoStartExt;
use tauri_plugin_store::StoreExt;
use tokio::sync::Mutex;

pub struct AppState {
    pub settings: Mutex<Settings>,
    pub token: Mutex<Option<String>>,
    pub keepalive: Mutex<Option<wsl::Keepalive>>,
    pub latest_notification_target: Mutex<Option<String>>,
    pub auth_epoch: AtomicU64,
}

fn internal<E: std::fmt::Display>(error: E) -> AppError {
    AppError::new(ErrorCode::Internal, redact(&error.to_string()))
}

fn bundle_path(app: &tauri::AppHandle) -> Result<PathBuf, AppError> {
    let path = app
        .path()
        .resource_dir()
        .map_err(internal)?
        // tauri.conf.json bundles "resources/*", which keeps the folder: <install>\resources\<file>.
        // The file name is what scripts/build-worker-bundle.sh writes.
        .join("resources")
        .join("aihub-worker.tar.gz");
    if path.is_file() {
        Ok(path)
    } else {
        Err(AppError::new(
            ErrorCode::InstallFailed,
            "Worker bundle is missing",
        ))
    }
}

#[tauri::command]
pub async fn check_hub(url: String) -> Result<HubInfo, AppError> {
    client::check_hub(&url).await
}

#[tauri::command]
pub async fn login(
    url: String,
    user: String,
    password: String,
    state: State<'_, AppState>,
) -> Result<LoginResult, AppError> {
    let (result, token, device) = client::login(&url, &user, &password).await?;
    let normalized = normalize_hub_url(&url)?;
    if let Some(device) = device {
        keyring::Entry::new("aihub-desktop", &format!("user-refresh:{normalized}"))
            .map_err(internal)?
            .set_password(&device)
            .map_err(internal)?;
    }
    keyring::Entry::new("aihub-desktop", &format!("user-token:{normalized}"))
        .map_err(internal)?
        .set_password(&token)
        .map_err(internal)?;
    *state.token.lock().await = Some(token);
    state.auth_epoch.fetch_add(1, Ordering::Relaxed);
    Ok(result)
}

#[tauri::command]
pub async fn get_settings(state: State<'_, AppState>) -> Result<Settings, AppError> {
    Ok(state.settings.lock().await.clone().with_derived_unit())
}

#[tauri::command]
pub async fn save_settings(
    settings: Settings,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<Settings, AppError> {
    if let Some(id) = &settings.worker_id {
        if !validate_worker_id(id) {
            return Err(AppError::new(
                ErrorCode::InvalidWorkerId,
                "Worker id is invalid",
            ));
        }
    }
    validate_engines(&settings.engines)?;
    if settings.existing_worker {
        // Adopting the hand-installed worker is allowed only for the one really there, under its own id.
        let found = wsl::detect_existing(settings.distro.as_deref().unwrap_or_default());
        if found.as_ref().map(|worker| worker.worker_id.as_str()) != settings.worker_id.as_deref() {
            return Err(AppError::new(
                ErrorCode::InvalidWorkerId,
                "No such hand-installed worker on this machine",
            ));
        }
    }
    let settings = settings.with_derived_unit();
    let previous = state.settings.lock().await.clone();
    let store = app.store("settings.json").map_err(internal)?;
    store.set(
        "settings",
        serde_json::to_value(&settings).map_err(internal)?,
    );
    store.save().map_err(internal)?;
    if settings.setup_complete && !previous.setup_complete {
        app.autolaunch().enable().map_err(internal)?;
    }
    *state.settings.lock().await = settings.clone();
    if settings.setup_complete {
        if let Some(distro) = settings.distro.as_deref() {
            let mut keepalive = state.keepalive.lock().await;
            if keepalive.is_none() {
                *keepalive = Some(wsl::Keepalive::start(distro).map_err(internal)?);
            }
        }
    }
    Ok(settings)
}

#[tauri::command]
pub async fn check_machine() -> Result<wsl::MachineReport, AppError> {
    wsl::check_machine()
        .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))
}

#[tauri::command]
pub async fn register_worker(
    id: String,
    engines: Vec<String>,
    state: State<'_, AppState>,
) -> Result<(), AppError> {
    if !validate_worker_id(&id) {
        return Err(AppError::new(
            ErrorCode::InvalidWorkerId,
            "Worker id is invalid",
        ));
    }
    validate_engines(&engines)?;
    let settings = state.settings.lock().await.clone();
    let token = state
        .token
        .lock()
        .await
        .clone()
        .ok_or_else(|| AppError::new(ErrorCode::NotLoggedIn, "Log in first"))?;
    let worker_token = client::register_worker(
        settings.hub_url.as_deref().unwrap_or_default(),
        &token,
        &id,
        &engines,
    )
    .await?;
    wsl::write_worker_token(
        settings.distro.as_deref().unwrap_or_default(),
        &id,
        &worker_token,
    )
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))
}

#[tauri::command]
pub async fn install_worker(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<(), AppError> {
    let settings = state.settings.lock().await.clone();
    if settings.existing_worker {
        return Err(AppError::new(
            ErrorCode::InstallFailed,
            "This machine's worker was installed by hand; the app only watches it",
        ));
    }
    let bundle = bundle_path(&app)?;
    wsl::install_worker(
        settings.distro.as_deref().unwrap_or_default(),
        &bundle,
        settings.valid_worker_id()?,
        &settings.engines,
        settings.hub_url.as_deref().unwrap_or_default(),
    )
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))
}

#[tauri::command]
pub async fn reinstall_worker(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<(), AppError> {
    install_worker(app, state).await
}

/// The worker installed by hand on this machine (unit `aihub-worker`), if any: the wizard offers to adopt it
/// instead of registering a second worker.
#[tauri::command]
pub async fn detect_existing_worker(
    distro: String,
) -> Result<Option<wsl::ExistingWorker>, AppError> {
    Ok(wsl::detect_existing(&distro))
}

#[tauri::command]
pub async fn worker_status(state: State<'_, AppState>) -> Result<WorkerStatus, AppError> {
    current_worker_status(&state).await
}

/// Renew the hour-long access token from the stored device sign-in. False = sign in again.
async fn renew_sign_in(state: &AppState) -> bool {
    let hub_url = state.settings.lock().await.hub_url.clone();
    let Some(Ok(normalized)) = hub_url.as_deref().map(normalize_hub_url) else {
        return false;
    };
    let Ok(entry) = keyring::Entry::new("aihub-desktop", &format!("user-refresh:{normalized}"))
    else {
        return false;
    };
    let Ok(device) = entry.get_password() else {
        return false;
    };
    let Ok((token, rotated)) = client::refresh(&normalized, &device).await else {
        return false;
    };
    if let Some(rotated) = rotated {
        let _ = entry.set_password(&rotated);
    }
    if let Ok(saved) = keyring::Entry::new("aihub-desktop", &format!("user-token:{normalized}")) {
        let _ = saved.set_password(&token);
    }
    *state.token.lock().await = Some(token);
    true
}

pub async fn current_worker_status(state: &AppState) -> Result<WorkerStatus, AppError> {
    let settings = state.settings.lock().await.clone();
    let hub = settings.hub_url.as_deref().unwrap_or_default();
    let token = state.token.lock().await.clone();
    let mut answer =
        client::worker_status(hub, token.as_deref(), settings.worker_id.as_deref()).await;
    if matches!(&answer, Err(error) if error.code == ErrorCode::Unauthorized)
        && renew_sign_in(state).await
    {
        let token = state.token.lock().await.clone();
        answer = client::worker_status(hub, token.as_deref(), settings.worker_id.as_deref()).await;
    }
    let (hub_reachable, worker_state, pending_approvals, worker_version, active_agents) = answer?;
    let unit = settings
        .unit()
        .ok()
        .and_then(|unit| {
            wsl::unit_status(settings.distro.as_deref().unwrap_or_default(), &unit).ok()
        })
        .unwrap_or_else(|| "unknown".into());
    let outdated = worker_is_outdated(env!("CARGO_PKG_VERSION"), worker_version.as_deref());
    let warning = if outdated && settings.existing_worker {
        Some("Подключённый вручную воркер устарел. Обновите его вручную: установите свежий bundle и перезапустите службу aihub-worker.".into())
    } else if outdated {
        Some("Воркер будет обновлён вместе с приложением при следующем обновлении.".into())
    } else if hub_reachable && worker_state != "online" {
        hub_reach_warning(&settings)
    } else {
        None
    };
    Ok(WorkerStatus {
        unit,
        hub: settings.hub_url.unwrap_or_default(),
        hub_reachable,
        worker_id: settings.worker_id,
        worker_state,
        pending_approvals,
        active_agents,
        worker_version,
        worker_outdated: outdated,
        warning,
    })
}

/// The hub answers Windows but shows this worker offline: look from inside WSL (DNS, then TCP).
fn hub_reach_warning(settings: &crate::types::Settings) -> Option<String> {
    let url = reqwest::Url::parse(settings.hub_url.as_deref()?).ok()?;
    let host = url.host_str()?.to_owned();
    let port = url.port_or_known_default()?;
    let output = wsl::hub_reach(settings.distro.as_deref()?, &host, port).ok()?;
    wsl::diagnose_hub_reach(&output, &host)
}

#[tauri::command]
pub async fn worker_logs(
    lines: Option<u32>,
    state: State<'_, AppState>,
) -> Result<String, AppError> {
    let settings = state.settings.lock().await.clone();
    wsl::logs(
        settings.distro.as_deref().unwrap_or_default(),
        &settings.unit()?,
        lines.unwrap_or(200).min(1000) as usize,
    )
    .map(|value| redact(&value))
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))
}

#[tauri::command]
pub async fn restart_worker(consent: bool, state: State<'_, AppState>) -> Result<(), AppError> {
    let settings = state.settings.lock().await.clone();
    let status = current_worker_status(&state).await?;
    if !can_restart_worker(status.active_agents, consent) {
        return Err(AppError::new(
            ErrorCode::InstallFailed,
            "Agents are active; explicit restart consent is required",
        ));
    }
    wsl::restart(
        settings.distro.as_deref().unwrap_or_default(),
        &settings.unit()?,
    )
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))
}

#[tauri::command]
pub async fn disconnect_machine(
    delete_from_hub: bool,
    state: State<'_, AppState>,
) -> Result<(), AppError> {
    let settings = state.settings.lock().await.clone();
    if settings.existing_worker {
        // The app only watched it: forgetting it here leaves the service and its hub record as they are.
        return Ok(());
    }
    wsl::stop_disable(
        settings.distro.as_deref().unwrap_or_default(),
        &settings.unit()?,
    )
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))?;
    if delete_from_hub {
        let token = state
            .token
            .lock()
            .await
            .clone()
            .ok_or_else(|| AppError::new(ErrorCode::NotLoggedIn, "Log in first"))?;
        client::delete_worker(
            settings.hub_url.as_deref().unwrap_or_default(),
            &token,
            settings.worker_id.as_deref().unwrap_or_default(),
        )
        .await?;
    }
    Ok(())
}

#[tauri::command]
pub async fn fix_wslconfig() -> Result<String, AppError> {
    let profile = std::env::var_os("USERPROFILE")
        .ok_or_else(|| AppError::new(ErrorCode::Io, "USERPROFILE is not available"))?;
    let (backup, changed) =
        wsl::wslconfig::patch_file(PathBuf::from(profile).join(".wslconfig"))
            .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))?;
    Ok(if changed {
        format!("Updated .wslconfig; backup created at {}", backup.display())
    } else {
        "WSL idle timeouts are already configured".into()
    })
}

#[tauri::command]
pub async fn set_autostart(on: bool, app: tauri::AppHandle) -> Result<(), AppError> {
    if on {
        app.autolaunch().enable().map_err(internal)
    } else {
        app.autolaunch().disable().map_err(internal)
    }
}

/// Download and install the signed desktop update. Restarting is refused while agents are active
/// unless the UI has shown the user the explicit consent prompt.
/// The app's own settings window (machine connection, setup) — opened from the panel's settings.
#[tauri::command]
pub fn open_app_settings(app: tauri::AppHandle) -> Result<(), AppError> {
    crate::app::open_settings(&app)
        .map(|_| ())
        .map_err(|e| AppError::new(ErrorCode::Internal, e))
}

#[tauri::command]
pub async fn check_update(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<crate::types::UpdateCheck, AppError> {
    let hub_url = state.settings.lock().await.hub_url.clone();
    let updater = crate::app::hub_updater(&app, hub_url.as_deref())
        .map_err(|e| AppError::new(ErrorCode::Network, &e))?;
    let update = updater
        .check()
        .await
        .map_err(|e| AppError::new(ErrorCode::Network, &e.to_string()))?;
    if let Some(update) = &update {
        let _ = app.emit("update-available", update.version.clone());
    }
    Ok(crate::types::UpdateCheck {
        current: app.package_info().version.to_string(),
        available: update.map(|update| update.version),
    })
}

#[tauri::command]
pub async fn update_app(
    consent: bool,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<(), AppError> {
    // The owner confirmed the update; an expired sign-in or an unreachable hub must not block it (the
    // app restart does not stop the worker's agents). Known active agents still need explicit consent.
    let active_agents = current_worker_status(&state)
        .await
        .map(|status| status.active_agents)
        .unwrap_or(0);
    if !can_restart_worker(active_agents, consent) {
        return Err(AppError::new(
            ErrorCode::InstallFailed,
            "Agents are active; explicit update consent is required",
        ));
    }
    let hub_url = state.settings.lock().await.hub_url.clone();
    let updater = crate::app::hub_updater(&app, hub_url.as_deref()).map_err(internal)?;
    let Some(update) = updater.check().await.map_err(internal)? else {
        return Ok(());
    };
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(internal)?;
    app.restart();
}

#[tauri::command]
pub async fn open_panel(
    path: Option<String>,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<(), AppError> {
    let settings = state.settings.lock().await.clone();
    crate::app::show_panel(
        &app,
        settings.hub_url.as_deref().unwrap_or_default(),
        path.as_deref(),
    )
    .map_err(internal)
}

fn account_id(id: &str) -> Result<&str, AppError> {
    if !validate_worker_id(id) {
        return Err(AppError::new(
            ErrorCode::InvalidWorkerId,
            "Account id is invalid",
        ));
    }
    Ok(id)
}
fn auth_context(
    state: &AppState,
) -> impl std::future::Future<Output = Result<(Settings, String), AppError>> + '_ {
    async move {
        let settings = state.settings.lock().await.clone();
        let token = state
            .token
            .lock()
            .await
            .clone()
            .ok_or_else(|| AppError::new(ErrorCode::NotLoggedIn, "Log in first"))?;
        Ok((settings, token))
    }
}

#[tauri::command]
pub async fn found_logins(state: State<'_, AppState>) -> Result<Vec<FoundLogin>, AppError> {
    let (settings, token) = auth_context(state.inner()).await?;
    client::found_logins(settings.hub_url.as_deref().unwrap_or_default(), &token).await
}
#[tauri::command]
pub async fn accounts(state: State<'_, AppState>) -> Result<Vec<AccountProfile>, AppError> {
    let (settings, token) = auth_context(state.inner()).await?;
    client::accounts(
        settings.hub_url.as_deref().unwrap_or_default(),
        &token,
        settings.worker_id.as_deref().unwrap_or_default(),
    )
    .await
}
#[tauri::command]
pub async fn create_subscription(
    engine: String,
    adopt_found_login: bool,
    state: State<'_, AppState>,
) -> Result<AccountProfile, AppError> {
    let (settings, token) = auth_context(state.inner()).await?;
    client::create_subscription(
        settings.hub_url.as_deref().unwrap_or_default(),
        &token,
        settings.worker_id.as_deref().unwrap_or_default(),
        &engine,
        adopt_found_login,
    )
    .await
}
#[tauri::command]
pub async fn login_account(id: String, state: State<'_, AppState>) -> Result<(), AppError> {
    let id = account_id(&id)?;
    let (settings, token) = auth_context(state.inner()).await?;
    let shell =
        client::login_command(settings.hub_url.as_deref().unwrap_or_default(), &token, id).await?;
    wsl::open_login(settings.distro.as_deref().unwrap_or_default(), &shell)
        .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))?;
    client::login_started(settings.hub_url.as_deref().unwrap_or_default(), &token, id).await
}
#[tauri::command]
pub async fn cli_install_command(
    engine: String,
    state: State<'_, AppState>,
) -> Result<CliInstall, AppError> {
    if !matches!(engine.as_str(), "claude" | "codex" | "node") {
        return Err(AppError::new(ErrorCode::InvalidEngine, "Invalid CLI"));
    }
    let settings = state.settings.lock().await.clone();
    let command = wsl::cli_install(
        settings.distro.as_deref().unwrap_or_default(),
        &engine,
        true,
    )
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))?;
    Ok(CliInstall {
        engine,
        command: command.trim().to_owned(),
        installed: false,
    })
}
#[tauri::command]
pub async fn install_cli(
    engine: String,
    state: State<'_, AppState>,
) -> Result<CliInstall, AppError> {
    if !matches!(engine.as_str(), "claude" | "codex" | "node") {
        return Err(AppError::new(ErrorCode::InvalidEngine, "Invalid CLI"));
    }
    let settings = state.settings.lock().await.clone();
    let command = wsl::cli_install(
        settings.distro.as_deref().unwrap_or_default(),
        &engine,
        false,
    )
    .map_err(|error| AppError::new(error_code(&error), redact(&error.to_string())))?;
    Ok(CliInstall {
        engine,
        command: command.trim().to_owned(),
        installed: true,
    })
}

fn error_code(error: &wsl::WslError) -> ErrorCode {
    match error.code() {
        "invalid_worker_id" => ErrorCode::InvalidWorkerId,
        "invalid_engine" => ErrorCode::InvalidEngine,
        "invalid_url" => ErrorCode::InvalidUrl,
        "insecure_url" => ErrorCode::InsecureUrl,
        "wsl_missing" => ErrorCode::WslMissing,
        "distro_missing" => ErrorCode::DistroMissing,
        "systemd_off" => ErrorCode::SystemdOff,
        "python_old" => ErrorCode::PythonOld,
        "git_missing" => ErrorCode::GitMissing,
        "install_failed" => ErrorCode::InstallFailed,
        "timeout" => ErrorCode::Timeout,
        "io" => ErrorCode::Io,
        _ => ErrorCode::Internal,
    }
}
