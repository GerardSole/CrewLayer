import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from crewlayer.db.models import Base
from crewlayer.core.config import settings

target_metadata = Base.metadata

# Override sqlalchemy.url from settings — .env is the single source of truth
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

_CONFIGURE_ARGS = dict(
    target_metadata=target_metadata,
    compare_type=True,
    compare_server_default=True,
)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_CONFIGURE_ARGS,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, **_CONFIGURE_ARGS)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
