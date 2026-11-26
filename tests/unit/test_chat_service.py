from uuid import uuid4

import pytest

from themed_chat.chat.models import DraftTurn, Turn
from themed_chat.chat.service import ChatService, GenerationError, InvalidMessage


class Repository:
    def __init__(self) -> None:
        self.saved: list[DraftTurn] = []

    async def append_turn(self, draft: DraftTurn) -> Turn:
        self.saved.append(draft)
        return Turn(len(self.saved), draft)

    async def list_turns(self) -> list[Turn]:
        return [Turn(i, draft) for i, draft in enumerate(self.saved, 1)]


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
    repository, model = Repository(), Model("reply")
    with pytest.raises(InvalidMessage):
        await ChatService(repository, model).send(uuid4(), text)
    assert not model.inputs
    assert not repository.saved


@pytest.mark.anyio
@pytest.mark.parametrize("answer", [" \n  ", "\ud800", "invalid\x00text"])
async def test_invalid_model_response_is_not_persisted(answer: str) -> None:
    repository, model = Repository(), Model(answer)
    with pytest.raises(GenerationError):
        await ChatService(repository, model).send(uuid4(), "coffee")
    assert not repository.saved


@pytest.mark.anyio
async def test_maximum_length_user_message_is_saved_as_one_turn() -> None:
    repository, model = Repository(), Model("reply")
    text = "☕" * 500
    guest = uuid4()
    turn = await ChatService(repository, model).send(guest, text)
    assert model.inputs == [text]
    assert repository.saved == [turn.draft]
    assert (turn.draft.user_id, turn.draft.question, turn.draft.answer) == (guest, text, "reply")
