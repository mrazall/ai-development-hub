use super::{
    validate_engines, validate_unit_name, validate_worker_id, worker_token_path, WslError,
};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WslCommand {
    pub program: String,
    pub args: Vec<String>,
}

fn distro_arg(distro: &str) -> Result<String, WslError> {
    if distro.is_empty() || distro.contains(['\0', '\r', '\n']) {
        return Err(WslError::DistroMissing);
    }
    Ok(distro.to_owned())
}

pub fn build_wsl_list_command() -> WslCommand {
    WslCommand {
        program: "wsl.exe".into(),
        args: vec!["--list".into(), "--verbose".into()],
    }
}

pub fn build_check_command(distro: &str, command: &str) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    let fixed = match command {
        "systemd" => "systemctl is-system-running",
        "python" => "python3 --version",
        "git" => "command -v git",
        "engines" => "PATH=\"$HOME/.local/bin:$PATH\"; command -v claude; command -v codex",
        _ => return Err(WslError::Internal("unsupported check".into())),
    };
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--exec".into(),
            "sh".into(),
            "-c".into(),
            fixed.into(),
        ],
    })
}

/// Reads the hand-installed worker's unit: its ExecStart line and whether it runs.
pub fn build_detect_existing_command(distro: &str) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    let script = r#"systemctl --user cat aihub-worker.service 2>/dev/null | sed -n 's/^ExecStart=//p' | tail -1
echo "active=$(systemctl --user is-active aihub-worker.service 2>/dev/null)""#;
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--exec".into(),
            "sh".into(),
            "-c".into(),
            script.into(),
        ],
    })
}

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExistingWorker {
    pub worker_id: String,
    pub hub_url: String,
    pub active: bool,
}

/// The worker id and hub of `aihub-worker` from `build_detect_existing_command` output; None when there is
/// no such unit or its id is not a valid one.
pub fn parse_existing_worker(output: &str) -> Option<ExistingWorker> {
    let exec = output
        .lines()
        .find(|line| line.contains("aihub-worker") && line.contains("--worker-id"))?;
    let words: Vec<&str> = exec.split_whitespace().collect();
    let value = |flag: &str| {
        words
            .iter()
            .position(|w| *w == flag)
            .and_then(|i| words.get(i + 1))
            .map(|v| v.to_string())
    };
    let worker_id = value("--worker-id")?;
    validate_worker_id(&worker_id).ok()?;
    Some(ExistingWorker {
        worker_id,
        hub_url: value("--control-plane")?,
        active: output.lines().any(|line| line.trim() == "active=active"),
    })
}

/// Checks from inside WSL whether the hub's host resolves and its port accepts a connection. Host and port
/// are positional arguments (validated), never interpolated into the script. Prints `dns=ok|fail tcp=ok|fail`.
pub fn build_hub_reach_command(
    distro: &str,
    host: &str,
    port: u16,
) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    if host.is_empty()
        || !host
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | ':'))
    {
        return Err(WslError::Internal("invalid hub host".into()));
    }
    let script = r#"if getent hosts "$1" >/dev/null; then d=ok; else d=fail; fi
if timeout 5 bash -c 'exec 3<>"/dev/tcp/$0/$1"' "$1" "$2" 2>/dev/null; then t=ok; else t=fail; fi
echo "dns=$d tcp=$t""#;
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--exec".into(),
            "sh".into(),
            "-c".into(),
            script.into(),
            "sh".into(),
            host.into(),
            port.to_string(),
        ],
    })
}

/// Why a worker the hub shows offline cannot reach it, from `build_hub_reach_command` output.
/// None when WSL reaches the hub (then the cause is elsewhere: the unit, the token).
pub fn diagnose_hub_reach(output: &str, host: &str) -> Option<String> {
    if output.contains("dns=fail") {
        return Some(format!(
            "WSL cannot resolve {host}, so the worker cannot reach the hub. Check in WSL: getent hosts {host}              (see the desktop guide, 'Worker is offline')."
        ));
    }
    if output.contains("tcp=fail") {
        return Some(format!(
            "WSL resolves {host} but cannot connect to it (network, VPN or firewall between WSL and the hub)."
        ));
    }
    None
}

