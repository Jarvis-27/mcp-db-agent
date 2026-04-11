import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Load .env so AUTH_DATABASE_URL is available when running alembic from the CLI
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Set up logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pull the auth DB URL from the environment, falling back to alembic.ini
_auth_url = os.environ.get("AUTH_DATABASE_URL")
if _auth_url:
    config.set_main_option("sqlalchemy.url", _auth_url)

# Import our models so autogenerate can detect schema changes
from src.auth.user_store import Base as AuthBase  # noqa: E402

target_metadata = AuthBase.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL output only, no live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER support
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
