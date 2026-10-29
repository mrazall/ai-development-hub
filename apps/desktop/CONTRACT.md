# AI Development Hub Desktop — IPC contract (v1, owned by orchestrator)

UI (`apps/desktop/ui`) calls these via `@tauri-apps/api/core` `invoke(name, args)`.
Shell (`src-tauri/src/commands.rs`) implements them as thin wrappers over `src-tauri/src/wsl/` (pure logic + process runner).
Argument names are camelCase on the JS side (Tauri default conversion from snake_case Rust args). Result structs (`Settings`, `LoginResult`, `WorkerStatus`, `MachineReport`) are serialized camelCase.

## Errors
Every command rejects with an `AppError` JSON object (never a raw string):
```ts
type AppError = { code: ErrorCode; message: string /* English, no secrets */; detail?: string /* no secrets */ };
type ErrorCode =
  | "invalid_url" | "insecure_url" | "network" | "tls" | "not_a_hub" | "http"
  | "unauthorized" | "forbidden" | "not_logged_in"
  | "wsl_missing" | "distro_missing" | "systemd_off" | "python_old" | "git_missing"
  | "invalid_worker_id" | "invalid_engine" | "worker_exists"
  | "install_failed" | "timeout" | "io" | "internal";
```
UI translates by `code` via `t('desktop.err.<code>')`; `message` is a fallback.

## URL rules
`https://` any host; `http://` only for `localhost` / `127.0.0.1`. Trailing slash stripped. Else `insecure_url`/`invalid_url`.

## Worker id rules
`^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$` (2–63 chars, same length as the hub). Default = computer name lowercased, other chars → `-`, collapse/trim dashes; 1-char result → `worker-<c>`, empty → `worker`.
Engines: subset of `["claude_code","codex"]` (plus `"mock"` allowed for testing), non-empty.

## Per-worker unit and token
Every worker id owns its own systemd user unit `aihub-worker-<id>.service` and token file
`~/.aihub/workers/<id>/token`; `ExecStart` passes `--token-file %h/.aihub/workers/<id>/token`.
All unit operations (status, logs, restart, disconnect, reinstall) use the unit of the id from the app settings;
the unit name is built only from a validated id. The legacy `aihub-worker` unit and `~/.aihub/worker-token`
(manually installed worker) are never read or modified. Several hubs/workers on one machine coexist.
`install-worker.sh` has no `--unit` option.

## Commands
| Command | Args | Result |
|---|---|---|
| `check_hub` | `{ url: string }` | `{ url: string /*normalized*/, version: string, demo: boolean }` (health + /system/info) |
| `login` | `{ url, user, password }` | `{ username: string, isAdmin: boolean }`. Token kept in process memory and stored in Credential Manager (keyring service `aihub-desktop`, account `user-token:<url>`). Password never stored. |
| `check_machine` | `{}` | `MachineReport` (below) |
| `register_worker` | `{ id: string, engines: string[] }` | `{ id: string }`. POST /api/v0/workers; `worker_token` written straight to WSL `~/.aihub/workers/<id>/token` (dir 0700, file 0600) via stdin; never returned to UI. 409 → `worker_exists`. |
| `install_worker` | `{}` | `{ version: string, path: string }` installs bundled archive into WSL, starts unit |
| `worker_status` | `{}` | `{ unit: "active"\|"inactive"\|"failed"\|"unknown", hub: "online"\|"offline"\|"unknown", hubReachable: boolean, pendingApprovals: number, activeAgents: number, workerVersion: string\|null, workerOutdated: boolean, warning: string\|null }` |
| `worker_logs` | `{ lines?: number /*default 200, max 1000*/ }` | `string` (journalctl output, redacted) |
| `restart_worker` | `{ consent?: boolean }` | `null`; active agents require `consent: true` |
| `set_autostart` | `{ on: boolean }` | `null` |
| `get_settings` | `{}` | `Settings` |
| `save_settings` | `{ settings: Settings }` | `Settings` |
| `fix_wslconfig` | `{}` | `{ backupPath: string, changed: boolean }` (adds only missing keys under `[wsl2]`, backup first) |
| `disconnect_machine` | `{ deleteFromHub: boolean }` | `null` (stop+disable unit; DELETE worker in hub only if flag) |
| `reinstall_worker` | `{}` | same as `install_worker` |
| `open_panel` | `{ path?: string }` | `null` (shows main window at hub URL + path) |
| `found_logins` | `{}` | `FoundLogin[]` from `GET /api/v0/accounts/found-logins`; identities only, never credentials |
| `accounts` | `{}` | subscription profiles for this worker |
| `create_subscription` | `{ engine: "claude"|"codex", adoptFoundLogin?: boolean }` | creates a subscription profile; hub may enqueue adoption of a found login |
| `login_account` | `{ id: string }` | validates account id, gets `GET /accounts/{id}/login-command`, opens `wsl.exe -d <distro> -- bash -lc '<shell>'`, then POSTs `login-started` |
| `cli_install_command` | `{ engine: "claude"|"codex"|"node" }` | runs installed-worker `install-cli.sh <engine> --dry-run` and returns the command for consent UI |
| `install_cli` | `{ engine: "claude"|"codex"|"node" }` | runs the same installed-worker script after the command was shown |

