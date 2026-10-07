"""What is searched, counted so that no count leads back to a person.

The API counts the ``q`` of ``/api/search`` in memory, per day: a normalised term and how
often it was asked (``SearchTermCounter``), never who asked or at what time of the day. Now
and then it merges what it counted into the file of that day in ``LAWGRAPH_SEARCH_STATS_DIR``
(``search-YYYY-MM-DD.json``, one object, term → n): the file holds the day's totals only, so
no line of it can be laid next to a line of the access log.

A day file is kept in full for ``KEEP_DAYS``; then it is added to the file of its month
(``search-YYYY-MM.json``) with only the terms asked at least ``MIN_COUNT`` times in that day
and the days kept after it: a term asked now and then stays, a rare one, which may name a
person ("rechtszaak Jansen"), is then gone.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import tempfile
import threading
import unicodedata
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

# The longest term kept; what is longer is cut.
MAX_TERM_CHARS = 100
# Days a day file is kept in full before it goes into its month.
KEEP_DAYS = 7
# How often a term must be asked in the days around it to be kept after ``KEEP_DAYS``.
MIN_COUNT = 5

_DAY = re.compile(r"^search-(\d{4}-\d{2}-\d{2})\.json$")
_MONTH = re.compile(r"^search-(\d{4}-\d{2})\.json$")
_LOCK = ".lock"


def normalise(q: str) -> str:
    """The term as it is counted: NFC, lower case, whitespace collapsed, at most
    ``MAX_TERM_CHARS`` characters; ``""`` for one that is empty."""
    folded = " ".join(unicodedata.normalize("NFC", q).lower().split())
    return folded[:MAX_TERM_CHARS].rstrip()


class SearchTermCounter:
    """The terms asked per day, in memory; thread safe (a route runs in a thread pool)."""

    def __init__(self) -> None:
        self._days: dict[str, Counter[str]] = {}
        self._lock = threading.Lock()

    def add(self, q: str, today: dt.date | None = None) -> None:
        term = normalise(q)
        if not term:
            return
        day = (today or dt.date.today()).isoformat()
        with self._lock:
            self._days.setdefault(day, Counter())[term] += 1

    def take(self) -> dict[str, Counter[str]]:
        """What was counted since the last take, per day; the counter starts again."""
        with self._lock:
            taken, self._days = self._days, {}
        return taken

    def flush(self, directory: Path) -> None:
        """Merge what was counted into the day files of *directory*."""
        for day, counts in self.take().items():
            merge_day(directory, day, counts)


@contextlib.contextmanager
def _locked(directory: Path) -> Iterator[None]:
    """One writer at a time in *directory*: the API and ``lawgraph search-stats prune``."""
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / _LOCK, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path: Path) -> Counter[str]:
    if not path.exists():
        return Counter()
    return Counter({str(k): int(v) for k, v in json.loads(path.read_text()).items()})


def _write(path: Path, counts: Counter[str]) -> None:
    """*counts* into *path* at once (a temporary file moved over it), most asked first."""
    ordered = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as out:
        json.dump(ordered, out, ensure_ascii=False, indent=0)
    os.replace(tmp, path)


def merge_day(directory: Path, day: str, counts: Counter[str]) -> None:
    """Add *counts* to the totals of *day* (``YYYY-MM-DD``)."""
    if not counts:
        return
    with _locked(directory):
        path = directory / f"search-{day}.json"
        _write(path, _read(path) + counts)


def prune(
    directory: Path,
    today: dt.date,
    *,
    keep_days: int = KEEP_DAYS,
    min_count: int = MIN_COUNT,
) -> list[str]:
    """Move every day file older than *keep_days* into the file of its month and remove it.
    Of a day moved only the terms are kept that were asked at least *min_count* times in
    that day and the *keep_days* days after it that are kept in full. Returns the days
    moved, oldest first."""
    if not directory.is_dir():
        return []
    oldest_kept = today - dt.timedelta(days=keep_days - 1)
    with _locked(directory):
        days = {
            dt.date.fromisoformat(found[1]): _read(path)
            for path in directory.iterdir()
            if (found := _DAY.match(path.name))
        }
        moved = sorted(day for day in days if day < oldest_kept)
        months: dict[str, Counter[str]] = {}
        for day in moved:
            around = Counter(days[day])
            for later in range(1, keep_days + 1):
                around += days.get(day + dt.timedelta(days=later), Counter())
            kept = Counter(
                {t: n for t, n in days[day].items() if around[t] >= min_count}
            )
            month = day.isoformat()[:7]
            if month not in months:
                months[month] = _read(directory / f"search-{month}.json")
            months[month] += kept
        for month, counts in months.items():
            _write(directory / f"search-{month}.json", counts)
        for day in moved:
            (directory / f"search-{day.isoformat()}.json").unlink()
    return [day.isoformat() for day in moved]


def totals(directory: Path, today: dt.date, days: int) -> Counter[str]:
    """The terms of the last *days* days: the day files, and for an older day that went
    into its month the whole month (its days are no longer apart)."""
    if not directory.is_dir():
        return Counter()
    first = today - dt.timedelta(days=days - 1)
    total: Counter[str] = Counter()
    for path in directory.iterdir():
        day, month = _DAY.match(path.name), _MONTH.match(path.name)
        if day and dt.date.fromisoformat(day[1]) >= first:
            total += _read(path)
        elif month and month[1] >= first.isoformat()[:7]:
            total += _read(path)
    return total
