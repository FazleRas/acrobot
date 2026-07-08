"""Client-side rate limiting for free-tier API budgets.

Two clocks:
  * RPM — sliding one-minute window; acquire() blocks until a slot frees.
    Handles a big PR firing 20 chunks at once (they drip instead of 429ing).
  * RPD — daily request budget, the real free-tier constraint. When it runs
    out mid-run, DailyBudgetExhausted is raised so the pipeline can post a
    partial review instead of failing the check red.
"""

import time
from collections import deque
from collections.abc import Callable


class DailyBudgetExhausted(RuntimeError):
    """The RPD budget for this run is spent; degrade gracefully upstream."""


class RateLimiter:
    def __init__(
        self,
        rpm: int,
        rpd: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rpm < 1 or rpd < 1:
            raise ValueError("rpm and rpd must be >= 1")
        self._rpm = rpm
        self._rpd = rpd
        self._clock = clock
        self._sleep = sleep
        self._window: deque[float] = deque()
        self._used_today = 0

    @property
    def remaining_today(self) -> int:
        return self._rpd - self._used_today

    def acquire(self) -> None:
        """Block until a request slot is available, then consume it."""
        if self._used_today >= self._rpd:
            raise DailyBudgetExhausted(f"daily budget of {self._rpd} requests spent")

        now = self._clock()
        while self._window and now - self._window[0] >= 60.0:
            self._window.popleft()
        if len(self._window) >= self._rpm:
            wait = 60.0 - (now - self._window[0])
            if wait > 0:
                self._sleep(wait)
            now = self._clock()
            while self._window and now - self._window[0] >= 60.0:
                self._window.popleft()

        self._window.append(now)
        self._used_today += 1
