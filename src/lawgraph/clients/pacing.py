"""Polite request pacing, per host, for every client.

Every ``BaseClient`` uses a ``PacedSession``. Before a request the session waits until the
host's interval has passed since the previous one; a host that answers HTTP 429 or 503 makes
the interval double (or follow ``Retry-After``), and it shrinks back to the base interval
while requests succeed. The base intervals are ``HOST_MIN_INTERVAL`` in the constants.

The pacer is shared by the whole process and thread safe: ``retrieve all --jobs`` runs the
sources of one host one after the other, but a host reached through two clients is still
paced as one. Two ``lawgraph`` processes cannot share a pacer; the first one to reach a host
holds a lock file for it, and a process that finds the lock taken paces that host at half
the speed, so together they stay under what one process alone may do.
"""

from __future__ import annotations

import fcntl
import threading
import time
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

import requests

from lawgraph.config.constants import DEFAULT_MIN_INTERVAL, HOST_MIN_INTERVAL
from lawgraph.core.logging import get_logger
from lawgraph.core.progress import PeriodicLog

logger = get_logger(__name__)

THROTTLE_STATUSES = (429, 503)
MAX_INTERVAL = 10.0
# Per successful request, towards the base interval: halved again after 35 requests. At 0.9
# (7 requests) a host that is asked too much was probed again at once: simulated against the
# limit of repository.overheid.nl with four clients, 547 HTTP 429 and 57 minutes for 8,000
# documents, against 149 and 45 minutes at 0.98; with one or two clients there is no
# difference (no 429 at all).
_SHRINK = 0.98


class HostPacer:
    """Hands out request slots at least ``interval`` seconds apart."""

    def __init__(self, host: str, base_interval: float) -> None:
        self.host = host
        self.base_interval = base_interval
        self.interval = base_interval
        self._next_slot = 0.0
        self._lock = threading.Lock()
        self._throttled = 0
        self._report = PeriodicLog(immediate=True)

    def wait(self) -> None:
        """Block until this request's slot."""
        with self._lock:
            now = _now()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.interval
        if slot > now:
            _sleep(slot - now)

    def throttled(self, retry_after: float | None = None) -> None:
        """The host pushed back: slow down, and stay quiet for ``retry_after`` if it said."""
        with self._lock:
            self.interval = min(
                MAX_INTERVAL, max(self.interval * 2, self.base_interval)
            )
            quiet_until = _now() + (retry_after or 0.0)
            self._next_slot = max(self._next_slot, quiet_until)
            self._throttled += 1
            if not self._report.due():
                return
            count, self._throttled = self._throttled, 0
            interval = self.interval
        logger.warning(
            "%s is throttling (%d HTTP 429/503 since the last report): pacing requests "
            "at %.1fs.",
            self.host,
            count,
            interval,
        )

    def succeeded(self) -> None:
        with self._lock:
            self.interval = max(self.base_interval, self.interval * _SHRINK)


class PacedSession(requests.Session):
    """A ``requests.Session`` that paces its requests per host."""

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        pacer = pacer_for(str(url))
        pacer.wait()
        response = super().request(method, url, *args, **kwargs)
        if response.status_code in THROTTLE_STATUSES:
            pacer.throttled(retry_after_seconds(response))
        else:
            pacer.succeeded()
        return response


def retry_after_seconds(response: requests.Response) -> float | None:
    """The ``Retry-After`` of a response in seconds, when it is given as a number."""
    value = response.headers.get("Retry-After")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


_pacers: dict[str, HostPacer] = {}
_host_locks: list[IO[str]] = []  # kept open: a lock lasts as long as the process
_registry_lock = threading.Lock()


def pacer_for(url: str) -> HostPacer:
    """The shared pacer of the host in *url*."""
    host = (urlsplit(url).hostname or "").lower()
    with _registry_lock:
        if host not in _pacers:
            interval = HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)
            if not _first_process_on(host):
                interval *= 2
                logger.warning(
                    "Another lawgraph process is already talking to %s; pacing it at "
                    "%.1fs here (half speed) so the two stay under its limit.",
                    host,
                    interval,
                )
            _pacers[host] = HostPacer(host, interval)
        return _pacers[host]


def _first_process_on(host: str) -> bool:
    """Take the lock file of *host*; ``False`` when another process holds it."""
    path = _lock_dir() / f"lawgraph-pacer-{host or 'unknown'}.lock"
    try:
        handle = path.open("w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except (
        OSError
    ) as exc:  # no lock directory, a file system without locks: pace as usual
        logger.debug("No pacer lock for %s: %s", host, exc)
        return True
    _host_locks.append(handle)
    return True


def _lock_dir() -> Path:
    """One place for every process of this user: a shell and a cron job have different
    temporary directories (``$TMPDIR``), and would not see each other's locks there."""
    path = Path.home() / ".cache" / "lawgraph"
    path.mkdir(parents=True, exist_ok=True)
    return path


# The clock and the sleep are module functions so tests can replace them.
def _now() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
