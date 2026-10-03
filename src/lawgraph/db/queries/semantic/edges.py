"""The edge removals of the semantic phase: a step that derives the edges of a node in full
removes those it no longer derives."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from lawgraph.db.counting import Store


def remove_edges_of_source_except(
    store: Store, relation: str, source: str, keep: list[str]
) -> int:
    """Remove the edges of *relation* made by *source* whose key is not in *keep*: for edges
    one pipeline derives in full on every run. How many went."""
    rows = store.execute(
        """
        DELETE FROM edges e
        WHERE e.relation = %(relation)s AND e.source = %(source)s
          AND NOT EXISTS (SELECT 1 FROM unnest(%(keep)s::text[]) AS k WHERE k = e.key)
        RETURNING 1
        """,
        {"relation": relation, "source": source, "keep": keep},
    )
    return len(rows)


# The edges of a node that *keep* (``{node id: [edge key, ...]}``, as jsonb) does not name.
_NOT_KEPT = "NOT coalesce((%(keep)s::jsonb -> e.{end}) ? e.key, false)"


def remove_edges_from(
    store: Store,
    relation: str,
    source: str,
    from_ids: list[str],
    keep: dict[str, set[str]],
    *,
    chunk: int = 5000,
) -> int:
    """Remove the edges of *relation* made by *source* from any of *from_ids* whose key is
    not in *keep* (per node id): a pipeline that derives the edges of a node in full removes
    those it no longer derives. How many went."""
    statement = f"""
        DELETE FROM edges e
        WHERE e.from_id = ANY(%(ids)s::text[])
          AND e.relation = %(relation)s AND e.source = %(source)s
          AND {_NOT_KEPT.format(end="from_id")}
        RETURNING 1
    """
    removed = 0
    for start in range(0, len(from_ids), chunk):
        ids = from_ids[start : start + chunk]
        removed += len(
            store.execute(
                statement,
                {
                    "ids": ids,
                    "relation": relation,
                    "source": source,
                    "keep": Jsonb({i: sorted(keep[i]) for i in ids if i in keep}),
                },
            )
        )
    return removed


def remove_edges_to(
    store: Store,
    relations: list[str],
    source: str,
    to_ids: list[str],
    keep: dict[str, set[str]],
    *,
    chunk: int = 5000,
) -> int:
    """Remove the edges of *relations* made by *source* into any of *to_ids* whose key is
    not in *keep* (per node id): the counterpart of ``remove_edges_from`` for a pipeline that
    derives the edges into a node in full. How many went."""
    statement = f"""
        DELETE FROM edges e
        WHERE e.to_id = ANY(%(ids)s::text[])
          AND e.relation = ANY(%(relations)s::text[]) AND e.source = %(source)s
          AND {_NOT_KEPT.format(end="to_id")}
        RETURNING 1
    """
    removed = 0
    for start in range(0, len(to_ids), chunk):
        ids = to_ids[start : start + chunk]
        removed += len(
            store.execute(
                statement,
                {
                    "ids": ids,
                    "relations": relations,
                    "source": source,
                    "keep": Jsonb({i: sorted(keep[i]) for i in ids if i in keep}),
                },
            )
        )
    return removed
