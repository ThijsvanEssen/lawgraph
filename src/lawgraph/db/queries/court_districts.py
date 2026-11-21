"""The court map per municipality and year (``lg_court_districts``): written whole by
``normalize cbs`` from the CBS tables and the text of the Wet op de rechterlijke indeling."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from psycopg.types.json import Json

from lawgraph.db.counting import Store

_COLUMNS = (
    "year integer, municipality_code text, municipality text, province text,"
    " district text, district_code text, circuit text, circuit_code text,"
    " district_article text, circuit_article text, law_district text,"
    " district_check text, circuit_check text"
)


def write(store: Store, rows: list[dict[str, Any]]) -> None:
    """Replace every row, in one transaction."""
    store.execute_together(
        [
            ("DELETE FROM lg_court_districts", None),
            (
                "INSERT INTO lg_court_districts SELECT * FROM"
                f" json_to_recordset(%(rows)s::json) AS r({_COLUMNS})",
                {"rows": Json(rows, dumps=partial(json.dumps, ensure_ascii=False))},
            ),
        ]
    )


def article_texts(store: Store, bwb_id: str) -> dict[str, str]:
    """The text of each numbered article of the regulation *bwb_id*, by its number."""
    return {
        row["article_number"]: row["text"]
        for row in store.query(
            """
            SELECT article_number, props ->> 'text' AS text
            FROM articles
            WHERE bwb_id = %(bwb_id)s AND article_number IS NOT NULL
            """,
            {"bwb_id": bwb_id},
        )
        if row["text"]
    }
