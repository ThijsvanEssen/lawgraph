"""Answers built from query rows in the schemas: the regulations under an article and under
a law in one order and one casing, the detail of a decision in one step, and the address of
a DTO built on the fields of another."""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.actors import ActorDossierDTO
from lawgraph.api.schemas.articles import DelegatedRegulationDTO
from lawgraph.api.schemas.decisions import DecisionDTO
from lawgraph.api.schemas.instruments import InstrumentDelegatedItem
from lawgraph.api.schemas.judgments import JudgmentDTO, RelatedJudgmentDTO
from lawgraph.api.schemas.members import MemberDetailDTO


def _regulation(key: str, kind: str, title: str) -> dict[str, Any]:
    return {
        "instrument": {
            "_id": f"instruments/{key}",
            "_key": key,
            "props": {"kind": kind, "citation_title": title},
        },
        "meta": {},
        "articles": [],
    }


ROWS = [
    _regulation("c", "kb", "Aa"),
    _regulation("b", "ministeriele-regeling", "Bb"),
    _regulation("a", "AMvB", "Zz"),
    _regulation("d", "AMvB", "aa"),
]


def test_the_regulations_under_an_article_and_a_law_alike() -> None:
    from lawgraph.api.schemas.common import in_regulation_order

    under_article = in_regulation_order(
        DelegatedRegulationDTO.from_row(r) for r in ROWS
    )
    under_law = in_regulation_order(InstrumentDelegatedItem.from_row(r) for r in ROWS)
    order = [(i.instrument.key, i.kind) for i in under_article]
    assert order == [
        ("d", "amvb"),
        ("a", "amvb"),
        ("b", "ministeriele-regeling"),
        ("c", "kb"),
    ]
    assert [(i.instrument.key, i.kind) for i in under_law] == order


def test_a_decision_with_its_motion_dictum_and_paper() -> None:
    decision = DecisionDTO.from_document(
        {"_id": "decisions/s1", "_key": "s1", "labels": ["TK"], "props": {}},
        {},
        motion={"collection": "documents", "key": "m", "path": "/kamerstukken/1/2"},
        dictum="verzoekt de regering",
        paper={
            "id": "documents/m",
            "light": {"kind": "Motie", "dossier_number": "36600", "sequence": 2},
        },
    )
    assert decision.dictum == "verzoekt de regering"
    assert decision.motion is not None and decision.motion.key == "m"
    assert decision.primary_document is not None
    assert decision.primary_document.kind == "Motie"
    bare = DecisionDTO.from_document(
        {"_id": "decisions/s1", "_key": "s1", "labels": ["TK"], "props": {}}, {}
    )
    assert (bare.dictum, bare.motion, bare.primary_document) == (None, None, None)


def test_a_dto_built_on_the_fields_of_another_has_its_address() -> None:
    member = MemberDetailDTO.from_document(
        {"_id": "members/m1", "_key": "m1", "props": {"slug": "bram-bakker"}}
    )
    assert member.path == "/leden/bram-bakker"
    dossier = ActorDossierDTO.from_row(
        {
            "dossier": {
                "_id": "dossiers/36600",
                "_key": "36600",
                "props": {"label": "36600"},
            }
        }
    )
    assert dossier.path == "/dossiers/36600"
    ecli = "ECLI:NL:HR:2019:2006"
    judgment = {"_id": "judgments/j", "_key": "j", "props": {"ecli": ecli}}
    assert JudgmentDTO.from_document(judgment).path == f"/uitspraken/{ecli}"
    assert RelatedJudgmentDTO.from_document(judgment).path == f"/uitspraken/{ecli}"