/// Writes stdin to `~/.aihub/workers/<id>/token` (dir 0700, file 0600).
/// The token is intentionally not represented in this argument vector; the id is
/// validated and additionally passed as a positional argument, not interpolated.
pub fn build_write_token_command(distro: &str, worker_id: &str) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    worker_token_path(worker_id)?;
    let script = r#"umask 077; dir="$HOME/.aihub/workers/$1"; mkdir -p "$dir" && chmod 700 "$dir" && cat > "$dir/token" && chmod 600 "$dir/token""#;
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--exec".into(),
            "sh".into(),
            "-c".into(),
            script.into(),
            "sh".into(),
            worker_id.into(),
        ],
    })
}

pub fn build_install_command(
    distro: &str,
    bundle: &Path,
    id: &str,
    engines: &[String],
    hub_url: &str,
) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    validate_worker_id(id)?;
    validate_engines(engines)?;
    if [bundle.to_string_lossy().as_ref(), hub_url]
        .iter()
        .any(|s| s.contains(['\0', '\r', '\n']))
    {
        return Err(WslError::InstallFailed(
            "invalid installation argument".into(),
        ));
    }
    // The bundle is a Windows path (the app's resources) and carries its own installer: translate the path,
    // take install-worker.sh out of the bundle into a temporary folder and run it from there.
    let script = r#"set -e
bundle=$(wslpath -u "$1")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar -xzf "$bundle" -C "$tmp" ./deploy/pc-worker/install-worker.sh
bash "$tmp/deploy/pc-worker/install-worker.sh" --bundle "$bundle" --worker-id "$2" --engines "$3" --hub-url "$4""#;
    let args = vec![
        "-d".into(),
        d,
        "--exec".into(),
        "sh".into(),
        "-c".into(),
        script.into(),
        "sh".into(),
        bundle.to_string_lossy().into_owned(),
        id.into(),
        engines.join(","),
        hub_url.into(),
    ];
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args,
    })
}

pub fn build_unit_command(distro: &str, unit: &str, action: &str) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    validate_unit_name(unit)?;
    if !matches!(action, "status" | "restart" | "stop-disable") {
        return Err(WslError::Internal("invalid unit action".into()));
    }
    let fixed = match action {
        "status" => format!("systemctl --user is-active {unit}"),
        "restart" => format!("systemctl --user restart {unit}"),
        _ => format!("systemctl --user stop {unit}; systemctl --user disable {unit}"),
    };
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--exec".into(),
            "sh".into(),
            "-c".into(),
            fixed,
        ],
    })
}

pub fn build_logs_command(distro: &str, unit: &str, lines: usize) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    validate_unit_name(unit)?;
    let count = lines.clamp(1, 1000);
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--exec".into(),
            "journalctl".into(),
            "--user".into(),
            "-u".into(),
            unit.into(),
            "-n".into(),
            count.to_string(),
            "--no-pager".into(),
        ],
    })
}

pub fn build_keepalive_command(distro: &str) -> Result<WslCommand, WslError> {
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            distro_arg(distro)?,
            "--exec".into(),
            "sleep".into(),
            "infinity".into(),
        ],
    })
}

pub fn build_open_login_command(distro: &str, shell: &str) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    if shell.is_empty()
        || shell.len() > 2048
        || shell.contains(['\0', '\r', '\n'])
        || shell.chars().any(|c| {
            c.is_control()
                || !c.is_ascii()
                || !matches!(c, 'a'..='z' | 'A'..='Z' | '0'..='9' | '_' | '-' | '/' | '.' | '~' | '=' | ' ')
        })
    {
        return Err(WslError::Internal("invalid login command".into()));
    }
    Ok(WslCommand {
        program: "cmd.exe".into(),
        args: vec![
            "/C".into(),
            "start".into(),
            "AI Development Hub login".into(),
            "wsl.exe".into(),
            "-d".into(),
            d,
            "--".into(),
            "bash".into(),
            "-lc".into(),
            shell.into(),
        ],
    })
}

