"""WTI abbreviations end to end: client download, retrieve record, short_title on the instrument."""

from __future__ import annotations

import pathlib
from typing import Any

from lawgraph.clients.bwb import WTI_CHUNK_SIZE, BWBClient, ToestandMeta
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_WTI_GENERAL,
    SOURCE_BWB,
)
from lawgraph.core.bwb_wti import extract_general_info
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from tests.fakes import RawSourcesFake
from tests.normalize.test_bwb import _Store

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SR_HEAD = (FIXTURES / "bwb_wti_sr_head.xml").read_text()
SR_GENERAL = extract_general_info(SR_HEAD) or ""
BW1_GENERAL = (FIXTURES / "bwb_wti_bw1_general.xml").read_text()
TOESTAND_XML = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()

SR = "BWBR0001854"
BW1 = "BWBR0002656"
BW5 = "BWBR0005288"
WTI_URL = f"https://repository.officiele-overheidspublicaties.nl/bwb/{SR}/{SR}.WTI"


def _meta(bwb_id: str = SR, wti_url: str | None = WTI_URL) -> ToestandMeta:
    return {
        "bwb_id": bwb_id,
        "locatie_toestand": "https://example.invalid/toestand.xml",
        "locatie_wti": wti_url,
        "locatie_manifest": None,
        "geldigheidsperiode_startdatum": "2026-07-01",
        "geldigheidsperiode_einddatum": "9999-12-31",
    }


# ── client ───────────────────────────────────────────────────────────────────


