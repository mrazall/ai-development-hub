use super::WslError;
use regex::Regex;

pub fn validate_worker_id(id: &str) -> Result<(), WslError> {
    let valid = Regex::new(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$").unwrap();
    if valid.is_match(id) {
        Ok(())
    } else {
        Err(WslError::InvalidWorkerId)
    }
}

/// systemd user unit owned by this worker id. The legacy `aihub-worker` unit is
/// never produced, so an existing manually installed worker is left alone.
pub fn worker_unit_name(id: &str) -> Result<String, WslError> {
    validate_worker_id(id)?;
    Ok(format!("aihub-worker-{id}"))
}

/// The unit of a worker installed by hand (deploy/pc-worker/setup-worker.sh), which the app can adopt
/// instead of registering a second worker on the same machine. It is watched, never installed or removed.
pub const EXISTING_UNIT: &str = "aihub-worker";

/// The unit the app manages: the adopted `aihub-worker` or its own `aihub-worker-<id>`.
pub fn unit_for(id: &str, existing: bool) -> Result<String, WslError> {
    if existing {
        validate_worker_id(id)?;
        Ok(EXISTING_UNIT.into())
    } else {
        worker_unit_name(id)
    }
}

/// Only the two shapes above ever reach a systemctl/journalctl command line.
pub fn validate_unit_name(unit: &str) -> Result<(), WslError> {
    let valid = Regex::new(r"^aihub-worker(-[a-z0-9][a-z0-9-]{0,61}[a-z0-9])?$").unwrap();
    if valid.is_match(unit) {
        Ok(())
    } else {
        Err(WslError::InvalidWorkerId)
    }
}

/// Token location inside WSL, relative to `$HOME`: `.aihub/workers/<id>/token`.
pub fn worker_token_path(id: &str) -> Result<String, WslError> {
    validate_worker_id(id)?;
    Ok(format!(".aihub/workers/{id}/token"))
}

pub fn default_worker_id(computer: &str) -> String {
    let mut out = String::new();
    for ch in computer.to_lowercase().chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch);
        } else if !out.ends_with('-') {
            out.push('-');
        }
    }
    let out = out.trim_matches('-').to_owned();
    // Ids must be 2..=63 chars; prefix too-short names rather than reject them.
    let out = match out.len() {
        0 => "worker".to_owned(),
        1 => format!("worker-{out}"),
        _ => out,
    };
    out.chars()
        .take(63)
        .collect::<String>()
        .trim_end_matches('-')
        .to_owned()
}

pub fn validate_engines(engines: &[String]) -> Result<(), WslError> {
    if engines.is_empty()
        || engines
            .iter()
            .any(|e| !matches!(e.as_str(), "claude_code" | "codex" | "mock"))
    {
        Err(WslError::InvalidEngine)
    } else {
        Ok(())
    }
}

pub fn normalize_hub_url(url: &str) -> Result<String, WslError> {
    let value = url.trim().trim_end_matches('/');
    let (scheme, rest) = value.split_once("://").ok_or(WslError::InvalidUrl)?;
    if scheme != "https" && scheme != "http" {
        return Err(WslError::InvalidUrl);
    }
    let host_port = rest
        .split('/')
        .next()
        .unwrap_or("")
        .split('@')
        .next_back()
        .unwrap_or("");
    let host = host_port
        .split(':')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase();
    if host.is_empty() {
        return Err(WslError::InvalidUrl);
    }
    if scheme == "http" && host != "localhost" && host != "127.0.0.1" {
        return Err(WslError::InsecureUrl);
    }
    Ok(value.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn url_rules() {
        assert_eq!(
            normalize_hub_url("https://hub.example/").unwrap(),
            "https://hub.example"
        );
        assert!(matches!(
            normalize_hub_url("http://example.com"),
            Err(WslError::InsecureUrl)
        ));
        assert!(normalize_hub_url("http://127.0.0.1:58090/").is_ok());
    }
    #[test]
    fn ids_and_engines() {
        assert_eq!(default_worker_id("My PC_name"), "my-pc-name");
        assert_eq!(default_worker_id("A"), "worker-a");
        assert_eq!(default_worker_id("!!"), "worker");
        assert!(validate_worker_id(&default_worker_id(&format!("{}-x", "a".repeat(62)))).is_ok());
        assert!(validate_worker_id("x").is_err());
        assert!(validate_worker_id("a-1").is_ok());
        assert!(validate_worker_id("-bad").is_err());
        assert!(validate_engines(&["mock".into()]).is_ok());
        assert!(validate_engines(&[]).is_err());
    }
    #[test]
    fn unit_and_token_are_per_worker() {
        assert_eq!(worker_unit_name("pc-1").unwrap(), "aihub-worker-pc-1");
        assert_eq!(worker_unit_name("pc-2").unwrap(), "aihub-worker-pc-2");
        assert_eq!(
            worker_token_path("pc-1").unwrap(),
            ".aihub/workers/pc-1/token"
        );
        for bad in ["", "x", "Bad", "a;rm", "../x", "a b"] {
            assert!(worker_unit_name(bad).is_err(), "{bad}");
            assert!(worker_token_path(bad).is_err(), "{bad}");
        }
    }
}
