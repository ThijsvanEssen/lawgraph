"""SQL string literals built from values of the code (``db/_sql.py``)."""

from __future__ import annotations

from lawgraph.db._sql import sql_text_array, sql_text_list


def test_sql_text_list_quotes_each_value() -> None:
    assert sql_text_list(("a", "b c")) == "'a', 'b c'"
    assert sql_text_list([]) == ""


def test_a_quote_in_a_value_is_doubled() -> None:
    assert sql_text_list(["d'Hondt"]) == "'d''Hondt'"


def test_sql_text_array() -> None:
    assert sql_text_array(("x", "y")) == "ARRAY['x', 'y']::text[]"
