"""The reads and updates of the semantic phase, one module per source domain. ``slim_sql``
projects a node onto the props a step reads; the other helpers are the SQL of AQL's
comparisons of a json value with null and of ``LENGTH(x) > 0``."""

from __future__ import annotations


def slim_sql(alias: str, *fields: str) -> str:
    """SQL for the document of the node row *alias* with only *fields* of its props, as one
    json value: ``{_key, type, labels, props}``, the shape of a document.

    ``KEEP`` returned the props it kept in the byte order of their names (probe P1), a prop
    the node does not have left out and one set to null kept; so does this.
    """
    names = ", ".join(f"'{field}'" for field in fields)
    return (
        f"json_build_object('_key', {alias}.key, 'type', {alias}.type,"
        f" 'labels', to_json({alias}.labels), 'props', ("
        f"SELECT coalesce(json_object_agg(kept.name, kept.value"
        f" ORDER BY kept.name COLLATE \"C\"), '{{}}')"
        f" FROM json_each({alias}.props) AS kept(name, value)"
        f" WHERE kept.name IN ({names})))"
    )


def nonempty_sql(value: str) -> str:
    """SQL for ``LENGTH(value) > 0`` of the json *value*: an array or object with an element,
    a string with a character, any number, ``true``; null, a missing value and ``false``
    have length 0."""
    return (
        f"CASE json_typeof({value})"
        f" WHEN 'array' THEN json_array_length({value}) > 0"
        f" WHEN 'object' THEN EXISTS (SELECT 1 FROM json_object_keys({value}))"
        f" WHEN 'string' THEN {value} #>> '{{}}' <> ''"
        f" WHEN 'number' THEN true"
        f" WHEN 'boolean' THEN {value} #>> '{{}}' = 'true'"
        f" ELSE false END"
    )


def present_sql(value: str) -> str:
    """SQL for ``value != null`` of the json *value*: there and not null (a missing prop is
    SQL NULL, a prop set to null the json ``null``)."""
    return f"json_typeof({value}) <> 'null'"


def absent_sql(value: str) -> str:
    """SQL for ``value == null`` of the json *value*: missing or null."""
    return f"coalesce(json_typeof({value}), 'null') = 'null'"


def differs_sql(stored: str, wanted: str) -> str:
    """SQL for ``stored != wanted`` of two json values: compared by value (``1`` equals
    ``1.0``, arrays and objects element by element), a missing value null."""
    return (
        f"coalesce(({stored})::jsonb, 'null')"
        f" IS DISTINCT FROM coalesce(({wanted})::jsonb, 'null')"
    )
