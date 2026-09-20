"""Progress of a long loop as one log line per minute, and one summary at the end.

Every pipeline that works through many records reports through ``Progress``: it counts
what was done, skipped (per reason) and failed, and writes a status line on a time basis,
never per record::

    12,400 / 34,593 (36%) · 4.9/s · ~1h12m left · 3 skipped · 0 errors

The step a line belongs to (``[retrieve rechtspraak]``) comes from the log context. A reason
to skip or fail is logged once, with the first record it happened to; the rest is counted
and shows up in the summary.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable

from lawgraph.core.time import format_duration

PROGRESS_INTERVAL_SECONDS = 60.0

_logger = logging.getLogger(__name__)


class PeriodicLog:
    """Says at most once per *interval* seconds that it is time to log.

    With *immediate* the first call is due; otherwise the first interval has to pass.
    """

    def __init__(
        self,
        interval: float = PROGRESS_INTERVAL_SECONDS,
        *,
        immediate: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._last = float("-inf") if immediate else clock()

    def due(self) -> bool:
        now = self._clock()
        if now - self._last < self.interval:
            return False
        self._last = now
        return True


class Progress:
    """Counts the outcome of each record and logs where the loop stands, once a minute."""

    def __init__(
        self,
        what: str = "records",
        *,
        total: int | None = None,
        interval: float = PROGRESS_INTERVAL_SECONDS,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.what = what
        self.total = total
        self.done = 0
        self.skips: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.problems: Counter[str] = Counter()
        self.notes: Counter[str] = Counter()
        self.examples: dict[str, object] = {}
        self._log = logger or _logger
        self._clock = clock
        self._started = clock()
        self._periodic = PeriodicLog(interval, clock=clock)
        self._mark = (self._started, 0)
        self._rate = 0.0

    # ------------------------------------------------------------------ counting

    @property
    def skipped(self) -> int:
        return sum(self.skips.values())

    @property
    def failed(self) -> int:
        return sum(self.failures.values())

    @property
    def handled(self) -> int:
        return self.done + self.skipped + self.failed

    def expect(self, total: int | None) -> None:
        """The number of records the loop will handle, once it is known."""
        self.total = total

    def ok(self, count: int = 1) -> None:
        self.done += count
        self._tick()

    def skip(self, reason: str, example: object = None, count: int = 1) -> None:
        """Count a record that was left out on purpose (no content, already stored)."""
        self._count(self.skips, reason, example, count, logging.INFO, "Skipping")

    def fail(self, reason: str, example: object = None, count: int = 1) -> None:
        """Count a record that went wrong; the run goes on."""
        self._count(self.failures, reason, example, count, logging.WARNING, "Failed")

    def problem(self, reason: str, example: object = None) -> None:
        """Count something that went wrong next to a record that is still handled."""
        self._count(self.problems, reason, example, 1, logging.WARNING, "Problem")

    def note(self, reason: str, example: object = None) -> None:
        """Count something worth knowing about a record that is fine (a text that was cut)."""
        self._count(self.notes, reason, example, 1, logging.WARNING, "Note")

    def _count(
        self,
        counter: Counter[str],
        reason: str,
        example: object,
        count: int,
        level: int,
        verb: str,
    ) -> None:
        if reason not in counter:
            first = f" (first: {example})" if example is not None else ""
            self.examples[reason] = example
            self._log.log(
                level, "%s: %s%s; further ones are counted.", verb, reason, first
            )
        elif example is not None:
            self._log.debug("%s: %s (%s)", verb, reason, example)
        counter[reason] += count
        self._tick()

    # ------------------------------------------------------------------- logging

    def _tick(self) -> None:
        if self._periodic.due():
            self._log.info("%s", self.line())

    def line(self) -> str:
        """``12,400 / 34,593 (36%) · 4.9/s · ~1h12m left · 3 skipped · 0 errors``."""
        now, handled = self._clock(), self.handled
        marked_at, marked = self._mark
        if now > marked_at:
            recent = (handled - marked) / (now - marked_at)
            self._rate = recent if not self._rate else (self._rate + recent) / 2
        self._mark = (now, handled)

        parts = [f"{handled:,}"]
        if self.total:
            share = min(100, round(100 * handled / self.total))
            parts[0] += f" / {self.total:,} ({share}%)"
        parts[0] += f" {self.what}"
        parts.append(f"{self._rate:.1f}/s")
        if self.total and self._rate > 0 and handled < self.total:
            left = (self.total - handled) / self._rate
            parts.append(f"~{format_duration(left)} left")
        parts.append(f"{self.skipped:,} skipped")
        parts.append(f"{self.failed:,} errors")
        return " · ".join(parts)

    def summary(self) -> str:
        """One line for the end of the run: duration and the count of every outcome."""
        elapsed = self._clock() - self._started
        parts = [f"{self.done:,} {self.what} done"]
        outcomes = (
            ("skipped", self.skips),
            ("failed", self.failures),
            ("problems", self.problems),
            ("notes", self.notes),
        )
        for label, counter in outcomes:
            if counter:
                reasons = ", ".join(f"{r}: {n:,}" for r, n in counter.most_common())
                parts.append(f"{sum(counter.values()):,} {label} ({reasons})")
        rate = f", {self.handled / elapsed:.1f}/s" if elapsed >= 1 else ""
        return f"{'; '.join(parts)} in {format_duration(elapsed)}{rate}"

    def errors(self) -> list[str]:
        """One line per cause of a failure or problem: its count and the first record."""
        lines = []
        for reason, count in (self.failures + self.problems).items():
            example = self.examples.get(reason)
            first = f" (first: {example})" if example is not None else ""
            lines.append(f"{count:,} x {reason}{first}")
        return lines

    def finish(self) -> None:
        self._log.info("%s.", self.summary())
