"""The citations of a judgment that name a law by an abbreviation: the real ``normalize
rechtspraak`` and ``semantic rechtspraak`` and the API on their answer.

The EVRM (the BWB treaty BWBV0001000, abbreviated EVRM in its WTI) and the AVG (an EU act
with the short title EUR-Lex gives, and the abbreviation of ``curated
instrument-abbreviations``) are in the graph: their articles are cited. The Rv and the Sv
are not: the judgment keeps those citations as ``unresolved_citations``, until the law is
loaded, and says how many it could not link (``completeness.references``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.db import GraphStore
from tests.asserts import assert_status
from tests.integration.graph import write_evrm
from tests.integration.seed import judgment_xml, write_judgments

ECLI = "ECLI:NL:HR:2019:1278"
GDPR = "32016R0679"
RV = "BWBR0001827"
TEXT_1 = (
    "De klacht over art. 392 Rv faalt. Het hof heeft art. 8 EVRM en artikel 6, eerste "
    "lid, AVG juist toegepast."
)
TEXT_2 = "Anders dan artikel 350 Sv en artikel 392, eerste lid, Rv bepalen."


def _put(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    doc = {"key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[tuple[TestClient, GraphStore, Any]]:
    store = GraphStore()
    write_evrm(store)
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        GDPR.lower(),
        celex=GDPR,
        title="Verordening (EU) 2016/679 van het Europees Parlement en de Raad",
        citation_title="Verordening (EU) 2016/679",
        short_title="Algemene verordening gegevensbescherming",
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        f"{GDPR.lower()}_6",
        celex=GDPR,
        article_number="6",
        text="Rechtmatigheid van de verwerking.",
    )
    write_judgments(
        store,
        {ECLI: judgment_xml(ECLI, "2019-09-06", [("3.1", TEXT_1), ("3.2", TEXT_2)])},
    )
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app), store, cli
    finally:
        app.dependency_overrides.clear()


def _cited(store: GraphStore) -> set[str]:
    return set(
        store.query(
            "SELECT split_part(to_id, '/', 2) FROM edges "
            "WHERE from_id = %(j)s AND relation = 'REFERS_TO'",
            {"j": "judgments/ecli_nl_hr_2019_1278"},
        )
    )


def test_an_abbreviated_treaty_and_eu_act_in_the_graph_are_cited(
    client: tuple[TestClient, GraphStore, Any],
) -> None:
    _, store, _ = client
    assert _cited(store) == {"bwbv0001000_8", "32016r0679_6"}


def test_a_citation_of_a_law_not_in_the_graph_is_kept_on_the_judgment(
    client: tuple[TestClient, GraphStore, Any],
) -> None:
    api, _, _ = client
    response = api.get(f"/api/judgments/{ECLI}")
    assert_status(response, 200)
    unresolved = response.json()["judgment"]["unresolved_citations"]
    assert unresolved == [
        {
            "law": "Rv",
            "article_number": "392",
            "raw_match": "art. 392 Rv",
            "qualifier": None,
            "leden": [],
            "onderdelen": [],
            "aanhef": False,
            "paragraph_ids": ["rov-3.1", "rov-3.2"],
            "mention_count": 2,
        },
        {
            "law": "Sv",
            "article_number": "350",
            "raw_match": "artikel 350 Sv",
            "qualifier": None,
            "leden": [],
            "onderdelen": [],
            "aanhef": False,
            "paragraph_ids": ["rov-3.2"],
            "mention_count": 1,
        },
    ]
    cited = {a["article"]["article_number"] for a in response.json()["cited_articles"]}
    assert cited == {"8", "6"}
    assert response.json()["completeness"] == {
        "references": {"state": "partial", "as_of": None, "missing": 2, "reason": None}
    }


def test_a_law_that_is_loaded_later_takes_its_citations_over(
    client: tuple[TestClient, GraphStore, Any],
) -> None:
    api, store, cli = client
    _put(
        store,
        COLLECTION_INSTRUMENTS,
        RV.lower(),
        bwb_id=RV,
        title="Wetboek van Burgerlijke Rechtsvordering",
        citation_title="Wetboek van Burgerlijke Rechtsvordering",
        short_title="Rv",
        aliases=["Rv"],
    )
    cli("semantic", "rechtspraak")

    assert f"{RV.lower()}_392" in _cited(store)
    (props,) = store.query(
        "SELECT props -> 'unresolved_citations' FROM judgments "
        "WHERE key = 'ecli_nl_hr_2019_1278'"
    )
    assert [(c["law"], c["article_number"]) for c in props] == [("Sv", "350")]
    completeness = api.get(f"/api/judgments/{ECLI}").json()["completeness"]
    assert completeness["references"]["missing"] == 1


def test_the_code_keeps_rv_beside_its_version_for_paper_in_slices(
    client: tuple[TestClient, GraphStore, Any],
) -> None:
    """As on the server: the code and its version for procedures on paper both have the
    abbreviation Rv, neither as its short title. The code is the law cited; a run over all
    in slices (``--after``, ``--limit``) reads every judgment once."""
    _, store, cli = client
    title = "Wetboek van Burgerlijke Rechtsvordering"
    _put(store, COLLECTION_INSTRUMENTS, RV.lower(), bwb_id=RV, title=title,
         citation_title=title, aliases=["Rv"])  # fmt: skip
    _put(store, COLLECTION_INSTRUMENTS, "bwbr0039872", bwb_id="BWBR0039872",
         title=f"{title} (geldt in geval van niet-digitaal procederen)",
         citation_title=f"{title} (geldt in geval van niet-digitaal procederen)",
         aliases=["Rv"])  # fmt: skip
    first = cli("semantic", "rechtspraak", "--limit", "1")
    assert "go on with --after ecli_nl_hr_2019_1278" in first.stderr + first.stdout
    assert f"{RV.lower()}_392" in _cited(store)
    assert "bwbr0039872_392" not in _cited(store)
    after = cli(
        "semantic", "rechtspraak", "--after", "ecli_nl_hr_2019_1278", "--limit", "1"
    )
    assert "The last read was None" in after.stderr + after.stdout
