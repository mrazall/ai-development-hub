use crate::types::{AppError, ErrorCode};
use url::Url;

pub fn normalize_hub_url(raw: &str) -> Result<String, AppError> {
    let value = raw.trim().trim_end_matches('/').to_string();
    let lower = value.to_ascii_lowercase();
    if !(lower.starts_with("https://") || lower.starts_with("http://")) {
        return Err(AppError::new(
            ErrorCode::InvalidUrl,
            "Hub URL must use http or https",
        ));
    }
    let authority = value
        .split_once("://")
        .map(|(_, rest)| rest.split('/').next().unwrap_or(""))
        .unwrap_or("");
    if authority.is_empty() || authority.starts_with(':') {
        return Err(AppError::new(ErrorCode::InvalidUrl, "Hub URL is invalid"));
    }
    if lower.starts_with("http://") {
        let host = value[7..]
            .split('/')
            .next()
            .unwrap_or("")
            .split(':')
            .next()
            .unwrap_or("");
        if host != "localhost" && host != "127.0.0.1" {
            return Err(AppError::new(
                ErrorCode::InsecureUrl,
                "HTTP is allowed only for localhost",
            ));
        }
    }
    if value.contains(' ') || value.contains('\n') {
        return Err(AppError::new(ErrorCode::InvalidUrl, "Hub URL is invalid"));
    }
    Ok(value)
}

/// Main-window navigation is restricted to the configured hub host.  The
/// scheme check keeps the existing HTTP policy in force for redirected links.
pub fn is_allowed_navigation(hub: &str, candidate: &Url) -> bool {
    let Ok(base) = Url::parse(hub) else {
        return false;
    };
    let Some(host) = candidate.host_str() else {
        return false;
    };
    let Some(base_host) = base.host_str() else {
        return false;
    };
    if !host.eq_ignore_ascii_case(base_host) {
        return false;
    }
    if candidate.scheme() == "https" {
        return true;
    }
    candidate.scheme() == "http" && matches!(host, "localhost" | "127.0.0.1")
}

pub fn validate_worker_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    (2..=63).contains(&id.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
        && bytes
            .last()
            .is_some_and(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
}

pub fn default_worker_id(computer: &str) -> String {
    crate::wsl::default_worker_id(computer)
}

pub fn validate_engines(engines: &[String]) -> Result<(), AppError> {
    if engines.is_empty()
        || engines
            .iter()
            .any(|e| !matches!(e.as_str(), "claude_code" | "codex" | "mock"))
    {
        return Err(AppError::new(
            ErrorCode::InvalidEngine,
            "At least one supported engine is required",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urls() {
        assert_eq!(
            normalize_hub_url("http://localhost:58090/").unwrap(),
            "http://localhost:58090"
        );
        assert!(normalize_hub_url("http://example.com").is_err());
    }

    #[test]
    fn navigation_allows_same_host() {
        let candidate = Url::parse("https://hub.example/sessions/1").unwrap();
        assert!(is_allowed_navigation("https://hub.example", &candidate));
    }

    #[test]
    fn navigation_blocks_other_host() {
        let candidate = Url::parse("https://evil.example/").unwrap();
        assert!(!is_allowed_navigation("https://hub.example", &candidate));
    }

    #[test]
    fn navigation_allows_http_only_for_localhost() {
        assert!(is_allowed_navigation(
            "http://localhost:58090",
            &Url::parse("http://localhost:58090/a").unwrap()
        ));
        assert!(!is_allowed_navigation(
            "https://hub.example",
            &Url::parse("http://hub.example/a").unwrap()
        ));
    }

    #[test]
    fn ids() {
        assert_eq!(default_worker_id("My PC!!"), "my-pc");
        assert!(validate_worker_id("pc"));
        assert!(!validate_worker_id("p"));
        assert!(!validate_worker_id(&"a".repeat(64)));
        assert!(validate_worker_id(&default_worker_id("A")));
    }
}
