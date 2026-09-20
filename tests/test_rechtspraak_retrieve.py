"""Rechtspraak judgments by court and decision date, from a real (recorded) index page."""

from __future__ import annotations

import datetime as dt
import pathlib
import xml.etree.ElementTree as ET
from typing import Any

import pytest
import requests

from lawgraph.clients.rechtspraak import OWMS_TERMS, RechtspraakClient
from lawgraph.config.constants import RECHTSPRAAK_COURT_GROUPS
from lawgraph.core.judgments import IndexEntry, parse_index
from lawgraph.pipelines.retrieve.rechtspraak import (
    RechtspraakRetrievePipeline,
    resolve_courts,
)
from tests.fakes import RawSourcesFake

INDEX_PAGE = (
    pathlib.Path(__file__).parent / "fixtures" / "rechtspraak_index_page.xml"
).read_text()  # one real Hoge Raad entry; the search matched 47

UTC = dt.timezone.utc


def _entry(ecli: str, updated: str | None = "2025-03-01T10:00:00Z") -> IndexEntry:
    when = (
        dt.datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
    )
    return IndexEntry(ecli=ecli, updated=when, title=ecli)


# ── the index page ───────────────────────────────────────────────────────────


def test_a_real_index_page_is_parsed() -> None:
    total, entries = parse_index(INDEX_PAGE)
    assert total == 47
    assert entries[0].ecli.startswith("ECLI:NL:HR:2024:")
    assert entries[0].updated is not None and entries[0].updated.tzinfo is not None
    assert "Hoge Raad" in entries[0].title


def test_an_index_that_is_not_xml_raises() -> None:
    with pytest.raises(ET.ParseError):
        parse_index("<html>Bad gateway")


# ── the client ───────────────────────────────────────────────────────────────


def _client(pages: list[Any], calls: list[dict]) -> RechtspraakClient:
    client = RechtspraakClient.__new__(RechtspraakClient)

    def fake_get_text(path, *, params=None, timeout=30):
        calls.append({"path": path, "params": dict(params)})
        page = pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page

    client._get_text = fake_get_text  # type: ignore[method-assign]
    return client


def _page(entries: int, total: int | None = None, offset: int = 0) -> str:
    body = "".join(
        f"<entry><id>ECLI:NL:HR:2025:{offset + n}</id><updated>2025-03-01T10:00:00Z"
        "</updated><title>t</title></entry>"
        for n in range(entries)
    )
    matched = total if total is not None else entries
    subtitle = f"<subtitle>Aantal gevonden ECLI's: {matched}</subtitle>"
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{subtitle}{body}</feed>'


def test_the_index_is_asked_for_the_courts_and_the_decision_dates() -> None:
    calls: list[dict] = []
    client = _client([_page(1)], calls)
    entries = list(
        client.iter_index(
            courts=["Hoge_Raad_der_Nederlanden", "Raad_van_State"],
            date_from=dt.date(2024, 9, 20),
            date_to=dt.date(2026, 9, 20),
        )
    )
    assert [e.ecli for e in entries] == ["ECLI:NL:HR:2025:0"]
    params = calls[0]["params"]
    assert calls[0]["path"] == "uitspraken/zoeken"
    assert params["creator"] == [
        OWMS_TERMS + "Hoge_Raad_der_Nederlanden",
        OWMS_TERMS + "Raad_van_State",
    ]
    assert params["date"] == ["2024-09-20", "2026-09-20"]
    assert params["type"] == "Uitspraak" and params["return"] == "DOC"
    assert "modifiedsince" not in params


def test_without_dates_the_whole_history_is_asked_for() -> None:
    calls: list[dict] = []
    list(_client([_page(0)], calls).iter_index(courts=["Raad_van_State"]))
    assert "date" not in calls[0]["params"]


