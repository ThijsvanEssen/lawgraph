"""The judgments of the Court of Justice of the EU from EUR-Lex: the real ``normalize eurlex``,
``semantic eurlex-cjeu`` and ``lawgraph check`` on a graph where an earlier normalize made an
instrument of one, and a Dutch judgment cites it by its ECLI.

The record is the real one of C-160/20 (ECLI:EU:C:2022:101, referred by the Rechtbank
Rotterdam on 20 March 2020 in case ROT 19/1249), with what CELLAR says of it; the Dutch
judgments are made up around it.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.clients.eu import EUClient
from lawgraph.commands.check import check
from lawgraph.config.constants import RAW_KIND_EURLEX_CELEX, SOURCE_EURLEX
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc
from tests.fakes import ScriptedSession
from tests.integration.seed import rechtspraak_xml, write_judgments
from tests.paths import fixture_text

RULING = "ECLI:EU:C:2022:101"
RULING_ID = "judgments/ecli_eu_c_2022_101"
ROOKPREVENTIE = "62020CJ0160"
# stored before retrieve kept what CELLAR says of a judgment: no ECLI
WITHOUT_ECLI = "62021CJ0562"
ACT = "31995L0046"
REFERRING = "ECLI:NL:RBROT:2020:2155"
CITING = "ECLI:NL:HR:2023:1"


def _facts() -> dict[str, str]:
    answer = json.loads(fixture_text("cellar_cjeu_facts.json"))
    client = EUClient(session=ScriptedSession(lambda sent: answer))
    return client.judgment_facts([ROOKPREVENTIE])[ROOKPREVENTIE]


def _store_records(store: GraphStore) -> None:
    records = [
        (ACT, fixture_text("eurlex_31995l0046.html"), {}),
        (ROOKPREVENTIE, fixture_text("cjeu_62020cj0160.html"), _facts()),
        (WITHOUT_ECLI, "<html><p>Arrest</p></html>", {}),
    ]
    with RawSourceWriter(store) as writer:
        for celex, html, facts in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_EURLEX,
                    kind=RAW_KIND_EURLEX_CELEX,
                    external_id=celex,
                    payload_text=html,
                    meta={"celex": celex, "lang": "NL", **facts},
                )
            )


def _seed_old_instruments(store: GraphStore) -> None:
    """What normalize made of the judgments before: an instrument and an article of each,
    tied by PART_OF."""
    for celex in (ROOKPREVENTIE, WITHOUT_ECLI):
        key = celex.lower()
        store.bulk_insert_or_update_nodes(
            "instruments",
            [{"key": key, "type": "instrument", "labels": ["EU"],
              "props": {"source": "eurlex", "celex": celex, "jurisdiction": "eu"}}],
        )  # fmt: skip
        store.bulk_insert_or_update_nodes(
            "articles",
            [{"key": f"{key}_1", "type": "article", "labels": ["EU", "Article"],
              "props": {"celex": celex, "article_number": "1"}}],
        )  # fmt: skip
        store.bulk_insert_or_update_edges(
            [make_edge_doc(f"articles/{key}_1", f"instruments/{key}", "PART_OF")]
        )


def _keys(store: GraphStore, table: str) -> list[str]:
    return list(store.query(f"SELECT key FROM {table} ORDER BY key"))


def _edges(store: GraphStore, relation: str) -> set[tuple[str, str, Any]]:
    sql = """
    SELECT e.from_id, e.to_id, e.doc -> 'meta' ->> 'basis' AS basis FROM edges e
    WHERE e.relation = %(relation)s
    """
    return {
        (row["from_id"], row["to_id"], row["basis"])
        for row in store.query(sql, {"relation": relation})
    }


def test_a_judgment_of_the_court_of_justice_is_a_judgment(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _store_records(store)
    _seed_old_instruments(store)
    write_judgments(
        store,
        {
            # the decision that referred the questions, its case number as the court
            # writes it
            REFERRING: rechtspraak_xml(
                REFERRING, "Rechtbank Rotterdam", "2020-03-20", "ROT 19/1249"
            ),
            CITING: rechtspraak_xml(
                CITING,
                "Hoge Raad",
                "2023-01-06",
                "22/00001",
                text=f"Zie HvJ EU 22 februari 2022, C-160/20, {RULING}.",
            ),
        },
    )
    cli("normalize", "rechtspraak")
    # before: the Dutch judgment cites a stub
    cli("semantic", "rechtspraak-citations")

    cli("normalize", "eurlex")
    cli("semantic", "eurlex-cjeu")

    # an act stays an instrument; no instrument or article of case law remains
    assert _keys(store, "instruments") == [ACT.lower()]
    assert not [k for k in _keys(store, "articles") if k.startswith("6")]
    assert not [e for e in _edges(store, "PART_OF") if "/6" in e[1]]
    ruling = store.get_document("judgments", "ecli_eu_c_2022_101")
    assert ruling is not None
    props = ruling["props"]
    assert (props["stub"], props["source"], props["case_number"]) == (
        False,
        "cjeu",
        "C-160/20",
    )
    # the Dutch citation reaches the judgment it was a stub of
    assert (f"judgments/{CITING.lower().replace(':', '_')}", RULING_ID, None) in _edges(
        store, "REFERS_TO"
    )
    # the ruling cites the judgments of the Court it names, as stubs while not loaded
    cited = {to for frm, to, _ in _edges(store, "REFERS_TO") if frm == RULING_ID}
    assert "judgments/ecli_eu_c_2016_325" in cited
    stub = store.get_document("judgments", "ecli_eu_c_2016_325")
    assert stub is not None and stub["props"]["stub"] is True
    # and answers the decision that referred its questions
    assert _edges(store, "ANSWERS") == {
        (RULING_ID, "judgments/ecli_nl_rbrot_2020_2155", "national_decision")
    }

    report = check(store, edges=True)
    assert "nodes of cjeu in judgments: 1" in report.notes
    assert "nodes of eurlex in instruments: 1" in report.notes
    assert not [
        p for p in report.problems if p.startswith(("cjeu", "eurlex:", "edges"))
    ]

    cli("semantic", "graph-list-stats", "--judgments-only")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = client.get("/api/judgments", params={"tier": "hvj_eu"}).json()
        read = client.get(f"/api/judgments/{RULING}").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert [(i["ecli"], i["court_kind"]) for i in listed["items"]] == [
        (RULING, "hvj_eu")
    ]
    assert read["judgment"]["source"] == "cjeu"
    assert read["judgment"]["official_url"].endswith("uri=CELEX:62020CJ0160")
