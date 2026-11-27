import json
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from support import (
    LOGIN,
    ORIGIN,
    WRITE,
    MemoryStorage,
    StubGenerator,
    client_for,
    make_settings,
)

from themed_chat.app import create_app
from themed_chat.chat.service import GenerationError, GenerationTimeout
from themed_chat.settings import ChatSettings, ModelSettings


@pytest.mark.anyio
async def test_authorized_guest_can_send_and_read_shared_history() -> None:
    storage, generator = MemoryStorage(), StubGenerator()
    app = create_app(make_settings(), storage.overrides(generator))
    async with (
        AsyncClient(
            transport=ASGITransport(app, raise_app_exceptions=False), base_url=ORIGIN
        ) as alice,
        client_for(app) as bob,
    ):
        assert (await alice.get("/api/messages")).status_code == 401
        assert (await alice.post("/api/session", headers=LOGIN)).status_code == 204
        invalid = await alice.post("/api/messages", headers=WRITE, json={"text": "   "})
        assert invalid.status_code == 422
        assert invalid.json() == {"error": {"code": "invalid_message"}}
        for malformed in (b'{"text":"\\ud800"}', b'{"text":1e400}', b'{"text":"x","user_id":"y"}'):
            response = await alice.post(
                "/api/messages",
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                content=malformed,
            )
            assert response.status_code == 422
            assert response.json() == {"error": {"code": "invalid_request"}}
        assert not generator.inputs
        generator.reply = "\ud800"
        rejected = await alice.post("/api/messages", headers=WRITE, json={"text": "Rejected"})
        assert rejected.status_code == 502
        # A failed turn keeps the question, marked as unanswered.
        failed_history = await alice.get("/api/messages")
        assert failed_history.status_code == 200
        body = failed_history.json()
        assert (body["title"], body["has_more"], body["revision"]) == ("Кофейный бариста", False, 1)
        [failed] = body["messages"]
        assert (failed["role"], failed["text"], failed["status"]) == ("user", "Rejected", "failed")
        generator.reply = "Start with 18 grams."
        sent = await alice.post("/api/messages", headers=WRITE, json={"text": "Espresso ratio?"})
        assert sent.status_code == 201
        assert sent.json()["messages"][0]["is_mine"] is True
        assert (await bob.post("/api/session", headers=LOGIN)).status_code == 204
        history = await bob.get("/api/messages")
        messages = history.json()["messages"]
        assert [m["text"] for m in messages] == [
            "Rejected",
            "Espresso ratio?",
            "Start with 18 grams.",
        ]
        assert [m["turn_id"] for m in messages] == [1, 2, 2]
        assert [m["status"] for m in messages] == ["failed", "answered", "answered"]
        assert messages[1]["is_mine"] is False
        assert messages[1]["question_at"] == messages[2]["question_at"]
        assert datetime.fromisoformat(messages[0]["created_at"]).utcoffset() is not None
    assert generator.inputs == ["Rejected", "Espresso ratio?"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (GenerationTimeout("slow"), 504, "model_timeout"),
        (GenerationError("broken"), 502, "model_unavailable"),
    ],
)
async def test_model_failures_map_to_error_codes_and_save_a_failed_turn(
    error: GenerationError, status: int, code: str
) -> None:
    storage, generator = MemoryStorage(), StubGenerator()
    generator.error = error
    app = create_app(make_settings(), storage.overrides(generator))
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        response = await client.post("/api/messages", headers=WRITE, json={"text": "Hi"})
    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}
    [turn] = storage.turns
    assert (turn.question, turn.answer, turn.status) == ("Hi", None, "failed")


