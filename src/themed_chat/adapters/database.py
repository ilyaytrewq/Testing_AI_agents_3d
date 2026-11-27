from asyncio import to_thread
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Connection, event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from themed_chat.settings import ConfigurationError, Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    db = settings.app.db
    secret = settings.secrets.database_url
    if db.backend == "sqlite" and secret is not None:
        raise ConfigurationError("DATABASE_URL cannot be used with an explicit SQLite backend.")
    if db.backend != "postgresql" and secret is None:
        if db.sqlite_path is None:
            raise ConfigurationError(
                "Set APP_DB__SQLITE_PATH for SQLite, or start the app with Docker Compose."
            )
        url = URL.create("sqlite+aiosqlite", database=str(db.sqlite_path.absolute()))
        engine = create_async_engine(url, hide_parameters=True)
        event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
        return engine
    if secret is None:
        raise ConfigurationError("DATABASE_URL is required with the postgresql backend.")
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


def _enable_foreign_keys(connection: DBAPIConnection, _record: object) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _upgrade(connection: Connection) -> None:
    config = Config()
    script_directory = str(Path(__file__).resolve().parents[1] / "migrations")
    config.set_main_option("script_location", script_directory.replace("%", "%%"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def migrate_database(engine: AsyncEngine) -> None:
    sqlite = engine.url.get_backend_name() == "sqlite"
    if sqlite and engine.url.database is not None:
        directory = Path(engine.url.database).parent
        await to_thread(directory.mkdir, parents=True, exist_ok=True)
    async with engine.begin() as connection:
        if sqlite:
            # sqlite3 legacy mode does not start a transaction before DDL on its own.
            await connection.exec_driver_sql("BEGIN IMMEDIATE")
        await connection.run_sync(_upgrade)
