"""Pipelines, commands and the API call a function of ``db/queries/`` and do not touch the
driver handle. (That SQL is written in ``db/`` only: ``test_sql_conventions``.)
"""

from __future__ import annotations

import pathlib

import pytest

from tests.paths import SRC
from tests.source_scan import DRIVER_CALL, sql_in


def test_the_scans_tell_a_query_from_prose() -> None:
    """The guards are only worth having if they match queries and nothing else."""
    assert sql_in('A = f"SELECT id FROM {TABLE} WHERE key = %(key)s"')
    assert sql_in('A = """\n  UPDATE nodes SET props = %(props)s WHERE id = %(id)s"""')
    assert sql_in('A = "WITH x AS (SELECT 1) SELECT * FROM x"')
    assert not sql_in('"""Select the rows from the list, then return the key."""')
    assert not sql_in('A = "select a court from the list"')
    assert not sql_in('A = "SELECT ?x WHERE { ?x a ?type } PREFIX"')
    assert DRIVER_CALL.search("rows = self.store.query(sql, params)")
    assert DRIVER_CALL.search("store.execute(statement)")
    assert DRIVER_CALL.search("import psycopg")
    assert not DRIVER_CALL.search("raw_queries.iter_raw_records(self.store, source=s)")
    assert not DRIVER_CALL.search("self.store.bulk_insert_or_update_nodes(nodes)")


@pytest.mark.parametrize(
    "path",
    [
        p
        for top in ("pipelines", "commands", "api")
        for p in sorted((SRC / top).rglob("*.py"))
    ],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_pipelines_commands_and_api_do_not_use_the_driver(path: pathlib.Path) -> None:
    calls = [
        number
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if DRIVER_CALL.search(line)
    ]
    assert not calls, (
        f"{path.relative_to(SRC)}:{calls} queries the database itself; the queries and "
        f"the driver live in db/."
    )
