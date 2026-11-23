"""The concepts a search names by a word of its own (``data/curated/concepts.json``, the list
``concepts`` of ``lawgraph curated``): a term of the law or of its practice, an abbreviation
or an English word (``wanprestatie``, ``ontslag op staande voet``, ``GDPR``, ``minimum
wage``) and the one article or law it is about (art. 6:74 BW, art. 7:677 BW, the AVG, art. 7
Wml), or the concept block of ``data/curated/concept_articles.json`` it names (``bezwaar
maken``: the block ``bezwaar-en-beroep``). The names of an act of the list ``eu-core``
(``data/curated/eu_kern.json``) are terms of that act (``DSA``, ``AI Act``,
``digitaledienstenverordening``). ``/api/search`` puts that article or law first when the
query is the term, or names that block as its best."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.core.models import make_node_key
from lawgraph.core.text_fold import plain_words

# The ``collection`` of a concept that names a concept block (``core.concept_articles``), whose
# ``key`` is the key of the block: no collection of the graph.
BLOCK = "concept_blocks"


@dataclass(frozen=True)
class Concept:
    """A term of the list and the node it is about (an article, else a law), or the concept
    block it names (``BLOCK``)."""

    term: str
    collection: str
    key: str


def concept_key(text: str) -> str:
    """How a term and a query are compared: their words in lower case, without accents and
    punctuation (``woo-verzoek`` is ``woo verzoek``, ``privéleven`` is ``priveleven``)."""
    return plain_words(text)


def concept_of(term: str, value: dict[str, object]) -> Concept:
    """The concept of an entry of the list: *term* and its ``block``, else its ``law`` (a
    BWB id or CELEX number) with its ``article``, or the law itself without one."""
    if block := value.get("block"):
        return Concept(term, BLOCK, str(block))
    law, article = str(value["law"]), value.get("article")
    if article:
        return Concept(term, COLLECTION_ARTICLES, make_node_key(law, str(article)))
    return Concept(term, COLLECTION_INSTRUMENTS, make_node_key(law))


# The brackets at the end of the title of an EU act that are no short title.
_NO_SHORT_TITLE = {"voor de eer relevante tekst", "herschikking", "codificatie"}
_LAST_BRACKET = re.compile(r"\(([^()]*)\)$")


def short_title(title: str) -> str | None:
    """The short title CELLAR gives at the end of the *title* of an EU act, in its last
    brackets (``... (digitaledienstenverordening) (Voor de EER relevante tekst)``:
    ``digitaledienstenverordening``); None when it gives none (``herschikking``)."""
    rest = title.strip()
    while found := _LAST_BRACKET.search(rest.rstrip(" .")):
        name = found.group(1).strip(" .\"'„”“")
        if concept_key(name) not in _NO_SHORT_TITLE:
            return name
        rest = rest.rstrip(" .")[: found.start()].strip()
    return None


def eu_names(name: str, title: str) -> list[str]:
    """The names an act of ``eu-core`` is called by: its *name* before a bracket or comma
    (``AI-verordening``, ``NIS2``), each name in its bracket of capitals (``AI Act``,
    ``AVG/GDPR``: AVG and GDPR; not ``traceerbaarheid`` nor ``artt. 101-102 VWEU``) and the
    short title of its *title* (``short_title``)."""
    head, _, bracket = name.partition("(")
    found = [head.split(",")[0].strip()]
    for part in bracket.rstrip(")").split("/"):
        words = part.split()
        if words and all(w[0].isupper() or w[0].isdigit() for w in words):
            found.append(part.strip())
    short = short_title(title)
    return [*found, short] if short else found


def _eu_names() -> dict[str, tuple[str, Concept]]:
    """The names of the acts of ``eu-core`` (``eu_names``) by ``concept_key``: each as
    written and the concept of its act, with its ``name`` as the term; a name two acts have
    (``Hernieuwbare energie``) is neither's."""
    from lawgraph.core.curated import LISTS

    found: dict[str, tuple[str, Concept]] = {}
    shared: set[str] = set()
    for celex, value in LISTS["eu-core"].entries().items():
        concept = Concept(
            str(value["name"]), COLLECTION_INSTRUMENTS, make_node_key(celex)
        )
        for name in eu_names(str(value["name"]), str(value["title"])):
            key = concept_key(name)
            if key in found and found[key][1] != concept:
                shared.add(key)
            found[key] = (name, concept)
    return {key: n for key, n in found.items() if key and key not in shared}


@functools.cache
def concept_names() -> dict[str, tuple[str, Concept]]:
    """Every term and variant of the list and every name of an act of ``eu-core`` that is
    no term of the list (``_eu_names``), by ``concept_key``: as written, and its concept."""
    from lawgraph.core.curated import LISTS

    found = _eu_names()
    for term, value in LISTS["concepts"].entries().items():
        concept = concept_of(term, value)
        for name in (term, *(value.get("variants") or [])):
            found[concept_key(name)] = (name, concept)
    return found


@functools.cache
def concepts() -> dict[str, Concept]:
    """Every term and variant of the list (``concept_key``) and its concept, and the names
    of the acts of ``eu-core`` that are no term of the list (``concept_names``)."""
    return {key: concept for key, (_, concept) in concept_names().items()}


def concept_named(q: str, words: list[str]) -> Concept | None:
    """The concept *q* is the term or a variant of, whole, or its *words* are (``q``
    without its stop words: ``wat is wanprestatie``); None for any other query."""
    named = concepts()
    return named.get(concept_key(q)) or named.get(concept_key(" ".join(words)))
