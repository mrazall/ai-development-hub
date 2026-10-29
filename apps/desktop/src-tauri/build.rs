/// Every app command. Declaring them makes Tauri generate `allow-<command>` permissions, which the
/// capabilities grant: all of them to the app's own window (capabilities/local.json), a few to the hub's
/// panel (app.rs, `grant_panel_bridge`). A remote page gets no app command without such a permission.
#[cfg(feature = "app")]
const COMMANDS: &[&str] = &[
    "accounts",
    "check_hub",
    "check_machine",
    "check_update",
    "cli_install_command",
    "create_subscription",
    "detect_existing_worker",
    "disconnect_machine",
    "fix_wslconfig",
    "found_logins",
    "get_settings",
    "install_cli",
    "install_worker",
    "login",
    "login_account",
    "open_app_settings",
    "open_panel",
    "register_worker",
    "reinstall_worker",
    "restart_worker",
    "save_settings",
    "set_autostart",
    "update_app",
    "worker_logs",
    "worker_status",
];

fn main() {
    #[cfg(feature = "app")]
    if std::env::var("HOST")
        .map(|host| host.contains("windows"))
        .unwrap_or(false)
        || !std::env::var("TARGET")
            .map(|target| target.contains("windows"))
            .unwrap_or(false)
    {
        tauri_build::try_build(
            tauri_build::Attributes::new()
                .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
        )
        .expect("failed to run tauri-build");
    }
}
