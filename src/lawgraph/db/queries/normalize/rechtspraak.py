"""The graph reads and updates of the normalize phase for Rechtspraak: the translated
judgments and the props set on them in place."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries._aql import sorted_merge


def translated_judgments(
    store: Store, rows: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """The judgment each translation of *rows* translates: ``{key, original: {key, ecli,
    summary}}`` for every row (``{key, court_code, date, case_key}``) whose court gave, on
    that day and under that case number, a judgment with a Dutch summary."""
    aql = f"""
    FOR row IN @rows
        LET original = FIRST(
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER row.case_key IN j.props.case_number_keys[*]
                FILTER j.props.court_code == row.court_code
                FILTER j.props.date_eff == row.date
                FILTER j._key != row.key AND j.props.summary != null
                SORT j._key
                LIMIT 1
                RETURN {{key: j._key, ecli: j.props.ecli, summary: j.props.summary}}
        )
        FILTER original != null
        RETURN {{key: row.key, original: original}}
    """
    return store.query(aql, {"rows": rows})


def update_judgment_props(store: Store, rows: list[dict[str, Any]]) -> int:
    """Merge ``props`` into the judgment ``key`` of each of *rows*; how many changed."""
    aql = f"""
    FOR row IN @rows
        FOR j IN {COLLECTION_JUDGMENTS}
            FILTER j._key == row.key
            FILTER NOT MATCHES(j.props, row.props)
            UPDATE j WITH {{ props: {sorted_merge("j.props", "row.props")} }}
                IN {COLLECTION_JUDGMENTS} OPTIONS {{ mergeObjects: false }}
            RETURN 1
    """
    return sum(store.query(aql, {"rows": rows}))
