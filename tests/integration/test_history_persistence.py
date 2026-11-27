import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from themed_chat.app import Overrides, create_app
from themed_chat.chat.service import GenerationTimeout
from themed_chat.settings import (
    AppSettings,
    ModelSettings,
    SecretSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:8000"
LOGIN = {"Origin": ORIGIN, "X-Access-Key": "history_test_key"}


class FixtureGenerator:
    async def generate(self, text: str) -> str:
        if text == "simulate timeout":
            raise GenerationTimeout("Test provider timeout.")
        return f"Reply: {text}"


@pytest.mark.anyio
async def test_history_is_atomic_shared_and_persistent(postgres_dsn: SecretStr) -> None:
    settings = Settings(
        AppSettings(
            llm=ModelSettings(
                base_url="https://unused.test/v1", model="fixture", system_prompt="fixture"
            )
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("history_test_key"),
            APP_SESSION_SECRET=SecretStr("session-secret-for-the-persistence-fixture"),
            LLM_API_KEY=SecretStr("unused-provider-key"),
            DATABASE_URL=postgres_dsn,
        ),
    )
    app = create_app(settings, Overrides(generator=FixtureGenerator()))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as alice,
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as bob,
    ):
        assert (await alice.post("/api/session", headers=LOGIN)).status_code == 204
        assert (await bob.post("/api/session", headers=LOGIN)).status_code == 204
        responses = await asyncio.gather(
            alice.post("/api/messages", headers={"Origin": ORIGIN}, json={"text": "first"}),
            bob.post("/api/messages", headers={"Origin": ORIGIN}, json={"text": "second"}),
        )
        assert [r.status_code for r in responses] == [201, 201]
        history = (await alice.get("/api/messages")).json()["messages"]
        other = (await bob.get("/api/messages")).json()["messages"]
        assert [m["id"] for m in history] == [m["id"] for m in other]
        failed = await alice.post(
            "/api/messages", headers={"Origin": ORIGIN}, json={"text": "simulate timeout"}
        )
        assert failed.status_code == 504
        assert len(history) == 4
        assert sum(m["is_mine"] for m in history) == 1
        assert all(m["created_at"].endswith("Z") for m in history)
        assert history[1]["text"] == f"Reply: {history[0]['text']}"
        assert history[3]["text"] == f"Reply: {history[2]['text']}"
        cookies = alice.cookies

    restarted = create_app(settings, Overrides(generator=FixtureGenerator()))
    async with (
        restarted.router.lifespan_context(restarted),
        AsyncClient(transport=ASGITransport(restarted), base_url=ORIGIN, cookies=cookies) as client,
    ):
        after_restart = (await client.get("/api/messages")).json()["messages"]
        assert after_restart[:4] == history
        # The timed-out question is stored as a failed turn, without an answer.
        [failed_turn] = after_restart[4:]
        assert (failed_turn["text"], failed_turn["status"]) == ("simulate timeout", "failed")


@pytest.mark.anyio
async def test_sql_history_is_paged_by_turn_id(postgres_dsn: SecretStr) -> None:
    settings = Settings(
        AppSettings(
            llm=ModelSettings(
                base_url="https://unused.test/v1", model="fixture", system_prompt="fixture"
            )
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("history_test_key"),
            APP_SESSION_SECRET=SecretStr("session-secret-for-the-persistence-fixture"),
            LLM_API_KEY=SecretStr("unused-provider-key"),
            DATABASE_URL=postgres_dsn,
        ),
    )
    app = create_app(settings, Overrides(generator=FixtureGenerator()))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as client,
    ):
        await client.post("/api/session", headers=LOGIN)
        for number in range(1, 6):
            sent = await client.post(
                "/api/messages", headers={"Origin": ORIGIN}, json={"text": f"q{number}"}
            )
            assert sent.status_code == 201

        async def page(**params: int) -> tuple[list[str], bool]:
            body = (await client.get("/api/messages", params=params)).json()
            questions = [m["text"] for m in body["messages"] if m["role"] == "user"]
            return questions, body["has_more"]

        assert await page(limit=2) == (["q4", "q5"], True)
        newest = (await client.get("/api/messages", params={"limit": 2})).json()["messages"]
        assert await page(limit=2, before=newest[0]["turn_id"]) == (["q2", "q3"], True)
        assert await page(limit=2, before=2) == (["q1"], False)
        assert await page(limit=2, after_revision=2) == (["q3", "q4"], True)
        assert await page(limit=2, after_revision=4) == (["q5"], False)
        assert await page(after_revision=5) == ([], False)
        assert await page() == (["q1", "q2", "q3", "q4", "q5"], False)


def sql_settings(postgres_dsn: SecretStr) -> Settings:
    return Settings(
        AppSettings(
            llm=ModelSettings(
                base_url="https://unused.test/v1", model="fixture", system_prompt="fixture"
            )
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("history_test_key"),
            APP_SESSION_SECRET=SecretStr("session-secret-for-the-persistence-fixture"),
            LLM_API_KEY=SecretStr("unused-provider-key"),
            DATABASE_URL=postgres_dsn,
        ),
    )


