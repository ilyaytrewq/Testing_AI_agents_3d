from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from themed_chat.settings import ConfigurationError, Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    secret = settings.secrets.database_url
    try:
        url = make_url(secret.get_secret_value())
        if (
            url.drivername != "postgresql+asyncpg"
            or not url.database
            or (url.port is not None and not 1 <= url.port <= 65535)
            or url.query.keys() - {"ssl"}
            or url.query.get("ssl", "prefer")
            not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        ):
            raise ValueError("invalid PostgreSQL connection options")
        return create_async_engine(url, hide_parameters=True, pool_pre_ping=True)
    except (ArgumentError, ValueError):
        raise ConfigurationError(
            "DATABASE_URL must use postgresql+asyncpg and may only specify the ssl query option."
        ) from None


def _upgrade(connection: Connection) -> None:
    config = Config()
    script_directory = str(Path(__file__).resolve().parents[1] / "migrations")
    config.set_main_option("script_location", script_directory.replace("%", "%%"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def migrate_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
