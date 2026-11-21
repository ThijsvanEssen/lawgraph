"""The concepts an article is one of, as the article route names them."""

from __future__ import annotations

from lawgraph.api.schemas.common import StrictModel

CONCEPTS = (
    "The concepts kept by hand the article is one of (articles that together make one "
    "doctrine); `/api/concepts/{key}` gives each."
)


class ConceptRefDTO(StrictModel):
    """A concept an article is one of: what ``/api/concepts/{key}`` answers for."""

    key: str
    name: str
