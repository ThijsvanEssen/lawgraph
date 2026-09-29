"""The ministry of a cabinet post whose function names none, from the official sources.

A Rijksoverheid cabinet page names the ministry of most posts (``Minister van Financiën``,
``Staatssecretaris van Justitie en Veiligheid``). A minister without portfolio ("Minister voor
Ontwikkelingssamenwerking") or a state secretary with a portfolio of their own ("Staatssecretaris
Herstel en Toeslagen") names none. For those the ministry comes from what the government
itself published while the post was held, in this order:

1. ``tk_signatures``: the functions the holder signed Tweede Kamer papers in
   (``DocumentActor.Functie``: "staatssecretaris van Financiën"), of the kind of the post;
2. ``tk_commitments``: the ministry of the commitments the holder made (``Toezegging.Ministerie``);
3. ``staatscourant``: the ministry that issued the publications in the Staatscourant and the
   Staatsblad that name the post (``dcterms:creator``; ``retrieve staatscourant-posts``).

Each source gives counts per ministry. The first whose largest count is at least its minimum
(``MIN_COUNT``) and at least ``MIN_SHARE`` of all its counts decides. When none does,
``ministry`` stays null, with ``ministry_missing``: ``ambiguous`` when a source had enough
counts but split them between ministries (Van Veldhoven, Minister voor Milieu en Wonen:
Infrastructuur en Waterstaat 50, BZK 32), ``no_source`` when no source had enough.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Any

from lawgraph.core.government import post_kind, surname_in
from lawgraph.core.ministries import (
    POST_DEPUTY_PRIME_MINISTER,
    POST_STATE_SECRETARY,
    classify_function,
    ministry_of,
)

SOURCE_PAGE = "page"
SOURCE_TK_SIGNATURES = "tk_signatures"
SOURCE_TK_COMMITMENTS = "tk_commitments"
SOURCE_STAATSCOURANT = "staatscourant"
# In the order they are asked.
SOURCES: tuple[str, ...] = (
    SOURCE_TK_SIGNATURES,
    SOURCE_TK_COMMITMENTS,
    SOURCE_STAATSCOURANT,
)

MISSING_NO_SOURCE = "no_source"
MISSING_AMBIGUOUS = "ambiguous"

# The share of its counts the largest ministry of a source must have.
MIN_SHARE = 0.6
# The least count a source needs: one signature or commitment says what it says; a
# publication can name a post in passing, so a handful is needed there.
MIN_COUNT = {
    SOURCE_TK_SIGNATURES: 1,
    SOURCE_TK_COMMITMENTS: 1,
    SOURCE_STAATSCOURANT: 5,
}


def _enough(counts: Counter[str], source: str) -> bool:
    return bool(counts) and counts.most_common(1)[0][1] >= MIN_COUNT[source]


def decide(counts: Counter[str], source: str) -> str | None:
    """The ministry *counts* name clearly enough, or ``None``."""
    if not _enough(counts, source):
        return None
    ministry, count = counts.most_common(1)[0]
    return ministry if count / sum(counts.values()) >= MIN_SHARE else None


def post_ministry(
    evidence: dict[str, Counter[str]],
) -> tuple[str | None, str | None, str | None]:
    """``(ministry, ministry_source, ministry_missing)`` of a post from the counts per
    source (``SOURCES``)."""
    split = False
    for source in SOURCES:
        counts = evidence.get(source) or Counter()
        ministry = decide(counts, source)
        if ministry is not None:
            return ministry, source, None
        split = split or _enough(counts, source)
    return None, None, MISSING_AMBIGUOUS if split else MISSING_NO_SOURCE


def in_period(day: str | None, post: dict[str, Any], *, grace: str = "") -> bool:
    """Whether *day* falls in the period of *post* (``to_date`` ``None``: still held).
    *grace* is a later last day, for a letter signed just after the post ended."""
    if not day or not post.get("from_date") or day < post["from_date"]:
        return False
    end = post.get("to_date")
    return end is None or day <= max(end, grace)


def count_by(ministries: Iterable[str | None]) -> Counter[str]:
    return Counter(m for m in ministries if m)


def _kind(post: dict[str, Any]) -> str:
    return (
        "staatssecretaris" if post.get("post") == POST_STATE_SECRETARY else "minister"
    )


def _plus_days(day: str | None, days: int) -> str:
    if not day:
        return ""
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


# A letter signed just after the post ended still belongs to it.
SIGNED_AFTER_POST_DAYS = 14


def signature_counts(
    post: dict[str, Any], signed: Iterable[dict[str, Any]]
) -> Counter[str]:
    """Per ministry: the months in which the holder signed Tweede Kamer papers in a function
    of the post's kind that names that ministry, while holding the post. *signed* are the
    holder's signatures in government, ``{function, first, last}`` per function and month."""
    grace = _plus_days(post.get("to_date"), SIGNED_AFTER_POST_DAYS)
    return count_by(
        classify_function(row.get("function"), on=row.get("first"))[1]
        for row in signed
        if post_kind(row.get("function")) == _kind(post)
        and in_period(row.get("first"), post, grace=grace)
    )


