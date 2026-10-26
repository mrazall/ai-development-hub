import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from aihub_control.config import Settings, database_url
from aihub_control.db import Base
from aihub_control import models

config = context.config
settings = Settings()
# ConfigParser interpolation: URL-encoded passwords contain "%", which must be escaped as "%%".
config.set_main_option(
    "sqlalchemy.url", database_url(settings.database_url or "postgresql+psycopg://invalid").replace("%", "%%")
)
if config.config_file_name and config.get_section("loggers"):
    fileConfig(config.config_file_name)
target_metadata = Base.metadata
def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema="control",
    )
    with context.begin_transaction(): context.run_migrations()
def run_migrations_online():
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url(settings.database_url or "postgresql+psycopg://invalid")
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS control"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
            version_table="alembic_version",
            version_table_schema="control",
        )
        with context.begin_transaction(): context.run_migrations()
if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