`login_account` accepts the shell only from the hub response and rejects NUL/control characters; the account id
is checked with the worker-id regex before the request. `existingWorker` follows the same account/CLI flow, but
never installs or updates the manually installed `aihub-worker` unit.

The updater is checked on startup and every 24 hours through `tauri-plugin-updater`. The configured endpoint is
the public GitHub `latest.json`; the public key is intentionally a placeholder until the owner supplies one.
The notification does not install silently: an update must be explicitly started by the owner, and a running
worker/agent must not be restarted without consent.

```ts
type MachineReport = {
  wslInstalled: boolean; distros: { name: string; state: string; version: number; isDefault: boolean }[];
  distro: string | null; systemd: boolean; python: string | null /* "3.12.3" */; pythonOk: boolean;
  git: boolean; engines: { claude_code: boolean; codex: boolean };
  wslconfig: { instanceIdleTimeoutOk: boolean; vmIdleTimeoutOk: boolean };
  computerName: string; defaultWorkerId: string;
  problems: { code: ErrorCode; hint: string }[];
};
type Settings = {
  hubUrl: string | null; workerId: string | null; distro: string | null;
  engines: string[]; autostart: boolean; setupComplete: boolean;
  unitName: string /* read-only, derived: "aihub-worker-<workerId>", "" without an id; input value ignored */;
};
```
Settings are stored with tauri-plugin-store (`settings.json`) — never secrets.

## Events (shell → UI)
- `worker-status` payload = `worker_status` result, emitted every 30 s.
- `navigate` payload `{ path: string }` — notification click.

## WSL module API (Rust, `crate::wsl`) used by the shell
Pure, unit-tested on Linux (`cargo test --no-default-features --lib`):
`parse_wsl_list(&str) -> Vec<Distro>` (handles UTF-16LE output of `wsl -l -v`), `validate_worker_id`, `worker_unit_name(id)`, `worker_token_path(id)`, `default_worker_id(computer)`,
`validate_engines`, `normalize_hub_url`, `wslconfig::patch(&str) -> (String, bool)`, `redact(&str) -> String`,
`build_*_command(...) -> WslCommand { program, args }` (args never contain secrets).
Side-effecting (Windows): `check_machine`, `write_worker_token(distro, worker_id, token)` (stdin), `install_worker(distro, bundle_path, id, engines, hub_url)`,
`unit_status/restart/stop_disable/logs(distro, worker_id, ..)`, `Keepalive::start(distro)` (`wsl -d <distro> --exec sleep infinity`, killed on exit).

## Build features
`src-tauri/Cargo.toml`: feature `app` (default) pulls tauri + plugins; `--no-default-features` builds only pure modules (`wsl`, `secrets` redaction, url/id validation) so tests run in WSL without GTK/WebKit.
