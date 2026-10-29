use super::WslError;
use std::fs;
use std::path::{Path, PathBuf};

// Where WSL reads each setting (WSL 2.5.4+): the distro idle timeout is a [general] key, the VM one a [wsl2]
// key. A key in the wrong section is ignored by WSL, so it neither counts as set nor is written there.
const KEYS: [(&str, &str); 2] = [
    ("general", "instanceIdleTimeout"),
    ("wsl2", "vmIdleTimeout"),
];

fn section_name(line: &str) -> Option<String> {
    let t = line.trim();
    (t.starts_with('[') && t.ends_with(']')).then(|| t[1..t.len() - 1].trim().to_ascii_lowercase())
}

/// The value of `key` in `[section]`, if present.
fn value_in(lines: &[String], section: &str, key: &str) -> Option<String> {
    let mut current = String::new();
    for line in lines {
        if let Some(name) = section_name(line) {
            current = name;
            continue;
        }
        let mut parts = line.splitn(2, '=');
        let k = parts.next().unwrap_or("").trim();
        if current == section && k.eq_ignore_ascii_case(key) {
            return Some(parts.next().unwrap_or("").trim().to_owned());
        }
    }
    None
}

/// Whether instanceIdleTimeout and vmIdleTimeout are set to -1 (never stop) in their sections.
pub fn status(input: &str) -> (bool, bool) {
    let lines: Vec<String> = input.lines().map(str::to_owned).collect();
    let ok = |(section, key): (&str, &str)| value_in(&lines, section, key).as_deref() == Some("-1");
    (ok(KEYS[0]), ok(KEYS[1]))
}

/// Add the missing keys (=-1) to their sections, creating a section when needed. Existing lines — including
/// a key with another value — are left as they are.
pub fn patch(input: &str) -> (String, bool) {
    let mut lines: Vec<String> = input.lines().map(str::to_owned).collect();
    let had_trailing_newline = input.ends_with('\n');
    let mut changed = false;
    for (section, key) in KEYS {
        if value_in(&lines, section, key).is_some() {
            continue;
        }
        let entry = format!("{key}=-1");
        match lines
            .iter()
            .position(|line| section_name(line).as_deref() == Some(section))
        {
            Some(i) => lines.insert(i + 1, entry),
            None => {
                if lines.last().is_some_and(|line| !line.trim().is_empty()) {
                    lines.push(String::new());
                }
                lines.push(format!("[{section}]"));
                lines.push(entry);
            }
        }
        changed = true;
    }
    let mut output = lines.join("\n");
    if had_trailing_newline || changed {
        output.push('\n');
    }
    (output, changed)
}

pub fn backup_and_patch(path: impl AsRef<Path>) -> Result<(PathBuf, bool), WslError> {
    let path = path.as_ref();
    let original = fs::read_to_string(path)?;
    let (updated, changed) = patch(&original);
    if !changed {
        return Ok((path.with_extension("bak"), false));
    }
    let backup = next_backup(path);
    fs::copy(path, &backup)?;
    fs::write(path, updated)?;
    Ok((backup, true))
}

/// Explicitly named alias for callers that treat this as a file-writing
/// operation rather than a generic patch.
pub fn patch_file(path: impl AsRef<Path>) -> Result<(PathBuf, bool), WslError> {
    backup_and_patch(path)
}

fn next_backup(path: &Path) -> PathBuf {
    let base = path.with_extension("bak");
    if !base.exists() {
        return base;
    }
    for n in 1..10_000 {
        let candidate = path.with_extension(format!("bak.{n}"));
        if !candidate.exists() {
            return candidate;
        }
    }
    base
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn owner_file_is_already_ok() {
        // The file on the owner's PC: both keys set, each in its own section.
        let input = "[general]
instanceIdleTimeout=-1

[wsl2]
vmIdleTimeout=-1
";
        assert_eq!(status(input), (true, true));
        assert_eq!(patch(input), (input.to_owned(), false));
    }

    #[test]
    fn keys_go_to_their_sections() {
        let (out, changed) = patch(
            "[wsl2]
memory=8GB
",
        );
        assert!(changed);
        assert_eq!(status(&out), (true, true));
        assert!(out.contains(
            "[general]
instanceIdleTimeout=-1"
        ));
        assert!(out.contains(
            "[wsl2]
vmIdleTimeout=-1
memory=8GB"
        ));
    }

    #[test]
    fn key_in_the_wrong_section_does_not_count() {
        assert_eq!(
            status(
                "[wsl2]
instanceIdleTimeout=-1
vmIdleTimeout=-1
"
            ),
            (false, true)
        );
    }

    #[test]
    fn existing_values_are_not_overwritten() {
        let input = "[general]
instanceIdleTimeout=42
";
        let (out, _) = patch(input);
        assert!(out.contains("instanceIdleTimeout=42"));
        assert_eq!(out.matches("instanceIdleTimeout").count(), 1);
        assert_eq!(status(&out), (false, true));
    }

    #[test]
    fn empty_file_gets_both_sections() {
        let (out, changed) = patch("");
        assert!(changed);
        assert_eq!(status(&out), (true, true));
    }
}
