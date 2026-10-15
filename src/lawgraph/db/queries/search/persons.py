"""The judgments a query finds by the persons they name (``lg_judgment_persons``: a party
not anonymised, whoever acts for a party).

A query finds such a judgment when every word of the query is a word of that one name: "R.
van Gelder", "Van Gelder" and "mr. drs. R. van Gelder" all find "mr. drs. R. van Gelder" (a
title is a word of the name too), "Vermeulen" finds "mr. I.T.F. Vermeulen". A word matches
whole; while typing, the last word by its start. The names are looked up by the trigram
index for the words that tell a name apart, of ``PERSON_MIN`` characters or more and none of
``_NAME_EXTRAS`` (a title, an article, a particle: "van" is in a third of the names); the
others are only checked in the names found. Without such a word the query names no person.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.core.dutch_names import PARTICLES, TITLES
from lawgraph.db import GraphStore
from lawgraph.db.queries.search.clause import Period
from lawgraph.db.queries.search.ranking import (
    SCORE_CONTAINS,
    SCORE_WORDS,
    folded,
    rank_hits,
    score_hit,
)
from lawgraph.db.queries.search.spec import Hit

PERSON_MIN = 3
# The rows a search of persons orders at most: a common name ("college van burgemeester en
# wethouders") is in far more, and the first found stand for them.
PERSON_CANDIDATES = 2_000
# The words of a name a query may leave out: a title, an article or a particle.
_NAME_EXTRAS = frozenset(TITLES) | PARTICLES
_PERSON_HIT = """
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'judgments', 'type', doc.type,
        'display_name', doc.props -> 'display_name',
        'snippet', left(coalesce(doc.props ->> 'summary', ''), 200),
        'extra', json_build_object(
            'ecli', doc.props -> 'ecli',
            'appno', doc.props -> 'appno',
            'names', doc.props -> 'names',
            'person', json_build_object(
                'name', top.name, 'role', top.role, 'party', top.party
            )
        )
    )
"""


def person_words(tokens: list[str]) -> list[str]:
    """The words of *tokens* as ``lg_person_words`` keeps those of a name: "zuid-holland" is
    two, "r." is "r"."""
    return [word for token in tokens for word in re.split(r"[\W_]+", token) if word]


def _telling(word: str) -> bool:
    """Does *word* tell a name apart: long enough and no title, article or particle?"""
    return len(word) >= PERSON_MIN and folded(word) not in _NAME_EXTRAS


def judgments_by_person(
    store: GraphStore,
    tokens: list[str],
    limit: int,
    period: Period,
    date: str | None,
    *,
    typing: bool,
) -> list[Hit]:
    """The judgments that name a person every word of the query is a word of (*typing*: the
    last word its start), the newest first of the first ``PERSON_CANDIDATES`` found, with
    the person in ``extra.person`` (``name``, ``role``, ``party``: the party they act for,
    null for a party), scored by ``_person_score``; *date* the date of a judgment a
    *period* asks for. None when no word tells a name apart (``_telling``)."""
    words = person_words(tokens)
    if not any(_telling(word) for word in words):
        return []
    params: dict[str, Any] = {}
    holds = []
    for i, word in enumerate(words):
        params[f"_person_{i}"] = word
        end = "" if typing and i == len(words) - 1 else " "
        if _telling(word):  # by the index
            holds.append(
                f"p.words LIKE '%% ' || lg_like(lg_fold(%(_person_{i})s)) || '{end}%%'"
            )
        else:  # in the names found
            holds.append(
                f"strpos(p.words, ' ' || lg_fold(%(_person_{i})s) || '{end}') > 0"
            )
    params.update(
        period.params(),
        candidates=PERSON_CANDIDATES,
        # a publication another replaces is left out after the order: some to spare
        wanted=2 * limit,
        limit=limit,
    )
    statement = f"""
        WITH found AS MATERIALIZED (
            SELECT p.id, p.n, p.name, p.role, p.party, p.date_eff
            FROM lg_judgment_persons p
            WHERE {" AND ".join(holds)} {period.where(date, "p")}
            LIMIT %(candidates)s
        ), first AS (
            SELECT DISTINCT ON (id) * FROM found ORDER BY id, n
        ), top AS (
            SELECT * FROM first
            ORDER BY date_eff DESC NULLS LAST, id DESC
            LIMIT %(wanted)s
        )
        SELECT {_PERSON_HIT}
        FROM top JOIN judgments doc ON doc.id = top.id
        WHERE doc.stub IS NOT TRUE AND doc.same_as IS NULL
        ORDER BY top.date_eff DESC NULLS LAST, top.id DESC
        LIMIT %(limit)s
        """
    return [
        {**hit, "score": _person_score(words, hit["extra"]["person"]["name"], typing)}
        for hit in store.query(statement, params)
    ]


def _person_score(words: list[str], name: str, typing: bool) -> float:
    """``SCORE_CONTAINS`` when the query *words* are all of the name but what it may leave
    out (``_NAME_EXTRAS``, initials): "Van Gelder" of "mr. drs. R. van Gelder", "college van
    gedeputeerde staten van zuid-holland" of the college; else ``SCORE_WORDS``: "minister"
    is only a word of "de minister van Financiën"."""
    asked = [folded(word) for word in words]
    for word in person_words([folded(name)]):
        if len(word) == 1 or word in _NAME_EXTRAS:
            continue
        if word not in asked and not (typing and word.startswith(asked[-1])):
            return SCORE_WORDS
    return SCORE_CONTAINS


def with_persons(q: str, persons: list[Hit], found: list[Hit], limit: int) -> list[Hit]:
    """The judgments *found* and those found by a person, each once (by a person when it
    is both), the best scored first; at most *limit*. A judgment found by a person the query
    is all of comes before those *found* of its score, one that merely holds its words after
    them."""
    if not persons:
        return found
    by_person = {hit["id"]: hit for hit in persons}
    named = [hit for hit in persons if hit["score"] >= SCORE_CONTAINS]
    rest = [hit for hit in persons if hit["score"] < SCORE_CONTAINS]
    hits: dict[str, Hit] = {}
    for hit in (
        named + [_also_by_person(q, h, by_person.get(h["id"])) for h in found] + rest
    ):
        hits.setdefault(hit["id"], hit)
    return rank_hits(q, list(hits.values()))[:limit]


def _also_by_person(q: str, hit: Hit, person: Hit | None) -> Hit:
    """*hit*, found by a person too: with that person, and the better of both scores."""
    if person is None:
        return hit
    score = max(hit.get("score", score_hit(q, hit)), person["score"])
    extra = {**(hit.get("extra") or {}), "person": person["extra"]["person"]}
    return {**hit, "extra": extra, "score": score}