def test_every_page_is_read_until_a_short_one() -> None:
    calls: list[dict] = []
    client = _client(
        [_page(1000, 2200), _page(1000, 2200, 1000), _page(200, 2200, 2000)], calls
    )
    entries = list(client.iter_index(courts=["Raad_van_State"]))
    assert len(entries) == 2200
    assert [c["params"]["from"] for c in calls] == ["0", "1000", "2000"]


def test_an_index_that_changed_while_it_was_read_is_only_a_warning(caplog) -> None:
    client = _client([_page(3, total=10)], [])
    with caplog.at_level("WARNING"):
        assert len(list(client.iter_index(courts=["Raad_van_State"]))) == 3
    assert any("the index changed" in m for m in caplog.messages)


def test_a_failing_page_raises_after_the_earlier_ones_were_yielded() -> None:
    client = _client([_page(1000, 5000), requests.ConnectionError("dropped")], [])
    seen = []
    with pytest.raises(requests.ConnectionError):
        for entry in client.iter_index(courts=["Raad_van_State"]):
            seen.append(entry)
    assert len(seen) == 1000


# ── which courts ─────────────────────────────────────────────────────────────


def test_short_names_and_groups_resolve_to_owms_terms() -> None:
    assert resolve_courts(["hr", "rvs"]) == [
        "Hoge_Raad_der_Nederlanden",
        "Raad_van_State",
    ]
    hoven = resolve_courts(["hoven"])
    assert "Gerechtshof_Amsterdam" in hoven and "Gerechtshof_'s-Hertogenbosch" in hoven
    assert len(hoven) == len(RECHTSPRAAK_COURT_GROUPS["hoven"])


def test_a_court_is_listed_once() -> None:
    assert (
        resolve_courts(["hr", "hr", "hoven", "gh-amsterdam"]).count(
            "Gerechtshof_Amsterdam"
        )
        == 1
    )


def test_an_unknown_court_is_named_with_the_known_ones() -> None:
    with pytest.raises(ValueError, match="unknown court 'rechtbank'.*hr"):
        resolve_courts(["rechtbank"])


# ── the pipeline ─────────────────────────────────────────────────────────────


class _Rs:
    def __init__(
        self, entries: list[IndexEntry], contents: dict[str, Any] | None = None
    ) -> None:
        self.entries = entries
        self.contents = contents or {}
        self.index_calls: list[dict] = []
        self.fetched: list[str] = []
        self.late: list[IndexEntry] = []  # what only the modified listing names

    def iter_index(self, *, courts, date_from=None, date_to=None, modified_from=None):
        call = {"courts": courts, "from": date_from, "to": date_to}
        if modified_from is not None:
            call["modified_from"] = modified_from
            yield from self.late
        else:
            yield from self.entries
        self.index_calls.append(call)

    def fetch_ecli_content(self, ecli: str) -> str:
        self.fetched.append(ecli)
        outcome = self.contents.get(ecli, f"<xml>{ecli}</xml>")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Store(RawSourcesFake):
    def __init__(self, stored: dict[str, str] | None = None) -> None:
        self.records: list[dict[str, Any]] = []
        self.stored = stored or {}  # ecli -> fetched_at

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict]:
        return [{"id": ecli, "at": at} for ecli, at in self.stored.items()]

    def insert_raw_source(self, **record: Any) -> None:
        self.records.append(record)


def _pipeline(rs: _Rs, store: _Store | None = None):
    store = store or _Store()
    return RechtspraakRetrievePipeline(store=store, rs_client=rs), store


def test_every_judgment_of_the_index_is_downloaded_and_stored() -> None:
    rs = _Rs([_entry("ECLI:A"), _entry("ECLI:B")])
    pipeline, store = _pipeline(rs)
    result = pipeline.run(courts=["hr"])

    assert (result.created, result.errors) == (2, [])
    first = store.records[0]
    assert first["source"] == "rechtspraak" and first["kind"] == "rs-content"
    assert (
        first["external_id"] == "ECLI:A"
        and first["payload_text"] == "<xml>ECLI:A</xml>"
    )
    assert first["meta"] == {"ecli": "ECLI:A", "updated": "2025-03-01T10:00:00+00:00"}