def commitment_counts(
    post: dict[str, Any], surname: str, commitments: Iterable[dict[str, Any]]
) -> Counter[str]:
    """Per ministry: the commitments made in a function of the post's kind by someone of
    the holder's surname while holding the post, by the ministry the Tweede Kamer gives them
    (``Toezegging.Ministerie``). *commitments* are ``{name, role, ministry_name, date}``."""
    return count_by(
        ministry_of(row.get("ministry_name"), on=row.get("date"))
        for row in commitments
        if row.get("ministry_name")
        and post_kind(row.get("role")) == _kind(post)
        and in_period(row.get("date"), post)
        and surname_in(surname, row.get("name"))
    )


def staatscourant_counts(
    post: dict[str, Any], records: dict[str, dict[str, Any]]
) -> Counter[str]:
    """Per ministry: the publications naming the post that it issued, from the record of
    ``retrieve staatscourant-posts`` (*records*, by external id)."""
    query = staatscourant_query(post)
    record = records.get(query_id(query)) if query else None
    counts: Counter[str] = Counter()
    for creator, n in ((record or {}).get("creators") or {}).items():
        ministry = ministry_of(
            re.sub(r"^ministerie\s+(?:van|voor)\s+", "", creator, flags=re.I),
            on=post.get("from_date"),
        )
        if ministry:
            counts[ministry] += n
    return counts


# ── The Staatscourant ────────────────────────────────────────────────────────

# The KOOP repository holds the Staatscourant and the Staatsblad in full from 1995.
STAATSCOURANT_FROM = "1995-01-01"


def phrase_of(function: str) -> str:
    """The words a publication names a post by: the function, lower case, without accents
    and punctuation (``minister voor ontwikkelingssamenwerking``)."""
    plain = unicodedata.normalize("NFKD", function)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def staatscourant_query(post: dict[str, Any]) -> dict[str, Any] | None:
    """``{phrase, from, to}`` to ask the Staatscourant about a post whose function names no
    ministry, or ``None``: for a post held before 1995, a viceminister-president, or a
    function that names nothing to search by (``Minister zonder Portefeuille``). ``to`` is
    ``None`` while the post is held."""
    if post.get("ministry") or post.get("post") == POST_DEPUTY_PRIME_MINISTER:
        return None
    phrase = phrase_of(post.get("function") or "")
    if not phrase or phrase.startswith("minister zonder portefeuille"):
        return None
    end = post.get("to_date")
    if end is not None and end < STAATSCOURANT_FROM:
        return None
    return {
        "phrase": phrase,
        "from": max(post["from_date"], STAATSCOURANT_FROM),
        "to": end,
    }


def query_id(query: dict[str, Any]) -> str:
    """The external id of the record of a query: ``<phrase>|<from>|<to>`` (``to`` empty
    while the post is held)."""
    return f"{query['phrase']}|{query['from']}|{query['to'] or ''}"
