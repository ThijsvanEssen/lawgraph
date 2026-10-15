"""SQL fragments over json values, each the one spelling of what it tests or gives.

A value is an SQL expression of type ``json``. A prop the node does not have is SQL NULL, a
prop set to null the json ``null``; the tests here treat both as null and never give SQL
NULL themselves, so they hold under ``NOT`` and in a column as in a ``WHERE``.
"""

from __future__ import annotations

# The json text of an empty array.
EMPTY_ARRAY = "'[]'::json"


def is_present(value: str) -> str:
    """*value* is there and not null."""
    return f"coalesce(json_typeof({value}), 'null') <> 'null'"


def is_absent(value: str) -> str:
    """*value* is missing or null."""
    return f"coalesce(json_typeof({value}), 'null') = 'null'"


def first_present(*values: str) -> str:
    """The first of *values* that is present (``is_present``); SQL NULL when none is."""
    cases = " ".join(f"WHEN {is_present(v)} THEN {v}" for v in values)
    return f"(CASE {cases} END)"


def truthy_or(*values: str) -> str:
    """The first of *values* that is true (``lg_truthy``: not missing, null, false, 0 or
    ""; an array or object, even empty, is), else the last."""
    whens = " ".join(f"WHEN lg_truthy({v}) THEN {v}" for v in values[:-1])
    return f"CASE {whens} ELSE {values[-1]} END"


def array_or_empty(value: str) -> str:
    """*value* when it is an array, else an empty one: what a walk over it reads."""
    return (
        f"CASE WHEN json_typeof({value}) = 'array' THEN {value} ELSE {EMPTY_ARRAY} END"
    )


def has_length(value: str) -> str:
    """*value* has a length above 0: an array or object with an element, a string with a
    character, any number, ``true``; null, missing and ``false`` have none."""
    return (
        f"CASE json_typeof({value})"
        f" WHEN 'array' THEN json_array_length({value}) > 0"
        f" WHEN 'object' THEN EXISTS (SELECT 1 FROM json_each({value}))"
        " WHEN 'number' THEN true"
        f" ELSE lg_truthy({value}) END"
    )


def json_length(value: str) -> str:
    """The length of *value*: of an array, string or object its size, of a number the
    length of its text, of ``true`` 1; of null, missing and ``false`` 0."""
    text = f"({value} #>> '{{}}')"
    return f"""CASE json_typeof({value})
        WHEN 'array' THEN json_array_length({value})
        WHEN 'string' THEN char_length{text}
        WHEN 'number' THEN char_length{text}
        WHEN 'object' THEN (SELECT count(*) FROM json_each({value}))::int
        WHEN 'boolean' THEN CASE WHEN {text}::boolean THEN 1 ELSE 0 END
        ELSE 0 END"""


def as_text(value: str) -> str:
    """*value* as text: a string as it is, a number or a boolean as written, null and
    missing ``''``."""
    return f"coalesce(({value}) #>> '{{}}', '')"


def keep_props(props: str, *fields: str) -> str:
    """The json object *props* with only *fields*: those it has (one set to null too), in
    its order; ``{}`` when it has none of them."""
    names = ", ".join(f"'{field}'" for field in fields)
    return f"""coalesce((
        SELECT json_object_agg(k, v)
        FROM json_each({props}) AS kept(k, v)
        WHERE k IN ({names})
    ), '{{}}'::json)"""


def differs(stored: str, wanted: str) -> str:
    """Two json values differ by value (``1`` equals ``1.0``, arrays and objects element by
    element), a missing value null."""
    return (
        f"coalesce(({stored})::jsonb, 'null')"
        f" IS DISTINCT FROM coalesce(({wanted})::jsonb, 'null')"
    )


def period_day(value: str) -> str:
    """The day of the json string *value* (its first ten characters, a timestamp read as its
    day); SQL NULL when it is missing, null, not a string or empty."""
    return f"nullif(left(lg_str({value}), 10), '')"


def period_holds(start: str, end: str, day: str) -> str:
    """The period from the json *start* to the json *end* (both inclusive, ``period_day``;
    no end: still going on) holds on *day* (text, ``YYYY-MM-DD``); a period without a start
    holds no day. The rule of ``lawgraph.core.time.covers``."""
    return (
        f"coalesce({period_day(start)} <= {day}"
        f" AND ({period_day(end)} IS NULL OR {period_day(end)} >= {day}), false)"
    )


def period_overlaps(start: str, end: str, first: str, last: str) -> str:
    """The period from the json *start* to the json *end* (inclusive; no start: from the
    first day, no end: still going on) overlaps the one from *first* to *last* (text,
    inclusive; NULL: open on that side)."""
    return (
        f"({last}::text IS NULL OR coalesce(lg_str({start}), '') <= {last})"
        f" AND ({first}::text IS NULL OR {is_absent(end)}"
        f" OR lg_str({end}) >= {first})"
    )
