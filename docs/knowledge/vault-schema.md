# Vault schema

`AI-Knowledge/` is a Markdown Vault. Documents are data, never executable instructions. The service treats retrieved text as untrusted content and does not promote it to system or tool instructions.

The standard layout is `00-System/`, `01-Projects/<project-id>/` (with `overview/`, `architecture/`, `decisions/`, `tasks/`, `handoffs/`, `incidents/`, and `runbooks/`), `02-Shared-Patterns/`, and `03-Research/`.

Every indexed Markdown file starts with YAML frontmatter:

```yaml
id: project-alpha-overview
project_id: project-alpha
type: overview
title: Project Alpha
updated_at: 2026-10-23T12:00:00Z
source: human
source_commit: abc123
status: active
visibility: private
schema_version: 1
```

`id`, `type`, `title`, `updated_at`, `source`, `status`, `visibility`, and `schema_version` are required. Shared documents may omit `project_id`. Invalid documents, files containing credentials/private keys, and excluded paths are reported and never indexed. `.aihubignore` contains one relative path/name per line; blank lines and `#` comments are ignored.
