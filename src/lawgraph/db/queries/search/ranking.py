"""The score of a hit: the tier of the best way it matches the query. Ties keep the order of
the database (the rank within a type)."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from lawgraph.core.models import make_node_key
from lawgraph.core.text_fold import ACCENTS
from lawgraph.core.time import dutch_today
from lawgraph.core.xml import collapse_ws

SCORE_IDENTIFIER = 1.0  # the query is the hit's key or one of its identifiers
SCORE_TITLE = 0.75  # the query is the whole of its name
SCORE_PREFIX = 0.5  # its name starts with the query
SCORE_CONTAINS = 0.25  # every word of the query is in its name
SCORE_WORDS = 0.1  # it matched on stems or text only

# What identifies a hit, besides its key: the fields of ``extra`` that are identifiers. Not
# the dossier of a paper: every paper of the dossier holds its number.
_IDENTIFIER_FIELDS = (
    "bwb_id",
    "celex",
    "ecli",
    "appno",
    "number",
    "external_id",
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
    (its display name, citation title, heading and aliases); of a member also its name
    without the names or initials before it ("Rutte": Mark Rutte, a whole name, above the
    P.J. Rutten that holds it). A query that is part of the
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
    if wanted in names or _surname_of(wanted, hit):
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


def _surname_of(wanted: str, hit: Mapping[str, Any]) -> bool:
    """Whether *wanted* (folded) is the name of the member *hit* without the names or
    initials before it: "rutte" of Mark Rutte, not of P.J. Rutten; of a double surname
    each of its parts too ("yesilgoz" of Dilan Yeşilgöz-Zegerius)."""
    if hit.get("collection") != "members":
        return False
    name = folded(hit.get("display_name"))
    return name.endswith(" " + wanted) or wanted in name.rsplit(" ", 1)[-1].split("-")


# What names a hit exactly, per collection: the fields of ``extra`` and its display name
# (``display_name``) that are its identifiers or its own whole name. Not the heading of an
# article (many have "Definities"), nor the title of a paper or a dossier (one title is that
# of many papers), nor the dossier of a paper: what holds the name is no hit that is it.
_EXACT_FIELDS: dict[str, tuple[str, ...]] = {
    "instruments": (
        "bwb_id",
        "celex",
        "short_title",
        "citation_title",
        "display_name",
        "aliases",
    ),
    "judgments": ("ecli", "appno", "names"),
    "dossiers": ("number",),
    "documents": ("external_id",),
    "members": ("display_name",),
    "factions": ("abbreviation", "display_name"),
    "committees": ("abbreviation", "display_name"),
    "cabinets": ("display_name",),
    "commitments": ("number",),
    "ministries": ("abbreviation", "display_name"),
}


def exact_hit(query: str, hit: Mapping[str, Any]) -> bool:
    """Whether *hit* is the one thing *query* names: found by what identifies it (an
    article by its citation of a law, a judgment by its ECLI, LJN or name, a law by its
    abbreviation: ``exact`` set by its search), or *query* is one of its identifiers or its
    own whole name (``_EXACT_FIELDS``). An article is exact only by its citation."""
    if hit.get("exact"):
        return True
    wanted = folded(query)
    extra = hit.get("extra") or {}
    for field in _EXACT_FIELDS.get(str(hit.get("collection")), ()):
        value = hit.get(field) if field == "display_name" else extra.get(field)
        values = value if isinstance(value, list) else [value]
        if wanted and wanted in {folded(v) for v in values if isinstance(v, str)}:
            return True
    return False


def expired(hit: Mapping[str, Any], today: str) -> bool:
    """Whether the law or article *hit* no longer holds on *today*: its ``extra.expired_on``
    (the first day it did not) is not after it."""
    ended = (hit.get("extra") or {}).get("expired_on")
    return isinstance(ended, str) and bool(ended) and ended[:10] <= today


def rank_hits(
    query: str, hits: list[dict[str, Any]], today: str | None = None
) -> list[dict[str, Any]]:
    """*hits* with a ``score`` each (a hit that has one keeps it), best first; a member
    without a role (``member_role``) after every hit with one, whatever its score; a law or
    an article that no longer holds on *today* (the Dutch day by default) after every hit
    that does, whatever its score, not left out: what the query identifies or names
    exactly (``exact_hit``) goes first still."""
    day = today or dutch_today().isoformat()
    scored = [{**h, "score": h.get("score", score_hit(query, h))} for h in hits]
    return sorted(
        scored,
        key=lambda h: (
            (h.get("extra") or {}).get("has_role") is False,
            _held_no_longer(query, h, day),
            -h["score"],
            expired(h, day),
        ),
    )


def _held_no_longer(query: str, hit: Mapping[str, Any], today: str) -> bool:
    """Whether *hit* no longer holds on *today* and the query neither identifies it nor
    names it exactly: such a hit goes after every one that holds."""
    return (
        expired(hit, today)
        and hit["score"] < SCORE_IDENTIFIER
        and not exact_hit(query, hit)
    )
