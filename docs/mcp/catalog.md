# MCP catalog (checked 2026-10-23)

This is a review list, not an installation action. Versions must be pinned at deployment time and checked against the upstream release and license.

| Server | Source | License / version checked | Support / permissions |
|---|---|---|---|
| Filesystem | `@modelcontextprotocol/server-filesystem` (official MCP servers) | MIT; `2.0.0` | maintained upstream; project allowlisted directories only |
| GitHub | `github/github-mcp-server` | repository license/release must be pinned at deployment | official GitHub server; read-only scopes by default, token via `${GITHUB_TOKEN}` |
| Playwright | `@playwright/mcp` | Apache-2.0; `0.0.83` | Microsoft-maintained; browser only, no filesystem or secrets |
| Context7 | `@upstash/context7-mcp` | MIT; `4.4.4` | Upstash-maintained; outbound documentation lookup only |
| PostgreSQL | `microsoft/postgres-mcp` / `@microsoft/postgres-mcp` | MIT; current upstream README checked 2026-10-23 | supported replacement; query tool is read-only, but writes are available unless the profile is configured `accessMode=ro`; use a separate least-privilege PostgreSQL role; seed disabled |
| Knowledge | this repository, `packages/mcp-knowledge` | MIT; `mcp==1.30.0` | local service; principal ACL, writes are drafts only |

Sources checked: [filesystem npm](https://www.npmjs.com/package/@modelcontextprotocol/server-filesystem), [Playwright MCP npm](https://www.npmjs.com/package/@playwright/mcp), [Context7 package](https://github.com/upstash/context7/tree/master/packages/mcp), [Microsoft postgres-mcp README](https://github.com/microsoft/postgres-mcp/blob/main/README.md), [Microsoft usage/security guide](https://github.com/microsoft/postgres-mcp/blob/main/USAGE.md), and [archived PostgreSQL server](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres). Microsoft’s server is the selected replacement because it is MIT, maintained upstream, supports PostgreSQL and exposes an unconditional read-only query tool. It is not intrinsically an authorization boundary: deployment must pin a release, set the connection/profile to read-only, and use a database role with only the required SELECT privileges. The registry seed remains enabled=false until deployment-time version and role review.
