"""A light table is derived once: its trigger and the fill of ``semantic graph-light`` read
the same row from one SQL fragment, so the two cannot drift apart."""

from __future__ import annotations

from lawgraph.db import schema
from lawgraph.db.queries import faction_votes, instrument_names


def test_instrument_names_trigger_and_fill_share_the_row() -> None:
    assert schema.instrument_name_columns("c") in "\n".join(schema.instrument_names())
    assert schema.instrument_name_columns("i") in instrument_names._FILL


def test_faction_votes_triggers_and_fill_share_the_row() -> None:
    triggers = "\n".join(schema.faction_votes())
    assert schema.faction_vote_columns("c", "d") in triggers  # of the edges
    assert schema.faction_vote_columns("e", "c") in triggers  # of the decisions
    assert schema.faction_vote_columns("e", "d") in faction_votes._FILL
