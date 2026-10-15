"""The amendments of a dossier as the Kamer handled them (``GET
/api/dossiers/{number}/amendments``)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import PathSource, StrictModel, WithPath
from lawgraph.api.schemas.documents import SubmitterDTO
from lawgraph.core.documents import chamber_of, number_in_dossier
from lawgraph.core.time import strip_time_component
from lawgraph.core.tk_records.actors import submitters as submitters_of
from lawgraph.core.votes import ChainOutcome, DocumentOutcome, decision_outcome


class AmendmentDocumentDTO(WithPath):
    """A document of a chain: the amendment as submitted, or as a newer document changed it."""

    id: str
    key: str
    number: str | None = Field(description="Its nr. in the dossier (``12``).")
    date: str | None
    title: str | None
    replaces: list[str] = Field(
        description="The ids of the documents of the chain it replaces (``REVISES``); empty "
        "for a document submitted new."
    )
    replaced_by: list[str] = Field(
        description="The ids of the documents of the chain that replace it; empty for the "
        "last."
    )


class AmendmentDecisionDTO(WithPath):
    """The decision that decides a chain."""

    path_source = PathSource("decisions")

    id: str
    key: str
    date: str | None
    passed: bool | None = Field(
        description="Whether it carried; null for a decision that is no vote."
    )
    outcome: DocumentOutcome | None = Field(
        description="``aangenomen`` or ``verworpen`` by ``passed``, else ``ingetrokken``, "
        "``aangehouden`` or ``vervallen`` as the decision names it (``core/votes.py``); "
        "null for a decision that is neither (``Stemmen - uitstellen``)."
    )
    decision_kind: str | None = Field(
        description="The ``BesluitSoort`` as the Kamer writes it (``Stemmen - "
        "uitstellen``)."
    )
    tally: dict[str, int] | None = Field(
        description='The seats per choice of the vote (``{"Voor": 92, "Tegen": 58}``); '
        "null without votes."
    )


class AmendmentChainDTO(StrictModel):
    """One amendment as it came to the vote: a chain of documents that replace each other
    (``REVISES``), named by its last document; chains that meet in one last document are one."""

    id: str = Field(description="The id of its last document.")
    first_date: str | None = Field(description="The day of its oldest document.")
    outcome: ChainOutcome = Field(
        description="Of its decision: ``aangenomen``, ``verworpen``, else ``other`` "
        "(withdrawn, held, postponed, lapsed, not voted yet)."
    )
    merged: bool = Field(
        description="More than one of its documents replaces none: amendments merged into "
        "its last document."
    )
    documents: list[AmendmentDocumentDTO] = Field(
        description="Every document of it, the oldest first (by date, then nr.), the last "
        "included."
    )
    submitters: list[SubmitterDTO] = Field(
        description="Who submitted its last document, the indiener first."
    )
    decision: AmendmentDecisionDTO | None = Field(
        description="Of the cases of its last document in their order the first with a "
        "decision that singles it out, of those the latest with an outcome, else the "
        "latest; null without one."
    )
    waiting: bool = Field(
        description="No decision, and a case of its last document is not done: not voted "
        "yet."
    )


class AmendmentChainsResponse(StrictModel):
    """The amendments of a dossier, each chain once, the oldest first (by its oldest
    document)."""

    number: str
    chains: list[AmendmentChainDTO]


def _sequence(document: dict[str, Any]) -> int:
    """The nr. of a document as a number, for its order; 0 without one."""
    sequence = (document.get("light") or {}).get("sequence")
    return int(sequence) if isinstance(sequence, int | float) else 0


def _document_order(document: dict[str, Any]) -> tuple[str, int]:
    return (document.get("light") or {}).get("date") or "", _sequence(document)


def _document(document: dict[str, Any], replaced_by: list[str]) -> AmendmentDocumentDTO:
    light = document.get("light") or {}
    return AmendmentDocumentDTO(
        id=document["id"],
        key=document["key"],
        number=number_in_dossier(chamber_of(document.get("labels")), light),
        date=strip_time_component(light.get("date")),
        title=light.get("title") or light.get("display_name"),
        replaces=list(document["replaces"]),
        replaced_by=replaced_by,
        path_props=light,
    )


def _decision(row: dict[str, Any] | None) -> AmendmentDecisionDTO | None:
    if row is None:
        return None
    tally = row.get("tally")
    return AmendmentDecisionDTO(
        id=row["id"],
        key=row["key"],
        date=strip_time_component(row.get("date")),
        passed=row.get("passed"),
        outcome=decision_outcome(
            row.get("passed"), row.get("decision_kind"), row.get("result")
        ),
        decision_kind=row.get("decision_kind"),
        tally=tally if isinstance(tally, dict) else None,
    )


def amendment_chain(chain: dict[str, Any]) -> AmendmentChainDTO:
    """A chain of ``queries/amendments.get_amendment_chains``."""
    documents = sorted(chain["documents"], key=_document_order)
    replaced_by: dict[str, list[str]] = {}
    for document in documents:
        for older in document["replaces"]:
            replaced_by.setdefault(older, []).append(document["id"])
    last = chain["last"]
    slugs = chain["member_slugs"]
    decision = _decision(chain["decision"])
    return AmendmentChainDTO(
        id=chain["chain_id"],
        first_date=strip_time_component(chain["first_date"]),
        outcome=chain["outcome"],
        merged=sum(1 for document in documents if not document["replaces"]) > 1,
        documents=[_document(p, replaced_by.get(p["id"], [])) for p in documents],
        submitters=[
            SubmitterDTO(**row, path_props={"slug": slugs.get(row["member_key"] or "")})
            for row in submitters_of(
                (last.get("light") or {}).get("kind"), last.get("actors") or []
            )
        ],
        decision=decision,
        waiting=decision is None and chain["open"],
    )


def amendment_chains(
    number: str, chains: list[dict[str, Any]]
) -> AmendmentChainsResponse:
    """The chains of the dossier *number*, the oldest first (by its oldest document)."""
    ordered = sorted(
        chains,
        key=lambda chain: (
            min(map(_document_order, chain["documents"])),
            chain["chain_id"],
        ),
    )
    return AmendmentChainsResponse(
        number=number, chains=[amendment_chain(chain) for chain in ordered]
    )
