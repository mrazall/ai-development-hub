"""MCP server registry and project assignments."""

from alembic import op
import sqlalchemy as sa

revision = "0006_mcp_registry"
down_revision = "0005_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(63), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("license", sa.String(128), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("command", sa.JSON, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("project_ids", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("status_detail", sa.Text),
        sa.Column("tools", sa.JSON, nullable=False),
        schema="control",
    )
    servers = sa.table(
        "mcp_servers",
        sa.column("id", sa.String), sa.column("name", sa.String), sa.column("source", sa.Text),
        sa.column("version", sa.String), sa.column("license", sa.String), sa.column("transport", sa.String),
        sa.column("command", sa.JSON), sa.column("url", sa.Text), sa.column("scopes", sa.JSON),
        sa.column("project_ids", sa.JSON), sa.column("enabled", sa.Boolean), sa.column("status", sa.String),
        sa.column("status_detail", sa.Text), sa.column("tools", sa.JSON), schema="control",
    )
    op.bulk_insert(servers, [
        {"id": "filesystem", "name": "Filesystem", "source": "https://github.com/modelcontextprotocol/servers",
         "version": "2.0.0", "license": "MIT", "transport": "stdio",
         "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem@2.0.0"], "url": None,
         "scopes": ["fs:read", "fs:write"], "project_ids": [], "enabled": False, "status": "unknown",
         "status_detail": None, "tools": []},
        {"id": "github", "name": "GitHub", "source": "https://github.com/github/github-mcp-server",
         "version": "review-at-deploy", "license": "MIT", "transport": "stdio",
         "command": ["docker", "run", "-i", "--rm", "ghcr.io/github/github-mcp-server"], "url": None,
         "scopes": ["github:read"], "project_ids": [], "enabled": False, "status": "unknown",
         "status_detail": "Pin an immutable release and review permissions before enabling.", "tools": []},
        {"id": "playwright", "name": "Playwright", "source": "https://github.com/microsoft/playwright-mcp",
         "version": "0.0.83", "license": "Apache-2.0", "transport": "stdio",
         "command": ["npx", "-y", "@playwright/mcp@0.0.83"], "url": None,
         "scopes": ["browser"], "project_ids": [], "enabled": False, "status": "unknown",
         "status_detail": None, "tools": []},
        {"id": "context7", "name": "Context7", "source": "https://github.com/upstash/context7",
         "version": "4.4.4", "license": "MIT", "transport": "http", "command": [],
         "url": "https://mcp.context7.com/mcp", "scopes": ["docs:read"], "project_ids": [],
         "enabled": False, "status": "unknown", "status_detail": None, "tools": []},
        {"id": "knowledge", "name": "AI Hub Knowledge", "source": "packages/mcp-knowledge",
         "version": "mcp==1.30.0", "license": "MIT", "transport": "stdio",
         "command": ["aihub-knowledge-mcp"], "url": None, "scopes": ["knowledge:read", "knowledge:draft"],
         "project_ids": [], "enabled": False, "status": "unknown", "status_detail": None, "tools": []},
        {"id": "postgres-readonly", "name": "PostgreSQL read-only", "source": "https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres",
         "version": "archived", "license": "MIT", "transport": "stdio",
         "command": ["mcp-server-postgres"], "url": None, "scopes": ["db:read"], "project_ids": [],
         "enabled": False, "status": "unknown", "status_detail": "Archived upstream; use only after independent review.", "tools": []},
    ])


def downgrade() -> None:
    op.drop_table("mcp_servers", schema="control")
