use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    InvalidUrl,
    InsecureUrl,
    Network,
    Tls,
    NotAHub,
    Http,
    Unauthorized,
    Forbidden,
    NotLoggedIn,
    WslMissing,
    DistroMissing,
    SystemdOff,
    PythonOld,
    GitMissing,
    InvalidWorkerId,
    InvalidEngine,
    WorkerExists,
    InstallFailed,
    Timeout,
    Io,
    Internal,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AppError {
    pub code: ErrorCode,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}
impl AppError {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            detail: None,
        }
    }
}
impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}
impl std::error::Error for AppError {}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    pub hub_url: Option<String>,
    pub worker_id: Option<String>,
    pub distro: Option<String>,
    pub engines: Vec<String>,
    pub autostart: bool,
    pub setup_complete: bool,
    /// The machine's hand-installed worker (`aihub-worker`) is adopted instead of installing one: the app
    /// watches and restarts it, never installs, re-registers or removes it.
    #[serde(default)]
    pub existing_worker: bool,
    /// Read-only for the UI: always derived from `worker_id` and `existing_worker`
    /// (`aihub-worker-<id>` or `aihub-worker`), never taken from storage or IPC input.
    #[serde(default)]
    pub unit_name: String,
}

impl Settings {
    /// Validated worker id; every unit/token operation goes through it.
    pub fn valid_worker_id(&self) -> Result<&str, AppError> {
        let id = self.worker_id.as_deref().unwrap_or_default();
        crate::wsl::validate_worker_id(id)
            .map_err(|_| AppError::new(ErrorCode::InvalidWorkerId, "Worker id is invalid"))?;
        Ok(id)
    }

    /// The systemd unit of this machine's worker, for every unit/journal operation.
    pub fn unit(&self) -> Result<String, AppError> {
        crate::wsl::unit_for(self.valid_worker_id()?, self.existing_worker)
            .map_err(|_| AppError::new(ErrorCode::InvalidWorkerId, "Worker id is invalid"))
    }

    pub fn with_derived_unit(mut self) -> Self {
        self.unit_name = self.unit().unwrap_or_default();
        self
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HubInfo {
    pub url: String,
    pub version: String,
    pub demo: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginResult {
    pub username: String,
    pub is_admin: bool,
}
/// The answer to «Проверить обновления»: the running version and a newer one on the hub, if any.
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateCheck {
    pub current: String,
    pub available: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkerStatus {
    pub unit: String,
    pub hub: String,
    pub hub_reachable: bool,
    pub worker_id: Option<String>,
    pub worker_state: String,
    pub pending_approvals: u32,
    pub active_agents: u32,
    pub worker_version: Option<String>,
    pub worker_outdated: bool,
    pub warning: Option<String>,
}

/// Returns true when the worker version is a well-formed older semantic version.
/// Unknown versions are deliberately not treated as stale: an older/manual worker
/// is warned about only when the comparison is reliable.
pub fn worker_is_outdated(app_version: &str, worker_version: Option<&str>) -> bool {
    let Some(worker) = worker_version else {
        return false;
    };
    match (version_parts(app_version), version_parts(worker)) {
        (Some(app), Some(worker)) => worker < app,
        _ => false,
    }
}

fn version_parts(value: &str) -> Option<[u64; 3]> {
    let value = value.strip_prefix('v').unwrap_or(value);
    let mut parts = value.split('.').map(|part| part.parse::<u64>().ok());
    Some([
        parts.next()??,
        parts.next()??,
        parts.next().unwrap_or(Some(0))?,
    ])
}

/// Restarting while agents are active is safe only after an explicit user consent.
pub fn can_restart_worker(active_agents: u32, consent: bool) -> bool {
    active_agents == 0 || consent
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Notification {
    pub id: String,
    pub kind: Option<String>,
    pub title: Option<String>,
    pub message: Option<String>,
    pub session_id: Option<String>,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FoundLogin {
    #[serde(alias = "worker_id")]
    pub worker_id: String,
    pub engine: String,
    pub identity: Option<String>,
    pub kind: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountProfile {
    pub id: String,
    pub name: String,
    pub kind: String,
    #[serde(alias = "worker_id")]
    pub worker_id: String,
    pub status: String,
    pub identity: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CliInstall {
    pub engine: String,
    pub command: String,
    pub installed: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings(id: Option<&str>, unit: &str) -> Settings {
        Settings {
            worker_id: id.map(str::to_owned),
            unit_name: unit.into(),
            ..Default::default()
        }
    }

    #[test]
    fn unit_is_derived_from_worker_id_only() {
        // A stored or UI-supplied legacy unit name is ignored.
        assert_eq!(
            settings(Some("pc-1"), "aihub-worker")
                .with_derived_unit()
                .unit_name,
            "aihub-worker-pc-1"
        );
        assert_eq!(
            settings(None, "aihub-worker").with_derived_unit().unit_name,
            ""
        );
        assert_eq!(
            settings(Some("Bad id"), "x").with_derived_unit().unit_name,
            ""
        );
        assert!(settings(None, "").valid_worker_id().is_err());
        assert_eq!(
            settings(Some("pc-2"), "").valid_worker_id().unwrap(),
            "pc-2"
        );
    }

    #[test]
    fn adopted_worker_uses_its_own_unit() {
        let adopted = Settings {
            existing_worker: true,
            ..settings(Some("pc-wsl"), "aihub-worker-pc-wsl")
        };
        assert_eq!(adopted.with_derived_unit().unit_name, "aihub-worker");
    }

    #[test]
    fn settings_use_camel_case_for_the_ui() {
        let value = serde_json::to_value(settings(Some("pc-1"), "")).unwrap();
        assert!(value.get("setupComplete").is_some());
        assert!(value.get("workerId").is_some());
        let parsed: Settings = serde_json::from_value(serde_json::json!({
            "hubUrl": null, "workerId": "pc-1", "distro": null, "engines": [],
            "autostart": true, "setupComplete": false
        }))
        .unwrap();
        assert_eq!(parsed.worker_id.as_deref(), Some("pc-1"));
    }

    #[test]
    fn compares_worker_versions_without_guessing_unknown_versions() {
        assert!(worker_is_outdated("1.4.0", Some("1.3.9")));
        assert!(!worker_is_outdated("1.4.0", Some("1.4.0")));
        assert!(!worker_is_outdated("1.4.0", Some("dev")));
        assert!(!worker_is_outdated("1.4.0", None));
        assert!(worker_is_outdated("v1.4.0", Some("v1.3.0")));
    }

    #[test]
    fn active_agents_require_restart_consent() {
        assert!(can_restart_worker(0, false));
        assert!(!can_restart_worker(2, false));
        assert!(can_restart_worker(2, true));
    }
}
