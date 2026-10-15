"""SQL text built from values of the code: string literals, quoted as SQL quotes them."""

from __future__ import annotations

from collections.abc import Iterable


def sql_text_list(values: Iterable[str]) -> str:
    """*values* as SQL string literals, one after the other: ``'a', 'b'``; a quote in one is
    doubled."""
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def sql_text_array(values: Iterable[str]) -> str:
    """*values* as a ``text[]``: ``ARRAY['a', 'b']::text[]``."""
    return f"ARRAY[{sql_text_list(values)}]::text[]"
