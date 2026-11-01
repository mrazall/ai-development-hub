# Changelog

## 0.3.0-alpha — repository and GitHub, agents' instructions, efficiency

- Repository and GitHub tab per project: the commit graph with agents' branches, a commit's files, open pull
  requests with checks and review state, CI runs with their jobs; merge or close a pull request and re-run failed
  jobs after a confirmation. Data comes from the worker's own `gh` login and is cached by the hub; tokens are
  scrubbed from every answer. Notifications about a project go only to its members.
- Agents' instructions: edit `AGENTS.md`, `CLAUDE.md` and skills of a project or of a worker in the panel, with a
  preview and the exact diff before saving. Project files are committed one at a time, worker files keep their
  last 20 versions; a file changed on the worker in the meantime is never overwritten. File contents are not
  stored or logged by the hub.
- Statistics → Efficiency: cost, tokens and time per task, the orchestrator's share, why each run started, and
  observations about tasks that cost more than usual or kept retrying. The page loads in about a second.
- Sessions show the account next to the model; long tool sequences in chats and sessions fold into one step with
  the model's own description.
- Workers: Claude agents get a rule against wait loops that match their own command line (they hung for
  hours); GitHub data is collected in parallel (about 24 s → 6 s on a real repository); a limit message such as
  "you've hit your 5-hour limit" is recognised for auto-resume; Codex gets network access and the git
  directory of its worktree inside its sandbox.

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
