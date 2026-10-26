from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from aihub_knowledge.config import database_url, get_settings
from aihub_knowledge.db import Base

config = context.config
target_metadata = Base.metadata
# ConfigParser interpolation: URL-encoded passwords contain "%", which must be escaped as "%%".
config.set_main_option("sqlalchemy.url", database_url(get_settings()).replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema="knowledge",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS knowledge")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="knowledge",
            include_schemas=True,
        )
        context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
