"""retrieve bwb asks the source for what it does not know yet, not three requests a regulation."""

from __future__ import annotations

from typing import Any

from lawgraph.clients.bwb import BWBClient, ToestandMeta, _newer
from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, RAW_KIND_BWB_WTI_GENERAL
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

    def enumerate_latest(self) -> dict[str, ToestandMeta]:
        self.requests.append("listing")
        return dict(self.current)

    def latest_toestand(self, bwb_id: str) -> ToestandMeta | None:
        self.requests.append(f"sru {bwb_id}")
        return self.current.get(bwb_id)

    def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
        self.requests.append(f"xml {meta['bwb_id']}")
        return "<toestand/>"

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
        if "cutoff" in bind:  # stored since: everything here was stored just now
            return [d["external_id"] for d in rows if not d.get("old")]
        return [
            {"id": d["external_id"], "url": d["meta"].get("state_url")} for d in rows
        ]


def test_the_current_toestand_is_the_valid_one_with_the_latest_dates() -> None:
    old = _meta("BWBR1", "2020-01-01", "2023-12-31")
    valid = _meta("BWBR1", "2024-01-01")
    future_end = _meta("BWBR1", "2019-01-01", "2030-01-01")
    assert _newer(valid, old) and _newer(valid, future_end) and not _newer(old, valid)
    assert not _newer(
        valid, valid
    )  # of two equals the first one stays, as sorted() did


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
