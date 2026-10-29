#[cfg(windows)]
use super::{build_keepalive_command, build_wsl_list_command, parse_wsl_list};
use super::{Distro, WslError};
use std::path::Path;
use std::process::Child;
#[cfg(windows)]
use std::process::{Command, Stdio};

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MachineReport {
    pub wsl_installed: bool,
    pub distros: Vec<Distro>,
    pub distro: Option<String>,
    pub systemd: bool,
    pub python: Option<String>,
    pub python_ok: bool,
    pub git: bool,
    pub engines: EngineReport,
    pub wslconfig: WslConfigReport,
    pub computer_name: String,
    pub default_worker_id: String,
    pub problems: Vec<MachineProblem>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct EngineReport {
    pub claude_code: bool,
    pub codex: bool,
}
#[derive(Debug, Clone, serde::Serialize)]
pub struct WslConfigReport {
    #[serde(rename = "instanceIdleTimeoutOk")]
    pub instance_idle_timeout_ok: bool,
    #[serde(rename = "vmIdleTimeoutOk")]
    pub vm_idle_timeout_ok: bool,
}
#[derive(Debug, Clone, serde::Serialize)]
pub struct MachineProblem {
    pub code: String,
    pub hint: String,
}

#[cfg(windows)]
pub fn check_machine() -> Result<MachineReport, WslError> {
    let list = run(&build_wsl_list_command())?;
    let distros = parse_wsl_list(&list);
    let distro = distros
        .iter()
        .find(|d| d.is_default)
        .or_else(|| distros.first())
        .map(|d| d.name.clone());
    let computer = std::env::var("COMPUTERNAME").unwrap_or_else(|_| "worker".into());
    let mut report = MachineReport {
        wsl_installed: true,
        distros,
        distro: distro.clone(),
        systemd: false,
        python: None,
        python_ok: false,
        git: false,
        engines: EngineReport {
            claude_code: false,
            codex: false,
        },
        wslconfig: WslConfigReport {
            instance_idle_timeout_ok: false,
            vm_idle_timeout_ok: false,
        },
        computer_name: computer.clone(),
        default_worker_id: super::default_worker_id(&computer),
        problems: Vec::new(),
    };
    // .wslconfig lives in the Windows profile; a missing file means neither key is set.
    if let Ok(profile) = std::env::var("USERPROFILE") {
        let text = std::fs::read_to_string(std::path::Path::new(&profile).join(".wslconfig"))
            .unwrap_or_default();
        let (instance, vm) = super::wslconfig::status(&text);
        report.wslconfig.instance_idle_timeout_ok = instance;
        report.wslconfig.vm_idle_timeout_ok = vm;
    }
    if let Some(d) = distro {
        report.systemd = run(&super::build_check_command(&d, "systemd")?)?.contains("running");
        let py = run(&super::build_check_command(&d, "python")?).unwrap_or_default();
        report.python_ok = parse_python_ok(&py);
        report.python = py.split_whitespace().last().map(str::to_owned);
        report.git = run(&super::build_check_command(&d, "git")?)
            .map(|s| !s.trim().is_empty())
            .unwrap_or(false);
        let engines = run(&super::build_check_command(&d, "engines")?).unwrap_or_default();
        report.engines = EngineReport {
            claude_code: engines.contains("claude"),
            codex: engines.contains("codex"),
        };
    }
    if !report.systemd {
        report.problems.push(MachineProblem {
            code: "systemd_off".into(),
            hint: "Enable systemd in /etc/wsl.conf and restart the distribution.".into(),
        });
    }
    if !report.python_ok {
        report.problems.push(MachineProblem {
            code: "python_old".into(),
            hint: "Install Python 3.12 or newer in the WSL distribution.".into(),
        });
    }
    if !report.git {
        report.problems.push(MachineProblem {
            code: "git_missing".into(),
            hint: "Install git in the WSL distribution.".into(),
        });
    }
    Ok(report)
}

#[cfg(not(windows))]
pub fn check_machine() -> Result<MachineReport, WslError> {
    Err(WslError::WslMissing)
}

#[cfg_attr(not(windows), allow(dead_code))]
fn parse_python_ok(output: &str) -> bool {
    let version = output.trim().strip_prefix("Python ").unwrap_or("");
    let mut parts = version.split('.');
    let major = parts.next().and_then(|v| v.parse::<u32>().ok());
    let minor = parts.next().and_then(|v| v.parse::<u32>().ok());
    matches!((major, minor), (Some(major), Some(minor)) if major > 3 || (major == 3 && minor >= 12))
}

#[cfg(windows)]
fn run(command: &super::WslCommand) -> Result<String, WslError> {
    let mut cmd = Command::new(&command.program);
    cmd.args(&command.args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console(&mut cmd);
    let output = cmd.output()?;
    if !output.status.success() {
        return Err(WslError::InstallFailed(
            decode_output(&output.stderr).chars().take(200).collect(),
        ));
    }
    Ok(decode_output(&output.stdout))
}
#[cfg(windows)]
fn decode_output(bytes: &[u8]) -> String {
    if bytes.starts_with(&[0xff, 0xfe]) {
        let (s, _, _) = encoding_rs::UTF_16LE.decode(&bytes[2..]);
        s.into_owned()
    } else if bytes.iter().take(64).any(|b| *b == 0) {
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|x| u16::from_le_bytes([x[0], x[1]]))
            .collect();
        String::from_utf16_lossy(&units)
    } else {
        String::from_utf8_lossy(bytes).into_owned()
    }
}
#[cfg(windows)]
fn hide_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x08000000);
}