pub fn build_cli_command(
    distro: &str,
    engine: &str,
    dry_run: bool,
) -> Result<WslCommand, WslError> {
    let d = distro_arg(distro)?;
    if !matches!(engine, "claude" | "codex" | "node") {
        return Err(WslError::InvalidEngine);
    }
    let suffix = if dry_run { " --dry-run" } else { "" };
    Ok(WslCommand {
        program: "wsl.exe".into(),
        args: vec![
            "-d".into(),
            d,
            "--".into(),
            "bash".into(),
            "-lc".into(),
            format!("~/.local/share/aihub-worker/current/scripts/install-cli.sh $1{suffix}"),
            "install-cli.sh".into(),
            engine.into(),
        ],
    })
}

#[cfg(test)]
mod tests {
    use super::super::unit_for;
    use super::*;
    #[test]
    fn no_secret_in_install_args() {
        let c = build_install_command(
            "Ubuntu",
            Path::new("worker.tar.gz"),
            "worker",
            &["mock".into()],
            "https://hub",
        )
        .unwrap();
        assert!(c.args.iter().all(|a| !a.contains("token")));
        assert!(!c.args.iter().any(|a| a == "--unit" || a.contains("--unit")));
    }

    #[test]
    fn open_login_builds_fixed_wsl_argv_and_validates_shell() {
        let command = build_open_login_command("Ubuntu", "aihub-login --account pc-1").unwrap();
        assert_eq!(command.program, "cmd.exe");
        assert_eq!(
            command.args,
            [
                "/C",
                "start",
                "AI Development Hub login",
                "wsl.exe",
                "-d",
                "Ubuntu",
                "--",
                "bash",
                "-lc",
                "aihub-login --account pc-1",
            ]
        );
        assert!(build_open_login_command("Ubuntu", "aihub-login; cat token").is_err());
        assert!(build_open_login_command("Ubuntu", "").is_err());
        assert!(build_open_login_command("Ubuntu\nsecret", "aihub-login").is_err());
    }

    #[test]
    fn cli_install_builds_fixed_argv_without_secrets() {
        let command = build_cli_command("Ubuntu", "codex", true).unwrap();
        assert_eq!(command.program, "wsl.exe");
        assert_eq!(
            command.args,
            [
                "-d",
                "Ubuntu",
                "--",
                "bash",
                "-lc",
                "~/.local/share/aihub-worker/current/scripts/install-cli.sh $1 --dry-run",
                "install-cli.sh",
                "codex",
            ]
        );
        assert!(command.args.iter().all(|arg| !arg.contains("secret")));
        assert!(build_cli_command("Ubuntu", "codex; cat token", false).is_err());
        assert!(build_cli_command("Ubuntu", "", false).is_err());
    }

    #[test]
    fn hub_reach_is_diagnosed() {
        // Found live: after a reboot WSL stopped resolving the hub's tailnet name; the hub showed "offline".
        let host = "hub.example.ts.net";
        let c = build_hub_reach_command("Ubuntu", host, 443).unwrap();
        assert_eq!(&c.args[7..], [host, "443"]);
        assert!(build_hub_reach_command("Ubuntu", "a;rm -rf ~", 443).is_err());
        assert!(diagnose_hub_reach("dns=fail tcp=fail", host)
            .unwrap()
            .contains("cannot resolve hub.example.ts.net"));
        assert!(diagnose_hub_reach("dns=ok tcp=fail", host)
            .unwrap()
            .contains("cannot connect"));
        assert_eq!(diagnose_hub_reach("dns=ok tcp=ok", host), None);
    }

