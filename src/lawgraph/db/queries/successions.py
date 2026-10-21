"""The reads of old law to new law: the stored transposition tables (a PDF of their own, or
in the XML of a Kamerstuk or a Staatsblad), the stored HTML of the EU acts with a concordance table, and the
laws a table names with their articles (``semantic tk-transposition-tables``, ``lawgraph
succession-gaps``)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_EURLEX_CELEX,
    RAW_KIND_STAATSBLAD_TRANSPOSITION,
    RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
    RAW_KIND_TK_TRANSPOSITION_TABLE,
    RELATION_ESTABLISHES,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    SOURCE_EURLEX,
    SOURCE_STAATSBLAD,
    SOURCE_TK,
)
from lawgraph.core.transposition_xml import PLACEHOLDER_YEAR
from lawgraph.db._rows import raw_doc
from lawgraph.db.counting import Store
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries._json_sql import array_or_empty

# The laws whose articles a publication made in the dossier enacted (``ESTABLISHES``) or put
# in (``INTRODUCES``: Stb. 2026, 57 the Boeken 7 and 8 of the new Sv of Stb. 2026, 56): a law
# of the Staatsblad or of the BWB, with its citation title.
_LAWS_OF_DOSSIER = f"""
SELECT DISTINCT i.id, i.citation_title
FROM edges l
JOIN edges est ON est.from_id = l.from_id
  AND est.relation IN ('{RELATION_ESTABLISHES}', '{RELATION_INTRODUCES}')
JOIN edges p ON p.from_id = est.to_id AND p.relation = '{RELATION_PART_OF}'
  AND p.to_collection = '{COLLECTION_INSTRUMENTS}'
JOIN {COLLECTION_INSTRUMENTS} i ON i.id = p.to_id
WHERE l.to_id = %(dossier)s AND l.relation = '{RELATION_LEGISLATED_IN}'
ORDER BY i.id
"""

# The laws of the BWB of a citation title, as written in any case and with or without its
# spaces, hyphens and other marks ("Omgevings-wet", "Monumentenwet1988"): its folded title
# matches the pattern of the name (``name_pattern``).
_FOLDED = "regexp_replace(lower({}), '[^[:alnum:]]+', '', 'g')"
_BWB_LAWS_NAMED = f"""
SELECT id FROM {COLLECTION_INSTRUMENTS}
WHERE bwb_id IS NOT NULL AND stub IS DISTINCT FROM TRUE
  AND {_FOLDED.format("citation_title")} ~ %(pattern)s
ORDER BY id
"""

# The EU acts with a concordance table: an article of theirs says that references to the acts
# it repeals are read by it ("… worden gelezen volgens de concordantietabel in bijlage III").
_ACTS_WITH_CONCORDANCE = f"""
SELECT DISTINCT celex FROM {COLLECTION_ARTICLES}
WHERE celex IS NOT NULL
  AND strpos(lower(lg_str(props -> 'text')), 'concordantietabel') > 0
