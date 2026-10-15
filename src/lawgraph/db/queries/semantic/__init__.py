"""The reads and updates of the semantic phase, one module per source domain. ``slim_sql``
projects a node onto the props a step reads."""

from __future__ import annotations

from lawgraph.db.queries._json_sql import keep_props


def slim_sql(alias: str, *fields: str) -> str:
    """SQL for the document of the node row *alias* with only *fields* of its props, as one
    json value: ``{_key, type, labels, props}``, the shape of a document (what
    ``Node.from_document`` reads). The props are ``keep_props``: those the node has."""
    return (
        f"json_build_object('_key', {alias}.key, 'type', {alias}.type,"
        f" 'labels', to_json({alias}.labels), 'props', {keep_props(f'{alias}.props', *fields)})"
    )
