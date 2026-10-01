"""The ECHR Convention is one instrument: the treaty of the BWB, BWBV0001000.

The real ``semantic echr``, ``semantic rechtspraak`` and the API, on the small test server. A
judgment of the ECHR names the Convention articles it applies as HUDOC writes them
(``8;8-1;8-2;41;P1-1``: article 8, its first and second paragraph, article 41, and article 1
of the first Protocol, a treaty of its own). Those articles are the articles of BWBV0001000,
the same nodes a Dutch judgment reaches with "art. 8 EVRM"; while the treaty is not loaded they
are stubs, as the articles of any law that is not loaded.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.commands.check import check
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RELATION_REFERS_TO,
    SOURCE_ECHR,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.edges import make_edge_doc
from tests.integration.test_judgment_mentions import _judgment_xml

EVRM = "BWBV0001000"
ECHR_ECLI = "ECLI:CE:ECHR:2021:0209JUD001098215"
ECHR_KEY = make_node_key(ECHR_ECLI)
NL_ECLI = "ECLI:NL:HR:2019:1278"


def _put(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def _echr_judgment(store: GraphStore) -> None:
    """As ``normalize echr`` writes it."""
    _put(
        store,
        COLLECTION_JUDGMENTS,
        ECHR_KEY,
        source=SOURCE_ECHR,
        external_id="001-208058",
        appno="10982/15",
        ecli=ECHR_ECLI,
        title="CASE OF X v. THE NETHERLANDS",
        display_name="CASE OF X v. THE NETHERLANDS",
        date="2021-02-09",
        articles=["8;8-1;8-2;41;P1-1"],
        conclusion="Violation of Article 8",
    )


def _load_the_treaty(store: GraphStore) -> None:
    """BWBV0001000 as ``normalize bwb`` writes it: its WTI abbreviation is EVRM."""
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        make_node_key(EVRM),
        bwb_id=EVRM,
        title="Verdrag tot bescherming van de rechten van de mens en de fundamentele "
        "vrijheden",
        citation_title="Verdrag tot bescherming van de rechten van de mens en de "
        "fundamentele vrijheden",
        short_title="EVRM",
        aliases=["EVRM"],
        kind="verdrag",
    )
    for number in ("6", "8", "41"):
        _put(
            store,
            COLLECTION_ARTICLES,
            make_node_key(EVRM, number),
            bwb_id=EVRM,
            article_number=number,
            label=f"Artikel {number}",
            text=f"Tekst van artikel {number}.",
        )


def _cited(store: GraphStore, judgment_key: str) -> dict[str, dict[str, Any]]:
    rows = store.query(
        "SELECT a.key, coalesce(a.stub, false) AS stub, e.doc -> 'meta' AS meta "
        "FROM edges e LEFT JOIN articles a ON a.id = e.to_id "
        "WHERE e.from_id = %(j)s AND e.relation = %(r)s",
        {"j": f"judgments/{judgment_key}", "r": RELATION_REFERS_TO},
    )
    return {row["key"]: row for row in rows}


def test_the_articles_an_echr_judgment_applies_are_stubs_of_the_treaty_not_loaded(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _echr_judgment(store)
    # an edge an earlier run made to the Convention of the ECHR pipeline's own
    _put(store, COLLECTION_ARTICLES, "echr_convention_8", article_number="8")
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"judgments/{ECHR_KEY}",
                "articles/echr_convention_8",
                RELATION_REFERS_TO,
                source="echr-citation-linker",
                confidence=0.95,
            )
        ]
    )

    cli("semantic", "echr")

    cited = _cited(store, ECHR_KEY)
    assert set(cited) == {"bwbv0001000_8", "bwbv0001000_41"}  # the Protocol is not it
    assert cited["bwbv0001000_8"]["stub"] is True
    assert cited["bwbv0001000_8"]["meta"]["leden"] == ["1", "2"]
    (stub,) = store.query(
        "SELECT json_build_object('bwb_id', props -> 'bwb_id', "
        "'article_number', props -> 'article_number') "
        "FROM articles WHERE key = 'bwbv0001000_8'"
    )
    assert stub == {"bwb_id": EVRM, "article_number": "8"}
    assert not list(
        store.query("SELECT key FROM instruments WHERE key = 'echr_convention'")
    )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[tuple[TestClient, GraphStore]]:
    store = GraphStore()
    _load_the_treaty(store)
    _echr_judgment(store)
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=NL_ECLI,
                payload_text=_judgment_xml(
                    NL_ECLI,
                    "2019-09-06",
                    [("3.1", "Het hof heeft art. 8 EVRM geschonden.")],
                ),
                meta={"ecli": NL_ECLI},
            )
        )
    cli("normalize", "rechtspraak")
    cli("semantic", "echr")
    cli("semantic", "rechtspraak")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app), store
    finally:
        app.dependency_overrides.clear()


def test_the_echr_and_a_dutch_judgment_cite_one_article_of_the_loaded_treaty(
    client: tuple[TestClient, GraphStore],
) -> None:
    _, store = client
    echr = _cited(store, ECHR_KEY)
    assert set(echr) == {"bwbv0001000_8", "bwbv0001000_41"}
    assert not any(row["stub"] for row in echr.values())
    assert "bwbv0001000_8" in _cited(store, make_node_key(NL_ECLI))
    assert not list(store.query("SELECT key FROM articles WHERE stub"))


def test_an_echr_judgment_links_to_hudoc(
    client: tuple[TestClient, GraphStore],
) -> None:
    api, _ = client
    echr = api.get(f"/api/judgments/{ECHR_ECLI}").json()["judgment"]
    assert echr["official_url"] == "https://hudoc.echr.coe.int/eng?i=001-208058"
    dutch = api.get(f"/api/judgments/{NL_ECLI}").json()["judgment"]
    assert dutch["official_url"] == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2019:1278"
    )


def test_the_check_counts_the_protocol_articles_that_are_not_linked(
    database: str,
) -> None:
    store = GraphStore()
    _echr_judgment(store)  # 8;8-1;8-2;41;P1-1
    _put(
        store,
        COLLECTION_JUDGMENTS,
        "echr_001_2",
        source=SOURCE_ECHR,
        external_id="001-2",
        articles=["P1-1;P1-1-1;P4-2;6"],
    )

    report = check(store, edges=False)

    assert (
        "echr: 3 articles of a Protocol in 2 judgments are not linked (P1-1, P4-2): "
        "a Protocol is a treaty of its own, and no source maps its number to a BWB id"
    ) in report.notes
