"""``retrieve bwb-history`` on a real database: a second run fetches only what is new."""

from __future__ import annotations

from lawgraph.clients.bwb import ToestandMeta
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_MISSING_SUFFIX,
    SOURCE_BWB,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline


def _meta(bwb_id: str, start: str) -> ToestandMeta:
    return {
        "bwb_id": bwb_id,
        "title": None,
        "locatie_toestand": f"https://repo/{bwb_id}/{start}/xml/{bwb_id}.xml",
        "locatie_wti": None,
        "locatie_manifest": None,
        "geldigheidsperiode_startdatum": start,
        "geldigheidsperiode_einddatum": "9999-12-31",
    }


class _Sru:
    """The SRU and the repository: the toestanden of each regulation; 2021 has no file."""

    def __init__(self, history: dict[str, list[str]]) -> None:
        self.history = history
        self.downloaded: list[str] = []

    def search_toestanden(self, bwb_id: str) -> list[ToestandMeta]:
        return [_meta(bwb_id, start) for start in self.history.get(bwb_id, [])]

    def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
        import requests

        start = meta["geldigheidsperiode_startdatum"]
        self.downloaded.append(f"{meta['bwb_id']}@{start}")
        if start == "2021-01-01":
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404", response=response)
        return f"<toestand start='{start}'/>"


def _current(store: ArangoStore, *bwb_ids: str) -> None:
    """What ``retrieve bwb`` leaves: the current toestand of each regulation."""
    with RawSourceWriter(store) as writer:
        for bwb_id in bwb_ids:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text="<toestand/>",
                    meta={"bwb_id": bwb_id, "state_url": f"https://repo/{bwb_id}"},
                )
            )


def _stored(store: ArangoStore, kind: str) -> set[str]:
    statement = "SELECT external_id FROM raw_sources WHERE kind = %(kind)s"
    return set(store.query(statement, {"kind": kind}))


def test_a_second_run_downloads_only_the_toestanden_that_are_new(
    database: str,
) -> None:
    store = ArangoStore()
    _current(store, "BWBR0000001", "BWBR0000002")
    sru = _Sru(
        {
            "BWBR0000001": ["2020-01-01", "2021-01-01", "2024-01-01"],
            "BWBR0000002": ["2023-07-01"],
        }
    )
    first = BWBRetrievePipeline(store=store, client=sru).run_history()  # type: ignore[arg-type]
    assert (first.created, first.errors) == (3, [])
    assert _stored(store, RAW_KIND_BWB_TOESTAND_ALL) == {
        "BWBR0000001@2020-01-01",
        "BWBR0000001@2024-01-01",
        "BWBR0000002@2023-07-01",
    }
    assert _stored(store, RAW_KIND_BWB_TOESTAND_ALL + RAW_KIND_MISSING_SUFFIX) == {
        "BWBR0000001@2021-01-01"
    }

    # A new toestand of a known regulation, and a regulation bwb stored since.
    sru.history["BWBR0000001"].append("2027-01-01")
    sru.history["BWBR0000003"] = ["2025-01-01", "2026-01-01"]
    _current(store, "BWBR0000003")
    sru.downloaded.clear()
    second = BWBRetrievePipeline(store=store, client=sru).run_history()  # type: ignore[arg-type]

    assert second.created == 3
    assert sorted(sru.downloaded) == [
        "BWBR0000001@2027-01-01",
        "BWBR0000003@2025-01-01",
        "BWBR0000003@2026-01-01",
    ]
