"""SQL text the schema and the queries share: values of the code as string literals, quoted
as SQL quotes them, and the expressions of an index that its queries write alike (or the
planner does not take the index)."""

from __future__ import annotations

from collections.abc import Iterable


def sql_text_list(values: Iterable[str]) -> str:
    """*values* as SQL string literals, one after the other: ``'a', 'b'``; a quote in one is
    doubled."""
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def sql_text_array(values: Iterable[str]) -> str:
    """*values* as a ``text[]``: ``ARRAY['a', 'b']::text[]``."""
    return f"ARRAY[{sql_text_list(values)}]::text[]"


def instrument_dossier_numbers(alias: str = "") -> str:
    """The dossier numbers of an instrument (a publication's; of the row *alias*), as text:
    the expression of the index ``instruments_dossier_numbers``."""
    p = f"{alias}." if alias else ""
    return f"public.lg_text_array({p}props -> 'dossier_numbers')"


# The title an instrument sorts by in the list (``INSTRUMENT_ORDERS``): the one it shows (its
# citation title, else title, display name or key), without the marks it may start with.
INSTRUMENT_SORT_TITLE = (
    "regexp_replace(coalesce(citation_title, public.lg_str(props -> 'title'),"
    " public.lg_str(props -> 'display_name'), key), '^[^[:alnum:]]+', '')"
)


def member_name_sql(p: str) -> str:
    """SQL: the name a member goes by, of the props *p* (``core.member_slugs.member_name``)."""
    kamer = f"lg_truthy({p} -> 'name') AND lg_truthy({p} -> 'family_name')"
    known, name = f"lg_truthy({p} -> 'known_as')", f"lg_truthy({p} -> 'name')"
    whens = f"WHEN {kamer} THEN {p} ->> 'name' WHEN {known} THEN {p} ->> 'known_as'"
    return f"CASE {whens} WHEN {name} THEN {p} ->> 'name' ELSE {p} ->> 'government_name' END"