class _StreamedResponse:
    """A large WTI body; records how much of it was read and whether it was closed."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.chunks_read = 0
        self.closed = False

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.body), chunk_size):
            self.chunks_read += 1
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


def _client(response: _StreamedResponse, calls: list[dict]) -> BWBClient:
    client = BWBClient.__new__(BWBClient)  # no HTTP session needed

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return response

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def test_client_stops_downloading_once_the_element_is_complete() -> None:
    body = SR_HEAD.encode() + b"<regeling/>" * 100_000  # the real file is 27 MB
    response = _StreamedResponse(body)
    calls: list[dict] = []

    general_info = _client(response, calls).fetch_wti_general_info(_meta())

    assert general_info == SR_GENERAL
    assert calls == [{"url": WTI_URL, "timeout": 30, "stream": True}]
    assert response.chunks_read == len(SR_GENERAL.encode()) // WTI_CHUNK_SIZE + 1
    assert response.closed


def test_client_returns_nothing_without_a_wti_location_or_element() -> None:
    calls: list[dict] = []
    empty = _StreamedResponse(b"<wetstechnische-informatie/>")

    assert _client(empty, calls).fetch_wti_general_info(_meta(wti_url=None)) is None
    assert calls == []
    assert _client(empty, calls).fetch_wti_general_info(_meta()) is None
    assert empty.closed


# ── retrieve ─────────────────────────────────────────────────────────────────


class _RawStore(RawSourcesFake):
    def __init__(self, recent: list[str] | None = None) -> None:
        self.records: list[dict[str, Any]] = []
        self.recent = recent or []  # stored by an interrupted run in the last 24 hours

    def query(self, aql: str, bind_vars: dict | None = None) -> list[str]:
        return list(self.recent)

    def insert_raw_source(self, **record: Any) -> dict[str, Any]:
        self.records.append(record)
        return record


class _Client:
    def __init__(self, general_info: str | None | Exception) -> None:
        self.general_info = general_info

    def latest_toestand(self, bwb_id: str) -> ToestandMeta:
        return _meta(bwb_id)

    def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
        return TOESTAND_XML

    def fetch_wti_general_info(self, meta: ToestandMeta) -> str | None:
        if isinstance(self.general_info, Exception):
            raise self.general_info
        return self.general_info


def _retrieve(general_info: str | None | Exception) -> tuple[_RawStore, PipelineResult]:
    store = _RawStore()
    pipeline = BWBRetrievePipeline(store=store, client=_Client(general_info))  # type: ignore[arg-type]
    return store, pipeline.run(bwb_ids=[SR])


def test_retrieve_stores_the_general_information_next_to_the_toestand() -> None:
    store, result = _retrieve(SR_GENERAL)

    # The toestand last: it is what a re-run takes for "this regulation is done".
    assert [r["kind"] for r in store.records] == [
        RAW_KIND_BWB_WTI_GENERAL,
        RAW_KIND_BWB_TOESTAND,
    ]
    wti = store.records[0]
    assert (wti["source"], wti["external_id"]) == (SOURCE_BWB, SR)
    assert wti["payload_text"] == SR_GENERAL
    assert wti["meta"] == {"bwb_id": SR, "wti_url": WTI_URL}
    assert (result.created, result.errors) == (2, [])


def test_retrieve_without_general_information_stores_the_toestand_only() -> None:
    store, result = _retrieve(None)

    assert [r["kind"] for r in store.records] == [RAW_KIND_BWB_TOESTAND]
    assert (result.created, result.errors) == (1, [])


def test_a_failing_wti_download_is_an_error_but_keeps_the_toestand() -> None:
    store, result = _retrieve(RuntimeError("HTTP 500"))

    assert [r["kind"] for r in store.records] == [RAW_KIND_BWB_TOESTAND]
    assert result.created == 1
    assert len(result.errors) == 1 and SR in result.errors[0]


# ── normalize ────────────────────────────────────────────────────────────────


class _WtiStore(_Store):
    """Serves the stored WTI records and applies the short-title UPDATE."""

    def __init__(self, wti: dict[str, str], instruments: dict[str, dict]) -> None:
        super().__init__(
            {
                "instruments": {
                    make_node_key(b): {"props": p} for b, p in instruments.items()
                }
            }
        )
        self.wti = wti

    def query(self, aql: str, bind_vars: dict | None = None, **kw):
        bind = bind_vars or {}
        if bind.get("kinds") == [RAW_KIND_BWB_WTI_GENERAL]:
            assert "since" not in bind  # the rule needs every regulation
            return [
                {"external_id": bwb_id, "payload_text": xml, "meta": {"bwb_id": bwb_id}}
                for bwb_id, xml in self.wti.items()
            ]
        if "rows" in bind:
            changed = []
            for row in bind["rows"]:
                doc = self.nodes["instruments"].get(row["key"])
                if doc is None or doc["props"].get("short_title") == row["short_title"]:
                    continue
                doc["props"].pop("short_title", None)  # keepNull: false
                if row["short_title"] is not None:
                    doc["props"]["short_title"] = row["short_title"]
                changed.append(1)
            return changed
        return super().query(aql, bind_vars, **kw)

    def short_title(self, bwb_id: str) -> str | None:
        return self.nodes["instruments"][make_node_key(bwb_id)]["props"].get(
            "short_title"
        )


def _normalize(store: _WtiStore) -> PipelineResult:
    result = PipelineResult()
    BWBNormalizePipeline(store=store).normalize_nodes([], result)  # type: ignore[arg-type]
    return result


def test_normalize_writes_the_short_title_and_keeps_the_other_props() -> None:
    store = _WtiStore({SR: SR_GENERAL}, {SR: {"title": "Wetboek van Strafrecht"}})

    result = _normalize(store)

    key = make_node_key(SR)
    assert store.nodes["instruments"][key]["props"] == {
        "title": "Wetboek van Strafrecht",
        "short_title": "Sr",
    }
    assert result.updated == 1
    assert _normalize(store).updated == 0  # a second run changes nothing


def test_a_shared_abbreviation_is_replaced_once_the_other_regulation_is_loaded() -> (
    None
):
    bw5_general = BW1_GENERAL.replace("BW Boek 1", "BW Boek 5").replace("BW1", "BW5")
    store = _WtiStore({BW1: BW1_GENERAL}, {BW1: {}, BW5: {}})

    _normalize(store)
    assert store.short_title(BW1) == "BW"  # alone, BW is its shortest abbreviation

    store.wti[BW5] = bw5_general
    _normalize(store)
    assert (store.short_title(BW1), store.short_title(BW5)) == ("BW1", "BW5")


def test_no_instrument_is_created_and_a_lost_short_title_is_removed() -> None:
    no_abbreviations = BW1_GENERAL.replace("afkorting", "x")
    store = _WtiStore(
        {SR: SR_GENERAL, BW1: no_abbreviations}, {BW1: {"short_title": "BW"}}
    )

    _normalize(store)

    assert set(store.nodes["instruments"]) == {make_node_key(BW1)}
    assert store.short_title(BW1) is None


def test_the_toestand_stream_does_not_read_wti_records() -> None:
    store = _WtiStore({}, {})
    seen: list[list[str]] = []
    store.query = lambda aql, bind_vars=None, **kw: (
        seen.append(bind_vars["kinds"]) or []
    )  # type: ignore[method-assign]

    list(BWBNormalizePipeline(store=store).fetch_raw())  # type: ignore[arg-type]

    assert seen and RAW_KIND_BWB_WTI_GENERAL not in seen[0]
