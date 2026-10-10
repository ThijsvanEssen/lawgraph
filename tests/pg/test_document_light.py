"""A paper without its text, on a real PostgreSQL: ``lg_document_light`` kept by the triggers
on every write of ``documents``, filled by ``semantic graph-light`` for the papers written
before them, and read by the signals of a dossier (``normalize tk-dossiers``) instead of the
props of each paper, which hold its whole text."""

from __future__ import annotations

import json
import random
import string
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries import document_light
from lawgraph.db.queries.normalize import tk as normalize_tk

DOSSIERS = ["dossiers/36000", "dossiers/36001"]


def _paper(key: str, dossier: str, **props: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "type": "document",
        "labels": ["TK"],
        "props": {
            "title": f"Stuk {key}",
            "kind": "Motie",
            "date": f"2025-01-{int(key[-1]) + 1:02d}",
            "dossier_numbers": [dossier],
            "dossier_number": dossier,
            "sequence": int(key[-1]),
            "case_kinds": ["Motie"],
            "text": "De hele tekst. " * 50,
            "sections": [{"n": 1, "text": "lid 1"}],
            **props,
        },
    }


def _light(store: GraphStore, key: str) -> Any:
    rows = list(
        store.query(
            "SELECT props FROM lg_document_light WHERE id = %(id)s",
            {"id": f"documents/{key}"},
        )
    )
    return rows[0] if rows else None


def test_a_paper_written_is_kept_light(store: GraphStore) -> None:
    """The props the signals read, in their stored order; no text; kept again when the
    paper changes, also when only its text does, and gone with it."""
    store.bulk_insert_or_update_nodes("documents", [_paper("d1", "36000")])
    light = _light(store, "d1")
    assert list(light) == [
        "title",
        "kind",
        "date",
        "dossier_numbers",
        "dossier_number",
        "sequence",
        "case_kinds",
        "has_text",
    ]
    assert "text" not in light and "sections" not in light
    assert light["has_text"] is True

    store.bulk_insert_or_update_nodes(
        "documents", [_paper("d1", "36000", title="Gewijzigd")]
    )
    assert _light(store, "d1")["title"] == "Gewijzigd"
    store.bulk_insert_or_update_nodes(
        "documents", [_paper("d1", "36000", title="Gewijzigd", text="Nieuwe tekst.")]
    )
    assert _light(store, "d1")["title"] == "Gewijzigd"  # a write of the text alone

    store.execute("DELETE FROM documents WHERE id = 'documents/d1'")
    assert _light(store, "d1") is None


def test_whether_a_paper_has_its_text_is_kept_light(store: GraphStore) -> None:
    """``has_text``: the paper's text is in the data; it changes when the text comes."""
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _paper("d1", "36000", text=None),
            _paper("d2", "36000", text=""),
            _paper("d3", "36000", text=["no", "string"]),
        ],
    )
    assert [_light(store, f"d{n}")["has_text"] for n in (1, 2, 3)] == [False] * 3
    store.bulk_insert_or_update_nodes(
        "documents", [_paper("d1", "36000", text="De tekst kwam later.")]
    )
    assert _light(store, "d1")["has_text"] is True
    # a paper without any of the light props has the flag alone
    store.bulk_insert_or_update_nodes(
        "documents", [{"_key": "bare", "type": "document", "labels": [], "props": {}}]
    )
    assert _light(store, "bare") == {"has_text": False}


def test_the_papers_written_before_are_filled(store: GraphStore, monkeypatch) -> None:
    """``semantic graph-light`` keeps those without (in batches); with ``--all`` every
    paper again."""
    store.bulk_insert_or_update_nodes(
        "documents", [_paper(f"d{n}", "36000") for n in range(5)]
    )
    store.execute("DELETE FROM lg_document_light")
    monkeypatch.setattr(document_light, "BATCH", 2)
    assert document_light.fill_document_light(store) == 5
    assert _light(store, "d3")["title"] == "Stuk d3"
    assert document_light.fill_document_light(store) == 0
    assert document_light.fill_document_light(store, every=True) == 5


