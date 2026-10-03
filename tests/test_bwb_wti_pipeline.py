"""WTI abbreviations end to end: client download, retrieve record, short_title on the instrument."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from lawgraph.clients.bwb import WTI_CHUNK_SIZE, BWBClient, ToestandMeta
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_WTI_GENERAL,
    RAW_KIND_TOOI_THESAURUS,
    SOURCE_BWB,
    TOOI_BWB_LEGAL_AREAS,
    TOOI_BWB_THEMES,
)
from lawgraph.core.bwb_wti import extract_general_info
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.normalize import bwb as normalize_bwb
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from tests.fakes import RawSourcesFake

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
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def insert_raw_source(self, **record: Any) -> dict[str, Any]:
        self.records.append(record)
        return record


@pytest.fixture
def nothing_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    """No record stored by an interrupted run, none waiting for a retry."""
    monkeypatch.setattr(raw_queries, "ids_stored_since", lambda store, **kw: iter([]))
    monkeypatch.setattr(
        raw_queries, "ids_waiting_for_retry", lambda store, **kw: iter([])
    )


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


def test_retrieve_stores_the_general_information_next_to_the_toestand(
    nothing_stored: None,
) -> None:
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


def test_retrieve_without_general_information_stores_the_toestand_only(
    nothing_stored: None,
) -> None:
    store, result = _retrieve(None)

    assert [r["kind"] for r in store.records] == [RAW_KIND_BWB_TOESTAND]
    assert (result.created, result.errors) == (1, [])


def test_a_failing_wti_download_is_an_error_but_keeps_the_toestand(
    nothing_stored: None,
) -> None:
    store, result = _retrieve(RuntimeError("HTTP 500"))

    assert [r["kind"] for r in store.records] == [RAW_KIND_BWB_TOESTAND]
    assert result.created == 1
    assert len(result.errors) == 1 and SR in result.errors[0]


# ── normalize ────────────────────────────────────────────────────────────────


class _WtiStore(RawSourcesFake):
    """The stored WTI records and the instruments their short titles go to."""

    def __init__(
        self,
        wti: dict[str, str],
        instruments: dict[str, dict],
        thesauri: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.wti = wti
        self.thesauri = thesauri or {}
        self.subjects: dict[str, dict[str, Any]] = {}
        self.nodes: dict[str, dict[str, dict]] = {
            "instruments": {
                make_node_key(b): {"props": p} for b, p in instruments.items()
            }
        }

    def wti_records(self) -> list[dict[str, Any]]:
        return [
            {"external_id": bwb_id, "payload_text": xml, "meta": {"bwb_id": bwb_id}}
            for bwb_id, xml in self.wti.items()
        ]

    def update_abbreviations(self, rows: list[dict[str, Any]]) -> int:
        """Like the query: only existing instruments that differ; an empty value is removed."""
        changed = 0
        for row in rows:
            doc = self.nodes["instruments"].get(row["key"])
            wanted = {
                "short_title": row["short_title"],
                "aliases": row["aliases"] or None,
            }
            if doc is None or all(doc["props"].get(k) == v for k, v in wanted.items()):
                continue
            for k, v in wanted.items():
                doc["props"].pop(k, None)
                if v is not None:
                    doc["props"][k] = v
            changed += 1
        return changed

    def thesaurus_records(self) -> list[dict[str, Any]]:
        return [
            {"external_id": name, "payload_json": {"items": items}}
            for name, items in self.thesauri.items()
        ]

    def update_subjects(self, rows: list[dict[str, Any]]) -> int:
        """Records what the pipeline asks to write; the query itself is tested on
        PostgreSQL (``tests/pg/test_bwb_pipeline_queries.py``)."""
        self.subjects = {row["key"]: row for row in rows}
        return 0

    def update_instrument_abbreviations(self, rows: list[dict[str, Any]]) -> int:
        """Records what the pipeline asks to write; the query itself is tested on
        PostgreSQL (``tests/pg/test_bwb_pipeline_queries.py``)."""
        self.abbreviations = {row["key"]: row["abbreviation"] for row in rows}
        return 0

    def short_title(self, bwb_id: str) -> str | None:
        return self.nodes["instruments"][make_node_key(bwb_id)]["props"].get(
            "short_title"
        )


@pytest.fixture(autouse=True)
def _wti_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The raw records and the short-title update, served by a ``_WtiStore``."""

    def iter_raw_records(store: _WtiStore, *, kinds, since_iso, **_kw):
        assert since_iso is None  # the rule needs every regulation
        if kinds == [RAW_KIND_TOOI_THESAURUS]:
            return iter(store.thesaurus_records())
        assert kinds == [RAW_KIND_BWB_WTI_GENERAL]
        return iter(store.wti_records())

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    monkeypatch.setattr(raw_queries, "count_raw_records", lambda *a, **kw: None)
    monkeypatch.setattr(
        normalize_bwb,
        "update_abbreviations",
        lambda store, rows: store.update_abbreviations(rows),
    )
    monkeypatch.setattr(
        normalize_bwb,
        "update_instrument_abbreviations",
        lambda store, rows: store.update_instrument_abbreviations(rows),
    )
    monkeypatch.setattr(
        normalize_bwb,
        "update_subjects",
        lambda store, rows: store.update_subjects(rows),
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
        "aliases": ["Sr", "WvS", "WvSr"],
    }
    assert result.updated == 1
    assert _normalize(store).updated == 0  # a second run changes nothing


