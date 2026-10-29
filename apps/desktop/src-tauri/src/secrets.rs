pub fn redact(value: &str) -> String {
    let mut result = value.to_string();
    for key in [
        "password",
        "token",
        "access_token",
        "worker_token",
        "authorization",
    ] {
        let lower = result.to_ascii_lowercase();
        if let Some(pos) = lower.find(key) {
            if let Some(colon) = result[pos..].find(':') {
                let start = pos + colon + 1;
                let end = result[start..]
                    .find([',', '}', ' ', '\n'])
                    .map(|n| start + n)
                    .unwrap_or(result.len());
                result.replace_range(start..end, "[REDACTED]");
            }
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn no_secret_in_redacted_output() {
        let s = redact("password:super-secret token:abc123");
        assert!(!s.contains("super-secret"));
        assert!(!s.contains("abc123"));
    }
    #[test]
    fn settings_have_no_secret_fields() {
        let settings = crate::types::Settings::default();
        let encoded = serde_json::to_string(&settings).unwrap();
        assert!(!encoded.contains("token"));
        assert!(!encoded.contains("password"));
    }
}
