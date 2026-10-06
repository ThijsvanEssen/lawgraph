"""Polite request pacing, per host, for every client.

Every ``BaseClient`` uses a ``PacedSession``. Before a request the session waits until the
host's interval has passed since the previous one; a host that answers HTTP 429 or 503 makes
the interval double (or follow ``Retry-After``), and it shrinks back while requests succeed:
to the base interval (``HOST_MIN_INTERVAL`` in the constants), or to just above the pace
the host last pushed back at, which is forgotten slowly.

The pacer is shared by the whole process and thread safe: ``retrieve all --jobs`` runs the
sources of one host one after the other, but a host reached through two clients is still
paced as one. Two ``lawgraph`` processes cannot share a pacer; the process that reaches a
host first holds a lock file for it, and a process that finds the lock taken paces that host
at half the speed, so together they stay under what one process alone may do. The lock goes
with the use: a process gives it back when it has not asked the host anything for
``RELEASE_AFTER`` seconds (a ``retrieve all`` whose lane of that host is done), and a process
at half speed tries to take it every ``RECLAIM_EVERY`` seconds, and goes back to full speed
when it can.
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
# The pace a host pushed back at, after requests that went well, is a limit of that host: the
# interval shrinks back to this much above it, not to the base. Without it one client on
# repository.overheid.nl came back to 0.6 s every 30 s and met an HTTP 429 every time (88
# warnings in a rebuild). Simulated for 5,000 documents against a minimum gap of 0.62 s:
# 146 HTTP 429 and 68 minutes without, 20 and 58 minutes with; against a bucket of 1/s: 145
# and 21, the same 83 minutes. A fixed higher base is slower or still throttled, by model.
_FLOOR_MARGIN = 1.15
_FLOOR_CEILING = 4.0  # times the base interval
_FLOOR_DECAY = 0.9995  # per successful request: halved after 1,400 of them
_LEARN_AFTER = 5  # successes since the last pushback; a burst of 429s teaches one pace
# The lock of a host: given back after this long without a request to it, and tried again
# this often by a process that paces the host at half speed.
RELEASE_AFTER = 300.0
RECLAIM_EVERY = 60.0


class HostPacer:
    """Hands out request slots at least ``interval`` seconds apart."""

    def __init__(self, host: str, base_interval: float) -> None:
        self.host = host
        self.full_speed = (
            base_interval  # the interval of the process that holds the lock
        )
        self.base_interval = base_interval
        self.interval = base_interval
        self.holding = True
        self._last_used = _now()
        self._last_claim = _now()
        self._floor = 0.0
        self._successes = 0
        self._next_slot = 0.0
        self._lock = threading.Lock()
        self._throttled = 0
        self._report = PeriodicLog(immediate=True)

    def wait(self) -> None:
        """Block until this request's slot."""
        with self._lock:
            now = _now()
            self._last_used = now
            if not self.holding and now - self._last_claim >= RECLAIM_EVERY:
                self._claim(now)
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.interval
        if slot > now:
            _sleep(slot - now)

    def throttled(self, retry_after: float | None = None) -> None:
        """The host pushed back: slow down, and stay quiet for ``retry_after`` if it said."""
        with self._lock:
            if self._successes >= _LEARN_AFTER:
                learned = max(self._floor, self.interval * _FLOOR_MARGIN)
                self._floor = min(learned, self.base_interval * _FLOOR_CEILING)
            self._successes = 0
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

    def _claim(self, now: float) -> None:
        """Take the lock of the host if no other process holds it: full speed with it, half
        speed without (``self._lock`` held)."""
        self._last_claim = now
        self.holding = holding = _take_lock(self.host)
        base = self.full_speed * (1.0 if holding else 2.0)
        if base == self.base_interval:
            return
        self.interval = min(
            MAX_INTERVAL, max(base, self.interval * base / self.base_interval)
        )
        self.base_interval = base
        if holding:
            logger.info(
                "No other lawgraph process talks to %s any more; pacing it at %.1fs here "
                "(full speed).",
                self.host,
                base,
            )
        else:
            _warn_half_speed(self.host, base)

    def release_if_idle(self, now: float) -> bool:
        """Give the lock of the host back when nothing was asked of it for
        ``RELEASE_AFTER`` seconds; whether it was."""
        with self._lock:
            if not self.holding or now - self._last_used < RELEASE_AFTER:
                return False
            self.holding = False
            self._last_claim = float("-inf")  # the next request takes it again at once
            _give_back_lock(self.host)
        logger.info(
            "Gave the pacer lock of %s back: nothing asked of it for %.0f minutes.",
            self.host,
            RELEASE_AFTER / 60,
        )
        return True

    def succeeded(self) -> None:
        with self._lock:
            self._successes += 1
            self._floor *= _FLOOR_DECAY
            self.interval = max(
                self.base_interval, self._floor, self.interval * _SHRINK
            )


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
# The lock file of every host this process holds; None: no lock files here (no directory, a
# file system without locks), as if the host were this process's alone.
_host_locks: dict[str, IO[str] | None] = {}
_registry_lock = threading.Lock()
_releaser: threading.Thread | None = None


def pacer_for(url: str) -> HostPacer:
    """The shared pacer of the host in *url*."""
    host = (urlsplit(url).hostname or "").lower()
    with _registry_lock:
        if host not in _pacers:
            pacer = HostPacer(host, HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL))
            if not _take_lock(host):
                pacer.holding = False
                pacer.base_interval = pacer.interval = pacer.full_speed * 2
                _warn_half_speed(host, pacer.base_interval)
            _pacers[host] = pacer
            _start_releaser()
        return _pacers[host]


def release_idle_hosts(now: float) -> list[str]:
    """Give back the lock of every host this process has not asked anything for
    ``RELEASE_AFTER`` seconds; their names."""
    with _registry_lock:
        pacers = list(_pacers.values())
    return [pacer.host for pacer in pacers if pacer.release_if_idle(now)]


def _start_releaser() -> None:
    """One daemon thread per process that gives idle locks back (``_registry_lock`` held)."""
    global _releaser
    if _releaser is not None:
        return

    def release_forever() -> None:
        while True:
            time.sleep(RECLAIM_EVERY)
            release_idle_hosts(_now())

    _releaser = threading.Thread(
        target=release_forever, name="lawgraph-pacer-release", daemon=True
    )
    _releaser.start()


def _warn_half_speed(host: str, interval: float) -> None:
    logger.warning(
        "Another lawgraph process is already talking to %s; pacing it at %.1fs here "
        "(half speed) so the two stay under its limit.",
        host,
        interval,
    )


def _take_lock(host: str) -> bool:
    """Take the lock file of *host*, or keep it; ``False`` when another process holds it."""
    if host in _host_locks:
        return True
    path = _lock_dir() / f"lawgraph-pacer-{host or 'unknown'}.lock"
    try:
        handle = path.open("w")
    except OSError as exc:  # no lock directory: pace as usual
        logger.debug("No pacer lock for %s: %s", host, exc)
        _host_locks[host] = None
        return True
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    except OSError as exc:  # a file system without locks: pace as usual
        logger.debug("No pacer lock for %s: %s", host, exc)
        handle.close()
        _host_locks[host] = None
        return True
    _host_locks[host] = handle
    return True


def _give_back_lock(host: str) -> None:
    handle = _host_locks.pop(host, None)
    if handle is not None:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


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
