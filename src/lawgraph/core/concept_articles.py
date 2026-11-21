"""The concepts of the law kept by hand: articles that together make one doctrine
(``data/curated/concept_articles.json``, ``lawgraph curated``), shown on each of their pages
as one block. No source groups them; the block adds no text of its own, only the articles,
what cites them and a link to an official explanation."""

from __future__ import annotations

from dataclasses import dataclass

from lawgraph.core import models
from lawgraph.core.curated import ARTICLE_REF, LISTS


@dataclass(frozen=True)
class Concept:
    key: str
    name: str
    # ``<BWB id>/<article number>``, in the order of the list
    articles: tuple[str, ...]
    explanation_label: str | None = None
    explanation_url: str | None = None

    @property
    def article_ids(self) -> tuple[str, ...]:
        """The node ids of its articles, in its order."""
        return tuple(article_id(ref) for ref in self.articles)


def article_id(ref: str) -> str:
    """The node id of the article ``<BWB id>/<article number>``."""
    match = ARTICLE_REF.match(ref)
    if match is None:
        raise ValueError(f"{ref}: no <BWB id>/<article number>")
    return models.article_id(match.group(1), match.group(2))


def concepts() -> dict[str, Concept]:
    """Every concept by its key, in the order of the list."""
    found = {}
    for key, value in LISTS["concept-articles"].entries().items():
        explanation = value.get("explanation") or {}
        found[key] = Concept(
            key=key,
            name=value["name"],
            articles=tuple(value["articles"]),
            explanation_label=explanation.get("label"),
            explanation_url=explanation.get("url"),
        )
    return found


def concepts_of(bwb_id: str, article_number: str) -> list[Concept]:
    """The concepts the article is one of, in the order of the list."""
    ref = f"{bwb_id.upper()}/{article_number}"
    return [c for c in concepts().values() if ref in c.articles]