@pytest.mark.anyio
async def test_messages_are_rate_limited_per_guest() -> None:
    storage, generator = MemoryStorage(), StubGenerator()
    settings = make_settings(chat=ChatSettings(message_limit=2, message_window_seconds=60))
    app = create_app(settings, storage.overrides(generator))
    async with client_for(app) as alice, client_for(app) as bob:
        await alice.post("/api/session", headers=LOGIN)
        await bob.post("/api/session", headers=LOGIN)
        for _ in range(2):
            assert (
                await alice.post("/api/messages", headers=WRITE, json={"text": "Hi"})
            ).status_code == 201
        blocked = await alice.post("/api/messages", headers=WRITE, json={"text": "Hi"})
        assert blocked.status_code == 429
        assert blocked.json() == {"error": {"code": "too_many_requests"}}
        assert 1 <= int(blocked.headers["retry-after"]) <= 60
        assert len(generator.inputs) == 2
        # Another guest has their own allowance, and reading is not limited.
        assert (
            await bob.post("/api/messages", headers=WRITE, json={"text": "Hi"})
        ).status_code == 201
        assert (await alice.get("/api/messages")).status_code == 200


@pytest.mark.anyio
async def test_history_is_paged_by_turn_id() -> None:
    storage = MemoryStorage()
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        storage.add_turns(7, storage.guests[0])

        def ids(response: Response) -> list[int]:
            return [m["turn_id"] for m in response.json()["messages"] if m["role"] == "user"]

        latest = await client.get("/api/messages", params={"limit": 3})
        assert ids(latest) == [5, 6, 7] and latest.json()["has_more"] is True
        earlier = await client.get("/api/messages", params={"limit": 3, "before": 5})
        assert ids(earlier) == [2, 3, 4] and earlier.json()["has_more"] is True
        oldest = await client.get("/api/messages", params={"limit": 3, "before": 2})
        assert ids(oldest) == [1] and oldest.json()["has_more"] is False
        assert latest.json()["revision"] == 7
        newer = await client.get("/api/messages", params={"limit": 2, "after_revision": 2})
        assert ids(newer) == [3, 4] and newer.json()["has_more"] is True
        assert newer.json()["revision"] == 4
        tail = await client.get("/api/messages", params={"limit": 2, "after_revision": 5})
        assert ids(tail) == [6, 7] and tail.json()["has_more"] is False
        nothing = await client.get("/api/messages", params={"after_revision": 7})
        assert nothing.json()["messages"] == [] and nothing.json()["has_more"] is False
        assert nothing.json()["revision"] == 7
        everything = await client.get("/api/messages")
        assert ids(everything) == [1, 2, 3, 4, 5, 6, 7]
        assert everything.json()["has_more"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"before": 0}, {"after_revision": -1}]
    + [{"before": 2, "after_revision": 1}, {"after_revision": 2**63}]
    + [{"before": 2**31}, {"limit": "many"}],
)
async def test_bad_paging_parameters_are_rejected(params: dict[str, object]) -> None:
    app = create_app(make_settings(), MemoryStorage().overrides(StubGenerator()))
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        response = await client.get("/api/messages", params=params)  # type: ignore[arg-type]
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request"}}


@pytest.mark.anyio
async def test_every_api_error_uses_the_same_format() -> None:
    storage = MemoryStorage()
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        assert (await client.get("/api/missing")).status_code == 401
        await client.post("/api/session", headers=LOGIN)
        unknown = await client.get("/api/missing")
        assert unknown.status_code == 404
        assert unknown.json() == {"error": {"code": "not_found"}}
        wrong_method = await client.put("/api/messages", headers=WRITE)
        assert wrong_method.status_code == 405
        assert wrong_method.json() == {"error": {"code": "method_not_allowed"}}
        assert wrong_method.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_unexpected_errors_become_internal_error() -> None:
    storage = MemoryStorage()

    async def broken(**_: object) -> list[object]:
        raise RuntimeError("secret detail")

    storage.list_turns = broken  # type: ignore[method-assign,assignment]
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
        await client.post("/api/session", headers=LOGIN)
        response = await client.get("/api/messages")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    assert "secret" not in response.text


