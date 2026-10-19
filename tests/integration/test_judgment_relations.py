"""Conclusions and preliminary rulings: the real ``normalize rechtspraak`` and the two semantic
steps that tie judgments of one case, and the node responses on their edges.

The headers are those of ECLI:NL:HR:2019:1278 (a preliminary ruling that names its conclusion
and, in its text, the case number of the referring decision) and ECLI:NL:PHR:2019:496 (its
conclusion); the rest is made up around them.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RELATION_ANSWERS
from lawgraph.core.case_numbers import Referral
from lawgraph.db import EdgeWriter, GraphStore
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.semantic.rechtspraak_referrals import EDGE_SOURCE
from tests.integration.seed import (
    rechtspraak_relation,
    rechtspraak_xml,
    write_judgments,
)

REFERRAL = (
    "Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de "
    "rechtbank Assen op de voet van art. 392 Rv prejudiciële vragen aan de Hoge Raad gesteld."
)
JUDGMENTS = {
    "ECLI:NL:HR:2019:1278": rechtspraak_xml(
        "ECLI:NL:HR:2019:1278",
        "Hoge Raad",
        "2019-07-19",
        "18/04298",
        procedure="Prejudiciële beslissing",
        relations=rechtspraak_relation(
            "ECLI:NL:PHR:2019:496", "conclusie", "eerdereAanleg"
        ),
        text=REFERRAL,
    ),
    "ECLI:NL:PHR:2019:496": rechtspraak_xml(
        "ECLI:NL:PHR:2019:496",
        "Parket bij de Hoge Raad",
        "2019-05-10",
        "18/04298",
        document_type="Conclusie",
        relations=rechtspraak_relation(
            "ECLI:NL:HR:2019:1278", "conclusie", "latereAanleg"
        ),
    ),
    # the referring decision, its case number spaced as the metadata spaces it
    "ECLI:NL:RBNNE:2018:4308": rechtspraak_xml(
        "ECLI:NL:RBNNE:2018:4308",
        "Rechtbank Noord-Nederland",
        "2018-10-10",
        "C/19/117301 / HA ZA 16-256",
    ),
    # a conclusion that no relation ties, and the judgment of its case
    "ECLI:NL:PHR:2020:1": rechtspraak_xml(
        "ECLI:NL:PHR:2020:1",
        "Parket bij de Hoge Raad",
        "2020-01-10",
        "19/00001",
        document_type="Conclusie",
    ),
    "ECLI:NL:HR:2020:2": rechtspraak_xml(
        "ECLI:NL:HR:2020:2", "Hoge Raad", "2020-03-06", "19/00001", procedure="Cassatie"
    ),
    # a preliminary ruling (ECLI:NL:HR:2022:824) whose text writes the case number of the
    # referring decision otherwise than its metadata
    "ECLI:NL:HR:2022:824": rechtspraak_xml(
        "ECLI:NL:HR:2022:824",
        "Hoge Raad",
        "2022-06-03",
        "21/02242",
        procedure="Prejudiciële beslissing",
        text="Bij tussenvonnis in de zaak C/09/610280/ KG ZA 21/346 van 11 juni 2021 heeft "
        "voorzieningenrechter in de rechtbank te Den Haag op de voet van art. 392 Rv "
        "prejudiciële vragen aan de Hoge Raad gesteld.",
    ),
    "ECLI:NL:RBDHA:2021:5927": rechtspraak_xml(
        "ECLI:NL:RBDHA:2021:5927",
        "Rechtbank Den Haag",
        "2021-06-11",
        "C-09-610280-KG ZA 21-346",
    ),
    # a preliminary ruling (ECLI:NL:HR:2024:1366) whose referring decision is not loaded
    "ECLI:NL:HR:2024:1366": rechtspraak_xml(
        "ECLI:NL:HR:2024:1366",
        "Hoge Raad",
        "2024-10-04",
        "23/01968",
        procedure="Prejudiciële beslissing",
        text="Bij tussenvonnis in de zaak 8963920 CV EXPL 21-1168 van 12 mei 2023 heeft de "
        "rechtbank Rotterdam op de voet van art. 392 Rv een prejudiciële vraag aan de Hoge "
        "Raad gesteld.",
    ),
    # a preliminary ruling whose metadata names the referring decision
    "ECLI:NL:HR:2026:1265": rechtspraak_xml(
        "ECLI:NL:HR:2026:1265",
        "Hoge Raad",
        "2026-06-01",
        "S 26/01234",
        procedure="Prejudiciële beslissing",
        relations=rechtspraak_relation(
            "ECLI:NL:GHSHE:2026:724", "uitspraak", "eerdereAanleg"
        ),
    ),
}


def _edges(store: GraphStore, relation: str) -> set[tuple[str, str, str]]:
    sql = """
    SELECT f.ecli AS from_ecli, t.ecli AS to_ecli, e.doc -> 'meta' ->> 'basis' AS basis
    FROM edges e
    LEFT JOIN judgments f ON f.id = e.from_id
    LEFT JOIN judgments t ON t.id = e.to_id
    WHERE e.relation = %(relation)s
    """
    return {
        (row["from_ecli"], row["to_ecli"], row["basis"])
        for row in store.query(sql, {"relation": relation})
    }


def test_conclusions_and_referrals_tie_the_judgments_of_a_case(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    write_judgments(store, JUDGMENTS)
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-appeal")
    cli("semantic", "rechtspraak-conclusions")
    cli("semantic", "rechtspraak-referrals")

    assert _edges(store, "ADVISES_ON") == {
        ("ECLI:NL:PHR:2019:496", "ECLI:NL:HR:2019:1278", "formal_relation"),
        ("ECLI:NL:PHR:2020:1", "ECLI:NL:HR:2020:2", "case_number"),
    }
    assert _edges(store, "ANSWERS") == {
        ("ECLI:NL:HR:2019:1278", "ECLI:NL:RBNNE:2018:4308", "referral_text"),
        ("ECLI:NL:HR:2022:824", "ECLI:NL:RBDHA:2021:5927", "referral_text"),
        # not loaded: a stub, which `retrieve rechtspraak --mode gaps` fetches
        ("ECLI:NL:HR:2026:1265", "ECLI:NL:GHSHE:2026:724", "formal_relation"),
    }
    # a preliminary ruling appeals nothing
    assert _edges(store, "APPEAL_OF") == set()
    # what `retrieve rechtspraak --mode gaps` looks up in the index of the referral date
    assert _gaps.unanswered_referrals(store) == [
        Referral(case_numbers=("8963920 CV EXPL 21-1168",), date="2023-05-12")
    ]

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        ruling = client.get("/api/nodes/judgments/ecli_nl_hr_2019_1278").json()
        conclusion = client.get("/api/nodes/judgments/ecli_nl_phr_2019_496").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    buckets = {
        (b["relation"], b["direction"]): [i["key"] for i in b["items"]]
        for b in ruling["neighbors"]["buckets"]
    }
    assert buckets[("ADVISES_ON", "inbound")] == ["ecli_nl_phr_2019_496"]
    assert buckets[("ANSWERS", "outbound")] == ["ecli_nl_rbnne_2018_4308"]
    assert [
        (b["relation"], b["direction"]) for b in conclusion["neighbors"]["buckets"]
    ] == [("ADVISES_ON", "outbound")]


def test_referrals_since_derive_the_rulings_fetched_since_as_a_run_over_all(
    database: str, cli: Any
) -> None:
    """With ``--since`` the rulings fetched since then get the edges a run over all gives
    them, and lose those it no longer gives; so does a ruling that answered no decision,
    whose referring decision may be one fetched since. The edges of the others wait for a
    run over all."""
    store = GraphStore()
    write_judgments(store, JUDGMENTS)
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-referrals")
    full = _edges(store, "ANSWERS")
    ids = {r["ecli"]: r["id"] for r in store.query("SELECT ecli, id FROM judgments")}
    with EdgeWriter(store, what=None) as edges:
        for ruling in ["ECLI:NL:HR:2019:1278", "ECLI:NL:HR:2026:1265"]:
            edges.add(
                ids[ruling],
                ids["ECLI:NL:PHR:2020:1"],
                RELATION_ANSWERS,
                source=EDGE_SOURCE,
            )
    store.execute(
        "DELETE FROM edges WHERE relation = 'ANSWERS' AND from_id = %(id)s",
        {"id": ids["ECLI:NL:HR:2022:824"]},
    )
    time.sleep(1.1)  # fetched_at has a precision of a second
    since = dt.datetime.now(dt.UTC).isoformat()
    write_judgments(
        store,
        {
            **{
                e: JUDGMENTS[e] for e in ["ECLI:NL:HR:2019:1278", "ECLI:NL:HR:2022:824"]
            },
            # the decision ECLI:NL:HR:2024:1366 answers, fetched after it
            "ECLI:NL:RBROT:2023:4000": rechtspraak_xml(
                "ECLI:NL:RBROT:2023:4000",
                "Rechtbank Rotterdam",
                "2023-05-12",
                "8963920 CV EXPL 21-1168",
            ),
        },
    )
    cli("normalize", "rechtspraak", "--since", since)

    cli("semantic", "rechtspraak-referrals", "--since", since)

    assert _edges(store, "ANSWERS") == full | {
        ("ECLI:NL:HR:2026:1265", "ECLI:NL:PHR:2020:1", None),
        ("ECLI:NL:HR:2024:1366", "ECLI:NL:RBROT:2023:4000", "referral_text"),
    }
