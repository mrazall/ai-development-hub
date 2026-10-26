# MCP installation

Install only on an explicitly approved worker. This change does not install anything on a real machine.

```bash
cd packages/mcp-knowledge
python3 -m venv .venv
PIP_CACHE_DIR=.cache/pip .venv/bin/pip install -e '.[dev]'
export AIHUB_KNOWLEDGE_URL=http://127.0.0.1:8001
export AIHUB_PRINCIPAL='<signed value supplied by control-plane>'
.venv/bin/aihub-knowledge-mcp
```

The principal is injected at runtime and is never put in a `.mcp.json`, Vault document, or command-line argument. The control-plane configuration generator should emit the command with an allowlisted project working directory and runtime environment.

For stdio clients, the generated server entry is conceptually:

```json
{"mcpServers":{"aihub-knowledge":{"command":"/path/to/packages/mcp-knowledge/.venv/bin/aihub-knowledge-mcp","env":{"AIHUB_KNOWLEDGE_URL":"http://127.0.0.1:8001"}}}}
```

Do not inline a principal or API/database secret in this file.
