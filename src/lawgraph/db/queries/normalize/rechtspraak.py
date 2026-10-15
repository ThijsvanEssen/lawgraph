"""The graph reads and updates of the normalize phase for Rechtspraak: the translated
judgments and the props set on them in place."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg.types.json import Json

from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.core.models import require_named_props
from lawgraph.db.counting import Store
from lawgraph.db.queries._json_sql import is_absent, is_present


def _same(column: str, row_value: str, props_value: str) -> str:
    """SQL for ``j.props.x == row.x``: the string column equals the row's value, or both
    are null or missing."""
    return f"""({column} = lg_str({row_value})
        OR ({is_absent(row_value)} AND {is_absent(props_value)}))"""


def translated_judgments(
    store: Store, rows: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """The judgment each translation of *rows* translates: ``{key, original: {key, ecli,
    summary}}`` for every row (``{key, court_code, date, case_key}``) whose court gave, on
    that day and under that case number, a judgment with a Dutch summary (the first by
    key); in the order of *rows*. A court code or date of None is a judgment without
    one."""
    sql = f"""
        SELECT json_build_object(
            'key', r.row -> 'key',
            'original', json_build_object(
                'key', o.key, 'ecli', o.props -> 'ecli', 'summary', o.props -> 'summary'
            )
        )
        FROM json_array_elements(%(rows)s::json) WITH ORDINALITY AS r(row, n)
        CROSS JOIN LATERAL (
            SELECT j.key, j.props FROM judgments j
            WHERE j.case_number_keys @> ARRAY[lg_str(r.row -> 'case_key')]
              AND {_same("j.court_code", "r.row -> 'court_code'", "j.props -> 'court_code'")}
              AND {_same("j.date_eff", "r.row -> 'date'", "j.props -> 'date_eff'")}
              AND j.key IS DISTINCT FROM lg_str(r.row -> 'key')
              AND {is_present("j.props -> 'summary'")}
            ORDER BY j.key
            LIMIT 1
        ) o
        ORDER BY r.n
        """
    return store.query(sql, {"rows": Json(rows)})


def update_judgment_props(store: Store, rows: list[dict[str, Any]]) -> int:
    """Merge ``props`` into the judgment ``key`` of each of *rows*, its props keys in
    order (``lg_update``), where one of them differs (a None for a missing key does
    not); how many changed. A key that occurs twice is written twice, in the order of
    *rows*. ``ValueError`` for a prop the judgment schema does not name."""
    require_named_props(
        COLLECTION_JUDGMENTS, {key for row in rows for key in row["props"]}
    )
    sql = """
        UPDATE judgments j SET props = lg_update(j.props, r.row -> 'props')
        FROM json_array_elements(%(rows)s::json) AS r(row)
        WHERE j.key = r.row ->> 'key'
          AND EXISTS (
              SELECT 1 FROM json_each(r.row -> 'props') AS p(k, v)
              WHERE coalesce((j.props -> p.k)::jsonb, 'null') IS DISTINCT FROM p.v::jsonb
          )
        RETURNING 1
        """
    return len(store.execute_in_rounds(sql, rows, "key"))
