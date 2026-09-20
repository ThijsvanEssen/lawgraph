"""Polite request pacing, per host, for every client.

Every ``BaseClient`` uses a ``PacedSession``. Before a request the session waits until the
host's interval has passed since the previous one; a host that answers HTTP 429 or 503 makes
the interval double (or follow ``Retry-After``), and it shrinks back to the base interval
while requests succeed. The base intervals are ``HOST_MIN_INTERVAL`` in the constants.

The pacer is shared by the whole process and thread safe: ``retrieve all --jobs`` runs the
sources of one host one after the other, but a host reached through two clients is still
paced as one.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import requests

from lawgraph.config.constants import DEFAULT_MIN_INTERVAL, HOST_MIN_INTERVAL
from lawgraph.core.logging import get_logger
from lawgraph.core.progress import PeriodicLog

logger = get_logger(__name__)

THROTTLE_STATUSES = (429, 503)
MAX_INTERVAL = 10.0
_SHRINK = 0.9  # per successful request, towards the base interval


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
_registry_lock = threading.Lock()


def pacer_for(url: str) -> HostPacer:
    """The shared pacer of the host in *url*."""
    host = (urlsplit(url).hostname or "").lower()
    with _registry_lock:
        if host not in _pacers:
            _pacers[host] = HostPacer(
                host, HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)
            )
        return _pacers[host]


# The clock and the sleep are module functions so tests can replace them.
def _now() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
