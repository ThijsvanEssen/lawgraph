"""The concepts a search names by a word of its own (``data/curated/concepts.json``, the list
``concepts`` of ``lawgraph curated``): a term of the law or of its practice, an abbreviation
or an English word (``wanprestatie``, ``ontslag op staande voet``, ``GDPR``, ``minimum
wage``) and the one article or law it is about (art. 6:74 BW, art. 7:677 BW, the AVG, art. 7
Wml). ``/api/search`` puts that article or law first when the query is the term."""

from __future__ import annotations

import functools
from dataclasses import dataclass

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.core.models import make_node_key
from lawgraph.core.text_fold import plain_words


@dataclass(frozen=True)
class Concept:
    """A term of the list and the node it is about (an article, else a law)."""

    term: str
    collection: str
    key: str


def concept_key(text: str) -> str:
    """How a term and a query are compared: their words in lower case, without accents and
    punctuation (``woo-verzoek`` is ``woo verzoek``, ``privéleven`` is ``priveleven``)."""
    return plain_words(text)


def concept_of(term: str, value: dict[str, object]) -> Concept:
    """The concept of an entry of the list: *term* and its ``law`` (a BWB id or CELEX
    number) with its ``article``, or the law itself without one."""
    law, article = str(value["law"]), value.get("article")
    if article:
        return Concept(term, COLLECTION_ARTICLES, make_node_key(law, str(article)))
    return Concept(term, COLLECTION_INSTRUMENTS, make_node_key(law))


@functools.cache
def concepts() -> dict[str, Concept]:
    """Every term and variant of the list (``concept_key``) and its concept."""
    from lawgraph.core.curated import LISTS

    found: dict[str, Concept] = {}
    for term, value in LISTS["concepts"].entries().items():
        concept = concept_of(term, value)
        for name in (term, *(value.get("variants") or [])):
            found[concept_key(name)] = concept
    return found


def concept_named(q: str, words: list[str]) -> Concept | None:
    """The concept *q* is the term or a variant of, whole, or its *words* are (``q``
    without its stop words: ``wat is wanprestatie``); None for any other query."""
    named = concepts()
    return named.get(concept_key(q)) or named.get(concept_key(" ".join(words)))
