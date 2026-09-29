"""retrieve bwb asks the source for what it does not know yet, not three requests a regulation."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.clients.bwb import BWBClient, ToestandMeta, _newer
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_BWB_WTI_GENERAL,
)
from lawgraph.pipelines.retrieve import bwb
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from tests.fakes import RawSourcesFake


def _meta(bwb_id: str, start: str, end: str = "9999-12-31") -> ToestandMeta:
    return {
        "bwb_id": bwb_id,
        "locatie_toestand": f"https://repo/{bwb_id}/{start}/xml/{bwb_id}.xml",
        "locatie_wti": f"https://repo/{bwb_id}/{bwb_id}.WTI",
        "locatie_manifest": None,
        "geldigheidsperiode_startdatum": start,
        "geldigheidsperiode_einddatum": end,
    }


class _Client:
    def __init__(self, current: dict[str, ToestandMeta]) -> None:
        self.current = current
        self.requests: list[str] = []
        self.history: dict[
            str, list[ToestandMeta]
        ] = {}  # every toestand per regulation

    def enumerate_latest(self) -> dict[str, ToestandMeta]:
        self.requests.append("listing")
        return dict(self.current)

    def latest_toestand(self, bwb_id: str) -> ToestandMeta | None:
        self.requests.append(f"sru {bwb_id}")
        return self.current.get(bwb_id)

    def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
        self.requests.append(f"xml {meta['bwb_id']}")
        return "<toestand/>"

    def search_toestanden(self, bwb_id: str) -> list[ToestandMeta]:
        self.requests.append(f"sru {bwb_id}")
        return list(self.history.get(bwb_id, []))

    def enumerate_toestanden(self) -> dict[str, list[ToestandMeta]]:
        self.requests.append("listing")
        return {bwb_id: list(metas) for bwb_id, metas in self.history.items()}

    def fetch_wti_general_info(self, meta: ToestandMeta) -> str | None:
        self.requests.append(f"wti {meta['bwb_id']}")
        return "<algemene-informatie/>"


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}

    def insert_raw_source(self, *, kind: str, external_id: str, **fields: Any) -> None:
        self.docs[(kind, external_id)] = {"external_id": external_id, **fields}

    def query(self, aql: str, bind_vars: dict | None = None, **_kw: Any) -> list[Any]:
        bind = bind_vars or {}
        rows = [d for (kind, _), d in self.docs.items() if kind == bind["kind"]]
        if "now" in bind:  # remembered as missing: every such record is a fresh one
            return [d["external_id"] for d in rows]
        if "cutoff" in bind:  # stored since: everything here was stored just now
            return [d["external_id"] for d in rows if not d.get("old")]
        return [  # the state urls and the fetch times
            {
                "id": d["external_id"],
                "url": d["meta"].get("state_url"),
                "at": "2026-01-01T00:00:00Z",
            }
            for d in rows
        ]


def test_the_current_toestand_is_the_one_in_force_today() -> None:
    import datetime as dt

    today = dt.date(2026, 9, 20)
    old = _meta("BWBR1", "2020-01-01", "2023-12-31")
    in_force = _meta("BWBR1", "2024-01-01", "2026-12-31")
    next_year = _meta(
        "BWBR1", "2027-01-01"
    )  # runs to 9999-12-31, and is not the law yet

    assert _newer(in_force, old, today) and _newer(in_force, next_year, today)
    assert not _newer(next_year, in_force, today)
    assert not _newer(in_force, in_force, today)  # of two equals the first one stays
    # A repealed regulation: the last toestand that was in force, not one still to come.
    ended = _meta("BWBR1", "2024-01-01", "2025-12-31")
    assert _newer(ended, old, today) and _newer(ended, next_year, today)
    # The usual case: one toestand, in force with an open end.
    assert _newer(_meta("BWBR1", "2024-01-01"), old, today)


def test_latest_toestand_picks_the_same_one_as_the_listing() -> None:
    toestanden = [
        _meta("BWBR1", "2020-01-01", "2023-12-31"),
        _meta("BWBR1", "2024-01-01"),
        _meta("BWBR1", "2022-01-01", "2022-12-31"),
    ]
    client = BWBClient.__new__(BWBClient)
    client.search_toestanden = lambda bwb_id: toestanden  # type: ignore[method-assign]
    assert client.latest_toestand("BWBR1") == toestanden[1]


def test_a_full_load_asks_no_second_time_for_the_toestand_it_listed() -> None:
    client = _Client(
        {"BWBR1": _meta("BWBR1", "2024-01-01"), "BWBR2": _meta("BWBR2", "2023-07-01")}
    )
    store = _Store()
    result = BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]

    assert result.created == 4 and result.errors == []
    assert not [r for r in client.requests if r.startswith("sru")]
    assert (
        len(client.requests) == 1 + 2 * 2
    )  # the listing, then XML and WTI per regulation


def test_an_unchanged_toestand_is_not_downloaded_again() -> None:
    client = _Client(
        {"BWBR1": _meta("BWBR1", "2024-01-01"), "BWBR2": _meta("BWBR2", "2023-07-01")}
    )
    store = _Store()
    BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]

    # A week later: BWBR2 has a new toestand, BWBR1 has not. (Nothing counts as stored in the
    # last 24 hours any more; the WTI records are younger than a month.)
    for (kind, _), doc in store.docs.items():
        doc["old"] = kind == RAW_KIND_BWB_TOESTAND
    client.current["BWBR2"] = _meta("BWBR2", "2026-01-01")
    client.requests.clear()
    result = BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]

    assert client.requests == ["listing", "xml BWBR2", "wti BWBR2"]
    assert (result.created, result.skipped) == (2, 1)
    assert (
        store.docs[(RAW_KIND_BWB_TOESTAND, "BWBR2")]["meta"]["start_date"]
        == "2026-01-01"
    )


def test_the_wti_of_an_unchanged_toestand_is_read_again_after_a_month() -> None:
    client = _Client({"BWBR1": _meta("BWBR1", "2024-01-01")})
    store = _Store()
    BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]
    for doc in store.docs.values():
        doc["old"] = True  # the WTI record too
    client.requests.clear()
    BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]

    assert client.requests == ["listing", "wti BWBR1"]
    assert (RAW_KIND_BWB_WTI_GENERAL, "BWBR1") in store.docs


def test_an_id_that_is_asked_for_by_name_is_always_downloaded() -> None:
    client = _Client({"BWBR1": _meta("BWBR1", "2024-01-01")})
    store = _Store()
    BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]
    for doc in store.docs.values():
        doc["old"] = True
    client.requests.clear()
    BWBRetrievePipeline(store=store, client=client).run(bwb_ids=["BWBR1"])  # type: ignore[arg-type]

    assert client.requests == ["sru BWBR1", "xml BWBR1", "wti BWBR1"]


def test_a_toestand_the_repository_does_not_serve_is_remembered_not_a_failure() -> None:
    """BWBR0015091 on 2026-09-21: listed by the SRU, and its file redirects to itself
    (HTTP 301 for ever). As a failure it made every full load end failed."""
    import requests

    from lawgraph.config.constants import RAW_KIND_MISSING_SUFFIX

    response = requests.Response()
    response.status_code = 301

    class Client(_Client):
        def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
            self.requests.append(f"xml {meta['bwb_id']}")
            if meta["bwb_id"] == "BWBR2":
                raise requests.TooManyRedirects("30 redirects", response=response)
            return "<toestand/>"

    store = _Store()
    client = Client(
        {"BWBR1": _meta("BWBR1", "2020-01-01"), "BWBR2": _meta("BWBR2", "2020-01-01")}
    )
    result = BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]

    assert result.errors == []
    missing = store.docs[(RAW_KIND_BWB_TOESTAND + RAW_KIND_MISSING_SUFFIX, "BWBR2")]
    assert missing["meta"]["status"] == 301
    assert (RAW_KIND_BWB_TOESTAND, "BWBR1") in store.docs

    client.requests.clear()
    store.docs[(RAW_KIND_BWB_TOESTAND, "BWBR1")]["old"] = True  # not stored today
    BWBRetrievePipeline(store=store, client=client).run_full()  # type: ignore[arg-type]
    assert "xml BWBR2" not in client.requests


# ── the history ──────────────────────────────────────────────────────────────


def _history_client() -> _Client:
    client = _Client(
        {"BWBR1": _meta("BWBR1", "2024-01-01"), "BWBR2": _meta("BWBR2", "2023-07-01")}
    )
    client.history = {
        "BWBR1": [
            _meta("BWBR1", "2020-01-01", "2023-12-31"),
            _meta("BWBR1", "2024-01-01"),
        ],
        "BWBR2": [_meta("BWBR2", "2023-07-01")],
    }
    return client


def _history_keys(store: _Store) -> set[str]:
    return {key for kind, key in store.docs if kind == RAW_KIND_BWB_TOESTAND_ALL}


@pytest.mark.parametrize("listing", [False, True])
def test_a_second_history_run_downloads_only_the_new_toestanden(
    monkeypatch, listing: bool
) -> None:
    """Of a known regulation only what is new, of a new regulation everything: whether the
    toestanden come from one SRU query per regulation or from the listing of them all."""
    monkeypatch.setattr(bwb, "HISTORY_LISTING_FROM", 1 if listing else 1000)
    client = _history_client()
    store = _Store()
    first = BWBRetrievePipeline(store=store, client=client).run_history(  # type: ignore[arg-type]
        bwb_ids=["BWBR1", "BWBR2"]
    )
    assert (first.created, first.errors) == (3, [])
    assert _history_keys(store) == {
        "BWBR1@2020-01-01",
        "BWBR1@2024-01-01",
        "BWBR2@2023-07-01",
    }

    # BWBR1 gets a toestand of next year; BWBR3 is new.
    client.history["BWBR1"].append(_meta("BWBR1", "2027-01-01"))
    client.history["BWBR3"] = [
        _meta("BWBR3", "2025-01-01", "2025-12-31"),
        _meta("BWBR3", "2026-01-01"),
    ]
    client.requests.clear()
    second = BWBRetrievePipeline(store=store, client=client).run_history(  # type: ignore[arg-type]
        bwb_ids=["BWBR1", "BWBR2", "BWBR3"]
    )

    assert second.created == 3
    downloads = sorted(r for r in client.requests if r.startswith("xml"))
    assert downloads == ["xml BWBR1", "xml BWBR3", "xml BWBR3"]
    asked = [r for r in client.requests if not r.startswith("xml")]
    assert asked == (
        ["listing"] if listing else ["sru BWBR1", "sru BWBR2", "sru BWBR3"]
    )


def test_full_mode_downloads_every_toestand_again() -> None:
    client = _history_client()
    store = _Store()
    BWBRetrievePipeline(store=store, client=client).run_history(bwb_ids=["BWBR1"])  # type: ignore[arg-type]
    client.requests.clear()
    result = BWBRetrievePipeline(store=store, client=client).run_history(  # type: ignore[arg-type]
        bwb_ids=["BWBR1"], refetch=True
    )
    assert result.created == 2
    assert client.requests.count("xml BWBR1") == 2


def test_without_ids_the_history_is_that_of_the_regulations_bwb_stored() -> None:
    client = _history_client()
    store = _Store()
    BWBRetrievePipeline(store=store, client=client).run(bwb_ids=["BWBR2"])  # type: ignore[arg-type]
    client.requests.clear()
    BWBRetrievePipeline(store=store, client=client).run_history()  # type: ignore[arg-type]

    assert client.requests == ["sru BWBR2", "xml BWBR2"]
    assert _history_keys(store) == {"BWBR2@2023-07-01"}


def test_a_toestand_without_a_file_is_remembered_and_not_asked_for_again() -> None:
    import requests

    from lawgraph.config.constants import RAW_KIND_MISSING_SUFFIX

    response = requests.Response()
    response.status_code = 404

    class Client(_Client):
        def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
            self.requests.append(f"xml {meta['geldigheidsperiode_startdatum']}")
            if meta["geldigheidsperiode_startdatum"] == "2020-01-01":
                raise requests.HTTPError("404", response=response)
            return "<toestand/>"

    client = Client({})
    client.history = _history_client().history
    store = _Store()
    result = BWBRetrievePipeline(store=store, client=client).run_history(  # type: ignore[arg-type]
        bwb_ids=["BWBR1"]
    )
    assert (result.created, result.errors) == (1, [])
    assert (
        RAW_KIND_BWB_TOESTAND_ALL + RAW_KIND_MISSING_SUFFIX,
        "BWBR1@2020-01-01",
    ) in (store.docs)

    client.requests.clear()
    BWBRetrievePipeline(store=store, client=client).run_history(bwb_ids=["BWBR1"])  # type: ignore[arg-type]
    assert client.requests == ["sru BWBR1"]
