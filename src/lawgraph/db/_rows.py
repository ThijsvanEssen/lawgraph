"""Rows as the documents the code reads: the shape ArangoDB gave them.

The query functions return dicts with ``_id``, ``_key``, ``_from`` and ``_to`` as before, so
nothing outside ``db/`` changes with the database. These build them from the rows of the
tables (``schema.py``).
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_EDGES, COLLECTION_RAW_SOURCES

# The props the graph views (``/api/nodes``, its neighbourhood, ``/api/paths``) leave out of
# every node, the node itself too: its text and its raw payloads, which the detail routes
# (``/api/judgments/{ecli}``, ``/api/articles/...``) give.
GRAPH_PROPS_LEFT_OUT = (
    "text",
    "paragraphs",
    "parties",
    "subjects",
    "judgment_metadata",
    "raw_data",
    "raw",  # documents carry the source TK payload here
    "entries",  # annexes carry their table rows here
    "unresolved_citations",
)

# And a neighbour, a node of a neighbourhood or of a path: the text of a paper (its sections
# and footnotes, hundreds of kB) and the structure of an article (its parts, references and
# breadcrumb: three quarters of what the articles of a law weigh). A neighbour is light; its
# text belongs to the node itself (``/api/nodes/{collection}/{key}``, the readers).
NEIGHBOUR_PROPS_LEFT_OUT = (
    *GRAPH_PROPS_LEFT_OUT,
    "sections",
    "footnotes",
    "parts",
    "references",
    "breadcrumb",
)


def light_props(alias: str) -> str:
    """SQL: the props of the row *alias* of the view ``nodes`` without
    ``NEIGHBOUR_PROPS_LEFT_OUT``, the others in their order; of a judgment those kept in
    ``lg_judgment_light`` (``schema.JUDGMENT_LIGHT_PROPS``), which do not read its props and
    their text, while it has them."""
    keys = ", ".join(f"'{key}'" for key in NEIGHBOUR_PROPS_LEFT_OUT)
    unset = f"lg_unset({alias}.props, ARRAY[{keys}])"
    kept = f"(SELECT l.props FROM lg_judgment_light l WHERE l.id = {alias}.id)"
    return (
        f"(CASE WHEN {alias}.collection = 'judgments'"
        f" THEN coalesce({kept}, {unset}) ELSE {unset} END)"
    )


def node_doc(row: dict[str, Any]) -> dict[str, Any]:
    """A node row (``id``, ``key``, ``type``, ``labels``, ``props``) as its document."""
    return {
        "_key": row["key"],
        "_id": row["id"],
        "type": row["type"],
        "labels": list(row["labels"] or []),
        "props": row["props"] if row["props"] is not None else {},
    }


def edge_doc(row: dict[str, Any]) -> dict[str, Any]:
    """An edge row (``key``, ``from_id``, ``to_id``, ``doc``) as its document."""
    return {
        "_key": row["key"],
        "_id": f"{COLLECTION_EDGES}/{row['key']}",
        "_from": row["from_id"],
        "_to": row["to_id"],
        **(row["doc"] or {}),
    }


def raw_doc(row: dict[str, Any]) -> dict[str, Any]:
    """A raw_sources row (``key``, ``doc``) as its document."""
    return {
        "_key": row["key"],
        "_id": f"{COLLECTION_RAW_SOURCES}/{row['key']}",
        **row["doc"],
    }


def split_node(doc: dict[str, Any], collection: str) -> dict[str, Any]:
    """The columns of a node document to write."""
    return {
        "id": f"{collection}/{doc['_key']}",
        "type": doc.get("type", ""),
        "labels": list(doc.get("labels") or []),
        "props": doc.get("props") or {},
    }


def split_edge(doc: dict[str, Any]) -> dict[str, Any]:
    """The columns of an edge document to write: the rest goes into ``doc``, in its order."""
    rest = {k: v for k, v in doc.items() if k not in ("_key", "_id", "_from", "_to")}
    return {
        "key": doc["_key"],
        "from_id": doc["_from"],
        "to_id": doc["_to"],
        "doc": rest,
    }
