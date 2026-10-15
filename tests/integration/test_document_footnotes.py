"""A Kamerstuk that cites a law in a footnote only (the MvT of 33328, Wet open overheid, and
the VIR-BI): the real ``semantic tk`` says on the edge which footnote it is in, and
``/api/documents/{key}`` serves that footnote, with where its marker stands in the text."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_DOCUMENTS, COLLECTION_INSTRUMENTS
from lawgraph.db import GraphStore

VIRBI = "BWBR0016435"
TITLE = "Besluit voorschrift informatiebeveiliging rijksdienst – bijzondere informatie"
TEXT = "ALGEMEEN\nDe Wob regelt de openbaarheid van bestuur.\nArtikel 2\nGeen."
NOTE = f"Toelichting op het {TITLE} (Virbi), Stcrt. 2004, 47."
AT = TEXT.index("bestuur") + len("bestuur")  # the marker of footnote 2 stands there
ARTICLE = TEXT.index("Artikel 2")


def _put(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    labels = ["TK"] if collection == COLLECTION_DOCUMENTS else []
    doc = {"key": key, "type": collection.rstrip("s"), "labels": labels}
    store.bulk_insert_or_update_nodes(collection, [{**doc, "props": props}])


def test_a_law_cited_in_a_footnote_is_found_where_it_stands(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _put(store, COLLECTION_INSTRUMENTS, VIRBI.lower(), bwb_id=VIRBI, title=TITLE)
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "mvt_33328",
        external_id="3de9f42e",
        title="Memorie van toelichting",
        text=TEXT,
        sections=[
            {
                "id": "s-1",
                "heading": "ALGEMEEN",
                "level": 1,
                "kind": "algemeen",
                "char_start": 0,
                "char_end": ARTICLE - 1,
            },
            {
                "id": "s-2",
                "heading": "Artikel 2",
                "level": 1,
                "kind": "article",
                "char_start": ARTICLE,
                "char_end": len(TEXT),
            },
        ],  # fmt: skip
        footnotes=[
            {
                "number": "1",
                "text": "Kamerstukken II 1986/87, 19 859, nr. 3.",
                "at": 17,
            },
            {"number": "2", "text": NOTE, "at": AT},
        ],
    )

    cli("semantic", "tk")

    (meta,) = store.query(
        "SELECT doc -> 'meta' FROM edges WHERE from_id = 'documents/mvt_33328'"
        " AND to_id = %(to)s AND relation = 'REFERS_TO'",
        {"to": f"instruments/{VIRBI.lower()}"},
    )
    meta = meta if isinstance(meta, dict) else json.loads(meta)
    place = meta["place"]
    assert (place["part"], place["footnote"], place["footnote_id"]) == (
        "footnote",
        "2",
        "fn-2",
    )
    assert NOTE[place["start"] : place["end"]] == TITLE

    app.dependency_overrides[get_store] = lambda: store
    try:
        body = TestClient(app).get("/api/documents/mvt_33328").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert body["footnotes"] == [
        {
            "id": "fn-1",
            "label": "1",
            "text": "Kamerstukken II 1986/87, 19 859, nr. 3.",
            "at": 17,
            "section_id": "s-1",
        },
        {"id": "fn-2", "label": "2", "text": NOTE, "at": AT, "section_id": "s-1"},
    ]
    assert body["text"][:AT].endswith("openbaarheid van bestuur")
    note = next(n for n in body["footnotes"] if n["id"] == place["footnote_id"])
    assert note["text"][place["start"] : place["end"]] == TITLE
