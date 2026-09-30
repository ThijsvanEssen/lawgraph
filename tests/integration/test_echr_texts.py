"""The text of an ECHR judgment joins the node of its ECLI, run for real on the test server.

HUDOC serves a judgment once per language, and its text as a DOCX of its own item: the text
record and the judgment record are two records of one node, which one normalize writes, in
either order, in one buffer or two.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_ECHR_TEXT,
    SOURCE_ECHR,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures"
ECLI = "ECLI:CE:ECHR:2003:0729JUD004808699"


def _judgment(item_id: str, language: str) -> dict[str, Any]:
    return {
        "itemid": item_id,
        "ecli": ECLI,
        "appno": "48086/99",
        "docname": f"CASE OF BEUMER v. THE NETHERLANDS ({language})",
        "languageisocode": language,
        "kpdate": "2003-07-29T00:00:00",
        "respondent": "NLD",
        "article": "6;6-1",
    }


def _store(store: ArangoStore, *, text_first: bool) -> None:
    text = raw_source_doc(
        source=SOURCE_ECHR,
        kind=RAW_KIND_ECHR_TEXT,
        external_id="001-61254",
        payload_text=(FIXTURES / "hudoc_001_61254_document.xml").read_text(),
        meta={"ecli": ECLI, "language": "ENG"},
    )
    judgments = [
        raw_source_doc(
            source=SOURCE_ECHR,
            kind=RAW_KIND_ECHR_JUDGMENT,
            external_id=item_id,
            payload_json=_judgment(item_id, language),
        )
        for item_id, language in (("001-61254", "ENG"), ("001-66000", "FRE"))
    ]
    with RawSourceWriter(store) as writer:
        for doc in [text, *judgments] if text_first else [*judgments, text]:
            writer.add(doc)


def _node(store: ArangoStore) -> dict[str, Any]:
    node = store.get_node(COLLECTION_JUDGMENTS, make_node_key(ECLI))
    assert node is not None
    return node.props


def test_a_judgment_has_the_text_of_its_english_item(
    database: str, cli: Callable[..., Any]
) -> None:
    store = ArangoStore()
    _store(store, text_first=True)
    cli("normalize", "echr")

    props = _node(store)
    assert props["title"] == "CASE OF BEUMER v. THE NETHERLANDS (ENG)"
    assert props["text"].startswith("SECOND SECTION\n\nCASE OF BEUMER")
    paragraphs = {p["id"]: p for p in props["paragraphs"]}
    assert paragraphs["par-1"]["number"] == "1"
    assert paragraphs["kop-i"]["kind"] == "subheading"
    assert store.collection(COLLECTION_JUDGMENTS).count() == 1


def test_a_normalize_again_keeps_the_text_and_the_title(
    database: str, cli: Callable[..., Any]
) -> None:
    store = ArangoStore()
    _store(store, text_first=False)
    cli("normalize", "echr")
    cli("normalize", "echr")

    props = _node(store)
    assert props["title"] == "CASE OF BEUMER v. THE NETHERLANDS (ENG)"
    assert len(props["paragraphs"]) == 104
