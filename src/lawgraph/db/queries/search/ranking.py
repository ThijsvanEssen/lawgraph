"""The score of a hit: the tier of the best way it matches the query. Ties keep the order of
the database (the rank within a type)."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from lawgraph.core.models import make_node_key
from lawgraph.core.text_fold import ACCENTS
from lawgraph.core.xml import collapse_ws

SCORE_IDENTIFIER = 1.0  # the query is the hit's key or one of its identifiers
SCORE_TITLE = 0.75  # the query is the whole of its name
SCORE_PREFIX = 0.5  # its name starts with the query
SCORE_CONTAINS = 0.25  # every word of the query is in its name
SCORE_WORDS = 0.1  # it matched on stems or text only

# What identifies a hit, besides its key: the fields of ``extra`` that are identifiers.
_IDENTIFIER_FIELDS = (
    "bwb_id",
    "celex",
    "ecli",
    "appno",
    "number",
    "external_id",
    "dossier_number",
    "abbreviation",
    "short_title",
    "slug",
)
_NAME_FIELDS = ("citation_title", "instrument_title", "heading")
# The names of a hit that are lists: the aliases of an instrument.
_NAME_LIST_FIELDS = ("aliases",)
# What places a hit without naming it: the titles of the divisions an article stands in.
_CONTEXT_LIST_FIELDS = ("division_titles",)


def folded(value: Any) -> str:
    """*value* as ``lg_fold`` folds it (lower case, without accents: "yesilgoz" is part of
    "Yeşilgöz-Zegerius"), its spaces one each."""
    if not value:
        return ""
    plain = unicodedata.normalize("NFD", str(value).lower())
    plain = unicodedata.normalize("NFC", ACCENTS.sub("", plain))
    return collapse_ws(plain)


def _folded_list(extra: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [
        folded(value)
        for field in fields
        for value in extra.get(field) or ()
        if isinstance(value, str) and value.strip()
    ]


def score_hit(query: str, hit: Mapping[str, Any]) -> float:
    """The rank tier of *hit* for *query*: identifier, whole name, name prefix, name part.

    Pure: compares the query with the key, the identifiers and the names the hit carries
    (its display name, citation title, heading and aliases). A query that is part of the
    title of a division an article stands in counts as part of its name; the name of its
    law only with its number ("art 2 klimaatfonds"): every article of the Wet
    conflictenrecht onrechtmatige daad would hold "onrechtmatige daad", where art. 6:162 BW
    holds it in its title (the law itself is a hit of the instruments, by its name).
    """
    wanted = folded(query)
    if not wanted:
        return SCORE_WORDS
    extra = hit.get("extra") or {}
    identifiers = {
        folded(hit.get("key")),
        *(folded(extra.get(field)) for field in _IDENTIFIER_FIELDS),
    }
    if wanted in identifiers or make_node_key(wanted) == hit.get("key"):
        return SCORE_IDENTIFIER
    names = [
        folded(hit.get("display_name")),
        *(folded(extra.get(field)) for field in _NAME_FIELDS),
        *(folded(name) for name in extra.get("names") or []),
    ]
    names = [n for n in names if n] + _folded_list(extra, _NAME_LIST_FIELDS)
    if wanted in names:
        return SCORE_TITLE
    if any(n.startswith(wanted) for n in names):
        return SCORE_PREFIX
    words = wanted.split()
    context = _folded_list(extra, _CONTEXT_LIST_FIELDS)
    own = names
    if hit.get("collection") == "articles" and folded(
        extra.get("article_number")
    ) not in set(words):
        # without its number the words are the law's, not the article's
        own = [folded(extra.get("heading"))]
    if hit.get("collection") == "judgments":
        # a judgment's case number is no name: "Rechtbank Amsterdam 2009-07-08 / AWB
        # 08/5197 HUUR" is named by its court and day, the type code of the case is none
        # of its words (``compose_display_name``)
        own = [
            folded(str(hit.get("display_name") or "").split(" / ", 1)[0]),
            *(folded(name) for name in extra.get("names") or []),
        ]
    if any(all(w in n for w in words) for n in own + context if n):
        return SCORE_CONTAINS
    return SCORE_WORDS


def rank_hits(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*hits* with a ``score`` each (a hit that has one keeps it), best first; a member
    without a role (``member_role``) after every hit with one, whatever its score."""
    scored = [{**h, "score": h.get("score", score_hit(query, h))} for h in hits]
    return sorted(
        scored,
        key=lambda h: ((h.get("extra") or {}).get("has_role") is False, -h["score"]),
    )
