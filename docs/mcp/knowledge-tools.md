# Knowledge MCP tools

`packages/mcp-knowledge` is a thin official MCP SDK facade over the knowledge HTTP API. Set `AIHUB_KNOWLEDGE_URL` and the signed `AIHUB_PRINCIPAL` header value in the MCP process environment. The MCP process does not make ACL decisions: the knowledge service verifies the principal and applies project visibility filters.

| Tool | Input | Permission | HTTP mapping |
|---|---|---|---|
| `knowledge.search` | `{query, limit?}` | server ACL | `GET /search` |
| `knowledge.read` | `{document_id}` | server ACL; foreign private documents are 404 | `GET /documents/{id}` |
| `knowledge.context` | `{query, limit?}` | server ACL | search, then visible reads |
| `knowledge.decisions` | `{query?, limit?}` | server ACL | search with a decision query |
| `knowledge.index_status` | `{}` | service status | `GET /index/status` |
| `knowledge.handoff.create` | `{project_id, title, content}` | admin or project member | `POST /drafts`, handoff |
| `knowledge.handoff.get` | `{document_id}` | server ACL | document read |
| `knowledge.write_draft` | `{project_id, title, content}` | admin or project member | `POST /drafts`, draft |
| `knowledge.propose_update` | `{project_id, title, content}` | admin or project member | `POST /drafts`, proposal |

Input JSON Schema (the MCP SDK also publishes schemas from Python annotations):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$defs": {
    "search": {"type":"object","required":["query"],"properties":{"query":{"type":"string","minLength":1},"limit":{"type":"integer","minimum":1,"maximum":100,"default":10}},"additionalProperties":false},
    "read": {"type":"object","required":["document_id"],"properties":{"document_id":{"type":"string","minLength":1}},"additionalProperties":false},
    "write": {"type":"object","required":["project_id","title","content"],"properties":{"project_id":{"type":"string","pattern":"^[a-z0-9][a-z0-9-]{1,62}$"},"title":{"type":"string","minLength":1,"maxLength":200},"content":{"type":"string","minLength":1}},"additionalProperties":false}
  }
}
```

Writes never modify a critical source document: they create a Markdown file below `01-Projects/<project-id>/handoffs/`. A read-only Vault returns HTTP 409 with `vault is read-only`.
