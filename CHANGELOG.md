# Changelog

## Unreleased

- Windows desktop installer documentation, a manual-only NSIS build workflow, and a WSL local build script.

## 0.1.0-alpha — first public release

- Workspace: agent sessions on your own machines (Claude Code, Codex, mock engines) with live output, a shell,
  chat, events, file changes and attachments; auto-resume when a subscription limit refills.
- Orchestration: a Claude orchestrator plans and hands work to Codex executors on separate git branches, with
  usage per executor and optional manual merge approval.
- Chats with access to your knowledge base through MCP; agents propose notes as drafts that a person applies
  (a git commit that can be reverted).
- Knowledge: Obsidian vault indexing, hybrid search and a link graph.
- Accounts and limits of Claude/Codex subscriptions, notifications, backups, a system health page.
- Settings in the panel, English and Russian UI, a one-command demo (`scripts/quickstart.sh --demo`).
