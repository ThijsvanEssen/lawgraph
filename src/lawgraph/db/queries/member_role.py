"""Whether a member has a role, in SQL: ``core.member_role.has_role`` on the props of a row of
``members`` (a seat in a faction, a post in a cabinet, a seat or period in the Eerste Kamer).

An expression on ``props`` (the table of members is small, and its props hold no text); a
column of its own when the database is built again.
"""

from __future__ import annotations

from lawgraph.core.member_role import ROLE_LISTS

_LIST = (
    "CASE json_typeof({alias}.props -> '{field}')"
    " WHEN 'array' THEN json_array_length({alias}.props -> '{field}') ELSE 0 END > 0"
)


def has_role(alias: str) -> str:
    """The boolean expression of whether the member row *alias* has a role."""
    lists = [_LIST.format(alias=alias, field=field) for field in ROLE_LISTS]
    ek = f"coalesce(json_typeof({alias}.props -> 'ek'), 'null') = 'object'"
    return "(" + " OR ".join([*lists, ek]) + ")"
