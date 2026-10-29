# Changelog

## 0.2.0-alpha — Windows app, accounts, staying signed in

- Windows desktop app (Tauri 2): a setup wizard for WSL and the worker, adoption of a worker installed by
  hand, a tray mark that animates while agents work, double click for the panel, the app's settings inside
  the panel's settings page. Updates are signed with your key and served by your own hub
  (`/desktop/latest.json`); the installer attached to this release has updates off until you set a key.
- Accounts: any number of Claude Code and Codex subscriptions, each in its own profile with shared history;
  continue a conversation on another account when one hits its limit; the panel shows who is signed in where.
- Signing in lasts until you sign out or 30 days without use (rotating device tokens in an httpOnly cookie).
- Sessions: a failed session can be marked «all good» so it stops showing as a problem.

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