"""

# The EU acts of these CELEX numbers in the graph.
_EU_ACTS = f"""
SELECT celex, id FROM {COLLECTION_INSTRUMENTS}
WHERE celex = ANY(%(celex)s) AND stub IS DISTINCT FROM TRUE
"""

# The articles of a law that are no stub and have a number, in the order of the law, each
# with the numbers of its leden (``props.parts`` of kind ``lid``) and the labels of the
# divisions it stands in (``props.breadcrumb``, outermost first); then the historical
# identities of a law of the BWB when asked for (``normalize bwb-history``: an article no
# longer in its current toestand), repealed, by their last number.
_LAW_ARTICLES = f"""
SELECT id, number, repealed, leden, divisions, historical FROM (
    SELECT a.id, a.position, a.article_number AS number,
           coalesce(a.repealed, false) AS repealed,
           ARRAY(
               SELECT p ->> 'number'
               FROM json_array_elements({array_or_empty("a.props -> 'parts'")}) p
               WHERE p ->> 'kind' = 'lid' AND p ->> 'number' IS NOT NULL
           ) AS leden,
           ARRAY(
               SELECT c ->> 'label'
               FROM json_array_elements({array_or_empty("a.props -> 'breadcrumb'")}) c
               WHERE c ->> 'label' IS NOT NULL
           ) AS divisions,
           false AS historical
    FROM edges e
    JOIN {COLLECTION_ARTICLES} a ON a.id = e.from_id
    WHERE e.to_id = %(law)s AND e.relation = '{RELATION_PART_OF}'
      AND e.from_collection = '{COLLECTION_ARTICLES}'
      AND a.article_number IS NOT NULL AND a.stub IS DISTINCT FROM TRUE
    UNION ALL
    SELECT a.id, NULL, a.props ->> 'last_article_number', true, ARRAY[]::text[],
           ARRAY[]::text[], true
    FROM {COLLECTION_INSTRUMENTS} i
    JOIN {COLLECTION_ARTICLES} a ON a.bwb_id = i.bwb_id AND a.article_number IS NULL
    WHERE %(historical)s AND i.id = %(law)s
      AND a.props ->> 'last_article_number' IS NOT NULL
      AND a.stub IS DISTINCT FROM TRUE
) articles
ORDER BY historical NULLS LAST, position NULLS LAST, id
"""


def laws_of_dossier(store: Store, dossier_id: str) -> list[dict[str, Any]]:
    """``{id, citation_title}`` of each law a publication of the dossier enacted or put
    articles in."""
    return list(store.query(_LAWS_OF_DOSSIER, {"dossier": dossier_id}))


def bwb_laws_named(store: Store, name: str) -> list[str]:
    """The ids of the laws of the BWB whose citation title is *name* (``_FOLDED``,
    ``name_pattern``)."""
    pattern = f"^{name_pattern(name)}$"
    return [str(row) for row in store.query(_BWB_LAWS_NAMED, {"pattern": pattern})]


def folded(name: str) -> str:
    """*name* in lower case without its spaces, hyphens and other marks (``_FOLDED``)."""
    return "".join(c for c in name.lower() if c.isalnum())


def name_pattern(name: str) -> str:
    """The regular expression a folded citation title of *name* matches: its folded letters
    and figures, a year a proposed law's name leaves open (``Mediawet 20..``) any year of
    this century."""
    return "20[0-9]{2}".join(re.escape(folded(p)) for p in PLACEHOLDER_YEAR.split(name))


def law_articles(
    store: Store, law_id: str, *, historical: bool = False
) -> list[dict[str, Any]]:
    """``{id, number, repealed, leden, divisions, historical}`` of each numbered article of
    the law, then, with *historical*, of each historical identity of it."""
    return list(store.query(_LAW_ARTICLES, {"law": law_id, "historical": historical}))


def transposition_tables(store: Store) -> Iterator[dict[str, Any]]:
    """Every stored transposition table, and Kamerstuk and Staatsblad naming one, with its
    payload."""
    for source, kinds in (
        (
            SOURCE_TK,
            [RAW_KIND_TK_TRANSPOSITION_TABLE, RAW_KIND_TK_TRANSPOSITION_DOCUMENT],
        ),
        (SOURCE_STAATSBLAD, [RAW_KIND_STAATSBLAD_TRANSPOSITION]),
    ):
        rows = raw_queries.iter_raw_records(
            store, source=source, kinds=kinds, since_iso=None, batch_size=1
        )
        yield from store.with_payloads(rows)


def law_titles(store: Store, law_ids: list[str]) -> list[dict[str, Any]]:
    """``{id, citation_title, date_expired, date_in_force}`` of the laws *law_ids*."""
    return list(
        store.query(
            f"""
            SELECT id, citation_title, lg_str(props -> 'date_expired') AS date_expired,
                   lg_str(props -> 'date_in_force') AS date_in_force
            FROM {COLLECTION_INSTRUMENTS} WHERE id = ANY(%(ids)s)
            """,
            {"ids": law_ids},
        )
    )


def eu_acts_with_concordance(store: Store) -> Iterator[dict[str, Any]]:
    """The stored HTML of every EU act with a concordance table, by CELEX number, with its
    payload."""
    acts = sorted(str(celex) for celex in store.query(_ACTS_WITH_CONCORDANCE))
    rows = store.query(
        """
        SELECT key, doc FROM raw_sources
        WHERE source = %(source)s AND kind = %(kind)s AND external_id = ANY(%(acts)s)
        ORDER BY external_id
        """,
        {"source": SOURCE_EURLEX, "kind": RAW_KIND_EURLEX_CELEX, "acts": acts},
        batch_size=1,
    )
    return store.with_payloads(raw_doc(row) for row in rows)


def eu_acts(store: Store, celex: list[str]) -> dict[str, str]:
    """The id of the instrument of each EU act of *celex* the graph holds."""
    return {
        str(row["celex"]): str(row["id"])
        for row in store.query(_EU_ACTS, {"celex": celex})
    }


def laws_of_bwb_ids(store: Store, bwb_ids: list[str]) -> dict[str, str]:
    """The id of the law of each of *bwb_ids* the graph holds (no stub)."""
    return {
        str(row["bwb_id"]): str(row["id"])
        for row in store.query(
            f"""
            SELECT bwb_id, id FROM {COLLECTION_INSTRUMENTS}
            WHERE bwb_id = ANY(%(ids)s) AND stub IS DISTINCT FROM TRUE
            """,
            {"ids": bwb_ids},
        )
    }
