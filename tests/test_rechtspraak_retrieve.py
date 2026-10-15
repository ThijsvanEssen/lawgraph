"""Rechtspraak judgments by court and decision date, from a real (recorded) index page."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

import pytest
import requests

from lawgraph.clients.base import ATTEMPTS
from lawgraph.clients.rechtspraak import OWMS_TERMS, RechtspraakClient
from lawgraph.config.constants import RAW_KIND_RECHTSPRAAK_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.config.sources import RECHTSPRAAK
from lawgraph.core.case_numbers import Referral
from lawgraph.core.courts import owms_terms
from lawgraph.core.rechtspraak_index import IndexEntry, parse_index
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from tests.fakes import InMemoryStore, ScriptedSession, Sent, external_ids, raw_record
from tests.paths import fixture_text

pytestmark = pytest.mark.usefixtures("raw_reads")

# one real Hoge Raad entry; the search matched 47
INDEX_PAGE = fixture_text("rechtspraak_index_page.xml")

UTC = dt.UTC


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


def test_a_page_that_is_no_feed_is_not_an_empty_index() -> None:
    """A maintenance page sent with HTTP 200 can be well-formed; it holds no entries."""
    page = '<html xmlns="http://www.w3.org/1999/xhtml"><body>Onderhoud</body></html>'
    with pytest.raises(ValueError, match="not an Atom feed.*<html>"):
        parse_index(page)


def test_an_entry_whose_time_cannot_be_read_raises_with_its_ecli() -> None:
    page = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>ECLI:NL:HR:2025:1</id>'
        "<updated>gisteren</updated><title>t</title></entry></feed>"
    )
    with pytest.raises(ValueError, match="ECLI:NL:HR:2025:1.*gisteren"):
        parse_index(page)


def test_an_entry_without_a_time_has_none() -> None:
    page = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>ECLI:NL:HR:2025:1</id>'
        "<title>t</title></entry></feed>"
    )
    assert parse_index(page)[1][0].updated is None


# ── the client ───────────────────────────────────────────────────────────────


def _client(pages: list[Any], calls: list[dict]) -> RechtspraakClient:
    """A client answered *pages* in turn (or an exception); the path and parameters of
    every request go into *calls*."""

    def step(page: Any):
        def answer(sent: Sent) -> Any:
            path = sent.url.removeprefix(RECHTSPRAAK.base_url)
            calls.append({"path": path, "params": dict(sent.params)})
            return page

        return answer

    return RechtspraakClient(session=ScriptedSession(*map(step, pages)))


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
            from_date=dt.date(2024, 9, 20),
            to_date=dt.date(2026, 9, 20),
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


def test_without_courts_every_court_is_asked_for() -> None:
    calls: list[dict] = []
    day = dt.date(2021, 1, 15)
    list(_client([_page(0)], calls).iter_index(from_date=day, to_date=day))
    assert "creator" not in calls[0]["params"]
    assert calls[0]["params"]["date"] == ["2021-01-15", "2021-01-15"]


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


def test_a_failing_page_raises_after_the_earlier_ones_were_yielded(slept) -> None:
    dropped = [requests.ConnectionError("dropped")] * ATTEMPTS
    client = _client([_page(1000, 5000), *dropped], [])
    seen = []
    with pytest.raises(requests.ConnectionError):
        for entry in client.iter_index(courts=["Raad_van_State"]):
            seen.append(entry)
    assert len(seen) == 1000


# ── which courts ─────────────────────────────────────────────────────────────


def test_codes_and_tiers_resolve_to_the_owms_terms_of_the_court_table() -> None:
    assert owms_terms(["HR", "rvs"]) == [
        "Hoge_Raad_der_Nederlanden",
        "Raad_van_State",
    ]
    hoven = owms_terms(["gerechtshof"])
    assert "Gerechtshof_Amsterdam" in hoven and "Gerechtshof_'s-Hertogenbosch" in hoven
    # the courts of appeal before 2013 too: the index keeps their judgments
    assert "Gerechtshof_Leeuwarden" in hoven and len(hoven) == 7


def test_a_court_the_index_cannot_be_filtered_by_or_an_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="cannot be filtered"):
        owms_terms(["XX"])  # the foreign courts: no OWMS term
    with pytest.raises(ValueError, match="unknown court"):
        owms_terms(["hoven"])


def test_all_is_every_court_so_no_filter_at_all() -> None:
    """The rechtbanken and every other court of the index are in it, none left out."""
    assert owms_terms(["all"]) == []
    assert owms_terms(["HR", "all"]) == []


def test_a_court_is_listed_once() -> None:
    assert (
        owms_terms(["HR", "hr", "gerechtshof", "GHAMS"]).count("Gerechtshof_Amsterdam")
        == 1
    )


def test_an_unknown_court_is_named_with_the_known_ones() -> None:
    with pytest.raises(ValueError, match="unknown court 'nope'.*gerechtshof"):
        owms_terms(["nope"])


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

    def iter_index(
        self, *, courts=(), from_date=None, to_date=None, modified_from=None
    ):
        call = {"courts": courts, "from": from_date, "to": to_date}
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


def _store(fetched: dict[str, str] | None = None) -> InMemoryStore:
    """The judgments stored before, by ECLI with when each was fetched."""
    return InMemoryStore(
        raw=[
            raw_record(
                SOURCE_RECHTSPRAAK, RAW_KIND_RECHTSPRAAK_CONTENT, ecli, fetched_at=at
            )
            for ecli, at in (fetched or {}).items()
        ]
    )


def _pipeline(rs: _Rs, store: InMemoryStore | None = None):
    store = store or _store()
    return RechtspraakRetrievePipeline(store=store, rs_client=rs), store


def test_every_judgment_of_the_index_is_downloaded_and_stored() -> None:
    rs = _Rs([_entry("ECLI:A"), _entry("ECLI:B")])
    pipeline, store = _pipeline(rs)
    result = pipeline.run(courts=["hr"])

    assert (result.created, result.errors) == (2, [])
    first = next(iter(store.raw.values()))
    assert first["source"] == "rechtspraak" and first["kind"] == "rs-content"
    assert (
        first["external_id"] == "ECLI:A"
        and first["payload_text"] == "<xml>ECLI:A</xml>"
    )
    assert first["meta"] == {"ecli": "ECLI:A", "updated": "2025-03-01T10:00:00+00:00"}


def test_the_courts_and_dates_reach_the_index() -> None:
    rs = _Rs([])
    pipeline, _ = _pipeline(rs)
    pipeline.run(courts=["hr", "gerechtshof"], from_date=dt.date(2024, 9, 20))
    call = rs.index_calls[0]
    assert call["courts"][0] == "Hoge_Raad_der_Nederlanden" and len(call["courts"]) == 8
    assert call["from"] == dt.date(2024, 9, 20)


def test_every_court_reads_the_index_without_a_court_filter() -> None:
    rs = _Rs([_entry("ECLI:NL:RBAMS:2025:1"), _entry("ECLI:NL:HR:2025:1")])
    pipeline, _ = _pipeline(rs)
    pipeline.run(courts=["all"], from_date=dt.date(2024, 9, 20))
    assert rs.index_calls[0]["courts"] == []
    assert rs.fetched == ["ECLI:NL:RBAMS:2025:1", "ECLI:NL:HR:2025:1"]


def test_a_judgment_stored_after_its_last_change_is_not_downloaded_again() -> None:
    rs = _Rs([_entry("ECLI:A"), _entry("ECLI:B"), _entry("ECLI:C")])
    store = _store(
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
    store = _store()

    class Interrupted(_Rs):
        def fetch_ecli_content(self, ecli: str) -> str:
            if ecli == "ECLI:2":
                raise KeyboardInterrupt
            return super().fetch_ecli_content(ecli)

    with pytest.raises(KeyboardInterrupt):
        _pipeline(Interrupted(entries), store)[0].run(courts=["hr"])
    assert external_ids(store) == ["ECLI:0", "ECLI:1"]

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
    assert external_ids(store) == ["ECLI:A", "ECLI:C"]


def test_a_failing_index_is_an_error_and_stores_nothing() -> None:
    class Down(_Rs):
        def iter_index(self, **kw):
            raise requests.ConnectionError("no route")
            yield  # pragma: no cover

    pipeline, store = _pipeline(Down([]))
    result = pipeline.run(courts=["hr"])
    assert store.raw == {} and "no route" in result.errors[0]


def test_a_referral_is_found_in_the_index_of_its_date_by_case_number() -> None:
    """ECLI:NL:HR:2021:1725 names "8527084 VZ VERZ 20-9656 van 15 januari 2021"; the
    titles are those of the index of that day."""
    listed = [
        IndexEntry(
            ecli=ecli,
            updated=dt.datetime(2021, 2, 1, tzinfo=UTC),
            title=f"{ecli}, Rechtbank Rotterdam, 15-01-2021, {numbers}",
        )
        for ecli, numbers in (
            ("ECLI:NL:RBROT:2021:207", "8527084 VZ VERZ 20-9656"),
            ("ECLI:NL:RBROT:2021:197", "8398405 CV EXPL 20-9220"),
        )
    ]
    rs = _Rs(listed)
    referrals = [
        Referral(case_numbers=("8527084 VZ VERZ 20-9656",), date="2021-01-15"),
        Referral(case_numbers=("9999999 CV EXPL 20-1",), date="2021-01-15"),
    ]
    pipeline, store = _pipeline(rs)
    pipeline.run(referrals=referrals)
    day = dt.date(2021, 1, 15)
    assert rs.index_calls == [{"courts": (), "from": day, "to": day}]  # once per date
    assert rs.fetched == ["ECLI:NL:RBROT:2021:207"]


def test_an_unknown_court_is_an_error_of_the_step() -> None:
    pipeline, store = _pipeline(_Rs([]))
    result = pipeline.run(courts=["nope"])
    assert store.raw == {} and "unknown court" in result.errors[0]


def test_explicit_eclis_are_fetched_unless_stored_in_the_last_24_hours() -> None:
    now = dt.datetime.now(UTC).isoformat()
    old = (dt.datetime.now(UTC) - dt.timedelta(days=3)).isoformat()
    rs = _Rs([])
    store = _store({"ECLI:RECENT": now, "ECLI:OLD": old})
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
    from lawgraph.pipelines import retrieve_commands
    from lawgraph.sources.registry import find

    seen: dict[str, Any] = {}

    class Recorder:
        def __init__(self, store) -> None:
            pass

        def run(self, **kwargs):
            seen.update(kwargs)
            from lawgraph.core.models import PipelineResult

            return PipelineResult()

    monkeypatch.setattr(retrieve_commands, "GraphStore", lambda: object())
    monkeypatch.setattr(retrieve_commands, "RechtspraakRetrievePipeline", Recorder)
    command = find("retrieve", "rechtspraak").command  # type: ignore[union-attr]
    return lambda argv: (command(argv), seen)[1]


def test_the_default_is_every_court(cli) -> None:
    assert cli([])["courts"] == ["all"]


def test_court_narrows_the_default(cli) -> None:
    assert cli(["--court", "hr", "--court", "gerechtshof"])["courts"] == [
        "hr",
        "gerechtshof",
    ]


def test_only_eclis_means_no_courts(cli) -> None:
    seen = cli(["--ecli", "ECLI:NL:HR:2025:1"])
    assert seen["courts"] == [] and seen["eclis"] == ["ECLI:NL:HR:2025:1"]


def test_courts_and_eclis_can_be_combined(cli) -> None:
    seen = cli(["--court", "hr", "--ecli", "ECLI:NL:HR:2025:1"])
    assert seen["courts"] == ["hr"] and seen["eclis"] == ["ECLI:NL:HR:2025:1"]


def test_an_incremental_run_looks_back_over_the_publication_lag(cli) -> None:
    seen = cli(["--since", "2026-01-31"])
    assert seen["from_date"] == dt.date(2026, 1, 1)  # 30 days before the date


def test_a_full_run_has_no_date_filter(cli) -> None:
    assert cli(["--mode", "full"])["from_date"] is None


def test_a_judgment_published_long_after_its_decision_is_found_by_its_modified_date() -> (
    None
):
    """Decided in June, published in September: it is in no decision window of a daily run."""
    decided_recently = IndexEntry(ecli="ECLI:NL:HR:2026:900", updated=None, title="")
    published_late = IndexEntry(ecli="ECLI:NL:GHARL:2026:100", updated=None, title="")
    rs = _Rs([decided_recently])
    rs.late = [published_late, decided_recently]  # the listings overlap
    pipeline, store = _pipeline(rs)
    since = dt.datetime(2026, 9, 19, tzinfo=dt.UTC)
    result = pipeline.run(
        courts=["hr"], from_date=dt.date(2026, 8, 20), modified_from=since
    )

    assert rs.fetched == ["ECLI:NL:HR:2026:900", "ECLI:NL:GHARL:2026:100"]  # each once
    assert result.created == 2
    assert [c.get("modified_from") for c in rs.index_calls] == [None, since]


def test_the_modified_window_is_sent_as_a_range_up_to_now() -> None:
    calls: list[dict] = []
    client = RechtspraakClient(
        session=ScriptedSession(
            "<feed xmlns='http://www.w3.org/2005/Atom'>"
            "<subtitle>Aantal gevonden ECLI's: 0</subtitle></feed>",
            asked=calls,
        )
    )
    list(
        client.iter_index(
            courts=["Hoge_Raad_der_Nederlanden"],
            modified_from=dt.datetime(2026, 9, 19, 6, 30, tzinfo=dt.UTC),
        )
    )
    assert calls[0]["modified"][0] == "2026-09-19T06:30:00" and "date" not in calls[0]
