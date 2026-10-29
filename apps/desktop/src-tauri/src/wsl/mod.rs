//! WSL integration used by the desktop shell.
//!
//! The pure helpers in this module deliberately do not invoke a shell.  The
//! process-facing API uses fixed `wsl.exe` argument vectors, so secrets can be
//! supplied on stdin rather than becoming command-line arguments.

mod commands;
mod error;
mod machine;
mod redact;
mod validation;
pub mod wslconfig;

pub use commands::*;
pub use error::WslError;
pub use machine::{
    check_machine, cli_install, detect_existing, hub_reach, install_worker, logs, open_login,
    restart, stop_disable, unit_status, write_worker_token, Keepalive, MachineReport,
};
pub use redact::redact;
pub use validation::{
    default_worker_id, normalize_hub_url, unit_for, validate_engines, validate_unit_name,
    validate_worker_id, worker_token_path, worker_unit_name, EXISTING_UNIT,
};

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Distro {
    pub name: String,
    pub state: String,
    pub version: u8,
    #[serde(rename = "isDefault")]
    pub is_default: bool,
}

/// Decode the output of `wsl -l -v`, which is UTF-16LE on Windows but can be
/// UTF-8 when invoked through a test double or a newer WSL build.
pub fn parse_wsl_list(output: &str) -> Vec<Distro> {
    let bytes = output.as_bytes();
    let text = if bytes.len() >= 2 && bytes[0] == 0xff && bytes[1] == 0xfe {
        let (decoded, _, _) = encoding_rs::UTF_16LE.decode(&bytes[2..]);
        decoded.into_owned()
    } else if output.chars().take(32).any(|c| c == '\0') {
        output.replace('\0', "")
    } else {
        output.to_owned()
    };

    decoded_distro_lines(&text)
}

fn decoded_distro_lines(text: &str) -> Vec<Distro> {
    let mut result = Vec::new();
    for raw in text.lines() {
        let line = raw.trim_end_matches('\r');
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with("NAME") || trimmed.starts_with("---") {
            continue;
        }
        let is_default = trimmed.starts_with('*');
        let without_marker = trimmed.trim_start_matches('*').trim();
        let fields: Vec<&str> = without_marker.split_whitespace().collect();
        if fields.len() < 3 {
            continue;
        }
        let version = match fields.last().and_then(|v| v.parse::<u8>().ok()) {
            Some(v) => v,
            None => continue,
        };
        let state = fields[fields.len() - 2].to_owned();
        let name = fields[..fields.len() - 2].join(" ");
        if !name.is_empty() {
            result.push(Distro {
                name,
                state,
                version,
                is_default,
            });
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_utf8_and_default() {
        let value = "NAME STATE VERSION\n* Ubuntu-24.04 Running 2\n  Debian Stopped 2\n";
        let distros = parse_wsl_list(value);
        assert_eq!(distros[0].name, "Ubuntu-24.04");
        assert!(distros[0].is_default);
        assert_eq!(distros[1].state, "Stopped");
    }

    #[test]
    fn parses_utf16le() {
        let text = "NAME STATE VERSION\r\n* Ubuntu Running 2\r\n";
        let mut bytes = vec![0xff, 0xfe];
        for unit in text.encode_utf16() {
            bytes.extend_from_slice(&unit.to_le_bytes());
        }
        let value = String::from_utf16_lossy(
            &bytes[2..]
                .as_chunks::<2>()
                .0
                .iter()
                .map(|x| u16::from_le_bytes(*x))
                .collect::<Vec<_>>(),
        );
        assert_eq!(parse_wsl_list(&value)[0].name, "Ubuntu");
    }

    #[test]
    fn command_vectors_never_contain_token() {
        let token = "super-secret-token";
        let command = build_write_token_command("Ubuntu", "pc-1").unwrap();
        assert!(!command.args.iter().any(|arg| arg.contains(token)));
        assert!(!redact(&format!(
            "Bearer {token} password={token} worker_token: \"{token}\""
        ))
        .contains(token));
    }
}
