use crate::commands::AppState;
use std::{
    collections::HashSet,
    sync::atomic::{AtomicU64, Ordering},
};
use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem},
    Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_autostart::ManagerExt as AutoStartExt;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_store::StoreExt;
use tauri_plugin_updater::UpdaterExt;
use tokio::sync::Mutex;

static AUTOSTART_ENABLED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
static GEOMETRY_REVISION: AtomicU64 = AtomicU64::new(0);

pub fn show_panel(app: &tauri::AppHandle, base: &str, path: Option<&str>) -> Result<(), String> {
    let url = format!("{}{}", base.trim_end_matches('/'), path.unwrap_or("/"));
    let parsed = url.parse().map_err(|_| "invalid panel URL")?;
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|e| e.to_string())?;
        let _ = window.unminimize();
        window.set_focus().map_err(|e| e.to_string())?;
        window.navigate(parsed).map_err(|e| e.to_string())?;
        return Ok(());
    }
    let hub = base.to_owned();
    let new_window_hub = hub.clone();
    let opener = app.clone();
    let new_window_opener = app.clone();
    let builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(parsed))
        .title("AI Development Hub")
        .inner_size(1280.0, 820.0)
        .min_inner_size(640.0, 400.0)
        // The panel's topbar is the title bar (drag region, window buttons); Windows keeps the resize
        // borders, the shadow, Aero Snap and the system shortcuts of the undecorated window.
        .decorations(!cfg!(windows))
        .visible(false)
        .on_navigation(move |candidate| {
            if crate::url::is_allowed_navigation(&hub, candidate) {
                true
            } else {
                let _ = opener.opener().open_url(candidate.as_str(), None::<&str>);
                false
            }
        })
        .on_new_window(move |candidate, _features| {
            if crate::url::is_allowed_navigation(&new_window_hub, &candidate) {
                tauri::webview::NewWindowResponse::Allow
            } else {
                let _ = new_window_opener
                    .opener()
                    .open_url(candidate.as_str(), None::<&str>);
                tauri::webview::NewWindowResponse::Deny
            }
        });
    let builder = restore_geometry(app, builder);
    grant_panel_bridge(app, base);
    builder.build().map_err(|e| e.to_string()).map(|window| {
        let _ = window.show();
    })
}

static PANEL_BRIDGE: std::sync::Once = std::sync::Once::new();

/// The panel's settings page shows the app's settings (version, updates, worker, autostart): it may call
/// the app's commands, but only from the hub this app is connected to and only in the panel window.
fn grant_panel_bridge(app: &tauri::AppHandle, base: &str) {
    let origin = base.trim_end_matches('/').to_owned();
    PANEL_BRIDGE.call_once(|| {
        let capability = [
            "core:event:default",
            "allow-get-settings",
            "allow-worker-status",
            "allow-check-update",
            "allow-update-app",
            "allow-set-autostart",
            "allow-restart-worker",
            "allow-worker-logs",
            "allow-login",
            "allow-open-app-settings",
            // The topbar as title bar: drag, double click, window buttons.
            "core:window:allow-start-dragging",
            "core:window:allow-internal-toggle-maximize",
            "core:window:allow-minimize",
            "core:window:allow-toggle-maximize",
            "core:window:allow-close",
            "core:window:allow-is-maximized",
            "core:window:allow-is-decorated",
        ]
        .into_iter()
        .fold(
            tauri::ipc::CapabilityBuilder::new("hub-panel")
                .remote(format!("{origin}/*"))
                .window("main"),
            |capability, permission| capability.permission(permission),
        );
        if let Err(error) = app.add_capability(capability) {
            eprintln!("panel bridge not granted: {error}");
        }
    });
}

