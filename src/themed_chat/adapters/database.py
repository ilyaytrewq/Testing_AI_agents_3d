from asyncio import to_thread
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Connection, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from themed_chat.settings import ConfigurationError, Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    db = settings.app.db
    if db.backend != "sqlite":
        raise ConfigurationError("This build currently supports the sqlite backend.")
    url = URL.create("sqlite+aiosqlite", database=str(db.sqlite_path.absolute()))
    engine = create_async_engine(url, hide_parameters=True)
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    return engine


def _enable_foreign_keys(connection: DBAPIConnection, _record: object) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _upgrade(connection: Connection) -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def migrate_database(engine: AsyncEngine) -> None:
    if engine.url.get_backend_name() == "sqlite" and engine.url.database is not None:
        directory = Path(engine.url.database).parent
        await to_thread(directory.mkdir, parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
