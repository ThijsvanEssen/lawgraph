"""``lg_amounts``: the numbers in the text of each ArticleVersion (``core.bwb_amounts``), kept
by ``semantic bwb-amounts``, and the numbers of an article with the versions they stand in."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import COLLECTION_ARTICLE_VERSIONS
from lawgraph.db.counting import Store
from lawgraph.db.queries.articles import version_identity
from lawgraph.db.schema import AMOUNTS_TABLE

_COLUMNS = (
    "version_id text, bwb_id text, span_start integer, span_end integer, part text, "
    "kind text, value numeric, unit text, date text, source text, valid_from text, "
    "cell smallint[]"
)
_NAMES = ", ".join(column.split()[0] for column in _COLUMNS.split(", "))
_EXCLUDED = ", ".join(f"EXCLUDED.{name}" for name in _NAMES.split(", "))
_KEPT = ", ".join(f"{AMOUNTS_TABLE}.{name}" for name in _NAMES.split(", "))


def version_texts(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{id, bwb_id, text, parts, tables, redactions}`` of the ArticleVersions of these
    regulations."""
    return store.query(
        f"""
        SELECT id, bwb_id, props ->> 'text' AS text, props -> 'parts' AS parts,
               props -> 'tables' AS tables, props -> 'redactions' AS redactions
        FROM {COLLECTION_ARTICLE_VERSIONS}
        WHERE bwb_id = ANY(%(ids)s::text[]) AND props ->> 'text' IS NOT NULL
        """,
        {"ids": bwb_ids},
        batch_size=200,
    )


def keep_amounts(store: Store, bwb_ids: list[str], rows: list[dict[str, Any]]) -> None:
    """The numbers of the versions of these regulations are *rows* (the columns of
    ``lg_amounts``), in one transaction: a row that holds them already is left, so a run
    that changes nothing leaves the data version; a row of these regulations not among
    them goes."""
    if not bwb_ids:
        return
    data = json.dumps(rows)
    store.execute_together(
        [
            (
                f"""
                DELETE FROM {AMOUNTS_TABLE} a
                WHERE a.bwb_id = ANY(%(ids)s::text[])
                  AND NOT EXISTS (
                      SELECT 1 FROM json_to_recordset(%(rows)s::json)
                           AS r(version_id text, span_start integer)
                      WHERE r.version_id = a.version_id AND r.span_start = a.span_start)
                """,
                {"ids": bwb_ids, "rows": data},
            ),
            (
                f"""
                INSERT INTO {AMOUNTS_TABLE} ({_NAMES})
                SELECT {_NAMES} FROM json_to_recordset(%(rows)s::json) AS r({_COLUMNS})
                ON CONFLICT (version_id, span_start) DO UPDATE SET ({_NAMES}) = ROW({_EXCLUDED})
                WHERE ({_KEPT}) IS DISTINCT FROM ({_EXCLUDED})
                """,
                {"rows": data},
            ),
        ]
    )


def article_amounts(
    store: Store, article: dict[str, Any], bwb_id: str, article_number: str
) -> list[dict[str, Any]]:
    """The versions of *article* (as its history finds them), oldest first, each a row per
    number it holds, or one row without a number (``kind`` null): ``{version_key,
    version_from, version_until, current, kind, value, unit, date, part, span_start,
    span_end, source, valid_from, cell, text}``, ``text`` the number as printed."""
    identity, bind = version_identity(article, bwb_id, article_number)
    return list(
        store.query(
            f"""
            SELECT v.key AS version_key, v.valid_from AS version_from,
                   v.valid_until AS version_until, v.current, a.kind, a.value, a.unit,
                   a.date, a.part, a.span_start, a.span_end, a.source, a.valid_from,
                   a.cell,
                   substr(v.props ->> 'text', a.span_start + 1, a.span_end - a.span_start)
                       AS text
            FROM {COLLECTION_ARTICLE_VERSIONS} v
            LEFT JOIN {AMOUNTS_TABLE} a ON a.version_id = v.id
            WHERE {identity}
            ORDER BY v.valid_from NULLS FIRST, v.key, a.span_start NULLS LAST
            """,
            bind,
        )
    )
