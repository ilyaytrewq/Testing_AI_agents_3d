from collections import deque
from collections.abc import Callable
from math import ceil
from time import monotonic

# Forget idle keys once the table grows beyond this many entries.
PRUNE_THRESHOLD = 4096
# Hard cap: if every key is still active, the oldest ones are evicted to bound memory.
MAX_KEYS = 2 * PRUNE_THRESHOLD


class RateLimiter:
    """In-memory sliding window; correct for one process, which is how the app is deployed."""

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int | None:
        """Record an attempt; return the seconds to wait if the limit is exceeded."""
        now = self.clock()
        if len(self._hits) > PRUNE_THRESHOLD:
            self._prune(now)
        if key not in self._hits and len(self._hits) >= MAX_KEYS:
            # Dicts keep insertion order: drop the keys tracked for the longest time.
            for old in list(self._hits)[: len(self._hits) - MAX_KEYS + 1]:
                del self._hits[old]
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, ceil(hits[0] + self.window - now))
        hits.append(now)
        return None

    def _prune(self, now: float) -> None:
        self._hits = {
            key: hits for key, hits in self._hits.items() if hits and hits[-1] > now - self.window
        }