def _dossiers_with_papers(store: GraphStore, text: str = "De hele tekst. ") -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {"_key": d.split("/")[1], "type": "dossier", "labels": [], "props": {}}
            for d in DOSSIERS
        ],
    )
    papers = [
        _paper(f"p{d[-1]}{n}", d.split("/")[1], text=text, kind=kind, title=title)
        for d in DOSSIERS
        for n, (kind, title) in enumerate(
            [("Voorstel van wet", "Wet A"), ("Memorie van toelichting", "MvT"),
             ("Motie", "Motie X")]
        )
    ]  # fmt: skip
    store.bulk_insert_or_update_nodes("documents", papers)
    store.bulk_insert_or_update_edges(
        [
            {
                "_key": f"part-{p['_key']}",
                "_from": f"documents/{p['_key']}",
                "_to": f"dossiers/{p['props']['dossier_number']}",
                "relation": "PART_OF",
                "source": "test",
                "meta": {},
            }
            for p in papers
        ]
    )


def test_the_signals_are_the_same_light_or_cut(store: GraphStore) -> None:
    """Read from ``lg_document_light`` or, while it is empty, from the props of each paper:
    the same titles, kinds, dates and case kinds."""
    _dossiers_with_papers(store)
    light = list(normalize_tk.dossier_signals(store, DOSSIERS))
    assert light[0]["docs"]  # it read papers
    store.execute("DELETE FROM lg_document_light")
    cut = list(normalize_tk.dossier_signals(store, DOSSIERS))
    assert json.dumps(light, sort_keys=True) == json.dumps(cut, sort_keys=True)


def _text_blocks(store: GraphStore) -> int:
    """The blocks of the texts of the papers (the TOAST table of ``documents``) the signals of
    the dossiers fetch, as this transaction counts them (``pg_stat_get_xact_blocks_fetched``:
    hit or read, whatever the shared buffers hold, so it does not depend on what ran
    before)."""
    with store.pool.connection() as conn, conn.transaction():
        conn.execute(
            normalize_tk._DOSSIER_SIGNALS_SQL,
            normalize_tk.dossier_signals_bind(DOSSIERS),
        ).fetchall()
        row = conn.execute(
            "SELECT pg_stat_get_xact_blocks_fetched(reltoastrelid) FROM pg_class"
            " WHERE oid = 'documents'::regclass"
        ).fetchone()
    return int(row[0])


def test_the_signals_do_not_read_the_text_of_a_paper(store: GraphStore) -> None:
    """With a text of 200 KB per paper (stored apart, in the TOAST table of documents), the
    signals read from ``lg_document_light`` fetch no block of those texts; reading the props
    fetches most of them."""
    rng = random.Random(1)
    text = "".join(rng.choices(string.ascii_letters + " ", k=200_000))
    _dossiers_with_papers(store, text=text)
    assert _text_blocks(store) == 0
    store.execute("DELETE FROM lg_document_light")
    text_pages = 6 * 200_000 // 8192  # six papers
    assert _text_blocks(store) > 0.8 * text_pages


def test_the_step_keeps_judgments_and_papers(store: GraphStore) -> None:
    """``semantic graph-light`` fills both tables: one step for both after a deploy."""
    from lawgraph.pipelines.semantic import graph_light

    store.bulk_insert_or_update_nodes("documents", [_paper("d1", "36000")])
    store.execute("DELETE FROM lg_document_light")
    result = graph_light.main([])
    assert result.updated == 1
    assert _light(store, "d1")["title"] == "Stuk d1"


def test_the_papers_alone_are_kept_again(store: GraphStore) -> None:
    """``semantic graph-light --papers``: every paper again (after what is kept of a paper
    changed, as ``has_text``), every other light table only where a row is missing."""
    from lawgraph.pipelines.semantic import graph_light

    store.bulk_insert_or_update_nodes(
        "documents", [_paper("d1", "36000"), _paper("d2", "36000", text=None)]
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [{"_key": "j1", "type": "judgment", "labels": [], "props": {"ecli": "ECLI:1"}}],
    )
    # as kept before the flag: no has_text
    store.execute('UPDATE lg_document_light SET props = \'{"title": "oud"}\'')
    store.execute('UPDATE lg_judgment_light SET props = \'{"ecli": "kept"}\'')

    assert graph_light.main(["--papers"]).updated == 2

    assert _light(store, "d1")["has_text"] is True
    assert _light(store, "d2")["has_text"] is False
    (judgment,) = store.query("SELECT props FROM lg_judgment_light")
    assert judgment == {"ecli": "kept"}  # not read again