fn restore_geometry<'a, R: tauri::Runtime>(
    app: &'a tauri::AppHandle<R>,
    builder: WebviewWindowBuilder<'a, R, tauri::AppHandle<R>>,
) -> WebviewWindowBuilder<'a, R, tauri::AppHandle<R>> {
    let Ok(store) = app.store("settings.json") else {
        return builder;
    };
    let Some(value) = store.get("main_geometry") else {
        return builder;
    };
    let (Some(width), Some(height)) = (
        value.get("width").and_then(|v| v.as_u64()),
        value.get("height").and_then(|v| v.as_u64()),
    ) else {
        return builder;
    };
    if width < 640 || height < 400 {
        return builder;
    }
    let builder = builder.inner_size(width as f64, height as f64);
    if let (Some(x), Some(y)) = (
        value.get("x").and_then(|v| v.as_i64()),
        value.get("y").and_then(|v| v.as_i64()),
    ) {
        if x <= -10_000 || y <= -10_000 {
            return builder;
        }
        builder.position(x as f64, y as f64)
    } else {
        builder
    }
}

fn persist_geometry<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    if window.is_minimized().unwrap_or(false) {
        return;
    }
    let (Ok(position), Ok(size)) = (window.outer_position(), window.inner_size()) else {
        return;
    };
    let Ok(store) = app.store("settings.json") else {
        return;
    };
    store.set("main_geometry", serde_json::json!({"x": position.x, "y": position.y, "width": size.width, "height": size.height}));
    let _ = store.save();
}

fn debounce_geometry<R: tauri::Runtime>(app: tauri::AppHandle<R>) {
    let revision = GEOMETRY_REVISION.fetch_add(1, Ordering::Relaxed) + 1;
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        if GEOMETRY_REVISION.load(Ordering::Relaxed) == revision {
            persist_geometry(&app);
        }
    });
}

pub fn open_settings(app: &tauri::AppHandle) -> Result<tauri::WebviewWindow, String> {
    if let Some(window) = app.get_webview_window("settings") {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        return Ok(window);
    }
    WebviewWindowBuilder::new(app, "settings", WebviewUrl::App("index.html".into()))
        .title("AI Development Hub — Settings")
        .inner_size(980.0, 760.0)
        .build()
        .map_err(|e| e.to_string())
}

/// Settings live in the panel; before setup (no hub yet) the app's own window is used.
fn open_panel_settings(app: &tauri::AppHandle, query: &str) {
    let settings = app.state::<AppState>().settings.blocking_lock().clone();
    match settings.hub_url.as_deref() {
        Some(hub) if settings.setup_complete => {
            let _ = show_panel(app, hub, Some(&format!("/settings{query}")));
        }
        _ => {
            let _ = open_settings(app);
        }
    }
}

fn open_latest_target(app: &tauri::AppHandle) {
    let state = app.state::<AppState>();
    let settings = state.settings.blocking_lock().clone();
    let target = state.latest_notification_target.blocking_lock().clone();
    if let Some(hub) = settings.hub_url.as_deref() {
        let _ = show_panel(app, hub, target.as_deref());
    }
}

