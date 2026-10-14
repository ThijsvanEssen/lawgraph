"""Time helpers: wait for another thread (``until``), move time by hand (``ManualClock``), or
count work (``assert_fast``, ``calls_made``) instead of fixed seconds."""

from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

# How long a test waits at most for something that happens at once in another thread: only
# reached when it never happens, so it can be ample.
PATIENCE = 10.0


def until(condition: Callable[[], bool], seconds: float = PATIENCE) -> bool:
    """Whether *condition* holds within *seconds* (another thread makes it true)."""
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class ManualClock:
    """A clock that stands still until the test moves it. A wait on it ends when it is
    notified or when the test moves the clock to its deadline (``move_to_wait``); the test
    learns of each wait that starts (``waits_until``), with no polling on either side."""

    def __init__(self) -> None:
        self._now = 0.0
        self.waiting_until: float | None = None
        self._condition: threading.Condition | None = None
        self._waits = threading.Condition()  # tells the test a wait started or ended

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def wait(self, condition: threading.Condition, timeout: float) -> bool:
        """Like ``condition.wait(timeout)`` (*condition* held), in the time of this clock.
        It waits without a timeout of its own: a notify that comes as a short wait ends is
        lost (``Condition.wait`` then says it timed out)."""
        deadline = self._now + timeout
        with self._waits:
            self._condition = condition
            self.waiting_until = deadline
            self._waits.notify_all()
        try:
            condition.wait()  # notified: by another thread, or by ``move_to_wait``
            return self._now < deadline
        finally:
            with self._waits:
                self.waiting_until = None
                self._waits.notify_all()

    def waits_until(self, deadline: float) -> bool:
        """Whether a wait until *deadline* starts (another thread waits) within
        ``PATIENCE``."""
        with self._waits:
            return self._waits.wait_for(
                lambda: (
                    self.waiting_until is not None
                    and math.isclose(self.waiting_until, deadline)
                ),
                timeout=PATIENCE,
            )

    def move_to_wait(self, deadline: float) -> None:
        """Once a wait until *deadline* lasts, move the clock to its end, which ends it."""
        assert self.waits_until(deadline), (
            f"no wait until {deadline} (waiting until {self.waiting_until})"
        )
        condition = self._condition
        assert condition is not None
        with condition:
            self._now = max(self._now, self.waiting_until or deadline)
            condition.notify_all()


# What a computation that is linear in its input may take at most (seconds): one that is
# not (backtracking) takes minutes on the same input, so a busy machine never reaches it.
FAST = 5.0


def assert_fast(function: Callable[[], Any], budget: float = FAST) -> Any:
    """The result of *function*, which must return within *budget* seconds."""
    started = time.perf_counter()
    result = function()
    took = time.perf_counter() - started
    assert took < budget, f"took {took:.2f} s, more than {budget} s"
    return result


def calls_made(function: Callable[[], Any]) -> int:
    """How many functions, Python and built-in, *function* calls in this thread: a cost
    that a busy machine does not change."""
    count = 0

    def profile(frame: Any, event: str, arg: Any) -> None:
        nonlocal count
        if event in ("call", "c_call"):
            count += 1

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        function()
    finally:
        sys.setprofile(previous)
    return count