def test_the_courts_and_dates_reach_the_index() -> None:
    rs = _Rs([])
    pipeline, _ = _pipeline(rs)
    pipeline.run(courts=["hr", "hoven"], date_from=dt.date(2024, 9, 20))
    call = rs.index_calls[0]
    assert call["courts"][0] == "Hoge_Raad_der_Nederlanden" and len(call["courts"]) == 8
    assert call["from"] == dt.date(2024, 9, 20)


def test_a_judgment_stored_after_its_last_change_is_not_downloaded_again() -> None:
    rs = _Rs([_entry("ECLI:A"), _entry("ECLI:B"), _entry("ECLI:C")])
    store = _Store(
        {
            "ECLI:A": "2025-04-01T00:00:00Z",  # stored after the change: up to date
            "ECLI:B": "2025-02-01T00:00:00Z",  # stored before the change: stale
        }
    )
    pipeline, _ = _pipeline(rs, store)
    pipeline.run(courts=["hr"])
    assert rs.fetched == ["ECLI:B", "ECLI:C"]


def test_an_interrupted_download_only_repeats_the_rest() -> None:
    entries = [_entry(f"ECLI:{n}") for n in range(4)]
    store = _Store()

    class Interrupted(_Rs):
        def fetch_ecli_content(self, ecli: str) -> str:
            if ecli == "ECLI:2":
                raise KeyboardInterrupt
            return super().fetch_ecli_content(ecli)

    with pytest.raises(KeyboardInterrupt):
        _pipeline(Interrupted(entries), store)[0].run(courts=["hr"])
    assert [r["external_id"] for r in store.records] == ["ECLI:0", "ECLI:1"]

    # the next run sees what was stored (with a fetch time after each change)
    now = dt.datetime.now(UTC).isoformat()
    store.stored = {r["external_id"]: now for r in store.records}
    rs = _Rs(entries)
    _pipeline(rs, store)[0].run(courts=["hr"])
    assert rs.fetched == ["ECLI:2", "ECLI:3"]


def test_a_failing_content_download_is_skipped_and_the_rest_goes_on() -> None:
    rs = _Rs(
        [_entry("ECLI:A"), _entry("ECLI:B"), _entry("ECLI:C")],
        {"ECLI:B": requests.ConnectionError("x")},
    )
    pipeline, store = _pipeline(rs)
    pipeline.run(courts=["hr"])
    assert [r["external_id"] for r in store.records] == ["ECLI:A", "ECLI:C"]


def test_a_failing_index_is_an_error_and_stores_nothing() -> None:
    class Down(_Rs):
        def iter_index(self, **kw):
            raise requests.ConnectionError("no route")
            yield  # pragma: no cover

    pipeline, store = _pipeline(Down([]))
    result = pipeline.run(courts=["hr"])
    assert store.records == [] and "no route" in result.errors[0]


def test_an_unknown_court_is_an_error_of_the_step() -> None:
    pipeline, store = _pipeline(_Rs([]))
    result = pipeline.run(courts=["rechtbank"])
    assert store.records == [] and "unknown court" in result.errors[0]


def test_explicit_eclis_are_fetched_unless_stored_in_the_last_24_hours() -> None:
    now = dt.datetime.now(UTC).isoformat()
    old = (dt.datetime.now(UTC) - dt.timedelta(days=3)).isoformat()
    rs = _Rs([])
    store = _Store({"ECLI:RECENT": now, "ECLI:OLD": old})
    _pipeline(rs, store)[0].run(eclis=["ECLI:RECENT", "ECLI:OLD", "ECLI:NEW"])
    assert rs.fetched == ["ECLI:OLD", "ECLI:NEW"]
    assert rs.index_calls == []  # no courts, no index


