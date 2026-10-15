"""The condition of a search: which rows of a type hold the words of the query, in the
period asked for.

A word of the query matches a field by its stemmed tokens (``text``), as the start of a value
in any case (``identity``), as the whole folded value (``norm``) or as a part of 3 to 12
characters of the folded value (``ngram``). Every word must match some field (of an article
also: be the abbreviation of its law, ``abbreviated_laws``; of an article or a dossier: name
it by a term, ``termed_articles`` and ``legislated_dossiers``). Which fields have which matches is ``SEARCH_FIELDS`` of
``db/schema.py``; the columns are generated there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import RELATION_LEGISLATED_IN
from lawgraph.core.time import shift_day
from lawgraph.core.word_forms import word_forms
from lawgraph.db import GraphStore
from lawgraph.db.schema import SEARCH_FIELDS, search_column, start_of_value_sql

Query = tuple[str, dict[str, Any]]


def tokenize_search_query(q: str) -> list[str]:
    """Split a free-text query into lowercase tokens for AND-matching.

    Whitespace is the only separator; punctuation is preserved inside tokens
    so identifiers like ``BWBR0001903`` or ``ECLI:NL:HR:2023:1`` remain intact.
    Tokens of length 1 are dropped to avoid pathological scans.
    """
    return [t for t in q.strip().lower().split() if len(t) > 1]


# ── a period ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Period:
    """The days a search keeps its hits to: from *start* to *end*, both included
    (YYYY-MM-DD); either open."""

    start: str | None = None
    end: str | None = None

    def __bool__(self) -> bool:
        return bool(self.start or self.end)

    def where(self, date: str | None, row: str = "doc") -> str:
        """``AND`` the date of a row in the period (empty without one); *date* is the SQL of
        the date of a row ``{row}`` (``SearchType.period_date``), None for a type without
        one, which no period holds. A date with a time of the last day is in it (before the
        day after)."""
        if not self:
            return ""
        if date is None:
            return " AND false"
        column = date.format(row=row)
        parts = []
        if self.start:
            parts.append(f"{column} >= %(_period_from)s")
        if self.end:
            parts.append(f"{column} < %(_period_until)s")
        return " AND " + " AND ".join(parts)

    def params(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        if self.start:
            found["_period_from"] = self.start
        if self.end:
            found["_period_until"] = shift_day(self.end, 1)
        return found


NO_PERIOD = Period()


# ── the words of the fields ───────────────────────────────────────────────────


def _field_condition(
    table: str, field: str, word: str, row: str, forms: list[str]
) -> list[str]:
    """How *field* of *table* (the row *row*) matches the word in the parameter *word*,
    one condition per analyzer it was indexed with; *forms* the parameters of the forms of
    the word that stem apart (``word_forms``)."""
    analyzers = SEARCH_FIELDS[table][field]
    parts: list[str] = []
    if "text" in analyzers:
        # every word of one of its forms ("huurprijs" or "huurprijzen"): a token the words
        # of a field split ("7:669" is 7 and 669) is found where all its words are, not
        # wherever one of them is (every judgment that holds a 7), as the live search of
        # papers does; a form of no word ("--") finds nothing, not every row
        column = f"{row}.{search_column(field, 'text')}"
        parts.extend(
            f"(cardinality(lg_tokens(%({form})s)) > 0"
            f" AND {column} @> lg_tokens(%({form})s))"
            for form in forms
        )
    # Each of them an index lookup: GIN on the arrays, trigrams on the strings.
    if "identity" in analyzers:
        # from three characters, as a part of a value: the start of a value of two (``hu``,
        # ``st``) is that of a large share of the rows, which the trigrams cannot narrow;
        # in any case, and without accents where the field is folded (``start_of_value_sql``)
        start = start_of_value_sql(table, field, f"%({word})s", row)
        parts.append(f"(char_length(%({word})s) >= 3 AND {start})")
    if "norm" in analyzers:
        parts.append(
            f"{row}.{search_column(field, 'norm')} @> ARRAY[lg_fold(%({word})s)]"
        )
    if "ngram" in analyzers:
        parts.append(
            f"(char_length(%({word})s) BETWEEN 3 AND 12"
            f" AND {row}.{search_column(field, 'ngram')}"
            f" LIKE '%%' || lg_like(lg_fold(%({word})s)) || '%%')"
        )
    return parts


def build_search_clause(
    table: str,
    tokens: list[str],
    fields: list[str],
    row: str = "doc",
    termed: list[list[str]] | None = None,
    laws: list[list[str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """A condition on *row* (a row of *table*): every token matches one of *fields*.

    Returns ``(condition, params)``; the parameters are ``_tok_0``, ``_tok_1``, … so they
    do not collide with those of the caller. A token is taken as typed (lower case, from
    ``tokenize_search_query``): its stems for the words of a field, as is for a prefix of
    its value or a part of it, folded for a whole folded value. ``_form_0_0``, … hold the
    forms of each that stem apart (``word_forms``), each of which matches with all its
    words. *termed* holds per token the rows
    that have it as a term (``termed_articles``: an article by what its case law calls it;
    ``legislated_dossiers``: a dossier by the abbreviation of the law it made), each
    found by its key as well; *laws* per token the BWB ids of the laws it is the
    abbreviation of (``abbreviated_laws``), whose articles it matches.
    """
    if not tokens:
        return "true", {}
    params: dict[str, Any] = {}
    parts: list[str] = []
    for i, token in enumerate(tokens):
        word = f"_tok_{i}"
        params[word] = token
        forms = []
        for j, form in enumerate(word_forms(token).split()):
            forms.append(f"_form_{i}_{j}")
            params[forms[-1]] = form
        per_field = [
            c for f in fields for c in _field_condition(table, f, word, row, forms)
        ]
        if termed:
            params[f"_termed_{i}"] = termed[i]
            per_field.append(f"{row}.id = ANY(%(_termed_{i})s::text[])")
        per_field += _of_laws(laws, i, params, row)
        parts.append("(" + " OR ".join(per_field) + ")")
    return " AND ".join(parts), params


def _of_laws(
    laws: list[list[str]] | None, i: int, params: dict[str, Any], row: str = "doc"
) -> list[str]:
    """The condition that *row* is an article of a law the token *i* is the abbreviation
    of (``abbreviated_laws``), its parameter added to *params*; none when it is of no law."""
    if not laws or not laws[i]:
        return []
    params[f"_law_{i}"] = laws[i]
    return [f"{row}.bwb_id = ANY(%(_law_{i})s::text[])"]


# ── while typing ──────────────────────────────────────────────────────────────

# The token in the parameter ``word`` folded, at the start of a value of an ``ngram``
# column, of a word in it or of a value after the separator of its values: a regular
# expression, every character but a letter or a digit escaped (``live_clause``).
_WORD_START = (
    "('(^|[ ' || chr(31) || '])' || "
    r"regexp_replace(lg_fold(%({word})s), '([^[:alnum:]])', '\\\1', 'g'))"
)


def live_clause(
    table: str,
    tokens: list[str],
    fields: list[str],
    termed: list[list[str]] | None = None,
    laws: list[list[str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """The condition of a search while typing: each an index lookup, none a part of a
    value within a word (``tikst``), which a short part finds in a large share of the
    rows."""
    params: dict[str, Any] = {}
    parts: list[str] = []
    for i, token in enumerate(tokens):
        word = f"_tok_{i}"
        params[word] = token
        per_field = []
        for field in fields:
            analyzers = SEARCH_FIELDS[table][field]
            if "text" in analyzers:
                # every word the token holds (``20/325``: 20 and 325), not any of them;
                # a token of no word (a stop word) holds none
                per_field.append(
                    f"(cardinality(lg_tokens(%({word})s)) > 0"
                    f" AND doc.{search_column(field, 'text')} @> lg_tokens(%({word})s))"
                )
            if "norm" in analyzers:
                per_field.append(
                    f"doc.{search_column(field, 'norm')} @> ARRAY[lg_fold(%({word})s)]"
                )
            if "ngram" in analyzers and len(token) >= 3:
                # at the start of the value, of a word in it or of a value after it: one
                # lookup, the trigrams of the token are the same at each
                column = f"doc.{search_column(field, 'ngram')}"
                per_field.append(f"{column} ~ {_WORD_START.format(word=word)}")
        if termed:
            params[f"_termed_{i}"] = termed[i]
            per_field.append(f"doc.id = ANY(%(_termed_{i})s::text[])")
        per_field += _of_laws(laws, i, params)
        parts.append("(" + " OR ".join(per_field or ["false"]) + ")")
    return " AND ".join(parts) or "true", params


# ── what a word stands for besides its fields ─────────────────────────────────

# An article whose case law calls it by a word of the query (``lg_article_terms``): at most
# ``TERMED`` of them per word, the first by id.
TERMED = 1_000

_TERMED_SQL = """
SELECT w.n::int AS n,
       coalesce(array_agg(t.article_id ORDER BY t.article_id)
                FILTER (WHERE t.article_id IS NOT NULL), '{}') AS ids
