"""The names of an instrument without its props, on a real PostgreSQL: ``lg_instrument_names``
kept by the triggers on every write of ``instruments``, filled by ``semantic graph-light`` for
the instruments written before them, and read by ``load_law_names`` (the laws a dossier title
names) instead of the props of every instrument."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries import dossiers, instrument_names
from lawgraph.db.queries.dossiers import _read_law_names, get_laws_named


def _law(key: str, **props: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "type": "instrument",
        "labels": [],
        "props": {"bwb_id": key.upper(), "text": "De hele tekst. " * 50, **props},
    }


LAWS = [
    _law("bwbr0001", citation_title="Wet milieubeheer", title="Wet van 13 juni 1979",
         short_title="Wm"),
    _law("bwbr0002", citation_title="Wet natuurbescherming", short_title="Wnb"),
    _law("bwbr0003", citation_title="Omgevingswet", title=12),  # a title not a string
    _law("bwbr0004", citation_title="Wet stub", stub=True),
]  # fmt: skip


# What ``load_law_names`` read before the table: the props of every instrument.
_FROM_PROPS = """
SELECT i.key, i.props -> 'bwb_id' AS bwb_id,
       lower(coalesce(i.props -> 'citation_title' #>> '{}', '')) AS citation_title,
       lower(coalesce(i.props -> 'title' #>> '{}', '')) AS title,
       lower(coalesce(i.props -> 'short_title' #>> '{}', '')) AS short_title
FROM instruments i
WHERE i.stub IS DISTINCT FROM TRUE
ORDER BY i.key ASC NULLS LAST
"""


def _names(store: GraphStore, key: str) -> Any:
    rows = list(
        store.query(
            "SELECT title, short_title FROM lg_instrument_names WHERE id = %(id)s",
            {"id": f"instruments/{key}"},
        )
    )
    return rows[0] if rows else None


def test_an_instrument_written_is_kept_by_its_names(store: GraphStore) -> None:
    """Its title and short title as text ('' for none); kept again when it changes, and
    gone with it."""
    store.bulk_insert_or_update_nodes("instruments", LAWS)
    assert _names(store, "bwbr0001") == {
        "title": "Wet van 13 juni 1979",
        "short_title": "Wm",
    }
    assert _names(store, "bwbr0002") == {"title": "", "short_title": "Wnb"}
    assert _names(store, "bwbr0003") == {"title": "12", "short_title": ""}
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_law("bwbr0002", citation_title="Wet natuurbescherming", short_title="WNB")],
    )
    assert _names(store, "bwbr0002")["short_title"] == "WNB"
    store.execute("DELETE FROM instruments WHERE id = 'instruments/bwbr0002'")
    assert _names(store, "bwbr0002") is None


def test_the_law_names_are_those_of_the_props_before_and_after_the_fill(
    store: GraphStore, monkeypatch
) -> None:
    """Before ``semantic graph-light`` fills the instruments written before the triggers,
    their names come from the props; after, from the table: the same names either way."""
    store.bulk_insert_or_update_nodes("instruments", LAWS)
    kept = _read_law_names(store)
    assert list(store.query(_FROM_PROPS)) == list(store.query(dossiers._LAW_NAMES_SQL))
    store.execute("DELETE FROM lg_instrument_names")  # as written before the triggers
    assert _read_law_names(store) == kept
    monkeypatch.setattr(instrument_names, "BATCH", 2)
    assert instrument_names.fill_instrument_names(store) == 4
    assert instrument_names.fill_instrument_names(store) == 0  # nothing left
    assert instrument_names.fill_instrument_names(store, every=True) == 4
    assert _read_law_names(store) == kept
    assert kept.exact["wm"] == ("bwbr0001", "BWBR0001")
    assert kept.exact["wet van 13 juni 1979"] == ("bwbr0001", "BWBR0001")
    assert kept.exact["12"] == ("bwbr0003", "BWBR0003")
    assert "wet stub" not in kept.exact
    assert [
        r["key"] for r in get_laws_named(store, ["Wnb", "Wet milieubeheer", "Wet x"])
    ] == [
        "bwbr0002",
        "bwbr0001",
        None,
    ]
