"""The citations of a judgment that name a law by an abbreviation: the real ``normalize
rechtspraak`` and ``semantic rechtspraak`` and the API on their answer.

The EVRM (the instrument ``semantic echr`` writes) and the AVG (an EU act with the short
title EUR-Lex gives, and the abbreviation of ``curated instrument-abbreviations``) are in the
graph: their articles are cited. The Rv and the Sv are not: the judgment keeps those
citations as ``unresolved_citations``, until the law is loaded.
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
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.semantic.echr import (
    _ensure_echr_article,
    _ensure_echr_convention_instrument,
)
from tests.integration.test_judgment_mentions import _judgment_xml

ECLI = "ECLI:NL:HR:2019:1278"
GDPR = "32016R0679"
RV = "BWBR0001827"
TEXT_1 = (
    "De klacht over art. 392 Rv faalt. Het hof heeft art. 8 EVRM en artikel 6, eerste "
    "lid, AVG juist toegepast."
)
TEXT_2 = "Anders dan artikel 350 Sv en artikel 392, eerste lid, Rv bepalen."


def _put(store: ArangoStore, collection: str, key: str, **props: Any) -> None:
    doc = {"_key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[tuple[TestClient, ArangoStore, Any]]:
    store = ArangoStore()
    convention = _ensure_echr_convention_instrument(store)
    _ensure_echr_article(store, convention, "8")
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
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=ECLI,
                payload_text=_judgment_xml(
                    ECLI, "2019-09-06", [("3.1", TEXT_1), ("3.2", TEXT_2)]
                ),
                meta={"ecli": ECLI},
            )
        )
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app), store, cli
    finally:
        app.dependency_overrides.clear()


def _cited(store: ArangoStore) -> set[str]:
    return set(
        store.query(
            "FOR e IN edges FILTER e._from == @j AND e.relation == 'REFERS_TO' "
            "RETURN PARSE_IDENTIFIER(e._to).key",
            {"j": "judgments/ecli_nl_hr_2019_1278"},
        )
    )


def test_an_abbreviated_treaty_and_eu_act_in_the_graph_are_cited(
    client: tuple[TestClient, ArangoStore, Any],
) -> None:
    _, store, _ = client
    assert _cited(store) == {"echr_convention_8", "32016r0679_6"}


def test_a_citation_of_a_law_not_in_the_graph_is_kept_on_the_judgment(
    client: tuple[TestClient, ArangoStore, Any],
) -> None:
    api, _, _ = client
    response = api.get(f"/api/judgments/{ECLI}")
    assert response.status_code == 200
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


def test_a_law_that_is_loaded_later_takes_its_citations_over(
    client: tuple[TestClient, ArangoStore, Any],
) -> None:
    _, store, cli = client
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
        "RETURN DOCUMENT('judgments/ecli_nl_hr_2019_1278').props.unresolved_citations"
    )
    assert [(c["law"], c["article_number"]) for c in props] == [("Sv", "350")]