pub fn run() {
    let state = AppState {
        settings: Mutex::new(crate::types::Settings::default()),
        token: Mutex::new(None),
        keepalive: Mutex::new(None),
        latest_notification_target: Mutex::new(None),
        auth_epoch: std::sync::atomic::AtomicU64::new(0),
    };
    let builder = tauri::Builder::default()
        .manage(state)
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            open_latest_target(app);
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .on_window_event(|window, event| match event {
            WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let _ = window.hide();
            }
            WindowEvent::Moved(_) | WindowEvent::Resized(_) if window.label() == "main" => {
                debounce_geometry(window.app_handle().clone())
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            crate::commands::check_hub,
            crate::commands::login,
            crate::commands::check_machine,
            crate::commands::detect_existing_worker,
            crate::commands::register_worker,
            crate::commands::install_worker,
            crate::commands::reinstall_worker,
            crate::commands::worker_status,
            crate::commands::worker_logs,
            crate::commands::restart_worker,
            crate::commands::set_autostart,
            crate::commands::update_app,
            crate::commands::check_update,
            crate::commands::open_app_settings,
            crate::commands::get_settings,
            crate::commands::save_settings,
            crate::commands::fix_wslconfig,
            crate::commands::disconnect_machine,
            crate::commands::open_panel,
            crate::commands::found_logins,
            crate::commands::accounts,
            crate::commands::create_subscription,
            crate::commands::login_account,
            crate::commands::cli_install_command,
            crate::commands::install_cli
        ]);
    builder
        .setup(|app| {
            load_settings(app);
            let notification_app = app.handle().clone();
            app.notification()
                .on_action(move |_| open_latest_target(&notification_app))
                .map_err(|e| e.to_string())?;
            let open = MenuItem::with_id(app, "open", "Open panel", true, None::<&str>)?;
            let status = MenuItem::with_id(app, "status", "Worker status", true, None::<&str>)?;
            let logs =
                MenuItem::with_id(app, "logs", "Worker log (200 lines)", true, None::<&str>)?;
            let autostart = CheckMenuItem::with_id(
                app,
                "autostart",
                "Launch at login",
                true,
                false,
                None::<&str>,
            )?;
            let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
            let check_updates = MenuItem::with_id(
                app,
                "check_updates",
                "Check for updates",
                true,
                None::<&str>,
            )?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let autostart_enabled = app.autolaunch().is_enabled().unwrap_or(false);
            AUTOSTART_ENABLED.store(autostart_enabled, Ordering::Relaxed);
            let _ = autostart.set_checked(autostart_enabled);
            let autostart_item = autostart.clone();
            let menu = Menu::with_items(
                app,
                &[
                    &open,
                    &status,
                    &logs,
                    &autostart,
                    &settings,
                    &check_updates,
                    &quit,
                ],
            )?;
            // Double click opens the panel full screen; the menu is on the right button.
            let mut tray = tauri::tray::TrayIconBuilder::with_id("main")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::DoubleClick {
                        button: tauri::tray::MouseButton::Left,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        open_latest_target(app);
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.maximize();
                        }
                    }
                });
            if let Some(icon) = tray_frame(None) {
                tray = tray.icon(icon);
            }
            tray.tooltip("AI Development Hub")
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "open" => open_latest_target(app),
                    "settings" => open_panel_settings(app, ""),
                    "check_updates" => open_panel_settings(app, "?check=1"),
                    "status" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn(async move {
                            let state = app.state::<AppState>();
                            if let Ok(status) = crate::commands::current_worker_status(&state).await
                            {
                                let mut body = format!(
                                    "Worker: {}; hub: {}; pending approvals: {}",
                                    status.worker_state,
                                    status.hub_reachable,
                                    status.pending_approvals
                                );
                                if let Some(warning) = &status.warning {
                                    body = format!(
                                        "{body}
{warning}"
                                    );
                                }
                                let _ = app
                                    .notification()
                                    .builder()
                                    .title("Worker status")
                                    .body(body)
                                    .show();
                            }
                        });
                    }
                    "logs" => {
                        if open_settings(app).is_ok() {
                            let app = app.clone();
                            tauri::async_runtime::spawn(async move {
                                let state = app.state::<AppState>();
                                if let Ok(logs) =
                                    crate::commands::worker_logs(Some(200), state).await
                                {
                                    let _ = app.emit("show-logs", logs);
                                }
                            });
                        }
                    }
                    "autostart" => {
                        let enabled = !AUTOSTART_ENABLED.load(Ordering::Relaxed);
                        let result = if enabled {
                            app.autolaunch().enable()
                        } else {
                            app.autolaunch().disable()
                        };
                        if result.is_ok() {
                            AUTOSTART_ENABLED.store(enabled, Ordering::Relaxed);
                            let _ = autostart_item.set_checked(enabled);
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            spawn_tray_animation(app.handle().clone());
            let settings = app.state::<AppState>().settings.blocking_lock().clone();
            if settings.setup_complete {
                start_keepalive(app, settings.distro.as_deref())?;
            } else {
                let _ = open_settings(app.handle());
            }
            start_background_loops(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AI Development Hub desktop")
        .run(|app, event| {
            if matches!(event, RunEvent::Exit) {
                let _ = app.state::<AppState>().keepalive.blocking_lock().take();
            }
        });
}

fn load_settings(app: &tauri::App) {
    if let Ok(store) = app.store("settings.json") {
        if let Some(value) = store.get("settings") {
            if let Ok(settings) = serde_json::from_value::<crate::types::Settings>(value) {
                if let Some(url) = settings.hub_url.as_deref() {
                    if let Ok(normalized) = crate::url::normalize_hub_url(url) {
                        if let Ok(entry) = keyring::Entry::new(
                            "aihub-desktop",
                            &format!("user-token:{normalized}"),
                        ) {
                            if let Ok(token) = entry.get_password() {
                                *app.state::<AppState>().token.blocking_lock() = Some(token);
                            }
                        }
                    }
                }
                *app.state::<AppState>().settings.blocking_lock() = settings.with_derived_unit();
            }
        }
    }
}

fn start_keepalive(app: &tauri::App, distro: Option<&str>) -> Result<(), String> {
    let Some(distro) = distro else {
        return Ok(());
    };
    let state = app.state::<AppState>();
    let mut keepalive = state.keepalive.blocking_lock();
    if keepalive.is_none() {
        *keepalive = Some(crate::wsl::Keepalive::start(distro).map_err(|e| e.to_string())?);
    }
    Ok(())
}

fn start_background_loops(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut seen_notifications = HashSet::new();
        let mut sent_relogin = false;
        let mut seen_auth_epoch = 0;
        let mut last_warning: Option<String> = None;
        let mut worker_update_attempted = false;
        let mut last_update_check: Option<std::time::Instant> = None;
        loop {
            let state = app.state::<AppState>();
            let settings = state.settings.lock().await.clone();
            let token = state.token.lock().await.clone();
            let auth_epoch = state.auth_epoch.load(Ordering::Relaxed);
            if auth_epoch != seen_auth_epoch {
                sent_relogin = false;
                seen_auth_epoch = auth_epoch;
            }
            if settings.setup_complete {
                if last_update_check
                    .is_none_or(|t| t.elapsed() >= std::time::Duration::from_secs(86400))
                {
                    last_update_check = Some(std::time::Instant::now());
                    check_for_update(&app).await;
                }
                if let Ok(status) = crate::commands::current_worker_status(&state).await {
                    if status.worker_outdated
                        && !settings.existing_worker
                        && status.active_agents == 0
                        && !worker_update_attempted
                    {
                        worker_update_attempted = true;
                        // The new app resources are available after an app update. Install the
                        // matching managed worker once on the next launch; adopted workers are
                        // deliberately excluded.
                        let _ = crate::commands::install_worker(app.clone(), state.clone()).await;
                    }
                    let _ = app.emit("worker-status", &status);
                    TRAY_BUSY.store(status.active_agents > 0, Ordering::Relaxed);
                    if let Some(tray) = app.tray_by_id("main") {
                        let tooltip = status.warning.as_deref().unwrap_or("AI Development Hub");
                        let _ = tray.set_tooltip(Some(tooltip));
                    }
                    // Say why the worker is offline once, when the reason appears or changes.
                    if status.warning != last_warning {
                        if let Some(warning) = &status.warning {
                            let _ = app
                                .notification()
                                .builder()
                                .title("Worker is offline")
                                .body(warning)
                                .show();
                        }
                        last_warning = status.warning.clone();
                    }
                }
                if let (Some(url), Some(token)) = (settings.hub_url.as_deref(), token.as_deref()) {
                    match crate::client::notifications(url, token).await {
                        Ok(items) => {
                            for item in items {
                                if !seen_notifications.insert(item.id.clone()) {
                                    continue;
                                }
                                if let Some(session_id) = item.session_id.as_deref() {
                                    *state.latest_notification_target.lock().await =
                                        Some(format!("/sessions/{session_id}"));
                                }
                                let title = item.title.as_deref().unwrap_or("AI Development Hub");
                                let body =
                                    item.message.as_deref().unwrap_or("New hub notification");
                                let _ = app.notification().builder().title(title).body(body).show();
                            }
                            sent_relogin = false;
                        }
                        Err(error)
                            if error.code == crate::types::ErrorCode::Unauthorized
                                && !sent_relogin =>
                        {
                            sent_relogin = true;
                            let _ = app
                                .notification()
                                .builder()
                                .title("AI Development Hub")
                                .body("Sign in again")
                                .show();
                        }
                        Err(_) => {}
                    }
                }
            }
            tokio::time::sleep(std::time::Duration::from_secs(30)).await;
        }
    });
}

