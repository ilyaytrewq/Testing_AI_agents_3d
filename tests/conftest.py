from collections.abc import AsyncIterator
from os import environ
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def postgres_dsn() -> AsyncIterator[SecretStr]:
    dsn = environ.get("TEST_POSTGRES_URL")
    if not dsn:
        pytest.fail("Set TEST_POSTGRES_URL to a dedicated PostgreSQL test server with CREATEDB.")
    admin_url = make_url(dsn)
    if admin_url.drivername != "postgresql+asyncpg":
        pytest.fail("TEST_POSTGRES_URL must use postgresql+asyncpg.")
    database = f"themed_chat_test_{uuid4().hex}"
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    try:
        async with admin.connect() as conn:
            await conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
        try:
            yield SecretStr(admin_url.set(database=database).render_as_string(hide_password=False))
        finally:
            async with admin.connect() as conn:
                await conn.exec_driver_sql(f'DROP DATABASE "{database}"')
    finally:
        await admin.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