FROM unnest(%(forms)s::text[]) WITH ORDINALITY AS w(forms, n)
LEFT JOIN LATERAL (
    -- found through the index of the terms first (OFFSET 0), not by walking the keys in
    -- order until the cap
    SELECT a.article_id FROM (
        SELECT a.article_id FROM lg_article_terms a
        WHERE a.terms && lg_tokens(w.forms)
        OFFSET 0
    ) a
    ORDER BY a.article_id NULLS LAST
    LIMIT %(cap)s
) t ON true
GROUP BY w.n
ORDER BY w.n
"""


def termed_articles(store: GraphStore, tokens: list[str]) -> list[list[str]] | None:
    """Per token the articles that have it (or a form of it) as a term; None when none
    has any."""
    if not tokens:
        return None
    rows = store.query(
        _TERMED_SQL, {"forms": [word_forms(t) for t in tokens], "cap": TERMED}
    )
    termed = [list(row["ids"]) for row in rows]
    return termed if any(termed) else None


# The laws a word ``w.word`` is a short title or an alias of (``bwb_wti``: the
# abbreviations of the WTI, ``BW`` of every book), whole and folded: an index lookup each.
_ABBREVIATES = f"""
    i.{search_column("aliases", "norm")} @> ARRAY[lg_fold(w.word)]
    OR i.{search_column("short_title", "norm")} @> ARRAY[lg_fold(w.word)]
