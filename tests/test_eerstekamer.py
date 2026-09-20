"""Eerste Kamer Kamerstukken over the KOOP SRU, from a real (recorded) result page."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.config.constants import RELATION_PART_OF
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.pipelines.normalize.eerstekamer import (
    EerstekamerNormalizePipeline,
    split_dossier_number,
)
from lawgraph.pipelines.retrieve.eerstekamer import EerstekamerRetrievePipeline
from lawgraph.pipelines.semantic.eerstekamer_dossier_link import (
    EerstekamerDossierLinkSemanticPipeline,
)
from tests.conftest import _BaseFakeStore
from tests.fakes import RawSourcesFake

PAGE = (
    pathlib.Path(__file__).parent / "fixtures" / "sru_eerstekamer_kamerstukken_page.xml"
).read_text()  # dossier 36867: kst-1259252, kst-36867-A, -B, -C (total 4)


def _client(responses: list[Any], calls: list[dict]) -> EerstekamerClient:
    client = EerstekamerClient.__new__(EerstekamerClient)
    client.base_url = "https://repository.overheid.nl/sru"

    def fake_get(url, *, params=None, timeout=30, **_kw):
        calls.append(params)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(text=response)

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


# ── the client ───────────────────────────────────────────────────────────────


def test_the_papers_of_a_real_page_are_parsed() -> None:
    papers = _client([PAGE], []).search_kamerstukken()

    assert [p["identifier"] for p in papers] == [
        "kst-1259252",
        "kst-36867-A",
        "kst-36867-B",
        "kst-36867-C",
    ]
    verslag = papers[3]
    assert verslag["document_title"] == "Verslag"
    assert verslag["kind"] == "Verslag"
    assert verslag["number"] == "C"
    assert verslag["dossier_number"] == "36867"
    assert verslag["session_year"] == "2025-2026"
    assert verslag["date"] == "2026-06-30"
    assert verslag["dossier_title"].startswith("Wijziging van de Wet openbare lichamen")
    assert verslag["url"] == "https://zoek.officielebekendmakingen.nl/kst-36867-C.html"


def test_a_paper_numbered_by_its_own_id_has_no_dossier_in_the_identifier() -> None:
    paper = _client([PAGE], []).search_kamerstukken()[0]
    assert paper["identifier"] == "kst-1259252"
    assert paper["dossier_number"] == "36867"


def test_only_eerste_kamer_kamerstukken_without_attachments_are_asked_for() -> None:
    calls: list[dict] = []
    _client([PAGE], calls).search_kamerstukken(since="2026-09-01")
    query = calls[0]["query"]
    assert 'dt.creator=="Eerste Kamer der Staten-Generaal"' in query
    assert "w.publicatienaam==Kamerstuk" in query and "dt.type==Kamerstuk" in query
    assert "dt.modified>=2026-09-01" in query
    assert "x-connection" not in calls[0]


def test_a_failing_request_raises_instead_of_an_empty_result() -> None:
    with pytest.raises(requests.ConnectionError):
        _client([requests.ConnectionError("no route")], []).search_kamerstukken()


def test_limit_stops_early() -> None:
    assert len(_client([PAGE], []).search_kamerstukken(limit=2)) == 2


# ── retrieve ─────────────────────────────────────────────────────────────────


class _RawStore(RawSourcesFake):
    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    def insert_raw_source(self, **kw: Any) -> None:
        self.stored.append(kw)


def test_every_paper_becomes_a_raw_record() -> None:
    store = _RawStore()
    pipeline = EerstekamerRetrievePipeline(store=store, client=_client([PAGE], []))
    result = pipeline.run()

    assert (result.created, result.errors) == (4, [])
    first = store.stored[1]
    assert first["source"] == "eerstekamer" and first["kind"] == "ek-kamerstuk-json"
    assert first["external_id"] == "kst-36867-A"
    assert first["payload_json"]["kind"] == "Voorstel van wet"
    assert first["meta"]["dossier_number"] == "36867"


def test_a_failed_search_is_an_error_of_the_run() -> None:
    client = _client([requests.ConnectionError("no route")], [])
    result = EerstekamerRetrievePipeline(store=_RawStore(), client=client).run()
    assert result.created == 0 and "no route" in result.errors[0]


# ── normalize ────────────────────────────────────────────────────────────────


class _NodeStore:
    def __init__(self) -> None:
        self.upserted: list[Any] = []

    def query(self, aql, bind_vars=None):
        return []

    def bulk_insert_or_update_nodes(self, collection, docs):
        self.upserted.extend(docs)
        return len(docs), 0

    def insert_or_update(self, node):
        self.upserted.append(node)
        return node, True


def _normalize(papers: list[dict[str, Any]]):
    store = _NodeStore()
    pipeline = EerstekamerNormalizePipeline(store=store)
    raw = [{"external_id": p.get("identifier"), "payload_json": p} for p in papers]
    result = PipelineResult()
    return pipeline.normalize_nodes(raw, result), result


def test_a_paper_becomes_a_document_with_its_dossier_number() -> None:
    papers = _client([PAGE], []).search_kamerstukken()
    nodes, result = _normalize(papers)

    node = nodes["ek_kst_36867_c"]
    assert node.type == NodeType.DOCUMENT
    assert node.labels == ["EersteKamer", "EK"]
    assert node.props["source"] == "eerstekamer"
    assert node.props["kind"] == "Verslag"
    assert node.props["title"] == "Verslag"
    assert node.props["number"] == "C"
    assert node.props["dossier_number"] == "36867"
    assert "dossier_suffix" not in node.props
    assert node.props["date"] == "2026-06-30"
    assert node.props["session_year"] == "2025-2026"
    assert node.props["subject"].startswith("Wijziging van de Wet openbare lichamen")
    assert node.props["display_name"].startswith("EK 36867, nr. C: Verslag")
    assert result.skipped == 0 and len(nodes) == 4


def test_a_budget_chapter_is_split_off_the_dossier_number() -> None:
    nodes, _ = _normalize(
        [
            {
                "identifier": "kst-35925-VII-A",
                "document_title": "Begroting",
                "dossier_number": "35925 VII",
            }
        ]
    )
    node = next(iter(nodes.values()))
    assert node.props["dossier_number"] == "35925"
    assert node.props["dossier_suffix"] == "VII"
    assert node.props["display_name"].startswith("EK 35925 VII")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("36867", ("36867", None)),
        ("35925 VII", ("35925", "VII")),
        ("35925-VII", ("35925", "VII")),
        ("32123 B", ("32123", "B")),
        ("", (None, None)),
        (None, (None, None)),
        ("Reglement van Orde", (None, None)),
    ],
)
def test_split_dossier_number(value, expected) -> None:
    assert split_dossier_number(value) == expected


def test_a_record_without_an_identifier_is_skipped() -> None:
    store = _NodeStore()
    result = PipelineResult()
    nodes = EerstekamerNormalizePipeline(store=store).normalize_nodes(
        [{"payload_json": {"title": "x"}}, {"external_id": "kst-1"}], result
    )
    assert nodes == {} and result.skipped == 2


# ── the link to the Tweede Kamer dossier ─────────────────────────────────────


class _LinkStore(_BaseFakeStore):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self._rows = rows
        self.queries: list[str] = []

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        self.queries.append(aql)
        return list(self._rows)


def test_the_paper_is_part_of_the_tk_dossier() -> None:
    rows = [
        {
            "document_key": "ek_kst_36867_c",
            "dossier_key": "36867",
            "dossier_number": "36867",
            "dossier_suffix": None,
        }
    ]
    store = _LinkStore(rows)
    result = EerstekamerDossierLinkSemanticPipeline(store=store).run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_PART_OF
    assert edge["_from"] == "documents/ek_kst_36867_c"
    assert edge["_to"] == "dossiers/36867"
    assert edge["confidence"] == 0.95
    assert edge["meta"]["chamber"] == "EK"


def test_the_link_query_matches_the_addition_and_has_no_row_cap() -> None:
    store = _LinkStore([])
    EerstekamerDossierLinkSemanticPipeline(store=store).run()
    aql = store.queries[0]
    assert '(d.props.suffix || "") == (document.props.dossier_suffix || "")' in aql
    assert "LIMIT 10000" not in aql


def test_no_match_writes_nothing() -> None:
    assert (
        EerstekamerDossierLinkSemanticPipeline(store=_LinkStore([])).run().created == 0
    )