@pytest.mark.anyio
async def test_service_is_unavailable_until_the_model_client_is_ready() -> None:
    app = create_app(make_settings(), MemoryStorage().overrides())
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        response = await client.get("/api/messages")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "service_unavailable"}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("https://llm.example.test/custom/openai/", "other-model"),
        ("https://llm.example.test/v1", "any-model"),
    ],
)
async def test_app_calls_chat_completions_at_configured_url(
    monkeypatch: pytest.MonkeyPatch, base_url: str, model: str
) -> None:
    def respond(request: Request) -> Response:
        assert str(request.url) == base_url.rstrip("/") + "/chat/completions"
        assert request.headers["authorization"] == "Bearer unused-provider-key"
        body = json.loads(request.content)
        assert body["model"] == model
        calls.append(body)
        # The topic guard's classifier calls are deterministic; the main answer is not.
        is_classifier = body.get("temperature") == 0
        assert ("response_format" in body) == is_classifier
        content = '{"label": "ON_TOPIC", "lang": "en"}' if is_classifier else "Use a filter."
        return Response(200, json={"choices": [{"message": {"content": content}}]})

    calls: list[dict[str, object]] = []

    clients: list[AsyncClient] = []

    def open_client(**_: object) -> AsyncClient:
        clients.append(AsyncClient(transport=MockTransport(respond)))
        return clients[-1]

    monkeypatch.setattr("themed_chat.adapters.openai_compatible.AsyncClient", open_client)
    llm = ModelSettings(base_url=base_url, model=model, system_prompt="Coffee only")
    app = create_app(make_settings(llm=llm), MemoryStorage().overrides())
    try:
        async with app.router.lifespan_context(app), client_for(app) as client:
            await client.post("/api/session", headers=LOGIN)
            reply = await client.post("/api/messages", headers=WRITE, json={"text": "How?"})
            assert reply.status_code == 201
            history = await client.get("/api/messages")
            assert [item["text"] for item in history.json()["messages"]][-2:] == [
                "How?",
                "Use a filter.",
            ]
        assert len(calls) == 3  # Question classifier, main model, answer classifier.
        # The main model and the classifier each have their own client, both closed.
        assert len(clients) == 2 and all(client.is_closed for client in clients)
    finally:
        for http in clients:
            await http.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [ConnectionResetError("reset"), OSError("tls")])
async def test_raw_os_error_from_the_model_transport_is_not_a_storage_outage(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    def respond(_: Request) -> Response:
        raise error

    clients: list[AsyncClient] = []

    def open_client(**_: object) -> AsyncClient:
        clients.append(AsyncClient(transport=MockTransport(respond)))
        return clients[-1]

    monkeypatch.setattr("themed_chat.adapters.openai_compatible.AsyncClient", open_client)
    app = create_app(make_settings(), MemoryStorage().overrides())
    try:
        async with app.router.lifespan_context(app), client_for(app) as client:
            await client.post("/api/session", headers=LOGIN)
            reply = await client.post("/api/messages", headers=WRITE, json={"text": "How?"})
            assert reply.status_code == 502
            assert reply.json() == {"error": {"code": "model_unavailable"}}
    finally:
        for http in clients:
            await http.aclose()


@pytest.mark.anyio
async def test_times_have_a_fixed_width_utc_format() -> None:
    import re
    from dataclasses import replace
    from datetime import UTC
    from datetime import datetime as moment

    storage = MemoryStorage()
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        storage.add_turns(1, storage.guests[0])
        whole = moment(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        storage.turns[0] = replace(storage.turns[0], question_at=whole, answer_at=whole)
        body = (await client.get("/api/messages")).json()
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
    for message in body["messages"]:
        assert pattern.fullmatch(message["question_at"]) and pattern.fullmatch(
            message["created_at"]
        )
    assert body["messages"][0]["question_at"] == "2026-01-02T03:04:05.000000Z"