class GatedGenerator:
    """Answers "slow" only after "fast" has been answered."""

    def __init__(self) -> None:
        self.fast_done = asyncio.Event()

    async def generate(self, text: str) -> str:
        if text == "slow":
            await self.fast_done.wait()
        else:
            self.fast_done.set()
        return f"Reply: {text}"


@pytest.mark.anyio
async def test_out_of_order_completion_is_shown_by_question_time_and_polled(
    postgres_dsn: SecretStr,
) -> None:
    generator = GatedGenerator()
    app = create_app(sql_settings(postgres_dsn), Overrides(generator=generator))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as client,
    ):
        await client.post("/api/session", headers=LOGIN)
        cursor = (await client.get("/api/messages")).json()["revision"]
        slow = asyncio.create_task(
            client.post("/api/messages", headers={"Origin": ORIGIN}, json={"text": "slow"})
        )
        await asyncio.sleep(0.05)  # "slow" is asked first.
        fast = await client.post("/api/messages", headers={"Origin": ORIGIN}, json={"text": "fast"})
        assert fast.status_code == 201
        first_poll = (await client.get("/api/messages", params={"after_revision": cursor})).json()
        assert (await slow).status_code == 201
        second_poll = (
            await client.get("/api/messages", params={"after_revision": first_poll["revision"]})
        ).json()
        polled = [
            m["text"]
            for m in first_poll["messages"] + second_poll["messages"]
            if m["role"] == "user"
        ]
        assert polled == ["fast", "slow"]  # Nothing is skipped.
        shown = (await client.get("/api/messages")).json()["messages"]
        assert [m["text"] for m in shown if m["role"] == "user"] == ["slow", "fast"]


@pytest.mark.anyio
async def test_concurrent_writes_commit_in_revision_order(postgres_dsn: SecretStr) -> None:
    class Echo:
        async def generate(self, text: str) -> str:
            return text

    app = create_app(sql_settings(postgres_dsn), Overrides(generator=Echo()))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as client,
    ):
        await client.post("/api/session", headers=LOGIN)
        seen: dict[int, str] = {}
        cursor = 0

        async def poll() -> None:
            nonlocal cursor
            body = (await client.get("/api/messages", params={"after_revision": cursor})).json()
            for message in body["messages"]:
                seen[message["turn_id"]] = message["text"]
            cursor = body["revision"]

        async def send(number: int) -> None:
            await client.post(
                "/api/messages", headers={"Origin": ORIGIN}, json={"text": f"{number}"}
            )

        for _ in range(5):
            await asyncio.gather(*(send(n) for n in range(6)), poll(), poll())
        await poll()
        all_turns = (await client.get("/api/messages", params={"limit": 100})).json()["messages"]
        assert set(seen) == {m["turn_id"] for m in all_turns}


@pytest.mark.anyio
async def test_sql_sessions_are_revoked_on_logout_and_deleted_with_the_guest(
    postgres_dsn: SecretStr,
) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    app = create_app(sql_settings(postgres_dsn), Overrides(generator=FixtureGenerator()))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as client,
    ):
        await client.post("/api/session", headers=LOGIN)
        stolen = client.cookies["chat_session"]
        await client.delete("/api/session", headers={"Origin": ORIGIN})
        client.cookies.set("chat_session", stolen, domain="127.0.0.1", path="/api")
        assert (await client.get("/api/messages")).status_code == 401

        await client.post("/api/session", headers=LOGIN)
        assert (await client.get("/api/messages")).status_code == 200
        engine = create_async_engine(postgres_dsn.get_secret_value())
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM chat_turns"))
                await connection.execute(text("DELETE FROM users"))
                remaining = await connection.scalar(text("SELECT count(*) FROM sessions"))
        finally:
            await engine.dispose()
        assert remaining == 0  # ON DELETE CASCADE
        assert (await client.get("/api/messages")).status_code == 401


@pytest.mark.anyio
async def test_migration_keeps_existing_turns_in_revision_order(postgres_dsn: SecretStr) -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import themed_chat

    def upgrade(connection: object, target: str) -> None:
        config = Config()
        location = Path(themed_chat.__file__).resolve().parent / "migrations"
        config.set_main_option("script_location", str(location))
        config.attributes["connection"] = connection
        command.upgrade(config, target)

    engine = create_async_engine(postgres_dsn.get_secret_value())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(upgrade, "0002_chat_turns")
            await connection.execute(
                text("INSERT INTO users VALUES ('00000000-0000-0000-0000-000000000001', now())")
            )
            for question in ("old-1", "old-2"):
                await connection.execute(
                    text(
                        "INSERT INTO chat_turns (user_id, question, answer, question_at, answer_at)"
                        " VALUES ('00000000-0000-0000-0000-000000000001', :q, 'a', now(), now())"
                    ),
                    {"q": question},
                )
            await connection.run_sync(upgrade, "head")
            rows = (
                await connection.execute(
                    text("SELECT question, status, revision FROM chat_turns ORDER BY id")
                )
            ).all()
            next_revision = await connection.scalar(
                text("SELECT nextval('chat_turns_revision_seq')")
            )
    finally:
        await engine.dispose()
    assert [tuple(row) for row in rows] == [("old-1", "answered", 1), ("old-2", "answered", 2)]
    assert next_revision == 3
