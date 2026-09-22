"""What a document node says about itself: its chamber and whether it explains a law.

Pure functions over the values stored on a document, shared by the semantic pipelines
(``tk-mvt`` links the explanatory documents) and the API (which reports both on every
document), so that each fact has one definition.
"""

from __future__ import annotations

from collections.abc import Iterable

from lawgraph.config.constants import CHAMBER_EK, CHAMBER_TK, EXPLANATORY_KIND_MARKER


def chamber_of(labels: Iterable[str] | None) -> str | None:
    """The chamber a node belongs to, read from its labels.

    ``"TK"`` (Tweede Kamer) or ``"EK"`` (Eerste Kamer); ``None`` for a node that belongs
    to neither, such as a Staatsblad or Staatscourant publication.
    """
    found = set(labels or ())
    for chamber in (CHAMBER_TK, CHAMBER_EK):
        if chamber in found:
            return chamber
    return None


def is_explanatory(kind: str | None) -> bool:
    """Whether a document of this ``props.kind`` is an MvT, NvT or nota van toelichting."""
    return EXPLANATORY_KIND_MARKER in (kind or "").lower()
