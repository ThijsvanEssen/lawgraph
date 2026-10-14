"""The closed vocabularies of the graph and the API: their values, pinned.

The API's ``Literal`` types and the runtime tuples of ``core`` are the same words; the
values the API answers are pinned in ``tests/api/openapi_enums.json``.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from lawgraph.api.schemas import (
    committees,
    common,
    documents,
    dossiers,
    feed,
    government,
    instruments,
    judgments,
)
from lawgraph.config import constants
from lawgraph.core import (
    cabinet_phases,
    cabinet_posts,
    coalition,
    curated,
    dossier_stages,
    echr_findings,
    eerstekamer_votes,
    judgment_outcome,
    post_ministries,
    tk_records,
)
from lawgraph.core import documents as core_documents
from lawgraph.core import feed as core_feed
from lawgraph.core import judgments as core_judgments

PINNED: list[tuple[str, Any, tuple[str, ...]]] = [
    ("chambers by label", core_documents.CHAMBERS, ("EK", "TK")),
    ("curated chambers", curated.CHAMBERS, ("TK", "EK")),
    (
        "feed kinds",
        core_feed.FEED_KINDS,
        (
            "toezegging",
            "Voorstel van wet",
            "Nota van wijziging",
            "Amendement",
            "Motie",
            "stemming",
            "publicatie",
            "inwerkingtreding",
            "Brief regering",
            "uitspraak",
        ),
    ),
    (
        "person roles",
        core_feed.PERSON_ROLES,
        ("indiener", "medeindiener", "bewindspersoon"),
    ),
    (
        "feed coalition",
        core_feed.FEED_COALITION,
        ("together", "split", "wissel", "decisive"),
    ),
    (
        "coalition patterns",
        (coalition.PATTERN_TOGETHER, coalition.PATTERN_SPLIT, coalition.PATTERN_WISSEL),
        ("together", "split", "wissel"),
    ),
    (
        "decision kinds",
        core_judgments.DECISION_KINDS,
        (
            "arrest",
            "vonnis",
            "beschikking",
            "uitspraak",
            "beslissing",
            "conclusie",
            "prejudiciële beslissing",
        ),
    ),
    (
        "phase kinds",
        cabinet_phases.PHASE_KINDS,
        ("formatie", "in_functie", "demissionair", "dubbel_demissionair", "missionair"),
    ),
    (
        "judgment outcomes",
        (
            judgment_outcome.REJECTED,
            judgment_outcome.QUASHED,
            judgment_outcome.PARTLY_QUASHED,
            judgment_outcome.QUASHED_REFERRED,
            judgment_outcome.AFFIRMED,
            judgment_outcome.CONFIRMED,
            judgment_outcome.WELL_FOUNDED,
            judgment_outcome.UNFOUNDED,
            judgment_outcome.INADMISSIBLE,
            judgment_outcome.DISMISSED,
            judgment_outcome.GRANTED,
            echr_findings.VIOLATION,
            echr_findings.NO_VIOLATION,
        ),
        get_args(common.JudgmentOutcome),
    ),
    (
        "conclusion outcomes",
        (
            judgment_outcome.TO_REJECT,
            judgment_outcome.TO_QUASH,
            judgment_outcome.TO_QUASH_REFER,
            judgment_outcome.TO_INADMISSIBLE,
            judgment_outcome.TO_WELL_FOUNDED,
            judgment_outcome.TO_UNFOUNDED,
            judgment_outcome.TO_ANSWER,
        ),
        get_args(common.ConclusionOutcome),
    ),
    (
        "ministry sources",
        (post_ministries.SOURCE_PAGE, *post_ministries.SOURCES),
        ("page", "tk_signatures", "tk_commitments", "staatscourant"),
    ),
    (
        "ministry missing",
        (post_ministries.MISSING_NO_SOURCE, post_ministries.MISSING_AMBIGUOUS),
        ("no_source", "ambiguous"),
    ),
    (
        "acting reasons",
        (cabinet_posts.ACTING_SOURCE, cabinet_posts.ACTING_HELD_OTHER_SEAT),
        ("source", "held_other_seat"),
    ),
    (
        "EK vote labels",
        (
            eerstekamer_votes.LABEL_FOR,
            eerstekamer_votes.LABEL_AGAINST,
            eerstekamer_votes.LABEL_NOTED,
        ),
        ("voor", "tegen", "aantekening gevraagd"),
    ),
    (
        "signing capacities",
        (
            tk_records.CAPACITY_MEMBER,
            tk_records.CAPACITY_GOVERNMENT,
            tk_records.CAPACITY_OTHER,
        ),
        ("kamerlid", "bewindspersoon", "overig"),
    ),
    (
        "dossier outcomes",
        (dossier_stages.OUTCOME_ENACTED, dossier_stages.OUTCOME_REJECTED),
        ("aangenomen", "verworpen"),
    ),
    (
        "edge statuses",
        (constants.EDGE_STATUS_CANONIEK, constants.EDGE_STATUS_VOORGESTELD),
        ("canoniek", "voorgesteld"),
    ),
    (
        "implements bases",
        (constants.IMPLEMENTS_BASIS_NIM, constants.IMPLEMENTS_BASIS_CONSIDERANS),
        ("national_implementing_measure", "considerans"),
    ),
    (
        "echr findings",
        (echr_findings.VIOLATION, echr_findings.NO_VIOLATION),
        ("schending", "geen schending"),
    ),
]


@pytest.mark.parametrize(
    ("name", "values", "pinned"), PINNED, ids=[p[0] for p in PINNED]
)
def test_a_vocabulary_keeps_its_values(name: str, values: Any, pinned: Any) -> None:
    assert tuple(values) == tuple(pinned)


# Each ``Literal`` of the API and the vocabulary of ``core`` it answers.
ANSWERED: list[tuple[str, Any, Any]] = [
    ("chamber", documents.Chamber, (constants.CHAMBER_TK, constants.CHAMBER_EK)),
    ("feed kind", feed.FeedKind, core_feed.FEED_KINDS),
    ("person role", feed.PersonRole, core_feed.PERSON_ROLES),
    ("decision kind", judgments.DecisionKind, core_judgments.DECISION_KINDS),
    ("phase kind", government.PhaseKind, cabinet_phases.PHASE_KINDS),
    (
        "committee kind",
        committees.CommitteeKind,
        (*(kind for kind, _ in tk_records._COMMITTEE_KINDS), "overig"),
    ),
    ("signing capacity", documents.SigningCapacity, PINNED[14][2]),
    ("dossier outcome", dossiers.DossierOutcome, PINNED[15][2]),
    ("edge status", dossiers.DossierInstrumentStatus, PINNED[16][2]),
    ("implements basis", instruments.ImplementsBasis, PINNED[17][2]),
]


@pytest.mark.parametrize(
    ("name", "literal", "core"), ANSWERED, ids=[a[0] for a in ANSWERED]
)
def test_the_api_answers_the_words_of_core(name: str, literal: Any, core: Any) -> None:
    assert set(get_args(literal)) == set(core)
