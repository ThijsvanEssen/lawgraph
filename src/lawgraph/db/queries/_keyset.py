"""Keyset pages of a list: the page after the last row of the one before, found by its place in
the order of the list (the values of its sort keys, the last a unique key), not by skipping
rows: a page deep in the list costs what the first does, and no row is on two pages or on
none when rows are written between two requests.

A list names its order as ``SortKey`` s (``Keyset``); a request passes the ``after`` token of
the page before (``Keyset.values``), the SQL of the rows after it is ``Keyset.after``, and
the token for the page behind is ``Keyset.token`` of the sort values of its last row."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


class InvalidCursor(ValueError):
    """A token this API did not hand out for this order."""


@dataclass(frozen=True)
class SortKey:
    """One key of an order: the SQL of its value, its direction, where its nulls sort, and
    whether it has none (``not_null``: a filter keeps them out, or the column is set)."""

    sql: str
    desc: bool = False
    nulls_first: bool = False
    not_null: bool = False

    @property
    def order(self) -> str:
        direction = "DESC" if self.desc else "ASC"
        return f"{self.sql} {direction} NULLS {'FIRST' if self.nulls_first else 'LAST'}"

    def ahead(self, param: str, value: Any) -> str:
        """SQL: the rows that sort after *value* by this key alone."""
        op = "<" if self.desc else ">"
        if value is None:
            return "FALSE" if not self.nulls_first else f"{self.sql} IS NOT NULL"
        if self.nulls_first or self.not_null:
            return f"{self.sql} {op} {param}"
        return f"({self.sql} {op} {param} OR {self.sql} IS NULL)"

    def same(self, param: str, value: Any) -> str:
        """SQL: the rows that hold *value* in this key."""
        return f"{self.sql} IS NULL" if value is None else f"{self.sql} = {param}"


@dataclass(frozen=True)
class Keyset:
    """The order of a list: *name* tells its tokens from those of another order, *keys* the
    sort keys, the last unique."""

    name: str
    keys: tuple[SortKey, ...]

    @property
    def order(self) -> str:
        """SQL: the ``ORDER BY`` of the list."""
        return ", ".join(key.order for key in self.keys)

    @property
    def columns(self) -> str:
        """SQL: the sort keys as columns, to read the token of a row (``ks0``, ``ks1``…)."""
        return ", ".join(f"{key.sql} AS ks{n}" for n, key in enumerate(self.keys))

    def token(self, values: Sequence[Any]) -> str:
        """The opaque token of the page that ends at the row with sort *values*."""
        raw = json.dumps([self.name, *values], separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    def values(self, token: str) -> list[Any]:
        """The sort values of a token of this order; ``InvalidCursor`` for another."""
        try:
            padded = token + "=" * (-len(token) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode()))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidCursor(f"not a cursor: {token!r}") from exc
        if (
            not isinstance(value, list)
            or len(value) != len(self.keys) + 1
            or value[0] != self.name
            or value[-1] is None
        ):
            raise InvalidCursor(f"not a cursor of this order: {token!r}")
        return value[1:]

    def after(self, values: Sequence[Any], bind: dict[str, Any]) -> str:
        """SQL: the rows after the row with sort *values* (put in *bind*). Where every key
        runs the same way, none is null and the nulls come before, one comparison of rows
        that an index in the order serves; else the keys one by one, the first also as a
        bound of its own for the index."""
        params = [f"%(after{n})s" for n in range(len(values))]
        bind.update({f"after{n}": value for n, value in enumerate(values)})
        first = self.keys[0]
        directions = {key.desc for key in self.keys}
        if (
            len(directions) == 1
            and None not in values
            and all(key.nulls_first or key.not_null for key in self.keys)
        ):
            op = "<" if first.desc else ">"
            columns = ", ".join(key.sql for key in self.keys)
            return f"({columns}) {op} ({', '.join(params)})"
        condition = self.keys[-1].ahead(params[-1], values[-1])
        for key, param, value in reversed(
            list(zip(self.keys, params, values, strict=True))[:-1]
        ):
            condition = (
                f"({key.ahead(param, value)} OR "
                f"({key.same(param, value)} AND {condition}))"
            )
        if first.not_null and values[0] is not None:
            bound = "<=" if first.desc else ">="
            return f"{first.sql} {bound} {params[0]} AND {condition}"
        return condition


def with_condition(where: str, condition: str) -> str:
    """SQL: the ``WHERE`` clause *where* (possibly empty) narrowed by *condition*."""
    return f"{where} AND ({condition})" if where else f"WHERE {condition}"


def page_of[R](
    rows: Sequence[R],
    limit: int,
    keyset: Keyset,
    values_of: Callable[[R], Sequence[Any]],
) -> tuple[list[R], str | None]:
    """The page of *limit* rows out of *rows* (read one more than that) and the token of
    the page behind it: None when *rows* has no row more."""
    page = list(rows[:limit])
    if len(rows) <= limit:
        return page, None
    return page, keyset.token(values_of(page[-1]))
