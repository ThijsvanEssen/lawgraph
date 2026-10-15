"""What an item of the news feed (``queries/feed.py``) says of the sources it is tied to, and
the events of one law (``instrument``) or one article of it (``article``).

Every fragment here is SQL on a row of the page (``pg``: its kind and id) and its node
(``n``: its id and props), read once per item of the page in the statement of the page: an
index probe or a few per item, never a read of the graph per event under the filters. What
a kind does not have is not read: each fragment is guarded by the kind of the row.

- ``RELATIONS``: of a letter of the government the motions and commitments it answers, of a
  commitment the letters that answer it, of an amendment the articles it proposes to change,
  of a motion or an amendment the document it replaces, of a judgment the articles it cites;
- ``COMMENCED``: of a new version of a law in force, the articles with a version that begins
  that day, the publication those versions came from and what the law is issued under;
- ``followed_ctes`` and ``VIA``: the events of a law, each with how it is tied to it.
"""

from __future__ import annotations

from typing import Final

from lawgraph.config.constants import (
    CHANGE_RELATIONS,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_ABOUT,
    RELATION_ANSWERS,
    RELATION_BASED_ON,
    RELATION_LEGISLATED_IN,
    RELATION_REFERS_TO,
    RELATION_REVISES,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.feed import (
    DOCUMENT_EVENTS,
    EVENT_AMENDMENT,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_GOVERNMENT_LETTER,
    EVENT_JUDGMENT,
    EVENT_MOTION,
    EVENT_PUBLICATION,
    EVENT_VOTE,
)
from lawgraph.core.tk_records.actors import FIRST_SIGNATORY
from lawgraph.db.queries._json_sql import EMPTY_ARRAY, array_or_empty, truthy_or

# What an item names at most of each relation.
MAX_LINKED = 20
# The articles of a judgment an item names: the most mentioned.
MAX_CITED = 5
# The article numbers of a new version an item names, in the order of the law.
MAX_COMMENCED_ARTICLES = 50

_CHANGES: Final = ", ".join(f"'{relation}'" for relation in CHANGE_RELATIONS)


def _kinds(*kinds: str) -> str:
    return ", ".join(f"'{kind}'" for kind in kinds)


def bwb_key(bwb: str) -> str:
    """SQL: the key of the instrument of the BWB id *bwb*: the id in lower case. A BWB id is
    letters and digits, so ``lg_node_key`` makes the same of it, but the planner prices that
    higher and turns the plan of the feed's page (an index scan of the instruments for the
    scan it reads them by)."""
    return f"lower({bwb})"


# The identifier of the publication ``n`` as a regulation names the one that enacted it
# (``props.enacted_publication``): its id on officielebekendmakingen.nl, else made of its
# series, year and number as the BWB makes it (``core.bwb_xml._publication``).
PUBLICATION_IDENTIFIER = (
    "coalesce(lg_str(n.props -> 'official_id'),"
    " lower(lg_str(n.props -> 'publication_kind')) || '-'"
    " || (n.props ->> 'publication_year') || '-' || lg_str(n.props -> 'publication_number'))"
)
# The publication that enacted a regulation ``r``: the expression of the index
# ``instruments_enacted_publication`` (``db.schema``).
ENACTED = "lg_str(r.props -> 'enacted_publication')"
ENACTED_OF_REGULATION = f"r.kind IS DISTINCT FROM '{KIND_PUBLICATION}'"


# ── the sources an item is tied to ───────────────────────────────────────────

# A document or a commitment as an item names it: what its readable address and its line are
# made of (its kind, title, date, number, dossier; of a document its first signatory).
_DOCUMENT = f"""(SELECT json_build_object(
                    'id', l.id, 'props', l.props, 'subject', d.pj_subject,
                    'signatory', (
                        SELECT s.v FROM json_array_elements(
                            {array_or_empty("d.pj_actors")}) AS s(v)
                        WHERE lg_str(s.v -> 'role') = '{FIRST_SIGNATORY}'
                        LIMIT 1))
                FROM lg_document_light l JOIN {COLLECTION_DOCUMENTS} d ON d.id = l.id
                WHERE l.id = {{id}})"""
_COMMITMENT = f"""(SELECT json_build_object(
                    'id', c.id, 'made_on', c.made_on,
                    'props', json_build_object(
                        'number', c.props -> 'number', 'text', c.props -> 'text',
                        'display_name', c.props -> 'display_name',
                        'status', c.props -> 'status'))
                FROM {COLLECTION_COMMITMENTS} c WHERE c.id = {{id}})"""


def _linked(node_id: str) -> str:
    """SQL: the document or commitment *node_id* as an item names it."""
    return (
        f"CASE WHEN starts_with({node_id}, '{COLLECTION_COMMITMENTS}/')"
        f" THEN {_COMMITMENT.format(id=node_id)}"
        f" ELSE {_DOCUMENT.format(id=node_id)} END"
    )


# An article as an item names it: its number, law and how the law is cited.
_ARTICLE = """json_build_object(
                    'key', a.key, 'bwb_id', a.bwb_id, 'article_number', a.article_number,
                    'law', a.props -> 'instrument_citation_title',
                    'law_short', a.props -> 'instrument_abbreviation',
                    'effect', {effect})"""

_ANSWERS = f"""CASE WHEN pg.kind = '{EVENT_GOVERNMENT_LETTER}' THEN (
                SELECT coalesce(json_agg(x.v ORDER BY x.id), {EMPTY_ARRAY}) FROM (
                    SELECT e.to_id AS id, {_linked("e.to_id")} AS v
                    FROM {COLLECTION_EDGES} e
                    WHERE e.from_id = pg.id AND e.relation = '{RELATION_ANSWERS}'
                      AND e.to_collection IN ('{COLLECTION_DOCUMENTS}', '{COLLECTION_COMMITMENTS}')
                    ORDER BY e.to_id
                    LIMIT {MAX_LINKED}
                ) x
            ) END"""

_ANSWERED_BY = f"""CASE WHEN pg.kind = '{EVENT_COMMITMENT}' THEN (
                SELECT coalesce(json_agg(x.v ORDER BY x.id), {EMPTY_ARRAY}) FROM (
                    SELECT e.from_id AS id, {_linked("e.from_id")} AS v
                    FROM {COLLECTION_EDGES} e
                    WHERE e.to_id = pg.id AND e.relation = '{RELATION_ANSWERS}'
                      AND e.from_collection = '{COLLECTION_DOCUMENTS}'
                    ORDER BY e.from_id
                    LIMIT {MAX_LINKED}
                ) x
            ) END"""

# The articles an amendment proposes to change, in the order of their law.
_AMENDS_ARTICLES = f"""CASE WHEN pg.kind = '{EVENT_AMENDMENT}' THEN (
                SELECT coalesce(json_agg(x.v ORDER BY x.bwb_id, x.position NULLS LAST, x.key),
                                {EMPTY_ARRAY}) FROM (
                    SELECT a.bwb_id, a.position, a.key,
                           {_ARTICLE.format(effect="lower(e.relation)")} AS v
                    FROM {COLLECTION_EDGES} e
                    JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
                    WHERE e.from_id = pg.id AND e.relation IN ({_CHANGES})
                      AND e.to_collection = '{COLLECTION_ARTICLES}'
                    ORDER BY a.bwb_id, a.position NULLS LAST, a.key
                    LIMIT {MAX_LINKED}
                ) x
            ) END"""

# The document a changed motion or amendment replaces ("ter vervanging van nr. 19").
_REPLACES = f"""CASE WHEN pg.kind IN ({_kinds(EVENT_MOTION, EVENT_AMENDMENT)}) THEN (
                SELECT {_linked("e.to_id")}
                FROM {COLLECTION_EDGES} e
                WHERE e.from_id = pg.id AND e.relation = '{RELATION_REVISES}'
                  AND e.to_collection = '{COLLECTION_DOCUMENTS}'
                ORDER BY e.to_id
                LIMIT 1
            ) END"""

# The articles a judgment cites, the most mentioned first.
_CITES = f"""CASE WHEN pg.kind = '{EVENT_JUDGMENT}' THEN (
                SELECT coalesce(json_agg(x.v ORDER BY x.n), {EMPTY_ARRAY}) FROM (
                    SELECT {_ARTICLE.format(effect="NULL::text")} AS v,
                           row_number() OVER (
                               ORDER BY lg_num(e.doc -> 'meta' -> 'mention_count')
                                        DESC NULLS LAST, a.bwb_id, a.position NULLS LAST,
                                        a.key) AS n
                    FROM {COLLECTION_EDGES} e
                    JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
                    WHERE e.from_id = pg.id AND e.relation = '{RELATION_REFERS_TO}'
                      AND e.to_collection = '{COLLECTION_ARTICLES}'
                    ORDER BY n
                    LIMIT {MAX_CITED}
                ) x
            ) END"""

# Per item: what it is tied to, by its kind (each null for the other kinds).
RELATIONS = (
    ("answers", _ANSWERS),
    ("answered_by", _ANSWERED_BY),
    ("amends_articles", _AMENDS_ARTICLES),
    ("replaces", _REPLACES),
    ("cites", _CITES),
)


# ── a new version of a law in force ──────────────────────────────────────────

# The bwb id and the first day of the version ``n``.
_BWB = "lg_str(n.props -> 'bwb_id')"
_DAY = "lg_str(n.props -> 'valid_from')"
_VERSIONS_OF_DAY = (
    f"FROM {COLLECTION_ARTICLE_VERSIONS} v"
    f" WHERE {_BWB} IS NOT NULL AND v.bwb_id = {_BWB} AND v.valid_from = {_DAY}"
)

COMMENCED = f"""CASE WHEN pg.kind = '{EVENT_COMMENCEMENT}' THEN json_build_object(
                -- the articles with a version that begins that day, in the order of the law
                'articles', (
                    SELECT coalesce(json_agg(v.article_number ORDER BY v.n), {EMPTY_ARRAY})
                    FROM (
                        SELECT v.article_number, row_number() OVER (
                            ORDER BY lg_num(v.props -> 'position') NULLS LAST, v.key) AS n
                        {_VERSIONS_OF_DAY}
                        ORDER BY n
                        LIMIT {MAX_COMMENCED_ARTICLES}
                    ) v
                ),
                -- the publication most of those versions came from (``origin_publication``)
                'publication', (
                    SELECT json_build_object(
                        'identifier', o.identifier, 'publication', o.publication,
                        'key', p.key)
                    FROM (
                        SELECT lg_str(v.props -> 'origin_publication' -> 'id') AS identifier,
                               (array_agg(v.props -> 'origin_publication'))[1] AS publication,
                               count(*) AS versions
                        {_VERSIONS_OF_DAY}
                          AND lg_str(v.props -> 'origin_publication' -> 'id') IS NOT NULL
                        GROUP BY 1
                        ORDER BY versions DESC NULLS LAST, identifier ASC NULLS LAST
                        LIMIT 1
                    ) o
                    LEFT JOIN {COLLECTION_INSTRUMENTS} p ON p.key = lg_node_key(o.identifier)
                ),
                -- the law its preamble names most articles of (``BASED_ON``)
                'based_on', (
                    SELECT json_build_object(
                        'key', law.key,
                        'title', {truthy_or("law.props -> 'citation_title'", "law.props -> 'title'")},
                        'bwb_id', law.bwb_id,
                        'articles', b.articles)
                    FROM (
                        SELECT a.bwb_id, json_agg(a.article_number
                                   ORDER BY a.position NULLS LAST, a.key) AS articles,
                               count(*) AS named
                        FROM {COLLECTION_EDGES} e
                        JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
                        WHERE {_BWB} IS NOT NULL
                          AND e.from_id = '{COLLECTION_INSTRUMENTS}/' || {bwb_key(_BWB)}
                          AND e.relation = '{RELATION_BASED_ON}'
                          AND e.to_collection = '{COLLECTION_ARTICLES}'
                          AND a.bwb_id IS NOT NULL
                        GROUP BY a.bwb_id
                        ORDER BY named DESC NULLS LAST, a.bwb_id
                        LIMIT 1
                    ) b
                    JOIN {COLLECTION_INSTRUMENTS} law ON law.bwb_id = b.bwb_id
                )
            ) END"""


# ── the events of one law ────────────────────────────────────────────────────


def followed_ctes(article: bool) -> str:
    """SQL: the CTEs of the events of the law ``%(instrument)s`` (a BWB id), or with
    *article* of its article ``%(article)s``, each read only by the kinds that use it:

    - ``followed_changes``: the publications that change, add to or repeal the law or its
      articles, the one that enacted the law, and the documents that propose to;
    - ``followed_dossiers``: the dossiers the law, or a publication of it, was legislated
      in (``LEGISLATED_IN``) and those of the documents that propose to change it;
    - ``followed_versions``: the versions of the law (with *article* the days that article
      changed) and of the regulations issued under it (``BASED_ON``);
    - ``followed_judgments``: the judgments that cite it.
    """
    one = " AND a.article_number = %(article)s" if article else ""
    # without an article: the law itself, its enactment and its dossiers too
    whole = "" if article else "UNION ALL SELECT id FROM law"
    enacted = (
        ""
        if article
        else f"""
        UNION ALL
        SELECT '{COLLECTION_INSTRUMENTS}/' || lg_node_key(law.enacted),
               '{COLLECTION_INSTRUMENTS}'
        FROM law WHERE law.enacted IS NOT NULL"""
    )
    changed_day = (
        f""" AND EXISTS (SELECT 1 FROM {COLLECTION_ARTICLE_VERSIONS} av
                         WHERE av.bwb_id = v.bwb_id AND av.article_number = %(article)s
                           AND av.valid_from = v.valid_from)"""
        if article
        else ""
    )
    return f""",
    law AS MATERIALIZED (
        SELECT i.id, lg_str(i.props -> 'enacted_publication') AS enacted
        FROM {COLLECTION_INSTRUMENTS} i WHERE i.bwb_id = %(instrument)s
    ),
    law_articles AS MATERIALIZED (
        SELECT a.id FROM {COLLECTION_ARTICLES} a WHERE a.bwb_id = %(instrument)s{one}
    ),
    law_targets AS MATERIALIZED (
        SELECT id FROM law_articles {whole}
    ),
    followed_changes AS MATERIALIZED (
        SELECT e.from_id AS id, e.from_collection AS collection
        FROM law_targets t
        CROSS JOIN LATERAL (
            SELECT e.from_id, e.from_collection FROM {COLLECTION_EDGES} e
            WHERE e.to_id = t.id AND e.relation IN ({_CHANGES})
              AND e.from_collection IN ('{COLLECTION_INSTRUMENTS}', '{COLLECTION_DOCUMENTS}')
            OFFSET 0
        ) e{enacted}
    ),
    followed_dossiers AS MATERIALIZED (
        SELECT DISTINCT ON (label) label, relation FROM (
            SELECT d.label, '{RELATION_LEGISLATED_IN.lower()}' AS relation, 0 AS rank
            FROM (SELECT id FROM followed_changes
                  WHERE collection = '{COLLECTION_INSTRUMENTS}' {whole}) s
            CROSS JOIN LATERAL (
                SELECT d.label FROM {COLLECTION_EDGES} e
                JOIN {COLLECTION_DOSSIERS} d ON d.id = e.to_id
                WHERE e.from_id = s.id AND e.relation = '{RELATION_LEGISLATED_IN}'
                  AND e.to_collection = '{COLLECTION_DOSSIERS}'
                OFFSET 0
            ) d
            UNION ALL
            SELECT unnest(p.dossier_numbers), 'proposes', 1
            FROM {COLLECTION_DOCUMENTS} p
            WHERE p.id IN (SELECT id FROM followed_changes
                           WHERE collection = '{COLLECTION_DOCUMENTS}')
        ) found
        WHERE label IS NOT NULL
        ORDER BY label ASC NULLS LAST, rank
    ),
    followed_versions AS MATERIALIZED (
        SELECT v.id FROM {COLLECTION_INSTRUMENT_VERSIONS} v
        WHERE v.bwb_id = %(instrument)s{changed_day}
        UNION ALL
        SELECT v.id FROM law_articles a
        CROSS JOIN LATERAL (
            SELECT e.from_id FROM {COLLECTION_EDGES} e
            WHERE e.to_id = a.id AND e.relation = '{RELATION_BASED_ON}'
              AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
            OFFSET 0
        ) e
        CROSS JOIN LATERAL (
            SELECT v.id FROM {COLLECTION_INSTRUMENTS} r
            JOIN {COLLECTION_INSTRUMENT_VERSIONS} v ON v.bwb_id = r.bwb_id
            WHERE r.id = e.from_id
            OFFSET 0
        ) v
    ),
    followed_judgments AS MATERIALIZED (
        SELECT e.from_id AS id FROM law_targets t
        CROSS JOIN LATERAL (
            SELECT e.from_id FROM {COLLECTION_EDGES} e
            WHERE e.to_id = t.id AND e.relation = '{RELATION_REFERS_TO}'
              AND e.from_collection = '{COLLECTION_JUDGMENTS}'
            OFFSET 0
        ) e
    )"""


def _among(source: str, column: str = "id") -> str:
    """SQL: ``n`` is one of the events *column* of *source* (a CTE of ``followed_ctes``, or
    a join on one) gives: looked up by its id, then put in date order. The events of a law
    are few next to those of a kind: read in date order and tested one by one, a law with
    few events would have every event of the kind read (seconds for a document kind on
    prod)."""
    return f"n.id = ANY(ARRAY(SELECT {column} FROM {source}))"


def _in_dossiers(table: str) -> str:
    """SQL (a source of ``_among``): the rows of *table* in a dossier of the law, by its
    index on ``dossier_numbers``."""
    return f"{table} x WHERE x.dossier_numbers && ARRAY(SELECT label FROM followed_dossiers)"


# Per kind: SQL on ``n`` that keeps the events of the law (``followed_ctes``).
FOLLOWS: Final[dict[str, str]] = {
    EVENT_COMMITMENT: _among(
        f"followed_dossiers f JOIN {COLLECTION_DOSSIERS} d ON d.label = f.label"
        " CROSS JOIN LATERAL ("
        f" SELECT e.from_id FROM {COLLECTION_EDGES} e WHERE e.to_id = d.id"
        f" AND e.relation = '{RELATION_ABOUT}'"
        f" AND e.from_collection = '{COLLECTION_COMMITMENTS}' OFFSET 0) e",
        "e.from_id",
    ),
    **dict.fromkeys(
        DOCUMENT_EVENTS,
        _among(
            "followed_changes"
            f" UNION SELECT x.id FROM {_in_dossiers(COLLECTION_DOCUMENTS)}"
        ),
    ),
    EVENT_VOTE: _among(_in_dossiers(COLLECTION_DECISIONS), "x.id"),
    EVENT_PUBLICATION: _among("followed_changes"),
    EVENT_COMMENCEMENT: _among("followed_versions"),
    EVENT_JUDGMENT: _among("followed_judgments"),
}


# A judgment that cites the law followed (or its article): tested on the judgment, by the
# index of its own edges, for a law many judgments cite (``feed._widely_cited``).
CITES_LAW = (
    f"EXISTS (SELECT 1 FROM {COLLECTION_EDGES} e"
    f" WHERE e.from_id = n.id AND e.relation = '{RELATION_REFERS_TO}'"
    " AND e.to_id IN (SELECT id FROM law_targets))"
)

# Whether ``%(n)s`` judgments or more cite the law ``%(instrument)s`` (with ``%(article)s``
# that article of it, when not null): its citations counted up to that many.
CITATIONS_OF_LAW = f"""
SELECT count(*) >= %(n)s AS widely FROM (
    SELECT 1 FROM {COLLECTION_ARTICLES} a
    CROSS JOIN LATERAL (
        SELECT 1 FROM {COLLECTION_EDGES} e
        WHERE e.to_id = a.id AND e.relation = '{RELATION_REFERS_TO}'
          AND e.from_collection = '{COLLECTION_JUDGMENTS}'
        OFFSET 0
    ) e
    WHERE a.bwb_id = %(instrument)s
      AND (%(article)s::text IS NULL OR a.article_number = %(article)s)
    LIMIT %(n)s
) cited
"""


def _of_law(alias: str, article: bool) -> str:
    """SQL: the article *alias* is of the law followed (with *article*: is that one)."""
    one = f" AND {alias}.article_number = %(article)s" if article else ""
    return f"{alias}.bwb_id = %(instrument)s{one}"


def via(article: bool) -> str:
    """SQL: how the item ``pg`` is tied to the law followed (``followed_ctes``): its
    ``relation``, the ``article`` of the law it touches (the first in the order of the law)
    and the ``dossier`` it came through; the closest tie of all it has."""
    law_id = "(SELECT id FROM law)"
    to_law = "" if article else f" OR e.to_id = {law_id}"
    numbers = array_or_empty("n.props -> 'dossier_numbers'")
    labels = f"ARRAY(SELECT x.v #>> '{{}}' FROM json_array_elements({numbers}) AS x(v))"
    ties = f"""
            -- the publication that enacted the law
            SELECT 'establishes' AS relation, NULL::text AS article, NULL::text AS dossier,
                   0 AS rank, NULL::float8 AS position
            FROM law
            WHERE pg.kind = '{EVENT_PUBLICATION}' AND {"false" if article else "true"}
              AND law.enacted = {PUBLICATION_IDENTIFIER}
            UNION ALL
            -- a change of the law or an article of it: made, or proposed by a paper
            SELECT CASE WHEN pg.kind = '{EVENT_PUBLICATION}' THEN lower(e.relation)
                        ELSE 'proposes' END,
                   a.article_number, NULL, 1, a.position
            FROM {COLLECTION_EDGES} e
            LEFT JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
            WHERE pg.kind IN ({_kinds(EVENT_PUBLICATION, *DOCUMENT_EVENTS)})
              AND e.from_id = pg.id AND e.relation IN ({_CHANGES})
              AND (({_of_law("a", article)}){to_law})
            UNION ALL
            -- a version of the law, or of a regulation issued under it
            SELECT 'version_of', NULL, NULL, 1, NULL
            WHERE pg.kind = '{EVENT_COMMENCEMENT}' AND {_BWB} = %(instrument)s
            UNION ALL
            SELECT 'based_on', a.article_number, NULL, 2, a.position
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
            WHERE pg.kind = '{EVENT_COMMENCEMENT}' AND {_BWB} IS NOT NULL
              AND e.from_id = '{COLLECTION_INSTRUMENTS}/' || {bwb_key(_BWB)}
              AND e.relation = '{RELATION_BASED_ON}'
              AND e.to_collection = '{COLLECTION_ARTICLES}' AND {_of_law("a", article)}
            UNION ALL
            -- a judgment that cites it
            SELECT 'refers_to', a.article_number, NULL, 1, a.position
            FROM {COLLECTION_EDGES} e
            LEFT JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
            WHERE pg.kind = '{EVENT_JUDGMENT}'
              AND e.from_id = pg.id AND e.relation = '{RELATION_REFERS_TO}'
              AND (({_of_law("a", article)}){to_law})
            UNION ALL
            -- an event of a dossier of the law
            SELECT f.relation, NULL, f.label, CASE f.relation WHEN 'proposes' THEN 4 ELSE 3 END,
                   NULL
            FROM followed_dossiers f
            WHERE pg.kind IN ({_kinds(*DOCUMENT_EVENTS, EVENT_VOTE)})
              AND (f.label = pg.dossier OR f.label = ANY({labels}))
            UNION ALL
            SELECT f.relation, NULL, f.label, CASE f.relation WHEN 'proposes' THEN 4 ELSE 3 END,
                   NULL
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_DOSSIERS} d ON d.id = e.to_id
            JOIN followed_dossiers f ON f.label = d.label
            WHERE pg.kind = '{EVENT_COMMITMENT}'
              AND e.from_id = pg.id AND e.relation = '{RELATION_ABOUT}'
              AND e.to_collection = '{COLLECTION_DOSSIERS}'"""
    return f"""(
            SELECT json_build_object(
                'relation', t.relation, 'article', t.article, 'dossier', t.dossier)
            FROM ({ties}
            ) t
            ORDER BY t.rank, t.position NULLS LAST, t.article ASC NULLS LAST,
                     t.dossier ASC NULLS LAST
            LIMIT 1
        )"""
