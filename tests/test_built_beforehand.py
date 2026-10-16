"""``lawgraph built-beforehand``: the SQL of every index of ``schema.BUILT_BEFOREHAND``."""

from __future__ import annotations

from lawgraph.db.schema import BUILT_BEFOREHAND, built_beforehand_sql, statements


def test_every_index_built_beforehand_is_one_the_schema_creates() -> None:
    schema = "\n".join(statements())
    assert BUILT_BEFOREHAND
    assert all(index.statement in schema for index in BUILT_BEFOREHAND)


def test_the_sql_builds_each_concurrently_checks_it_and_analyzes_an_expression() -> (
    None
):
    lines = built_beforehand_sql()
    for index in BUILT_BEFOREHAND:
        (built,) = [line for line in lines if f" EXISTS {index.name} ON " in line]
        assert built.startswith(
            (
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ",
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ",
            )
        )
        assert built.endswith(";") and "\n" not in built
        assert f"'{index.name}'" in lines[len(BUILT_BEFOREHAND)]
    analyzed = [line for line in lines if line.startswith("ANALYZE ")]
    expressions = {i.table for i in BUILT_BEFOREHAND if i.on_expression}
    assert analyzed == [
        f"ANALYZE {table};"
        for table in dict.fromkeys(i.table for i in BUILT_BEFOREHAND if i.on_expression)
    ]
    assert {"cases", "activities", "documents"} <= expressions
    assert "edges" not in expressions  # columns only: no statistics of its own
