from hmac import compare_digest
from hmac import digest as hmac_digest


class Credentials:
    """The shared access key, compared and fingerprinted without exposing it."""

    def __init__(self, access_key: str, session_secret: str) -> None:
        self._secret = session_secret.encode()
        self._expected = self._mac(b"login", access_key)
        # Stored with each session: a new access key makes every older session invalid.
        self.fingerprint = self._mac(b"session", access_key).hex()[:32]

    def _mac(self, purpose: bytes, value: str) -> bytes:
        return hmac_digest(self._secret, purpose + b":" + value.encode(), "sha256")

    def accepts(self, candidate: str) -> bool:
        # Equal-length digests, so the comparison time does not reveal the key's length.
        return compare_digest(self._mac(b"login", candidate), self._expected)
