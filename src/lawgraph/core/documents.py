"""What a document node says about itself: its chamber, whether it explains a law, the
dossier it is numbered in, its number there and who sent it.

Pure functions over the values stored on a document, shared by the semantic pipelines
(``tk-mvt`` links the explanatory documents) and the API (which reports both on every
document), so that each fact has one definition.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import CHAMBER_EK, CHAMBER_TK, EXPLANATORY_KIND_MARKER
from lawgraph.core.ministries import classify_function
from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, dossier_label

# The chambers in the order a node's labels are read: the first it carries is its chamber.
# One definition for the API (``chamber_of``) and the SQL built from it
# (``db/queries/_helpers.chamber_sql``). A node carries the label of each chamber whose
# source wrote it (labels are merged): of a paper both wrote, the Eerste Kamer's counts,
# as /api/documents always read it. No document carries both (lawgraph_small, 2026-10-02).
CHAMBERS: tuple[str, ...] = (CHAMBER_EK, CHAMBER_TK)


def chamber_of(labels: Iterable[str] | None) -> str | None:
    """The chamber a node belongs to, read from its labels (``CHAMBERS``).

    ``"TK"`` (Tweede Kamer) or ``"EK"`` (Eerste Kamer); ``None`` for a node that belongs
    to neither, such as a Staatsblad or Staatscourant publication.
    """
    found = set(labels or ())
    for chamber in CHAMBERS:
        if chamber in found:
            return chamber
    return None


def paper_number(chamber: str | None, props: dict[str, Any]) -> str | None:
    """Its number in the dossier as its chamber numbers it: the nr. of a Tweede Kamer paper
    (its ``sequence``), the letter of an Eerste Kamer one (its ``number``)."""
    if chamber == CHAMBER_EK:
        return props.get("number")
    sequence = props.get("sequence")
    return str(sequence) if chamber == CHAMBER_TK and sequence else None


# The signature that says who sent a Tweede Kamer paper (``DocumentActor.Relatie``), the
# first the paper has: its first signatory, else the one the source calls its sender.
SENDER_ROLES: tuple[str, ...] = ("Eerste ondertekenaar", "Afzender")


def document_sender(
    actors: Iterable[dict[str, Any]] | None, date: str | None = None
) -> dict[str, Any] | None:
    """Who sent a Tweede Kamer paper, from its signatures (``tk_records.document_actors``):
    ``name``, ``function``, ``faction``, ``capacity`` and ``member_key`` as the source
    gives them, and of a bewindspersoon the ``ministry`` the function names on *date*.
    None for a paper without such a signature, as every Eerste Kamer paper."""
    by_role: dict[str, dict[str, Any]] = {}
    for signature in actors or ():
        by_role.setdefault(signature.get("role") or "", signature)
    role = next((r for r in SENDER_ROLES if r in by_role), None)
    if role is None:
        return None
    actor = by_role[role]
    capacity = actor.get("capacity")
    function = actor.get("function")
    person = actor.get("person_id")
    return {
        "name": actor.get("name") or None,
        "function": function,
        "faction": actor.get("faction") or None,
        "capacity": capacity,
        "member_key": make_node_key(str(person)) if person else None,
        "ministry": (
            classify_function(function, on=date)[1]
            if capacity == CAPACITY_GOVERNMENT
            else None
        ),
    }


def is_explanatory(kind: str | None) -> bool:
    """Whether a document of this ``props.kind`` is an MvT, NvT or nota van toelichting."""
    return EXPLANATORY_KIND_MARKER in (kind or "").lower()


def numbered_in(number: object, suffix: object) -> str | None:
    """The label of the dossier a paper is numbered in (``31058``, ``37020-XV``), from its
    ``dossier_number`` and ``dossier_suffix``; ``None`` for a paper that is no Kamerstuk."""
    return dossier_label(number, suffix) or None
