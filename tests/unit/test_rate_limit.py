from themed_chat.api.rate_limit import PRUNE_THRESHOLD, RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_blocks_after_the_limit_and_reports_the_wait() -> None:
    clock = Clock()
    limiter = RateLimiter(2, 60, clock)
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") == 40  # The oldest hit leaves the window 40 s from now.
    assert limiter.hit("b") is None  # Keys are independent.


def test_limiter_allows_again_when_the_window_has_passed() -> None:
    clock = Clock()
    limiter = RateLimiter(1, 60, clock)
    assert limiter.hit("a") is None
    assert limiter.hit("a") == 60
    clock.now += 60
    assert limiter.hit("a") is None


def test_blocked_attempts_do_not_extend_the_block() -> None:
    clock = Clock()
    limiter = RateLimiter(1, 60, clock)
    limiter.hit("a")
    for _ in range(5):
        clock.now += 1
        limiter.hit("a")
    clock.now += 55
    assert limiter.hit("a") is None


def test_idle_keys_are_forgotten() -> None:
    clock = Clock()
    limiter = RateLimiter(1, 60, clock)
    for number in range(PRUNE_THRESHOLD + 1):
        limiter.hit(str(number))
    clock.now += 61
    limiter.hit("fresh")
    assert list(limiter._hits) == ["fresh"]


def test_tracked_keys_have_a_hard_cap() -> None:
    from themed_chat.api.rate_limit import MAX_KEYS

    limiter = RateLimiter(1, 60, Clock())
    for number in range(MAX_KEYS + 10):
        limiter.hit(f"key-{number}")
    assert len(limiter._hits) <= MAX_KEYS
    assert "key-0" not in limiter._hits and f"key-{MAX_KEYS + 9}" in limiter._hits
