"""Request pacing per host, and the retries of BaseClient."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from lawgraph.clients import base as base_module
from lawgraph.clients import pacing
from lawgraph.clients.base import BaseClient
from lawgraph.clients.pacing import HostPacer, PacedSession, pacer_for
from lawgraph.config.constants import DEFAULT_MIN_INTERVAL, HOST_MIN_INTERVAL


class _Clock:
    """A clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(pacing, "_now", lambda: fake.now)
    monkeypatch.setattr(pacing, "_sleep", fake.sleep)
    return fake


# ── spacing ──────────────────────────────────────────────────────────────────


def test_requests_are_spaced_by_the_interval(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    for _ in range(4):
        pacer.wait()
    # the first request goes at once, each next one waits for its slot
    assert clock.slept == pytest.approx([0.5, 0.5, 0.5])


def test_a_pause_of_the_caller_counts_as_waiting(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    pacer.wait()
    clock.now += 0.3  # the caller was busy for 0.3 s
    pacer.wait()
    assert clock.slept == pytest.approx([0.2])
    clock.now += 5
    pacer.wait()
    assert clock.slept == pytest.approx([0.2])  # long idle: no wait at all


# ── adapting to the host ─────────────────────────────────────────────────────


def test_a_throttling_host_doubles_the_interval_up_to_a_ceiling(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    seen = []
    for _ in range(8):
        pacer.throttled()
        seen.append(pacer.interval)
    assert seen[:3] == [1.0, 2.0, 4.0]
    assert seen[-1] == pacing.MAX_INTERVAL


def test_retry_after_keeps_the_pacer_quiet(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    pacer.wait()
    pacer.throttled(retry_after=7.0)
    clock.slept.clear()
    pacer.wait()
    assert clock.slept == pytest.approx([7.0])


def test_the_interval_shrinks_back_to_the_base_while_requests_succeed(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    pacer.throttled()
    pacer.throttled()
    assert pacer.interval == 2.0
    for _ in range(
        35
    ):  # halved after 35 successes: a throttling host is not probed at once
        pacer.succeeded()
    assert pacer.interval == pytest.approx(1.0, abs=0.02)
    for _ in range(60):
        pacer.succeeded()
    assert pacer.interval == pytest.approx(0.5)
    pacer.succeeded()
    assert pacer.interval >= 0.5  # never below the base


def _steady(pacer: HostPacer, requests: int) -> None:
    for _ in range(requests):
        pacer.succeeded()


def test_the_pace_a_host_pushed_back_at_is_not_tried_again_at_once(clock) -> None:
    """The rebuild of 2026-09-20: back to 0.6 s every 30 s, and an HTTP 429 every time."""
    pacer = HostPacer("example.test", 0.5)
    _steady(pacer, 10)
    pacer.throttled()  # at 0.5 s, after requests that went well: that pace is too fast
    assert pacer.interval == 1.0
    _steady(pacer, 100)
    assert pacer.interval == pytest.approx(0.5 * pacing._FLOOR_MARGIN, rel=0.06)
    assert pacer.interval > 0.5


def test_the_learned_pace_is_forgotten_slowly(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    _steady(pacer, 10)
    pacer.throttled()
    _steady(pacer, 5000)  # a limit of this morning is not one of tonight
    assert pacer.interval == pytest.approx(0.5)


def test_a_burst_of_pushbacks_teaches_one_pace_not_the_doubled_ones(clock) -> None:
    """Requests already under way when the first 429 came: they say nothing new."""
    pacer = HostPacer("example.test", 0.5)
    _steady(pacer, 10)
    for _ in range(3):
        pacer.throttled()
    assert pacer.interval == 4.0
    _steady(pacer, 200)
    assert pacer.interval < 0.6


def test_the_learned_pace_has_a_ceiling(clock) -> None:
    pacer = HostPacer("example.test", 0.5)
    for _ in range(20):  # a host that pushes back whatever the pace
        _steady(pacer, 10)
        pacer.throttled()
    _steady(pacer, 300)
    assert pacer.interval <= 0.5 * pacing._FLOOR_CEILING


# ── per host ─────────────────────────────────────────────────────────────────


def test_the_base_interval_comes_from_the_host_table() -> None:
    assert (
        pacer_for("https://repository.overheid.nl/sru").base_interval
        == (HOST_MIN_INTERVAL["repository.overheid.nl"])
    )
    assert (
        pacer_for("https://unlisted-host.test/x").base_interval == DEFAULT_MIN_INTERVAL
    )


def test_one_pacer_per_host_shared_by_all_clients() -> None:
    a = pacer_for("https://shared-host.test/one")
    b = pacer_for("https://SHARED-HOST.test/two?x=1")
    assert a is b
    assert pacer_for("https://other-host.test/") is not a


def test_every_client_uses_a_paced_session_by_default() -> None:
    assert isinstance(BaseClient(base_url="https://x.test").session, PacedSession)


# ── the session ──────────────────────────────────────────────────────────────


def _respond(monkeypatch, *statuses: int, headers: dict | None = None) -> list[int]:
    queue = list(statuses)
    sent: list[int] = []

    def fake_request(self, method, url, *args, **kwargs):
        status = queue.pop(0)
        sent.append(status)
        return SimpleNamespace(status_code=status, headers=headers or {})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return sent


def test_the_session_waits_for_the_slot_and_learns_from_the_answer(
    clock, monkeypatch
) -> None:
    _respond(monkeypatch, 200, 429, 200)
    session = PacedSession()
    url = "https://session-host.test/a"
    pacer = pacer_for(url)
    base = pacer.base_interval

    session.get(url)
    assert clock.slept == []
    session.get(url)  # 429: the host is throttling
    assert pacer.interval == base * 2
    session.get(url)  # waits the doubled interval, then succeeds
    assert clock.slept[-1] == pytest.approx(
        base
    )  # first wait after the 200 was the base
    assert pacer.interval < base * 2


def test_a_503_also_slows_down(clock, monkeypatch) -> None:
    _respond(monkeypatch, 503)
    url = "https://busy-host.test/"
    PacedSession().get(url)
    assert pacer_for(url).interval == pacer_for(url).base_interval * 2


def test_retry_after_of_a_response_is_read(clock, monkeypatch) -> None:
    _respond(monkeypatch, 429, headers={"Retry-After": "3"})
    url = "https://retry-host.test/"
    PacedSession().get(url)
    clock.slept.clear()
    pacer_for(url).wait()
    assert clock.slept[0] >= 3.0 - 1e-9


def test_a_retry_after_that_is_a_date_is_ignored() -> None:
    response = SimpleNamespace(headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert pacing.retry_after_seconds(response) is None
    assert pacing.retry_after_seconds(SimpleNamespace(headers={})) is None


# ── retries of BaseClient ────────────────────────────────────────────────────


class _Scripted:
    """A session that answers with the scripted statuses, then 200."""

    def __init__(self, *statuses: int, headers: dict | None = None) -> None:
        self.statuses = list(statuses)
        self.headers = headers or {}
        self.calls = 0

    def get(self, url, params=None, timeout=None, stream=False, headers=None):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else 200
        response = requests.Response()
        response.status_code = status
        response.headers.update(self.headers)
        response._content = b"ok"
        return response


def _client(session) -> BaseClient:
    return BaseClient(base_url="https://retry.test", session=session)


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    waits: list[float] = []
    monkeypatch.setattr(base_module.time, "sleep", waits.append)
    return waits


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_transient_statuses_are_retried(status, slept) -> None:
    session = _Scripted(status, status)
    assert (
        _client(session)._get_raw_absolute_with_retry("https://retry.test/x").text
        == "ok"
    )
    assert session.calls == 3
    assert slept == [1.0, 2.0]


def test_five_attempts_before_giving_up(slept) -> None:
    session = _Scripted(*[504] * 9)
    with pytest.raises(requests.HTTPError):
        _client(session)._get_raw_absolute_with_retry("https://retry.test/x")
    assert session.calls == 5
    assert slept == [1.0, 2.0, 4.0, 8.0, 16.0][: len(slept)]


def test_retry_after_longer_than_the_backoff_is_followed(slept) -> None:
    session = _Scripted(429, headers={"Retry-After": "30"})
    _client(session)._get_raw_absolute_with_retry("https://retry.test/x")
    assert slept == [30.0]


def test_a_404_is_not_retried(slept) -> None:
    session = _Scripted(404)
    with pytest.raises(requests.HTTPError):
        _client(session)._get_raw_absolute_with_retry("https://retry.test/x")
    assert session.calls == 1 and slept == []


# ── two processes on one host ────────────────────────────────────────────────


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pacing, "_lock_dir", lambda: tmp_path)
    monkeypatch.setattr(pacing, "_pacers", {})
    monkeypatch.setattr(pacing, "_host_locks", [])
    return tmp_path


def test_the_first_process_on_a_host_paces_it_at_the_base_interval(lock_dir) -> None:
    pacer = pacing.pacer_for("https://repository.overheid.nl/sru")
    assert pacer.base_interval == 0.5
    assert pacing.pacer_for("https://repository.overheid.nl/frbr/x") is pacer


def test_a_second_process_on_the_same_host_runs_at_half_speed(lock_dir, caplog) -> None:
    import fcntl

    # Another process holds the lock of the host (another open file is another holder).
    other = (lock_dir / "lawgraph-pacer-repository.overheid.nl.lock").open("w")
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with caplog.at_level("WARNING"):
            pacer = pacing.pacer_for("https://repository.overheid.nl/sru")
            free = pacing.pacer_for("https://data.rechtspraak.nl/uitspraken")
    finally:
        other.close()

    assert pacer.base_interval == 1.0 and free.base_interval == 0.125
    assert [m for m in caplog.messages if "Another lawgraph process" in m] == [
        "Another lawgraph process is already talking to repository.overheid.nl; pacing it "
        "at 1.0s here (half speed) so the two stay under its limit."
    ]


def test_without_a_lock_directory_the_host_is_paced_as_usual(
    lock_dir, monkeypatch
) -> None:
    monkeypatch.setattr(pacing, "_lock_dir", lambda: lock_dir / "missing")
    assert pacing.pacer_for("https://repository.overheid.nl/sru").base_interval == 0.5
