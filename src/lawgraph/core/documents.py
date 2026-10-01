"""What a document node says about itself: its chamber, whether it explains a law, and the
dossier it is numbered in.

Pure functions over the values stored on a document, shared by the semantic pipelines
(``tk-mvt`` links the explanatory documents) and the API (which reports both on every
document), so that each fact has one definition.
"""

from __future__ import annotations

from collections.abc import Iterable

from lawgraph.config.constants import CHAMBER_EK, CHAMBER_TK, EXPLANATORY_KIND_MARKER
from lawgraph.core.tk_records import dossier_label

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


def is_explanatory(kind: str | None) -> bool:
    """Whether a document of this ``props.kind`` is an MvT, NvT or nota van toelichting."""
    return EXPLANATORY_KIND_MARKER in (kind or "").lower()


def numbered_in(number: object, suffix: object) -> str | None:
    """The label of the dossier a paper is numbered in (``31058``, ``37020-XV``), from its
    ``dossier_number`` and ``dossier_suffix``; ``None`` for a paper that is no Kamerstuk."""
    return dossier_label(number, suffix) or None
