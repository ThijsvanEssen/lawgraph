"""A judgment the Rechtspraak withdrew, on a real PostgreSQL: ``normalize rechtspraak``
makes of its withdrawal (an ``rs-content`` record with ``meta.withdrawn`` and the RDF the
source still gives) a stub with the facts of the decision that name no one (ECLI, court,
date, case numbers, kind, area of law) and how it was withdrawn; its text, summary, parties
and its own edges go, what refers to it stays. ``/api/judgments/{ecli}`` gives that record.
A judgment published again is whole again."""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_RECHTSPRAAK_CONTENT,
    RELATION_REFERS_TO,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import GraphStore, edge_key, raw_source_doc
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from tests.asserts import assert_status
from tests.paths import fixture_text

ECLI = "ECLI:NL:GHAMS:2026:2678"
ID = "judgments/ecli_nl_ghams_2026_2678"
CITING = "judgments/ecli_nl_hr_2026_1"
ARTICLE = "articles/bwbr0005289_6_162"
WHOLE = fixture_text("rechtspraak_ghams_2026_2678.xml")
# what ``retrieve rechtspraak`` keeps of a withdrawn judgment: its RDF alone
_RDF = re.search(r"<rdf:RDF\b.*?</rdf:RDF>", WHOLE, re.S)
assert _RDF is not None
RDF = f"<open-rechtspraak>{_RDF[0]}</open-rechtspraak>"
WITHDRAWN_AT = "2026-10-15T22:39:19+00:00"  # 16 October in the Netherlands


def _content(store: GraphStore, ecli: str, xml: str, **meta: Any) -> None:
    store.insert_raw_sources(
        [
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RECHTSPRAAK_CONTENT,
                external_id=ecli,
                payload_text=xml,
                meta={"ecli": ecli, "updated": None, **meta},
            )
        ]
    )


def _normalize(store: GraphStore) -> None:
    result = RechtspraakNormalizePipeline(store=store).run()
    assert result.errors == []


def _withdraw(store: GraphStore, ecli: str, xml: str, how: str = "doc") -> None:
    _content(store, ecli, xml, withdrawn=how, updated=WITHDRAWN_AT)
    _normalize(store)


def _edges(store: GraphStore) -> set[tuple[str, str]]:
    rows = store.query("SELECT from_id, to_id FROM edges ORDER BY key")
    return {(row["from_id"], row["to_id"]) for row in rows}


def _loaded(store: GraphStore) -> None:
    """The judgment loaded whole, citing an article and cited by another judgment."""
    _content(store, ECLI, WHOLE)
    _normalize(store)
    store.bulk_insert_or_update_edges(
        [
            {
                "key": edge_key(from_id, RELATION_REFERS_TO, to_id),
                "from_id": from_id,
                "to_id": to_id,
                "relation": RELATION_REFERS_TO,
                "source": "rechtspraak",
            }
            for from_id, to_id in ((ID, ARTICLE), (CITING, ID))
        ]
    )


def _props(store: GraphStore, node_id: str = ID) -> dict[str, Any]:
    doc = store.get_document("judgments", node_id.split("/")[1])
    assert doc is not None
    return dict(doc["props"])


def test_a_withdrawn_judgment_keeps_the_facts_that_name_no_one(
    store: GraphStore,
) -> None:
    _loaded(store)
    whole = _props(store)
    assert whole.get("text") and whole.get("parties")
    persons = "SELECT 1 FROM lg_judgment_persons WHERE id = %(id)s"
    assert list(store.query(persons, {"id": ID}))

    _withdraw(store, ECLI, RDF)

    props = _props(store)
    assert props["stub"] is True
    assert (props["withdrawn"], props["withdrawn_on"]) == ("doc", "2026-10-16")
    for field in ("ecli", "court", "court_code", "tier", "date_eff", "case_number",
                  "case_number_keys", "decision_kind", "subjects"):  # fmt: skip
        assert props.get(field) == whole.get(field), field
    for gone in ("text", "summary", "paragraphs", "footnotes", "parties", "names",
                 "judgment_metadata", "meta", "outcome"):  # fmt: skip
        assert gone not in props, gone
    # what it said goes; what refers to it stays
    assert _edges(store) == {(CITING, ID)}
    assert list(store.query(persons, {"id": ID})) == []


def test_the_api_gives_the_record_of_a_withdrawn_judgment(store: GraphStore) -> None:
    _loaded(store)
    _withdraw(store, ECLI, RDF)
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(f"/api/judgments/{ECLI}")
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert_status(response, 200)
    judgment = response.json()["judgment"]
    assert (judgment["withdrawn"], judgment["withdrawn_on"]) == ("doc", "2026-10-16")
    assert judgment["paragraphs"] == [] and judgment["summary"] is None
    assert response.json()["articles"] == []


def test_an_ecli_given_in_error_names_the_ecli_the_source_gives_instead(
    store: GraphStore,
) -> None:
    ecli = "ECLI:NL:RBNHO:2026:13201"
    _withdraw(store, ecli, fixture_text("rs_withdrawn_ecli.xml"), how="ecli")
    props = _props(store, "judgments/ecli_nl_rbnho_2026_13201")
    assert props["withdrawn"] == "ecli"
    assert props["replaced_by"] == "ECLI:NL:RBDHA:2026:30255"
    assert props["court"] == "Rechtbank Noord-Holland"
    assert props["case_number"] == "NL26.49882"


def test_a_withdrawal_without_metadata_is_a_stub_of_its_ecli(
    store: GraphStore,
) -> None:
    """Never loaded, so nothing fetched of it: the court of its ECLI and no more. A
    citation found later makes no stub of its own, which ``retrieve rechtspraak --mode
    gaps`` would fetch again."""
    _withdraw(store, "ECLI:NL:RBZWB:2026:5617", "")
    props = _props(store, "judgments/ecli_nl_rbzwb_2026_5617")
    assert props["court_code"] == "RBZWB" and props["withdrawn"] == "doc"
    store.ensure_stub_node(
        "judgments", "ecli_nl_hr_2026_9", props={"ecli": "ECLI:NL:HR:2026:9"}
    )
    assert list(gap_queries.stub_dutch_eclis(store)) == ["ECLI:NL:HR:2026:9"]


def test_a_judgment_published_again_is_whole_again(store: GraphStore) -> None:
    _loaded(store)
    _withdraw(store, ECLI, RDF)

    _content(store, ECLI, WHOLE)
    _normalize(store)

    props = _props(store)
    assert props.get("text") and props["stub"] is False
    assert props.get("withdrawn") is None and props.get("withdrawn_on") is None
