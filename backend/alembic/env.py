"""Load application metadata and settings for user-run migrations."""

from logging.config import fileConfig

from alembic import context
from backend.config import Settings
from backend.database import create_database_engine
from backend.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Creating an engine does not connect. Keep credentials out of the INI file
    # and avoid string interpolation of passwords containing percent signs.
    engine = create_database_engine(Settings())
    try:
        context.configure(
            url=engine.url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        engine.dispose()


def run_migrations_online() -> None:
    engine = create_database_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
