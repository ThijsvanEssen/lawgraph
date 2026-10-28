"""The place of a row in the order of a list (``db/queries/_keyset.py``): its token, and the
SQL of the rows after it."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db.queries._keyset import (
    InvalidCursor,
    Keyset,
    SortKey,
    page_of,
    with_condition,
)

ASC = Keyset("a", (SortKey("t", nulls_first=True), SortKey("k", not_null=True)))
DESC_NULLS_LAST = Keyset(
    "d", (SortKey("n", desc=True), SortKey("k", desc=True, not_null=True))
)
MIXED = Keyset(
    "m", (SortKey("d", desc=True, not_null=True), SortKey("k", not_null=True))
)


def test_a_token_gives_back_its_values_and_only_for_its_order() -> None:
    token = ASC.token(["Wet", "k1"])
    assert ASC.values(token) == ["Wet", "k1"]
    with pytest.raises(InvalidCursor):
        DESC_NULLS_LAST.values(token)
    with pytest.raises(InvalidCursor):
        ASC.values("###")
    with pytest.raises(InvalidCursor):
        ASC.values(ASC.token(["Wet", None]))


def test_keys_that_run_one_way_with_nulls_before_compare_as_rows() -> None:
    bind: dict[str, Any] = {}
    assert ASC.after(["Wet", "k1"], bind) == "(t, k) > (%(after0)s, %(after1)s)"
    assert bind == {"after0": "Wet", "after1": "k1"}


def test_a_null_in_the_cursor_is_walked_key_by_key() -> None:
    sql = ASC.after([None, "k1"], {})
    assert sql == "(t IS NOT NULL OR (t IS NULL AND k > %(after1)s))"


def test_nulls_last_are_after_every_value() -> None:
    sql = DESC_NULLS_LAST.after([3, "k"], {})
    assert "n IS NULL" in sql and "n < %(after0)s" in sql
    assert DESC_NULLS_LAST.after([None, "k"], {}).startswith("(FALSE OR (n IS NULL")


def test_mixed_directions_keep_the_first_key_as_a_bound_for_the_index() -> None:
    sql = MIXED.after(["2025-01-01", "k"], {})
    assert sql.startswith("d <= %(after0)s AND ")
    assert "d < %(after0)s" in sql and "k > %(after1)s" in sql


def test_the_order_is_written_out() -> None:
    assert ASC.order == "t ASC NULLS FIRST, k ASC NULLS LAST"
    assert DESC_NULLS_LAST.order == "n DESC NULLS LAST, k DESC NULLS LAST"


def test_a_page_reads_one_row_more_to_know_the_next() -> None:
    rows = [{"t": "a", "k": "1"}, {"t": "b", "k": "2"}, {"t": "c", "k": "3"}]

    def values(row: dict[str, str]) -> list[str]:
        return [row["t"], row["k"]]

    page, token = page_of(rows, 2, ASC, values)
    assert page == rows[:2] and ASC.values(token or "") == ["b", "2"]
    assert page_of(rows[:2], 2, ASC, values) == (rows[:2], None)


def test_a_condition_narrows_a_where_or_makes_one() -> None:
    assert with_condition("WHERE a", "b") == "WHERE a AND (b)"
    assert with_condition("", "b") == "WHERE b"
