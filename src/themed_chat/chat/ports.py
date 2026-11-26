from typing import Protocol
from uuid import UUID


class GuestRepository(Protocol):
    async def create(self, guest_id: UUID) -> None: ...
