use regex::Regex;

pub fn redact(input: &str) -> String {
    let mut value = input.to_owned();
    for pattern in [
        r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+",
        r"(?i)(password\s*[=:]\s*)([^\s,;}&]+)",
        r#"(?i)(worker[_-]?token\s*[=:]\s*["']?)([^\s,;}&"']+)"#,
        r#"(?i)(["']worker[_-]?token["']\s*:\s*["'])([^"']+)(["'])"#,
    ] {
        let re = Regex::new(pattern).unwrap();
        value = re
            .replace_all(&value, |caps: &regex::Captures| {
                if caps.len() == 1 {
                    "[REDACTED]".to_owned()
                } else if caps.len() == 4 {
                    format!("{}[REDACTED]{}", &caps[1], &caps[3])
                } else {
                    format!("{}[REDACTED]", &caps[1])
                }
            })
            .into_owned();
    }
    value
}

#[cfg(test)]
mod tests {
    use super::redact;
    #[test]
    fn masks_common_secret_forms() {
        let result = redact(r#"Bearer abc.def password=xyz worker_token: "json-secret""#);
        assert!(
            !result.contains("abc.def")
                && !result.contains("xyz")
                && !result.contains("json-secret")
        );
        assert!(result.contains("[REDACTED]"));
    }
}