    #[test]
    fn install_runs_the_installer_from_the_bundle() {
        // Found live: the command ran ~/.local/bin/aihub-install-worker, which nothing creates, with the
        // bundle's Windows path. The installer comes out of the bundle; the path goes through wslpath.
        let c = build_install_command(
            "Ubuntu",
            Path::new(r"C:\Users\u\AppData\Local\AI Development Hub\resources\aihub-worker.tar.gz"),
            "pc-1",
            &["codex".into()],
            "http://127.0.0.1:58090",
        )
        .unwrap();
        let script = &c.args[5];
        assert!(script.contains(r#"wslpath -u "$1""#));
        assert!(script.contains("./deploy/pc-worker/install-worker.sh"));
        assert!(!script.contains(".local/bin/aihub-install-worker"));
        assert_eq!(
            &c.args[7..],
            [
                "C:\\Users\\u\\AppData\\Local\\AI Development Hub\\resources\\aihub-worker.tar.gz",
                "pc-1",
                "codex",
                "http://127.0.0.1:58090"
            ]
        );
    }

    #[test]
    fn token_goes_to_per_worker_path() {
        let c = build_write_token_command("Ubuntu", "pc-1").unwrap();
        let script = &c.args[5];
        assert!(script.contains(r#"$HOME/.aihub/workers/$1"#));
        assert!(script.contains("chmod 700") && script.contains("chmod 600"));
        assert!(!script.contains("worker-token"));
        assert_eq!(c.args.last().unwrap(), "pc-1");
        assert!(build_write_token_command("Ubuntu", "../etc").is_err());
        assert!(build_write_token_command("Ubuntu", "").is_err());
    }

    #[test]
    fn unit_commands_use_the_given_unit() {
        let own = unit_for("pc-1", false).unwrap();
        for action in ["status", "restart", "stop-disable"] {
            let c = build_unit_command("Ubuntu", &own, action).unwrap();
            let script = c.args.last().unwrap();
            assert!(script.contains("aihub-worker-pc-1"), "{script}");
            assert!(!script.contains("aihub-worker "), "{script}");
        }
        // An adopted, hand-installed worker: its own unit name, nothing else.
        assert_eq!(unit_for("pc-wsl", true).unwrap(), "aihub-worker");
        let logs = build_logs_command("Ubuntu", "aihub-worker", 50).unwrap();
        assert!(logs.args.iter().any(|a| a == "aihub-worker"));
        assert!(build_unit_command("Ubuntu", "pc-1", "status").is_err());
        assert!(build_unit_command("Ubuntu", "aihub-worker-pc-1; rm -rf ~", "restart").is_err());
        assert!(build_unit_command("Ubuntu", "", "status").is_err());
        assert!(build_logs_command("Ubuntu", "aihub-worker-Bad", 10).is_err());
    }

    #[test]
    fn existing_worker_is_detected_from_its_unit() {
        // A unit written by deploy/pc-worker/setup-worker.sh before the app existed.
        let output = "/home/dev/.venvs/aihub-worker/bin/aihub-worker --control-plane https://hub.example.ts.net \
                      --worker-id pc-wsl --token-file %h/.aihub/worker-token --enable-engines claude_code,codex\nactive=active\n";
        assert_eq!(
            parse_existing_worker(output),
            Some(ExistingWorker {
                worker_id: "pc-wsl".into(),
                hub_url: "https://hub.example.ts.net".into(),
                active: true,
            })
        );
        assert_eq!(parse_existing_worker("active=inactive\n"), None);
        assert!(
            !parse_existing_worker(&output.replace("active=active", "active=failed"))
                .unwrap()
                .active
        );
        assert_eq!(
            parse_existing_worker("x --worker-id ../etc --control-plane h\n"),
            None
        );
    }
}
