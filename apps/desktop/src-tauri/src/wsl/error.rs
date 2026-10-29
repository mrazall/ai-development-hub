use thiserror::Error;

#[derive(Debug, Error)]
pub enum WslError {
    #[error("invalid worker id")]
    InvalidWorkerId,
    #[error("invalid engine")]
    InvalidEngine,
    #[error("invalid hub URL")]
    InvalidUrl,
    #[error("insecure hub URL")]
    InsecureUrl,
    #[error("WSL is not available")]
    WslMissing,
    #[error("distribution is not available")]
    DistroMissing,
    #[error("systemd is not running")]
    SystemdOff,
    #[error("Python 3.12 or newer is required")]
    PythonOld,
    #[error("git is not available")]
    GitMissing,
    #[error("worker installation failed")]
    InstallFailed(String),
    #[error("operation timed out")]
    Timeout,
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("internal error: {0}")]
    Internal(String),
}

impl WslError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::InvalidWorkerId => "invalid_worker_id",
            Self::InvalidEngine => "invalid_engine",
            Self::InvalidUrl => "invalid_url",
            Self::InsecureUrl => "insecure_url",
            Self::WslMissing => "wsl_missing",
            Self::DistroMissing => "distro_missing",
            Self::SystemdOff => "systemd_off",
            Self::PythonOld => "python_old",
            Self::GitMissing => "git_missing",
            Self::InstallFailed(_) => "install_failed",
            Self::Timeout => "timeout",
            Self::Io(_) => "io",
            Self::Internal(_) => "internal",
        }
    }
}