/// Agents are working: the tray mark animates (the yellow node walks the graph); otherwise it is still.
static TRAY_BUSY: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// The site's Nodes mark: `None` at rest, `Some(n)` the n-th busy frame (icons/tray-*.svg).
fn tray_frame(frame: Option<usize>) -> Option<tauri::image::Image<'static>> {
    let bytes: &'static [u8] = match frame {
        None => include_bytes!("../icons/tray-idle@2x.png"),
        Some(n) => match n % 4 {
            0 => include_bytes!("../icons/tray-busy-0@2x.png"),
            1 => include_bytes!("../icons/tray-busy-1@2x.png"),
            2 => include_bytes!("../icons/tray-busy-2@2x.png"),
            _ => include_bytes!("../icons/tray-busy-3@2x.png"),
        },
    };
    tauri::image::Image::from_bytes(bytes).ok()
}

/// Steps the tray animation while agents work and puts the still mark back when they stop.
fn spawn_tray_animation(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut frame = 0usize;
        let mut was_busy = false;
        loop {
            let busy = TRAY_BUSY.load(Ordering::Relaxed);
            if busy || was_busy {
                if let Some(tray) = app.tray_by_id("main") {
                    let _ = tray.set_icon(tray_frame(busy.then_some(frame)));
                }
                frame = frame.wrapping_add(1);
            }
            was_busy = busy;
            tokio::time::sleep(std::time::Duration::from_millis(400)).await;
        }
    });
}