"""
# Per word the BWB ids of the laws it is the abbreviation of.
_CITED_BY_SQL = f"""
SELECT w.n::int AS n,
       coalesce(array_agg(DISTINCT i.bwb_id) FILTER (WHERE i.bwb_id IS NOT NULL), '{{}}')
           AS ids
FROM unnest(%(words)s::text[]) WITH ORDINALITY AS w(word, n)
LEFT JOIN LATERAL (
    SELECT i.bwb_id FROM instruments i WHERE {_ABBREVIATES}
) i ON true
GROUP BY w.n
ORDER BY w.n
"""
# Per word the dossiers the laws it is the abbreviation of were ``LEGISLATED_IN`` (the
# bill each became, as the BWB names it): an index lookup on the edges of each law.
_LEGISLATED_SQL = f"""
SELECT w.n::int AS n,
       coalesce(array_agg(DISTINCT d.id ORDER BY d.id) FILTER (WHERE d.id IS NOT NULL),
                '{{}}') AS ids
FROM unnest(%(words)s::text[]) WITH ORDINALITY AS w(word, n)
LEFT JOIN LATERAL (
    SELECT e.to_id AS id
    FROM instruments i
    JOIN edges e ON e.from_id = i.id AND e.relation = %(legislated_in)s
                AND e.to_collection = 'dossiers'
    WHERE {_ABBREVIATES}
) d ON true
GROUP BY w.n
ORDER BY w.n
"""


def abbreviated_laws(store: GraphStore, tokens: list[str]) -> list[list[str]] | None:
    """Per token the BWB ids of the laws it is the abbreviation of: a word of each of
    their articles, as the name of its law is ("zorgplicht cbw" finds art. 21 of the
    Cyberbeveiligingswet as "zorgplicht cyberbeveiligingswet" does). None when no token
    is one."""
    if not tokens:
        return None
    rows = store.query(_CITED_BY_SQL, {"words": tokens})
    laws = [list(row["ids"]) for row in rows]
    return laws if any(laws) else None


def legislated_dossiers(store: GraphStore, tokens: list[str]) -> list[list[str]] | None:
    """Per token the dossiers of the laws it is the abbreviation of: a name of each, as
    the name of its law in its title is ("cbw" finds dossier 36764, whose bill became the
    Cyberbeveiligingswet). None when no token is one."""
    if not tokens:
        return None
    rows = store.query(
        _LEGISLATED_SQL, {"words": tokens, "legislated_in": RELATION_LEGISLATED_IN}
    )
    dossiers = [list(row["ids"]) for row in rows]
    return dossiers if any(dossiers) else None
