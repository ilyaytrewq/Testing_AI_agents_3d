from uuid import UUID

from itsdangerous import BadSignature, TimestampSigner
from starlette.requests import Request
from starlette.responses import Response

GUEST_COOKIE = "chat_guest"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 3600
COOKIE_PATH = "/api"


class GuestCookie:
    """Long-lived signed cookie that keeps a person's guest id across logins.

    It only labels messages as "mine"; it never authorizes a request.
    """

    def __init__(self, secret: str, *, secure: bool) -> None:
        # A salt different from the session cookie's keeps the two signatures separate.
        self.signer = TimestampSigner(secret, salt="themed-chat.guest-cookie")
        self.secure = secure

    def read(self, request: Request) -> UUID | None:
        value = request.cookies.get(GUEST_COOKIE)
        if value is None:
            return None
        try:
            return UUID(self.signer.unsign(value, max_age=GUEST_COOKIE_MAX_AGE).decode())
        except (BadSignature, ValueError):
            return None

    def write(self, response: Response, guest_id: UUID) -> None:
        response.set_cookie(
            GUEST_COOKIE,
            self.signer.sign(str(guest_id)).decode(),
            max_age=GUEST_COOKIE_MAX_AGE,
            path=COOKIE_PATH,
            httponly=True,
            samesite="lax",
            secure=self.secure,
        )
