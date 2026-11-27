from uuid import uuid4

import pytest
from support import MemoryStorage, StubGenerator

from themed_chat.chat.service import ChatService, GenerationError, GenerationTimeout, InvalidMessage


class Model:
    def __init__(self, response: str) -> None:
        self.response = response
        self.inputs: list[str] = []

    async def generate(self, text: str) -> str:
        self.inputs.append(text)
        return self.response


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["", "   \t", "☕" * 501])
async def test_invalid_text_never_calls_model(text: str) -> None:
    repository, model = MemoryStorage(), Model("reply")
    with pytest.raises(InvalidMessage):
        await ChatService(repository, model).send(uuid4(), text)
    assert not model.inputs
    assert not repository.turns


@pytest.mark.anyio
@pytest.mark.parametrize("answer", [" \n  ", "\ud800", "invalid\x00text"])
async def test_invalid_model_response_saves_a_failed_turn(answer: str) -> None:
    repository, model = MemoryStorage(), Model(answer)
    with pytest.raises(GenerationError):
        await ChatService(repository, model).send(uuid4(), "coffee")
    [turn] = repository.turns
    assert (turn.question, turn.answer, turn.status) == ("coffee", None, "failed")


@pytest.mark.anyio
@pytest.mark.parametrize("error", [GenerationError("down"), GenerationTimeout("slow")])
async def test_model_failure_saves_the_question_and_still_raises(error: GenerationError) -> None:
    repository, model = MemoryStorage(), StubGenerator()
    model.error = error
    with pytest.raises(type(error)):
        await ChatService(repository, model).send(uuid4(), "coffee")
    [turn] = repository.turns
    assert (turn.answer, turn.status, turn.revision) == (None, "failed", 1)


@pytest.mark.anyio
async def test_maximum_length_user_message_is_saved_as_one_turn() -> None:
    repository, model = MemoryStorage(), Model("reply")
    text = "☕" * 500
    guest = uuid4()
    turn = await ChatService(repository, model).send(guest, text)
    assert model.inputs == [text]
    assert repository.turns == [turn]
    assert (turn.id, turn.user_id, turn.question, turn.answer) == (1, guest, text, "reply")
    assert turn.question_at <= turn.answer_at


@pytest.mark.anyio
async def test_history_reports_whether_older_or_newer_turns_remain() -> None:
    repository = MemoryStorage()
    repository.add_turns(5, uuid4())
    service = ChatService(repository, Model("reply"))

    latest = await service.history(limit=2)
    assert [t.id for t in latest.turns] == [4, 5] and latest.has_more
    exact = await service.history(limit=5)
    assert [t.id for t in exact.turns] == [1, 2, 3, 4, 5] and not exact.has_more
    assert latest.revision == 5
    earlier = await service.history(limit=2, before=4)
    assert [t.id for t in earlier.turns] == [2, 3] and earlier.has_more
    forward = await service.changes(after_revision=1, limit=2)
    assert [t.id for t in forward.turns] == [2, 3] and forward.has_more
    assert forward.revision == 3
    last = await service.changes(after_revision=3, limit=2)
    assert [t.id for t in last.turns] == [4, 5] and not last.has_more
    empty = await service.changes(after_revision=5, limit=2)
    assert not empty.turns and empty.revision == 5


@pytest.mark.anyio
async def test_a_question_answered_later_is_shown_by_question_time_and_still_polled() -> None:
    from datetime import UTC, datetime, timedelta

    from themed_chat.chat.models import NewTurn

    repository, guest = MemoryStorage(), uuid4()
    service = ChatService(repository, Model("reply"))
    start = datetime.now(UTC)
    cursor = (await service.history(limit=10)).revision
    # Asked first, answered last: written after a later question.
    await repository.append_turn(NewTurn(guest, "later", "a", start + timedelta(2), start))
    poll = await service.changes(after_revision=cursor, limit=10)
    await repository.append_turn(NewTurn(guest, "early", "a", start, start + timedelta(3)))
    poll2 = await service.changes(after_revision=poll.revision, limit=10)
    assert [t.question for t in poll.turns + poll2.turns] == ["later", "early"]
    shown = await service.history(limit=10)
    assert [t.question for t in shown.turns] == ["early", "later"]


@pytest.mark.anyio
@pytest.mark.parametrize("save_error", [RuntimeError("bug"), ConnectionError("down")])
@pytest.mark.parametrize("error", [GenerationError("down"), GenerationTimeout("slow")])
async def test_failed_save_of_a_failed_turn_keeps_the_model_error(
    save_error: Exception, error: GenerationError
) -> None:
    repository, model = MemoryStorage(), StubGenerator()
    model.error = error

    async def broken(_: object) -> None:
        raise save_error

    repository.append_turn = broken  # type: ignore[method-assign,assignment]
    with pytest.raises(type(error)):
        await ChatService(repository, model).send(uuid4(), "coffee")
