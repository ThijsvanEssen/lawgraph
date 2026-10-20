"""The ECHR Convention is one instrument: the treaty of the BWB, BWBV0001000.

The real ``semantic echr``, ``semantic rechtspraak`` and the API, on the small test server. A
judgment of the ECHR names the Convention articles it applies as HUDOC writes them
(``8;8-1;8-2;41;P1-1``: article 8, its first and second paragraph, article 41, and article 1
of the first Protocol, a treaty of its own). Those articles are the articles of BWBV0001000,
the same nodes a Dutch judgment reaches with "art. 8 EVRM"; an article of a Protocol is one of
its BWB treaty (curated ``echr-protocols``: P1 is BWBV0001001). While a treaty is not loaded
its articles are stubs, as the articles of any law that is not loaded.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.commands.check import check
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_REFERS_TO,
    SOURCE_ECHR,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from tests.databases import Api, module_store
from tests.integration.graph import cited_articles, put_node
from tests.integration.seed import judgment_xml, write_judgments

EVRM = "BWBV0001000"
ECHR_ECLI = "ECLI:CE:ECHR:2021:0209JUD001098215"
ECHR_KEY = make_node_key(ECHR_ECLI)
NL_ECLI = "ECLI:NL:HR:2019:1278"

# The tests on the loaded treaty read one database built for them all (``store``), on the
# worker that built it; the two that write have a database of their own (``database``).
pytestmark = pytest.mark.xdist_group("echr_convention")


def _echr_judgment(store: GraphStore) -> None:
    """As ``normalize echr`` writes it."""
    put_node(
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
    put_node(
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
        put_node(
            store,
            COLLECTION_ARTICLES,
            make_node_key(EVRM, number),
            bwb_id=EVRM,
            article_number=number,
            label=f"Artikel {number}",
            text=f"Tekst van artikel {number}.",
        )


def test_the_articles_an_echr_judgment_applies_are_stubs_of_the_treaty_not_loaded(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _echr_judgment(store)
    # an edge an earlier run made to the Convention of the ECHR pipeline's own
    put_node(store, COLLECTION_ARTICLES, "echr_convention_8", article_number="8")
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

    cited = cited_articles(store, ECHR_KEY)
    # P1-1 is article 1 of the first Protocol: BWBV0001001, a treaty of its own
    assert set(cited) == {"bwbv0001000_8", "bwbv0001000_41", "bwbv0001001_1"}
    assert cited["bwbv0001000_8"]["stub"] is True
    assert cited["bwbv0001000_8"]["meta"]["leden"] == ["1", "2"]
    assert cited["bwbv0001001_1"]["stub"] is True
    (stub,) = store.query(
        "SELECT json_build_object('bwb_id', props -> 'bwb_id', "
        "'article_number', props -> 'article_number') "
        "FROM articles WHERE key = 'bwbv0001000_8'"
    )
    assert stub == {"bwb_id": EVRM, "article_number": "8"}
    assert not list(
        store.query("SELECT key FROM instruments WHERE key = 'echr_convention'")
    )


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """The treaty loaded, built once for the tests that only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _load_the_treaty(store)
        _echr_judgment(store)
        write_judgments(
            store,
            {
                NL_ECLI: judgment_xml(
                    NL_ECLI,
                    "2019-09-06",
                    [("3.1", "Het hof heeft art. 8 EVRM geschonden.")],
                )
            },
        )
        cli("normalize", "rechtspraak")
        cli("semantic", "echr")
        cli("semantic", "rechtspraak")
        yield store


def test_the_echr_and_a_dutch_judgment_cite_one_article_of_the_loaded_treaty(
    store: GraphStore,
) -> None:
    echr = cited_articles(store, ECHR_KEY)
    assert set(echr) == {"bwbv0001000_8", "bwbv0001000_41", "bwbv0001001_1"}
    # the Convention is loaded; the first Protocol, a treaty of its own, is not
    assert {key for key, row in echr.items() if row["stub"]} == {"bwbv0001001_1"}
    assert "bwbv0001000_8" in cited_articles(store, make_node_key(NL_ECLI))
    assert list(store.query("SELECT key FROM articles WHERE stub")) == ["bwbv0001001_1"]


def test_an_echr_judgment_links_to_hudoc(api: Api) -> None:
    echr = api.get_json(f"/api/judgments/{ECHR_ECLI}")["judgment"]
    assert echr["official_url"] == "https://hudoc.echr.coe.int/eng?i=001-208058"
    dutch = api.get_json(f"/api/judgments/{NL_ECLI}")["judgment"]
    assert dutch["official_url"] == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2019:1278"
    )


def test_the_check_counts_the_protocol_articles_that_are_not_linked(
    database: str,
) -> None:
    store = GraphStore()
    _echr_judgment(store)  # 8;8-1;8-2;41;P1-1
    put_node(
        store,
        COLLECTION_JUDGMENTS,
        "echr_001_2",
        source=SOURCE_ECHR,
        external_id="001-2",
        articles=["P1-1;P1-1-1;P4-2;P11-1;6"],
    )

    report = check(store, edges=False)

    # P1 and P4 are in the curated list: linked; P11 changes the procedure of the Court
    assert (
        "echr: 1 articles of a Protocol in 1 judgments are not linked (P11-1): "
        "the Protocol is not in the curated list echr-protocols"
    ) in report.notes
