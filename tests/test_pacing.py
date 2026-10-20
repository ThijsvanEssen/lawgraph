"""Request pacing per host, and the retries of BaseClient."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import requests
from requests import Response

from lawgraph.clients import pacing
from lawgraph.clients.base import BaseClient
from lawgraph.clients.pacing import HostPacer, PacedSession, pacer_for
from lawgraph.config.sources import DEFAULT_MIN_INTERVAL, KOOP_REPOSITORY, USER_AGENT
from tests.asserts import show_items
from tests.fakes import ScriptedSession, answer

MACHINE_LOCK_DIR = pacing._lock_dir  # before conftest points it at the test run


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
        == KOOP_REPOSITORY.min_interval
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
    session = BaseClient(base_url="https://x.test").session
    assert isinstance(session, PacedSession)
    assert session.headers["User-Agent"] == USER_AGENT


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
    assert pacing.retry_after_seconds(cast(Response, response)) is None
    assert (
        pacing.retry_after_seconds(cast(Response, SimpleNamespace(headers={}))) is None
    )


# ── retries of BaseClient ────────────────────────────────────────────────────


def _client(*script) -> tuple[BaseClient, ScriptedSession]:
    session = ScriptedSession(*script)
    return BaseClient(base_url="https://retry.test", session=session), session


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_transient_statuses_are_retried(status, slept) -> None:
    client, session = _client(answer(status=status), answer(status=status), "ok")
    assert client.get("https://retry.test/x").text == "ok"
    assert len(session.sent) == 3
    assert slept == [1.0, 2.0]


def test_five_attempts_before_giving_up(slept) -> None:
    client, session = _client(*[answer(status=504)] * 5)
    with pytest.raises(requests.HTTPError):
        client.get("https://retry.test/x")
    assert len(session.sent) == 5
    assert slept == [1.0, 2.0, 4.0, 8.0]


def test_no_sleep_after_the_last_connection_error(slept) -> None:
    client, _ = _client(*[requests.ConnectionError("refused")] * 5)
    with pytest.raises(requests.ConnectionError):
        client.get("https://retry.test/x")
    assert slept == [1.0, 2.0, 4.0, 8.0]


def test_retry_after_longer_than_the_backoff_is_followed(slept) -> None:
    client, _ = _client(answer(status=429, headers={"Retry-After": "30"}), "ok")
    client.get("https://retry.test/x")
    assert slept == [30.0]


def test_a_404_is_not_retried(slept) -> None:
    client, session = _client(answer(status=404))
    with pytest.raises(requests.HTTPError):
        client.get("https://retry.test/x")
    assert len(session.sent) == 1 and slept == []


@pytest.mark.parametrize("status", [202, 204])
def test_an_answer_that_is_not_200_is_not_the_document(status, slept) -> None:
    """202 Accepted passes raise_for_status; its body stored as a judgment is never
    refetched."""
    client, _ = _client(answer("<html>being prepared</html>", status=status))
    with pytest.raises(requests.HTTPError, match=f"{status} is not the document"):
        client.get_text("uitspraken/content")
    assert slept == []


def test_a_path_is_asked_under_the_base_and_a_url_as_it_is() -> None:
    client, session = _client("a", "b")
    client.get("/uitspraken/content")
    client.get("https://elsewhere.test/x")
    assert [sent.url for sent in session.sent] == [
        "https://retry.test/uitspraken/content",
        "https://elsewhere.test/x",
    ]


# ── two processes on one host ────────────────────────────────────────────────


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pacing, "_lock_dir", lambda: tmp_path)
    monkeypatch.setattr(pacing, "_pacers", {})
    monkeypatch.setattr(pacing, "_host_locks", {})
    monkeypatch.setattr(pacing, "_start_releaser", lambda: None)  # the tests release
    return tmp_path


def _held_elsewhere(lock_dir, host: str):
    """Another process holding the lock of *host* (another open file is another holder)."""
    import fcntl

    other = (lock_dir / f"lawgraph-pacer-{host}.lock").open("w")
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return other


def _free(lock_dir, host: str) -> bool:
    """Whether another process could take the lock of *host* now."""
    try:
        _held_elsewhere(lock_dir, host).close()
    except BlockingIOError:
        return False
    return True


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


def test_an_unwritable_home_paces_the_host_as_usual(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o500)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(pacing, "_lock_dir", MACHINE_LOCK_DIR)
    monkeypatch.setattr(pacing, "_pacers", {})
    monkeypatch.setattr(pacing, "_host_locks", {})
    monkeypatch.setattr(pacing, "_start_releaser", lambda: None)

    pacer = pacing.pacer_for("https://x.test/")

    assert pacer.holding


REPOSITORY = "https://repository.overheid.nl/sru"


def test_a_process_gives_the_lock_back_when_it_no_longer_asks_the_host(
    lock_dir, clock
) -> None:
    pacer = pacing.pacer_for(REPOSITORY)
    pacer.wait()
    clock.now += pacing.RELEASE_AFTER - 1
    assert pacing.release_idle_hosts(clock.now) == []
    assert not _free(lock_dir, "repository.overheid.nl")

    clock.now += 1
    assert pacing.release_idle_hosts(clock.now) == ["repository.overheid.nl"]
    assert _free(lock_dir, "repository.overheid.nl")
    assert pacer.base_interval == 0.5  # unchanged while it asks nothing


def test_a_process_that_gave_the_lock_back_takes_it_again_with_its_next_request(
    lock_dir, clock
) -> None:
    pacer = pacing.pacer_for(REPOSITORY)
    clock.now += pacing.RELEASE_AFTER
    pacing.release_idle_hosts(clock.now)
    pacer.wait()
    assert pacer.holding and pacer.base_interval == 0.5
    assert not _free(lock_dir, "repository.overheid.nl")


def test_a_process_that_finds_the_lock_taken_again_goes_to_half_speed(
    lock_dir, clock
) -> None:
    pacer = pacing.pacer_for(REPOSITORY)
    clock.now += pacing.RELEASE_AFTER
    pacing.release_idle_hosts(clock.now)
    other = _held_elsewhere(lock_dir, "repository.overheid.nl")
    try:
        pacer.wait()
    finally:
        other.close()
    assert not pacer.holding and pacer.base_interval == 1.0


def test_a_process_at_half_speed_goes_back_to_full_speed_when_the_other_is_done(
    lock_dir, clock, caplog
) -> None:
    other = _held_elsewhere(lock_dir, "repository.overheid.nl")
    pacer = pacing.pacer_for(REPOSITORY)
    assert pacer.base_interval == pacer.interval == 1.0
    other.close()  # the other process gave it back, or ended

    pacer.wait()  # tried again only every RECLAIM_EVERY seconds
    assert pacer.base_interval == 1.0
    clock.now += pacing.RECLAIM_EVERY
    with caplog.at_level("INFO"):
        pacer.wait()
    assert pacer.holding and pacer.base_interval == 0.5 and pacer.interval == 0.5
    assert not _free(lock_dir, "repository.overheid.nl")
    assert any("full speed" in m for m in caplog.messages), show_items(caplog.messages)