/// Updates come from the hub the app is connected to (`<hub>/desktop/latest.json`), not a fixed address.
pub fn hub_updater(
    app: &tauri::AppHandle,
    hub_url: Option<&str>,
) -> Result<tauri_plugin_updater::Updater, String> {
    let hub =
        crate::url::normalize_hub_url(hub_url.unwrap_or_default()).map_err(|e| e.to_string())?;
    let endpoint = format!("{hub}/desktop/latest.json")
        .parse()
        .map_err(|e: url::ParseError| e.to_string())?;
    app.updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())
}

/// Ask the hub for a newer version and say so in a notification (and to an open settings window).
async fn check_for_update(app: &tauri::AppHandle) {
    let hub_url = app
        .state::<AppState>()
        .settings
        .lock()
        .await
        .hub_url
        .clone();
    let result = match hub_updater(app, hub_url.as_deref()) {
        Ok(updater) => updater.check().await.map_err(|e| e.to_string()),
        Err(error) => Err(error),
    };
    let body = match result {
        Ok(Some(update)) => {
            let _ = app.emit("update-available", update.version.clone());
            format!(
                "Доступна версия {}. Откройте настройки приложения, чтобы обновить.",
                update.version
            )
        }
        _ => return,
    };
    let _ = app
        .notification()
        .builder()
        .title("AI Development Hub")
        .body(body)
        .show();
}
