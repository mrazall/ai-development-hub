# Security

AI Development Hub lets AI agents run commands on your machines. Read this before you connect a worker
or make the panel reachable from anywhere but your own computer.

## Reporting a vulnerability

Please use **GitHub → Security → Report a vulnerability** (private advisory) on this repository. Do not open a
public issue. Include what an attacker needs (network position, account role) and what they gain. Expect a
first answer within a week; this is a small project maintained in spare time.

## What it is designed for

One owner (or a small trusted team) running the hub on a private network — a laptop, a home server behind
Tailscale or WireGuard — and connecting their own workstations as workers. It is **not** hardened as a
multi-tenant or internet-facing service.

## Threat model

### Assets

- Code and files in the project folders on workers.
- The knowledge vault (your notes) and its index.
- Credentials: hub user passwords, worker tokens, short-lived agent tokens, the signing keys of the hub,
  and the CLI logins of Claude Code / Codex that live on the workers.
- Subscription limits of your AI accounts.

### Trust boundaries

| Component | Trusted with | Notes |
|---|---|---|
| Hub (control plane, knowledge, Postgres, Qdrant) | everything it stores | Keep it on `127.0.0.1` or a private network. |
| Worker | full shell on its machine | Runs agent CLIs as **your user**. A compromised hub can make every connected worker run commands. |
| Agent (Claude Code / Codex) | the project folder | Follows instructions from prompts **and** from files, web pages and notes it reads. |
| Browser | the user's session | Token in memory/storage of the panel origin; CSP restricts scripts and frames. |

### What protects you

- **Authentication.** Passwords are hashed with Argon2. User and agent access tokens are short-lived
  (`AIHUB_ACCESS_TOKEN_TTL_S`, 1 h by default); workers renew agent tokens. Worker tokens are shown once and
  stored only as hashes.
- **Roles.** `admin` changes things; `viewer` is read-only. Agents get scoped tokens that reach only their own
  session, orchestration and knowledge tools.
- **Secrets stay out of the database and the UI.** Signing keys and database passwords are files with mode
  0600 mounted as Docker secrets, never environment values in Git. Agent output is passed through a redaction
  filter (API keys, tokens, private keys, high-entropy strings) before it is stored or shown.
- **Folders.** A session's working directory must be inside the project's allowed paths; the worker refuses
  anything else. Claude Code runs with `acceptEdits` (no blanket bypass); Codex runs with its
  `workspace-write` sandbox.
- **Notes.** The vault is mounted read-only into the knowledge service; agents can only write drafts into
  `_Агенты/`, and nothing reaches the vault until a person presses *Apply*. Applying is a git commit that
  can be reverted.
- **Network.** Compose binds ports to `127.0.0.1`. The panel sends a strict Content Security Policy;
  embedded terminals are allowed only from `AIHUB_FRAME_SRC`.
- **Supply chain.** Images and Python/JS dependencies are pinned; CI runs a secrets scan on every push.

### What does not protect you (known limits)

- **Agents are not sandboxed by this project.** Folder scoping is checked when a session starts; inside it an
  agent can run whatever its CLI allows, including network access and reading files your user can read. Use a
  dedicated OS user, a VM or a container for workers when that matters.
- **Prompt injection.** Text an agent reads (a README, an issue, a web page, a note) can steer it. Do not point
  agents at untrusted repositories with your main account logged in.
- **No login rate limiting** in the hub itself. Do not expose the panel to the internet; put it behind
  Tailscale/WireGuard or an authenticating proxy.
- **The hub is a single point of trust.** Whoever is admin of the hub can run code on every worker.
- **Backups contain your data.** `infra/backup` encrypts with restic; keep the repository password separate.

## Provider terms

The hub drives the official `claude` and `codex` CLIs logged in on your own machines, the way you would run
them by hand. It does not extract tokens, call private APIs or work around rate limits. Whether a given use
(sharing one subscription between people, commercial or automated use) is allowed is between you and your
provider — check their terms.

## Deployment checklist

- [ ] The panel is reachable only on `127.0.0.1` or your private network (`tailscale serve`, never `funnel`).
- [ ] The first admin password was changed and stored in a password manager.
- [ ] Workers run as a user that should be allowed to do what agents do.
- [ ] Projects have narrow allowed paths; secrets (`.env`, keys) are not inside them.
- [ ] Backups are configured and a restore was tested.
