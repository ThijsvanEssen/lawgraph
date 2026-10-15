"""A record of the Eerste Kamer that the normalizers leave out is skipped, with its reason."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_EK_BILL,
    RAW_KIND_EK_COMMITTEE_DAY,
    RAW_KIND_EK_PLENARY,
    RAW_KIND_EK_REJECTED,
    RAW_KIND_EK_VOTES_DAY,
)
from lawgraph.core import ek_composition as ec
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize import eerstekamer_composition as composition
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
from lawgraph.pipelines.normalize.eerstekamer_agenda import (
    EerstekamerAgendaNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_bills import (
    EerstekamerBillsNormalizePipeline,
)
from lawgraph.pipelines.normalize.eerstekamer_votes import (
    EerstekamerVotesNormalizePipeline,
)
from tests.fakes import InMemoryStore
from tests.paths import fixture_text


def _page(kind: str, external_id: str, text: str | None) -> dict[str, Any]:
    return {"kind": kind, "external_id": external_id, "payload_text": text}


def test_a_paper_without_payload_or_identifier_is_skipped() -> None:
    pipeline = EerstekamerNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]
    result = PipelineResult()

    pipeline.write([{"payload_json": {"title": "x"}}, {"external_id": "kst-1"}], result)
    pipeline.add_outcomes(result)

    assert pipeline.store.writes.created == 0 and result.skipped == 2
    assert pipeline.progress.skips == {"no identifier": 1, "no payload": 1}


def test_an_agenda_page_that_gives_no_activity_is_skipped() -> None:
    pipeline = EerstekamerAgendaNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]

    nodes = pipeline._write_nodes(
        [
            _page(RAW_KIND_EK_PLENARY, "/plenaire_vergadering_2026_10_06", None),
            _page(RAW_KIND_EK_COMMITTEE_DAY, "/commissievergaderingen/x", "<main/>"),
        ]
    )

    assert nodes == []
    assert pipeline.progress.skips == {"no page": 1, "no activities on the page": 1}


def test_a_bill_page_without_a_dossier_the_graph_holds_is_skipped() -> None:
    page = fixture_text("ek_bill_36791.html")
    pipeline = EerstekamerBillsNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]

    pipeline.write(
        [
            _page(RAW_KIND_EK_BILL, "/wetsvoorstel/x", "<main/>"),
            _page(RAW_KIND_EK_BILL, "/wetsvoorstel/36791", page),
        ],
        PipelineResult(),
    )

    assert pipeline.store.writes.created == 0
    assert pipeline.progress.skips == {
        "no dossier on the page": 1,
        "dossier not in the graph": 1,
    }


def test_a_votes_page_that_gives_no_vote_is_skipped_and_keeps_its_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    days: list[list[str]] = []
    monkeypatch.setattr(
        normalize_ek, "ek_vote_keys_on", lambda _s, read: days.append(read) or []
    )
    pipeline = EerstekamerVotesNormalizePipeline(store=InMemoryStore())  # type: ignore[arg-type]

    decisions = pipeline._write_nodes(
        [
            _page(RAW_KIND_EK_VOTES_DAY, "2026-10-06", None),
            _page(RAW_KIND_EK_VOTES_DAY, "2026-10-07", "<main/>"),
            _page(RAW_KIND_EK_REJECTED, "/verworpen", ""),
        ]
    )

    assert decisions == [] and days == [[]]
    assert pipeline.progress.skips == {"no page": 2, "no votes on the page": 1}


def test_a_listed_page_that_is_not_stored_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = fixture_text("ek_factions.html")
    state: dict[str, list[Any]] = {
        "factions": [],
        "committees": [],
        "members": [],
        "edges": [],
    }
    monkeypatch.setattr(normalize_tk, "ek_composition", lambda _s: state)
    monkeypatch.setattr(normalize_tk, "members_born_on", lambda *_a: [])
    monkeypatch.setattr(composition, "assign_member_slugs", lambda _s: None)
    pipeline = composition.EerstekamerCompositionNormalizePipeline(
        store=InMemoryStore()  # type: ignore[arg-type]
    )

    pipeline._write_nodes([{"external_id": ec.FACTIONS_PATH, "payload_text": listing}])

    assert pipeline.progress.skips == {"listed page not stored": 20}


def test_pages_without_the_list_of_factions_are_skipped() -> None:
    pipeline = composition.EerstekamerCompositionNormalizePipeline(
        store=InMemoryStore()  # type: ignore[arg-type]
    )

    written = pipeline._write_nodes(
        [
            {"external_id": "/fractie/pro", "payload_text": "<main/>"},
            {"external_id": ec.HALL_PATH, "payload_text": "<main/>"},
        ]
    )

    assert written is None
    assert pipeline.progress.skips == {"no list of factions": 2}
