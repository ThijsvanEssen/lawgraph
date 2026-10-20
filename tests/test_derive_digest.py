"""The digest of the derivation of a table (``schema.derive_digest``): its trigger and every
``lg_`` function the trigger calls, through the functions those call."""

from __future__ import annotations

import pytest

from lawgraph.db import schema


def test_a_changed_expression_changes_the_digest_of_its_table(monkeypatch) -> None:
    before = {c: schema.derive_digest(c) for c in schema.derived_collections()}
    columns = schema.COLUMNS["dossiers"]
    changed = (*columns[:1], schema.Column("label", "text", "lg_str(props -> 'title')"))
    monkeypatch.setitem(schema.COLUMNS, "dossiers", (*changed, *columns[2:]))
    after = {c: schema.derive_digest(c) for c in schema.derived_collections()}
    assert [c for c in after if after[c] != before[c]] == ["dossiers"]


def test_a_changed_function_changes_the_digest_of_the_tables_that_call_it(
    monkeypatch,
) -> None:
    """``lg_member_names`` is called by the search column of members alone; ``lg_join``,
    which it calls, by the search columns of many tables."""
    before = {c: schema.derive_digest(c) for c in schema.derived_collections()}

    def changed(old: str, new: str) -> set[str]:
        assert old in schema.SEARCH_FUNCTIONS
        with monkeypatch.context() as m:
            m.setattr(
                schema, "SEARCH_FUNCTIONS", schema.SEARCH_FUNCTIONS.replace(old, new)
            )
            after = {c: schema.derive_digest(c) for c in schema.derived_collections()}
        return {c for c in after if after[c] != before[c]}

    assert changed("coalesce(props ->> 'party', '')", "''") == {"members"}
    assert changed("array_to_string(vs, chr(31))", "array_to_string(vs, ' ')") >= {
        "members",
        "factions",
        "dossiers",
    }


@pytest.mark.parametrize("collection", ["judgments", "members", "documents"])
def test_a_digest_is_short_and_of_its_own_table(collection: str) -> None:
    assert len(schema.derive_digest(collection)) == 16
    assert schema.derive_digest(collection) != schema.derive_digest("dossiers")


def test_a_comment_is_no_change(monkeypatch) -> None:
    before = schema.derive_digest("members")
    monkeypatch.setattr(
        schema, "SEARCH_FUNCTIONS", schema.SEARCH_FUNCTIONS.replace("-- The", "-- the")
    )
    assert schema.derive_digest("members") == before