#[cfg(windows)]
pub fn write_worker_token(distro: &str, worker_id: &str, token: &str) -> Result<(), WslError> {
    let command = super::build_write_token_command(distro, worker_id)?;
    let mut child = Command::new(&command.program);
    child
        .args(&command.args)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console(&mut child);
    let mut process = child.spawn()?;
    use std::io::Write;
    process
        .stdin
        .take()
        .ok_or_else(|| WslError::Internal("stdin unavailable".into()))?
        .write_all(token.as_bytes())?;
    let status = process.wait()?;
    if status.success() {
        Ok(())
    } else {
        Err(WslError::InstallFailed("token write failed".into()))
    }
}
#[cfg(not(windows))]
pub fn write_worker_token(_distro: &str, _worker_id: &str, _token: &str) -> Result<(), WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn install_worker(
    distro: &str,
    bundle: &Path,
    id: &str,
    engines: &[String],
    hub_url: &str,
) -> Result<(), WslError> {
    let c = super::build_install_command(distro, bundle, id, engines, hub_url)?;
    run(&c).map(|_| ())
}
#[cfg(not(windows))]
pub fn install_worker(
    _distro: &str,
    _bundle: &Path,
    _id: &str,
    _engines: &[String],
    _hub_url: &str,
) -> Result<(), WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn hub_reach(distro: &str, host: &str, port: u16) -> Result<String, WslError> {
    run(&super::build_hub_reach_command(distro, host, port)?)
}
#[cfg(not(windows))]
pub fn hub_reach(_distro: &str, _host: &str, _port: u16) -> Result<String, WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn detect_existing(distro: &str) -> Option<super::ExistingWorker> {
    super::parse_existing_worker(&run(&super::build_detect_existing_command(distro).ok()?).ok()?)
}
#[cfg(not(windows))]
pub fn detect_existing(_distro: &str) -> Option<super::ExistingWorker> {
    None
}

#[cfg(windows)]
pub fn unit_status(distro: &str, unit: &str) -> Result<String, WslError> {
    run(&super::build_unit_command(distro, unit, "status")?)
}
#[cfg(not(windows))]
pub fn unit_status(_distro: &str, _unit: &str) -> Result<String, WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn restart(distro: &str, unit: &str) -> Result<(), WslError> {
    run(&super::build_unit_command(distro, unit, "restart")?).map(|_| ())
}
#[cfg(not(windows))]
pub fn restart(_distro: &str, _unit: &str) -> Result<(), WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn stop_disable(distro: &str, unit: &str) -> Result<(), WslError> {
    run(&super::build_unit_command(distro, unit, "stop-disable")?).map(|_| ())
}
#[cfg(not(windows))]
pub fn stop_disable(_distro: &str, _unit: &str) -> Result<(), WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn logs(distro: &str, unit: &str, lines: usize) -> Result<String, WslError> {
    Ok(super::redact(&run(&super::build_logs_command(
        distro, unit, lines,
    )?)?))
}
#[cfg(not(windows))]
pub fn logs(_distro: &str, _unit: &str, _lines: usize) -> Result<String, WslError> {
    Err(WslError::WslMissing)
}

#[cfg(windows)]
pub fn open_login(distro: &str, shell: &str) -> Result<(), WslError> {
    let c = super::build_open_login_command(distro, shell)?;
    Command::new(&c.program)
        .args(&c.args)
        .spawn()?
        .wait()
        .map(|_| ())
        .map_err(WslError::from)
}
#[cfg(not(windows))]
pub fn open_login(_distro: &str, _shell: &str) -> Result<(), WslError> {
    Err(WslError::WslMissing)
}
#[cfg(windows)]
pub fn cli_install(distro: &str, engine: &str, dry_run: bool) -> Result<String, WslError> {
    run(&super::build_cli_command(distro, engine, dry_run)?)
}
#[cfg(not(windows))]
pub fn cli_install(_distro: &str, _engine: &str, _dry_run: bool) -> Result<String, WslError> {
    Err(WslError::WslMissing)
}

pub struct Keepalive {
    child: Option<Child>,
}
impl Keepalive {
    #[cfg(windows)]
    pub fn start(distro: &str) -> Result<Self, WslError> {
        let c = build_keepalive_command(distro)?;
        let mut command = Command::new(c.program);
        command
            .args(c.args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_console(&mut command);
        Ok(Self {
            child: Some(command.spawn()?),
        })
    }
    #[cfg(not(windows))]
    pub fn start(_distro: &str) -> Result<Self, WslError> {
        Err(WslError::WslMissing)
    }
}
impl Drop for Keepalive {
    fn drop(&mut self) {
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn python_gate() {
        assert!(parse_python_ok("Python 3.12.3"));
        assert!(!parse_python_ok("Python 3.11.9"));
    }
}