def test_an_ecli_that_is_also_in_the_index_is_fetched_once() -> None:
    rs = _Rs([_entry("ECLI:A")])
    _pipeline(rs)[0].run(courts=["hr"], eclis=["ECLI:A", "ECLI:B"])
    assert rs.fetched == ["ECLI:A", "ECLI:B"]


# ── the command ──────────────────────────────────────────────────────────────


@pytest.fixture
def cli(monkeypatch):
    from lawgraph.pipelines import retrieve_cli

    seen: dict[str, Any] = {}

    class Recorder:
        def __init__(self, store) -> None:
            pass

        def run(self, **kwargs):
            seen.update(kwargs)
            from lawgraph.core.models import PipelineResult

            return PipelineResult()

    monkeypatch.setattr(retrieve_cli, "ArangoStore", lambda: object())
    monkeypatch.setattr(retrieve_cli, "RechtspraakRetrievePipeline", Recorder)
    return lambda argv: (retrieve_cli.retrieve_rechtspraak(argv), seen)[1]


def test_the_default_courts_are_the_hoge_raad_raad_van_state_and_the_hoven(cli) -> None:
    assert cli([])["courts"] == ["hr", "rvs", "hoven"]


def test_only_eclis_means_no_courts(cli) -> None:
    seen = cli(["--ecli", "ECLI:NL:HR:2025:1"])
    assert seen["courts"] == [] and seen["eclis"] == ["ECLI:NL:HR:2025:1"]


def test_courts_and_eclis_can_be_combined(cli) -> None:
    seen = cli(["--court", "hr", "--ecli", "ECLI:NL:HR:2025:1"])
    assert seen["courts"] == ["hr"] and seen["eclis"] == ["ECLI:NL:HR:2025:1"]


def test_an_incremental_run_looks_back_over_the_publication_lag(cli) -> None:
    seen = cli(["--since", "2026-01-31"])
    assert seen["date_from"] == dt.date(2026, 1, 1)  # 30 days before the date


def test_a_full_run_has_no_date_filter(cli) -> None:
    assert cli(["--mode", "full"])["date_from"] is None


def test_a_judgment_published_long_after_its_decision_is_found_by_its_modified_date() -> (
    None
):
    """Decided in June, published in September: it is in no decision window of a daily run."""
    decided_recently = IndexEntry(ecli="ECLI:NL:HR:2026:900", updated=None, title="")
    published_late = IndexEntry(ecli="ECLI:NL:GHARL:2026:100", updated=None, title="")
    rs = _Rs([decided_recently])
    rs.late = [published_late, decided_recently]  # the listings overlap
    pipeline, store = _pipeline(rs)
    since = dt.datetime(2026, 9, 19, tzinfo=dt.timezone.utc)
    result = pipeline.run(
        courts=["hr"], date_from=dt.date(2026, 8, 20), modified_from=since
    )

    assert rs.fetched == ["ECLI:NL:HR:2026:900", "ECLI:NL:GHARL:2026:100"]  # each once
    assert result.created == 2
    assert [c.get("modified_from") for c in rs.index_calls] == [None, since]


def test_the_modified_window_is_sent_as_a_range_up_to_now() -> None:
    calls: list[dict] = []
    client = RechtspraakClient.__new__(RechtspraakClient)

    def fake_get_text(path, *, params=None, timeout=30):
        calls.append(dict(params or {}))
        return (
            "<feed xmlns='http://www.w3.org/2005/Atom'>"
            "<subtitle>Aantal gevonden ECLI's: 0</subtitle></feed>"
        )

    client._get_text = fake_get_text  # type: ignore[method-assign]
    list(
        client.iter_index(
            courts=["Hoge_Raad_der_Nederlanden"],
            modified_from=dt.datetime(2026, 9, 19, 6, 30, tzinfo=dt.timezone.utc),
        )
    )
    assert calls[0]["modified"][0] == "2026-09-19T06:30:00" and "date" not in calls[0]
