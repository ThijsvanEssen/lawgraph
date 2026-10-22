"""Answers built from query rows in the schemas: the regulations under an article and under
a law in one order and one casing, the detail of a decision in one step, the address of a DTO
built on the fields of another, and the identifier a list row has besides its address."""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.actors import ActorDossierDTO
from lawgraph.api.schemas.articles import DelegatedRegulationDTO
from lawgraph.api.schemas.decisions import DecisionDTO
from lawgraph.api.schemas.documents import DocumentListItemDTO
from lawgraph.api.schemas.instruments import (
    InstrumentDelegatedItem,
    InstrumentListItemDTO,
)
from lawgraph.api.schemas.judgments import JudgmentDTO, RelatedJudgmentDTO
from lawgraph.api.schemas.members import MemberDetailDTO


def _regulation(key: str, kind: str, title: str) -> dict[str, Any]:
    return {
        "instrument": {
            "id": f"instruments/{key}",
            "key": key,
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
        {"id": "decisions/s1", "key": "s1", "labels": ["TK"], "props": {}},
        {},
        motion={"collection": "documents", "key": "m", "path": "/kamerstukken/1/2"},
        dictum="verzoekt de regering",
        document={
            "id": "documents/m",
            "light": {"kind": "Motie", "dossier_number": "36600", "sequence": 2},
        },
    )
    assert decision.dictum == "verzoekt de regering"
    assert decision.motion is not None and decision.motion.key == "m"
    assert decision.primary_document is not None
    assert decision.primary_document.kind == "Motie"
    bare = DecisionDTO.from_document(
        {"id": "decisions/s1", "key": "s1", "labels": ["TK"], "props": {}}, {}
    )
    assert (bare.dictum, bare.motion, bare.primary_document) == (None, None, None)


def test_a_dto_built_on_the_fields_of_another_has_its_address() -> None:
    member = MemberDetailDTO.from_document(
        {"id": "members/m1", "key": "m1", "props": {"slug": "bram-bakker"}}
    )
    assert member.path == "/leden/bram-bakker"
    dossier = ActorDossierDTO.from_row(
        {
            "dossier": {
                "id": "dossiers/36600",
                "key": "36600",
                "props": {"label": "36600"},
            }
        }
    )
    assert dossier.path == "/dossiers/36600"
    ecli = "ECLI:NL:HR:2019:2006"
    judgment = {"id": "judgments/j", "key": "j", "props": {"ecli": ecli}}
    assert JudgmentDTO.from_document(judgment).path == f"/uitspraken/{ecli}"
    assert RelatedJudgmentDTO.from_document(judgment).path == f"/uitspraken/{ecli}"


def test_a_listed_paper_without_an_address_has_its_number_and_page_at_the_kamer() -> (
    None
):
    letter = DocumentListItemDTO.from_row(
        {
            "id": "documents/x",
            "key": "x",
            "chamber": "TK",
            "kind": "Brief regering",
            "document_number": "2026D41234",
        },
        {},
    )
    assert (letter.path, letter.document_number) == (None, "2026D41234")
    assert letter.tk_url is not None and letter.tk_url.endswith("2026D41234")


def test_a_listed_law_has_its_staatsblad_or_treaty_number() -> None:
    def listed(**row: Any) -> InstrumentListItemDTO:
        return InstrumentListItemDTO.from_document(
            {"id": "instruments/k", "key": "k", "article_count": 0, **row}
        )

    assert listed(official_id="stb-2010-232").official_id == "stb-2010-232"
    assert listed(treaty_number="010783").treaty_number == "010783"
