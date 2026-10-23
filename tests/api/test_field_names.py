"""What the name of an answer field says (``api/schemas/__init__.py``), held for every
component of ``/openapi.json``. The fields that do not follow yet are listed: the list only
shrinks."""

from __future__ import annotations

from typing import Any

from lawgraph.api.app import app

SCHEMAS: dict[str, dict[str, Any]] = app.openapi()["components"]["schemas"]
FIELDS = [
    (name, field, spec)
    for name, schema in sorted(SCHEMAS.items())
    for field, spec in schema.get("properties", {}).items()
]

# A day is ``<verb>_on``: these still put ``date_`` in front.
DATE_PREFIXED = {
    ("AmendingInstrumentDTO", "date_published"),
    ("AmendingInstrumentDTO", "date_signed"),
    ("DelegatedRegulationDTO", "date_in_force"),
    ("InstrumentDelegatedItem", "date_in_force"),
    ("InstrumentDelegatedSummaryItem", "date_in_force"),
    ("InstrumentDetailDTO", "date_in_force"),
    ("InstrumentDetailDTO", "date_published"),
    ("InstrumentDetailDTO", "date_signed"),
    ("InstrumentRelatedItem", "date_in_force"),
    ("SubDelegatedDTO", "date_in_force"),
}
# A period is ``from_date``/``to_date``: these end it with ``until``.
FROM_DATE_UNTIL = {"MinistryPeriodDTO"}


def test_a_day_is_named_by_what_happened_on_it() -> None:
    found = {(name, field) for name, field, _ in FIELDS if field.startswith("date_")}
    assert found == DATE_PREFIXED


def test_a_period_from_a_date_ends_at_a_date() -> None:
    found = {
        name
        for name, schema in SCHEMAS.items()
        if {"from_date", "until"} <= set(schema.get("properties", {}))
    }
    assert found == FROM_DATE_UNTIL


# The things an answer names. A field with the name of one is the thing itself, an object;
# its key is ``<thing>_key``, its name ``<thing>_name`` and a dossier's number
# ``dossier_number``.
THINGS = {
    "activity",
    "annex",
    "article",
    "cabinet",
    "case",
    "commitment",
    "committee",
    "court",
    "decision",
    "document",
    "dossier",
    "faction",
    "instrument",
    "judgment",
    "law",
    "member",
    "ministry",
    "party",
    "person",
}
# A thing's name that holds a string (a key, a name or a number) yet.
THING_AS_STRING = {
    ("ActorDossierDTO", "cabinet"),
    ("AppealTarget", "court"),
    ("ArticleReferenceDTO", "article"),
    ("CitedByJudgment", "court"),
    ("CoalitionVoteDTO", "cabinet"),
    ("CommitmentDTO", "cabinet"),
    ("CoverageCourtDTO", "court"),
    ("DecisionCabinetCoalition", "cabinet"),
    ("DocumentListItemDTO", "decision"),
    ("DocumentTextResponse", "decision"),
    ("DossierDetailResponse", "cabinet"),
    ("DossierDocumentDTO", "decision"),
    ("DossierSummaryDTO", "cabinet"),
    ("EchrFindingDTO", "article"),
    ("EkMembershipDTO", "faction"),
    ("FactionBoardSeatDTO", "member"),
    ("FeedArticleDTO", "law"),
    ("FeedItemDTO", "cabinet"),
    ("FeedJudgmentDTO", "court"),
    ("FeedLinkDTO", "dossier"),
    ("FeedViaDTO", "article"),
    ("FeedViaDTO", "dossier"),
    ("GovernmentFunctionDTO", "cabinet"),
    ("HallPlaceDTO", "faction"),
    ("HallPlaceDTO", "member"),
    ("InstrumentJudgmentItem", "court"),
    ("JudgmentListItemDTO", "court"),
    ("MemberDTO", "party"),
    ("MemberDetailDTO", "party"),
    ("MemberVoteDTO", "party"),
    ("PartyRefDTO", "faction"),
    ("PartyVotes", "party"),
    ("SectionDTO", "law"),
    ("SenderDTO", "faction"),
    ("SubmitterDTO", "faction"),
    ("TimelineSignatoryDTO", "party"),
    ("TreatyDossierDTO", "dossier"),
    ("UnresolvedCitation", "law"),
    ("VoteOfficeDTO", "cabinet"),
}
# The type of a node is ``type``: these still call it ``node_type``.
NODE_TYPE = {
    "TimelineActivityEntry",
    "TimelineCommitmentEntry",
    "TimelineDecisionEntry",
    "TimelineDocumentEntry",
}


def _shapes(spec: dict[str, Any]) -> set[str]:
    """What a field holds: ``object``, ``string``, ...; of a list what its items hold;
    null not counted."""
    if "$ref" in spec:
        return {"object"}
    if "anyOf" in spec:
        return set().union(*(_shapes(option) for option in spec["anyOf"]))
    kind = spec.get("type")
    if kind == "array":
        return _shapes(spec.get("items", {}))
    return set() if kind == "null" else {kind or "any"}


def test_a_field_named_after_a_thing_holds_it() -> None:
    found = {
        (name, field)
        for name, field, spec in FIELDS
        if field in THINGS and _shapes(spec) != {"object"}
    }
    assert found == THING_AS_STRING


def test_a_key_a_name_or_a_number_is_a_string() -> None:
    found = [
        (name, field)
        for name, field, spec in FIELDS
        if field.endswith(("_key", "_name", "_number"))
        and not _shapes(spec) <= {"string"}
    ]
    assert found == []


def test_the_type_of_a_node_is_its_type() -> None:
    found = {name for name, field, _ in FIELDS if field == "node_type"}
    assert found == NODE_TYPE
