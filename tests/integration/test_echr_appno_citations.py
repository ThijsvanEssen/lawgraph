"""Decisions of the ECHR cited by application number: the real ``semantic
rechtspraak-citations`` on a stored Dutch judgment and ``semantic echr`` on a judgment of the
Court. A number with a date names that decision; a number alone only the one decision of its
number; any other is left."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.test_judgment_relations import _xml

RULING = "ECLI:NL:HR:2019:2006"
TEXT = (
    "Zie EHRM 28 maart 2000, nr. 22492/93 (Kiliç/Turkije), en EHRM 3 mei 2005, "
    "nr. 12345/01. Vgl. ook EHRM, nr. 55555/05, en in zaak nr. 24/6811 de rechtbank."
)


def _echr(item: str, appno: str, date: str, **props: Any) -> dict[str, Any]:
    return {
        "_key": "echr_" + item.replace("-", "_"),
        "type": "judgment",
        "labels": ["ECHR"],
        "props": {
            "source": "echr",
            "external_id": item,
            "appno": appno,
            "date": date,
            "date_eff": date,
            **props,
        },
    }


DECISIONS = [
    # 22492/93: its judgment and, another day, its decision on admissibility
    _echr("001-58554", "22492/93", "2000-03-28"),
    _echr("001-3434", "22492/93", "1997-01-15"),
    # the French version of the judgment, SAME_AS the English one: not a decision of its own
    _echr("001-58555", "22492/93", "2000-03-28", same_as="001-58554"),
    # 12345/01: one decision
    _echr("001-69000", "12345/01", "2005-05-03"),
    # 55555/05: two decisions, and the text names no date
    _echr("001-80000", "55555/05", "2008-01-01"),
    _echr("001-90000", "55555/05", "2010-01-01"),
]


def _cited(store: GraphStore, source: str) -> set[tuple[str, str, str | None]]:
    return {
        (row["from_id"], row["to_id"], row["date"])
        for row in store.query(
            "SELECT from_id, to_id, doc -> 'meta' ->> 'cited_date' AS date FROM edges"
            " WHERE relation = 'REFERS_TO' AND source = %(source)s"
            " AND to_id LIKE 'judgments/echr_%%'",
            {"source": source},
        )
    }


def test_a_dutch_judgment_cites_strasbourg_by_number(database: str, cli: Any) -> None:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=RULING,
                payload_text=_xml(
                    RULING, "Hoge Raad", "2019-12-20", "19/01234", text=TEXT
                ),
                meta={"ecli": RULING},
            )
        )
    store.bulk_insert_or_update_nodes("judgments", DECISIONS)
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-citations")

    ruling = "judgments/ecli_nl_hr_2019_2006"
    assert _cited(store, "judgment-citation-linker") == {
        # the date chooses the judgment, not the decision on admissibility
        (ruling, "judgments/echr_001_58554", "2000-03-28"),
        (ruling, "judgments/echr_001_69000", "2005-05-03"),
        # 55555/05 has two decisions and no date: none; 24/6811 is no ECHR number
    }


def test_a_judgment_of_the_court_cites_another_by_number(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    citing = _echr(
        "001-252192",
        "7481/23",
        "2026-03-10",
        text="As the Court held in X v. Y (dec.), no. 12345/01, 3 May 2005, and in "
        "Kılıç v. Turkey, no. 22492/93, § 62, ECHR 2000-III; the applicant (no. 7481/23).",
    )
    store.bulk_insert_or_update_nodes("judgments", [*DECISIONS, citing])
    cli("semantic", "echr")

    # 12345/01 by number and date; 22492/93 has two decisions and no date here; its own
    # number is no citation
    assert _cited(store, "echr-citation-linker") == {
        ("judgments/echr_001_252192", "judgments/echr_001_69000", "2005-05-03")
    }
