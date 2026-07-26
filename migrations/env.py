"""Alembic environment.

The URL comes from DATABASE_URL rather than alembic.ini so migrations run
against whatever the app is pointed at — including the throwaway databases the
test suite creates.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import database_url
from app.models import metadata

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False, or running migrations programmatically
    # (init_db does, on every startup and every test) silently switches off
    # every logger the app already configured.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", database_url())
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
