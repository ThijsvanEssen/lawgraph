"""A record the other normalizers leave out is skipped with its reason; one they cannot read
fails, and the run goes on. A link the Eerste Kamer votes cannot make is skipped too."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import COLLECTION_DECISIONS, COLLECTION_DOCUMENTS
from lawgraph.core.models import Node, PipelineResult
from lawgraph.db.queries import removals
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize import eerstekamer_votes
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.normalize.rijksoverheid import RijksoverheidNormalizePipeline
from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatscourant import (
    StaatscourantNormalizePipeline,
)
from lawgraph.pipelines.normalize.tk_content import TKContentNormalizePipeline
from tests.fakes import InMemoryStore
from tests.paths import fixture_text

_XML = "<regeling><titel>T</titel><tekst>De tekst.</tekst></regeling>"


@pytest.mark.parametrize(
    "pipeline_class", [StaatsbladNormalizePipeline, StaatscourantNormalizePipeline]
)
def test_a_publication_without_text_is_skipped_and_one_not_xml_fails(
    pipeline_class: Any,
) -> None:
    pipeline = pipeline_class(store=InMemoryStore())
    result = PipelineResult()

    count = pipeline.normalize_nodes(
        [
            {"external_id": "stb-2020-1", "payload_text": None},
            {"external_id": "stb-2020-2", "payload_text": "<open"},
            {"external_id": "stb-2020-3", "payload_text": _XML},
        ],
        result,
    )
    pipeline.add_outcomes(result)

    assert count == 1 and result.skipped == 2
    assert pipeline.progress.skips == {"no payload": 1}
    assert pipeline.progress.failures == {"publication not XML": 1}
    assert len(result.errors) == 1 and "stb-2020-2" in result.errors[0]


def test_a_judgment_without_ecli_is_skipped_and_one_not_xml_fails() -> None:
    pipeline = RechtspraakNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]
    result = PipelineResult()

    pipeline.normalize_nodes(
        {
            "content": iter(
                [
                    {"_key": "r1", "payload_text": "<x/>", "meta": {}},
                    {
                        "_key": "r2",
                        "payload_text": "<open",
                        "meta": {"ecli": "ECLI:NL:HR:2020:999"},
                    },
                ]
            )
        },
        result,
    )
    pipeline.add_outcomes(result)

    assert result.skipped == 2
    assert pipeline.progress.skips == {"no ECLI": 1}
    assert pipeline.progress.failures == {"unreadable judgment XML": 1}
    assert "ECLI:NL:HR:2020:999" in result.errors[0]


def test_a_paper_without_xml_text_or_document_node_is_skipped() -> None:
    store = InMemoryStore(
        {COLLECTION_DOCUMENTS: [{"_key": "d1", "type": "Document", "props": {}}]}
    )
    pipeline = TKContentNormalizePipeline(store=store)  # type: ignore[arg-type]
    result = PipelineResult()
    paper = fixture_text("kst_24138_3.xml")

    count = pipeline.normalize_nodes(
        [
            {"external_id": "k0", "payload_text": paper, "meta": {}},
            {"external_id": "k1", "payload_text": "<open", "meta": {"document": "d1"}},
            {"external_id": "k2", "payload_text": paper, "meta": {"document": "d2"}},
            {"external_id": "k3", "payload_text": paper, "meta": {"document": "d1"}},
        ],
        result,
    )
    pipeline.add_outcomes(result)

    assert count == 1 and result.skipped == 3
    assert pipeline.progress.skips == {
        "no document or XML": 1,
        "no text in the XML": 1,
        "no Document node yet": 1,
    }


def test_a_cabinet_record_without_page_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = RijksoverheidNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]
    monkeypatch.setattr(normalize_tk, "faction_names", _stop)

    with pytest.raises(_Stopped):
        pipeline.normalize_nodes(
            iter([{"external_id": "kabinet-x", "payload_text": None}]),
            PipelineResult(),
        )

    assert pipeline.progress.skips == {"no page": 1}


class _Stopped(Exception):
    pass


def _stop(*_args: Any) -> Any:
    raise _Stopped


def _decision(key: str, **props: Any) -> Node:
    return Node(
        collection=COLLECTION_DECISIONS,
        key=key,
        props={"date": "2026-10-06", "dossier_numbers": ["37020"], **props},
    )


def test_an_ek_vote_of_no_faction_or_on_a_motion_not_in_the_graph_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faction = {
        "id": "factions/ek_pvv",
        "abbreviation": "PVV",
        "seats": 4,
        "observed_from": "2026-01-01",
        "observed_until": None,
    }
    monkeypatch.setattr(normalize_ek, "ek_factions", lambda _s: [faction])
    monkeypatch.setattr(normalize_ek, "ek_papers_by_letter", lambda _s, _n: {})
    monkeypatch.setattr(removals, "remove_edges_into_except", lambda *_a: 0)
    pipeline = eerstekamer_votes.EerstekamerVotesNormalizePipeline(
        store=InMemoryStore()  # type: ignore[arg-type]
    )
    decisions = [
        _decision("ek_1", factions_for=["PVV", "LPF"], factions_against=["VVD"]),
        _decision("ek_2", letter="M"),
    ]

    eerstekamer_votes.link_motions(pipeline, decisions, source="test")
    eerstekamer_votes.link_faction_votes(pipeline, decisions, source="test")

    assert pipeline.progress.skips == {
        "motion not in the graph": 1,
        "name of no faction": 2,
    }
    assert pipeline.progress.examples["name of no faction"] == "LPF (2026-10-06)"