def test_a_book_has_its_own_code_whether_or_not_the_other_books_are_loaded() -> None:
    bw5_general = BW1_GENERAL.replace("BW Boek 1", "BW Boek 5").replace("BW1", "BW5")
    store = _WtiStore({BW1: BW1_GENERAL}, {BW1: {}, BW5: {}})

    _normalize(store)
    assert store.short_title(BW1) == "BW1"  # never "BW", which names every book

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


def test_every_book_is_named_by_its_code_also_without_a_wti_record() -> None:
    store = _WtiStore({BW1: BW1_GENERAL}, {BW1: {}, BW5: {}})

    _normalize(store)

    aliases = {
        b: store.nodes["instruments"][make_node_key(b)]["props"]["aliases"]
        for b in (BW1, BW5)
    }
    assert aliases[BW1] == ["BW", "BW Boek 1", "BW1", "Boek 1 BW", "1 BW", "BW 1"]
    assert aliases[BW5] == ["Boek 5 BW", "5 BW", "BW 5", "BW5", "BW Boek 5", "BW"]
    assert store.short_title(BW5) is None  # a short title comes from the WTI only


def test_the_toestand_stream_does_not_read_wti_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def iter_raw_records(store, *, kinds, **_kw):
        seen.append(kinds)
        return iter([])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)

    list(BWBNormalizePipeline(store=_WtiStore({}, {})).fetch_raw())  # type: ignore[arg-type]

    assert seen and RAW_KIND_BWB_WTI_GENERAL not in seen[0]


def test_the_abbreviation_is_the_wti_short_title_else_the_curated_one() -> None:
    """BE-8: one field for law and article. A BWB regulation gets its WTI short title
    (Sr), an EU act the abbreviation kept by hand (AVG for 32016R0679)."""
    store = _WtiStore({SR: SR_GENERAL}, {SR: {"title": "Wetboek van Strafrecht"}})
    _normalize(store)
    assert store.abbreviations[make_node_key(SR)] == store.short_title(SR) == "Sr"
    assert store.abbreviations[make_node_key("32016R0679")] == "AVG"


def test_normalize_writes_the_legal_areas_and_themes_with_their_tooi_concepts() -> None:
    thesauri = {
        TOOI_BWB_LEGAL_AREAS: json.loads(
            (FIXTURES / "tooi_bwb_rechtsgebieden.json").read_text()
        ),
        TOOI_BWB_THEMES: json.loads((FIXTURES / "tooi_bwb_themas.json").read_text()),
    }
    store = _WtiStore({BW1: BW1_GENERAL}, {BW1: {}}, thesauri)

    _normalize(store)

    row = store.subjects[make_node_key(BW1)]
    assert [(a["main"], a["specific"]) for a in row["legal_areas"]] == [
        ("Personen- en familierecht", "Familierecht"),
        ("Personen- en familierecht", "Personenrecht"),
    ]
    assert all(a["main_uri"] and a["specific_uri"] for a in row["legal_areas"])
    assert [d["label"] for d in row["policy_domains"]] == ["Familie, jeugd en gezin"]
    assert row["policy_domains"][0]["uri"]


def test_without_the_thesauri_the_labels_are_written_without_a_uri() -> None:
    store = _WtiStore({BW1: BW1_GENERAL}, {BW1: {}})

    _normalize(store)

    row = store.subjects[make_node_key(BW1)]
    assert row["legal_areas"][0]["main"] == "Personen- en familierecht"
    assert row["legal_areas"][0]["main_uri"] is None
    assert row["policy_domains"] == [
        {
            "label": "Familie, jeugd en gezin",
            "id": None,
            "uri": None,
            "slug": "familie-jeugd-en-gezin",
        }
    ]
    assert row["legal_areas"][0]["main_slug"] == "personen-en-familierecht"
