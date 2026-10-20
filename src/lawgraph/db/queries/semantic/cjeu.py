"""The reads of the semantic phase for the judgments of the courts of the Union."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import SOURCE_CJEU
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import slim_sql


def cjeu_judgments(store: Store, *, batch_size: int) -> Iterator[dict[str, Any]]:
    """``{key, type, labels, props: {ecli, paragraphs, meta}}`` of every judgment of a court
    of the Union, in key order."""
    return store.query(
        f"""
        SELECT {slim_sql("j", "ecli", "paragraphs", "meta")}
        FROM judgments j
        WHERE j.source = %(source)s
        ORDER BY j.key
        """,
        {"source": SOURCE_CJEU},
        batch_size=batch_size,
    )
