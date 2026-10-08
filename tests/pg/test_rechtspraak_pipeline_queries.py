"""The reads and writes of the Rechtspraak and ECHR normalize and semantic steps on a real
PostgreSQL: which judgments each reads, in which order, with which values (nulls and
missing props as ArangoDB saw them), and what the writes leave in the tables."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.appeals import APPEAL_PROCEDURE
from lawgraph.core.judgment_series import summary_fingerprint
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries.normalize import rechtspraak as normalize_queries
from lawgraph.db.queries.semantic import rechtspraak as queries

HR1 = "ECLI:NL:HR:2020:1"
HR2 = "ECLI:NL:HR:2020:2"
HR3 = "ECLI:NL:HR:2020:3"
PHR = "ECLI:NL:PHR:2020:1"
GH = "ECLI:NL:GHAMS:2019:5"
RB = "ECLI:NL:RBAMS:2019:7"
RB2 = "ECLI:NL:RBAMS:2019:8"
STUB = "ECLI:NL:HR:2001:1"
ECHR = "001-123"

SLIM_KEYS = ["_key", "type", "labels", "props"]


def _key(ecli: str) -> str:
    return make_node_key(ecli)


def _jid(ecli: str) -> str:
    return f"judgments/{_key(ecli)}"


def _judgment(ecli: str, **props: Any) -> dict[str, Any]:
    """A judgment with *props* as given (in this order), its ECLI first unless given."""
    return {
        "_key": _key(ecli),
        "type": "judgment",
        "labels": ["Judgment"],
        "props": {"ecli": ecli, **props},
    }


def _rs(ecli: str, **props: Any) -> dict[str, Any]:
    """A loaded Rechtspraak judgment."""
    return _judgment(ecli, **{"source": "rechtspraak", "stub": False, **props})


def _edge(source: str, target: str, relation: str, key: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
    }


def _seed(store: GraphStore, *docs: dict[str, Any]) -> None:
    store.bulk_insert_or_update_nodes("judgments", list(docs))


def _props(store: GraphStore, ecli: str) -> dict[str, Any]:
    doc = store.get_document("judgments", _key(ecli))
    assert doc is not None
    return doc["props"]


# ── judgment_paragraphs, count ───────────────────────────────────────────────


def test_judgment_paragraphs_are_slim_documents_in_key_order(
    store: GraphStore,
) -> None:
    # props written in an order of their own: the slim props come in byte order
    _seed(
        store,
        _judgment(
            HR2,
            unresolved_citations=["art. 1"],
            text="lang",
            source="rechtspraak",
            paragraphs=[{"text": "p"}],
        ),
        _rs(HR1, paragraphs=[{"text": "a"}, {"text": "b"}], xml="<x/>"),
        _judgment(ECHR, source="echr", paragraphs=[{"text": "e"}]),
    )
    rows = list(queries.judgment_paragraphs(store, eclis=None, batch_size=1))
    assert rows == [
        {
            "_key": _key(HR1),
            "type": "judgment",
            "labels": ["Judgment"],
            "props": {"ecli": HR1, "paragraphs": [{"text": "a"}, {"text": "b"}]},
        },
        {
            "_key": _key(HR2),
            "type": "judgment",
            "labels": ["Judgment"],
            "props": {
                "ecli": HR2,
                "paragraphs": [{"text": "p"}],
                "unresolved_citations": ["art. 1"],
            },
        },
    ]
    assert [list(r) for r in rows] == [SLIM_KEYS, SLIM_KEYS]
    assert list(rows[1]["props"]) == ["ecli", "paragraphs", "unresolved_citations"]
    # as stored, the props of HR2 begin with unresolved_citations
    assert list(_props(store, HR2))[:2] == ["ecli", "unresolved_citations"]

    recent = list(queries.judgment_paragraphs(store, eclis=[HR2, RB], batch_size=10))
    assert [r["_key"] for r in recent] == [_key(HR2)]
    assert list(queries.judgment_paragraphs(store, eclis=[], batch_size=10)) == []


def test_a_judgment_without_the_slim_props_has_empty_props(store: GraphStore) -> None:
    _seed(store, {"_key": "x", "type": "judgment", "props": {"source": "rechtspraak"}})
    rows = list(queries.judgment_paragraphs(store, eclis=None, batch_size=10))
    assert rows == [{"_key": "x", "type": "judgment", "labels": [], "props": {}}]


def test_count_rechtspraak_judgments(store: GraphStore) -> None:
    assert queries.count_rechtspraak_judgments(store) == 0
    _seed(store, _rs(HR1), _rs(HR2), _judgment(ECHR, source="echr"))
    assert queries.count_rechtspraak_judgments(store) == 2


# ── lookups by ECLI ──────────────────────────────────────────────────────────


def test_judgment_ids_by_ecli_and_loaded_judgment_ids(store: GraphStore) -> None:
    _seed(
        store,
        _rs(HR2),
        _rs(HR1),
        _judgment(STUB, stub=True),
        _judgment(RB, source="rechtspraak"),  # no stub prop: loaded
    )
    rows = list(queries.judgment_ids_by_ecli(store, [HR2, STUB, HR1, GH]))
    assert rows == [
        {"ecli": STUB, "id": _jid(STUB)},
        {"ecli": HR1, "id": _jid(HR1)},
        {"ecli": HR2, "id": _jid(HR2)},
    ]
    assert [list(r) for r in rows] == [["ecli", "id"]] * 3
    loaded = list(queries.loaded_judgment_ids(store, [HR2, STUB, RB, GH]))
    assert loaded == [{"ecli": HR2, "id": _jid(HR2)}, {"ecli": RB, "id": _jid(RB)}]
    assert list(queries.judgment_ids_by_ecli(store, [])) == []


# ── appeals ──────────────────────────────────────────────────────────────────


def test_judgments_with_related_eclis(store: GraphStore) -> None:
    _seed(
        store,
        _rs(
            HR1,
            date_eff="2020-05-01",
            case_number="19/01234",
            case_number_keys=["19/01234"],
            judgment_metadata={"type": "Cassatie", "document_type": "Uitspraak"},
            related_eclis=[GH],
        ),
        _rs(HR2, related_eclis=[]),
        _rs(HR3, later_eclis=[]),
        _rs(RB, related_eclis=[GH, RB2], case_number_keys=[]),
        # one that names only the instance that ruled on appeal of it
        _rs(RB2, later_eclis=[GH]),
    )
    rows = list(queries.judgments_with_related_eclis(store))
    assert rows == [
        {
            "j_id": _jid(HR1),
            "ecli": HR1,
            "date": "2020-05-01",
            "case_number": "19/01234",
            "case_number_keys": ["19/01234"],
            "procedure_type": "Cassatie",
            "related_eclis": [GH],
            "later_eclis": [],
        },
        {
            "j_id": _jid(RB),
            "ecli": RB,
            "date": None,
            "case_number": None,
            # an empty array is true for OR: it stays
            "case_number_keys": [],
            "procedure_type": None,
            "related_eclis": [GH, RB2],
            "later_eclis": [],
        },
        {
            "j_id": _jid(RB2),
            "ecli": RB2,
            "date": None,
            "case_number": None,
            "case_number_keys": [],
            "procedure_type": None,
            "related_eclis": [],
            "later_eclis": [GH],
        },
    ]
    assert list(rows[0]) == [
        "j_id",
        "ecli",
        "date",
        "case_number",
        "case_number_keys",
        "procedure_type",
        "related_eclis",
        "later_eclis",
    ]


def test_judgment_instances(store: GraphStore) -> None:
    _seed(
        store,
        _rs(
            HR1,
            date_eff="2020-05-01",
            case_number="19/01234",
            case_number_keys=["19/01234"],
            judgment_metadata={"type": "Cassatie"},
            court_code="HR",
        ),
        _rs(PHR, court_code="PHR", case_number_keys=None),
        _rs(GH, court_code="GHAMS", judgment_metadata={"document_type": "Conclusie"}),
    )
    rows = list(queries.judgment_instances(store, [HR1, PHR, GH, RB]))
    assert rows == [
        {
            "ecli": GH,
            "id": _jid(GH),
            "date": None,
            "case_number": None,
            "case_number_keys": [],
            "procedure": None,
            "is_conclusion": True,
        },
        {
            "ecli": HR1,
            "id": _jid(HR1),
            "date": "2020-05-01",
            "case_number": "19/01234",
            "case_number_keys": ["19/01234"],
            "procedure": "Cassatie",
            "is_conclusion": False,
        },
        {
            "ecli": PHR,
            "id": _jid(PHR),
            "date": None,
            "case_number": None,
            "case_number_keys": [],
            "procedure": None,
            "is_conclusion": True,
        },
    ]


def test_postgres_regex_turns_word_boundaries() -> None:
    assert queries._postgres_regex(r"\bab\b") == r"\yab\y"
    assert queries._postgres_regex(r"\\b") == r"\\b"
    assert queries._postgres_regex(r"\\\b") == r"\\\y"


def test_appeals_to_read(store: GraphStore) -> None:
    paragraphs = [{"nr": "1", "text": "een"}, {"text": "twee"}, "los", {"text": "drie"}]
    _seed(
        store,
        # read: the procedure matches (case-insensitive), no earlier instance named
        _rs(HR1, judgment_metadata={"type": "Hoger beroep"}, paragraphs=paragraphs),
        # not read (an earlier instance named) but with unresolved targets
        _rs(
            HR2,
            judgment_metadata={"type": "cassatie"},
            related_eclis=[GH],
            unresolved_appeal_targets=[{"date": "2019-01-01"}],
            paragraphs=paragraphs,
        ),
        # no word boundary after "cassatie": not an appeal
        _rs(HR3, judgment_metadata={"type": "Cassatieberoep"}),
        # read, without paragraphs, and with targets
        _rs(
            RB,
            judgment_metadata={"type": "Verwijzing na cassatie"},
            unresolved_appeal_targets=[],
        ),
        # no procedure, targets null: not at all
        _rs(RB2, unresolved_appeal_targets=None),
        _judgment(GH, source="echr", judgment_metadata={"type": "Hoger beroep"}),
    )
    rows = list(
        queries.appeals_to_read(store, procedure=APPEAL_PROCEDURE.pattern, paragraphs=3)
    )
    assert rows == [
        {
            "key": _key(HR1),
            "j_id": _jid(HR1),
            "ecli": HR1,
            "read": True,
            "paragraphs": [{"text": "een"}, {"text": "twee"}, {"text": None}],
            "unresolved_appeal_targets": None,
        },
        {
            "key": _key(HR2),
            "j_id": _jid(HR2),
            "ecli": HR2,
            "read": False,
            "paragraphs": [],
            "unresolved_appeal_targets": [{"date": "2019-01-01"}],
        },
        {
            "key": _key(RB),
            "j_id": _jid(RB),
            "ecli": RB,
            "read": True,
            "paragraphs": [],
            "unresolved_appeal_targets": [],
        },
    ]
    assert list(rows[0]) == [
        "key",
        "j_id",
        "ecli",
        "read",
        "paragraphs",
        "unresolved_appeal_targets",
    ]


def test_judgments_on_dates_and_the_conclusions_among_them(store: GraphStore) -> None:
    _seed(
        store,
        _rs(HR2, date_eff="2020-05-01", case_number="1", court_code="HR"),
        _rs(HR1, date_eff="2020-05-01", court_code="HR"),
        _rs(PHR, date_eff="2020-05-01", court_code="PHR"),
        _rs(
            GH, date_eff="2020-05-01", judgment_metadata={"document_type": "Conclusie"}
        ),
        _rs(RB, date_eff="2019-01-01"),  # no court code: not a conclusion court
        _rs(RB2, date_eff="2018-01-01"),
        {"_key": "no-ecli", "type": "judgment", "props": {"date_eff": "2020-05-01"}},
    )
    rows = list(queries.judgments_on_dates(store, ["2020-05-01", "2019-01-01"]))
    # every judgment of the dates, from the columns and the light table
    assert {row["ecli"] for row in rows} == {HR1, HR2, PHR, GH, RB}
    assert {"ecli": HR2, "date": "2020-05-01", "case_number": "1"} in rows
    # the conclusions among them: by court and by document type
    assert queries.conclusions_among(store, [HR1, HR2, PHR, GH, RB]) == {
        PHR.upper(),
        GH.upper(),
    }
    # a judgment not kept light yet reads its case number from its props
    store.execute("DELETE FROM lg_judgment_light")
    assert {"ecli": HR2, "date": "2020-05-01", "case_number": "1"} in list(
        queries.judgments_on_dates(store, ["2020-05-01"])
    )


# ── conclusions ──────────────────────────────────────────────────────────────


def test_conclusion_rows(store: GraphStore) -> None:
    _seed(
        store,
        _rs(
            PHR,
            court_code="PHR",
            date_eff="2020-01-01",
            case_number="19/01234",
            case_number_keys=["19/01234"],
        ),
        _rs(HR1, court_code="HR", conclusion_eclis=[PHR], date_eff="2020-05-01"),
        _rs(HR2, court_code="HR", conclusion_eclis=[]),
        _rs(GH, judgment_metadata={"document_type": "Conclusie"}),
        _judgment(RB, source="echr", court_code="PHR"),
    )
    rows = list(queries.conclusion_rows(store))
    assert rows == [
        {
            "ecli": GH,
            "court_code": None,
            "date": None,
            "case_number": None,
            "is_conclusion": True,
            "conclusion_eclis": [],
            "case_number_keys": [],
        },
        {
            "ecli": HR1,
            "court_code": "HR",
            "date": "2020-05-01",
            "case_number": None,
            "is_conclusion": False,
            "conclusion_eclis": [PHR],
            "case_number_keys": [],
        },
        {
            "ecli": PHR,
            "court_code": "PHR",
            "date": "2020-01-01",
            "case_number": "19/01234",
            "is_conclusion": True,
            "conclusion_eclis": [],
            "case_number_keys": ["19/01234"],
        },
    ]
    assert list(rows[0]) == [
        "ecli",
        "court_code",
        "date",
        "case_number",
        "is_conclusion",
        "conclusion_eclis",
        "case_number_keys",
    ]


def test_judgments_by_case_keys_one_row_per_key_in_the_order_of_the_keys(
    store: GraphStore,
) -> None:
    _seed(
        store,
        _rs(HR2, case_number_keys=["a", "b"], court_code="HR", date_eff="2020-05-01"),
        _rs(HR1, case_number_keys=["b"], court_code="HR"),
        _rs(PHR, case_number_keys=["a"], court_code="PHR"),
        _rs(RB, case_number_keys="b"),  # not an array: no key
    )
    rows = list(queries.judgments_by_case_keys(store, ["b", "a", "c"]))
    assert rows == [
        {
            "key": "b",
            "ecli": HR1,
            "court_code": "HR",
            "date": None,
            "is_conclusion": False,
        },
        {
            "key": "b",
            "ecli": HR2,
            "court_code": "HR",
            "date": "2020-05-01",
            "is_conclusion": False,
        },
        {
            "key": "a",
            "ecli": HR2,
            "court_code": "HR",
            "date": "2020-05-01",
            "is_conclusion": False,
        },
        {
            "key": "a",
            "ecli": PHR,
            "court_code": "PHR",
            "date": None,
            "is_conclusion": True,
        },
    ]


def test_court_decisions_between(store: GraphStore) -> None:
    _seed(
        store,
        _rs(HR2, court_code="RVS", date_eff="2021-01-01", case_number="2"),
        _rs(HR1, court_code="RVS", date_eff="2020-01-01", case_number="1"),
        _rs(HR3, court_code="RVS", date_eff="2023-01-02"),  # after the end
        _rs(
            PHR,
            court_code="RVS",
            date_eff="2021-01-01",
            judgment_metadata={"document_type": "Conclusie"},
        ),
        _rs(GH, court_code="CRVB", date_eff="2021-06-01"),
        _rs(RB, date_eff="2021-06-01"),  # no court code
        _rs(RB2, court_code="RVS"),  # no date
    )
    spans: list[Any] = [
        {"court_code": "CRVB", "start": "2021-01-01", "end": "2023-01-01"},
        {"court_code": "RVS", "start": "2020-06-01", "end": "2023-01-01"},
        {"court_code": "RVS", "start": "2020-01-01", "end": "2023-01-01"},
        {"court_code": None, "start": "2021-01-01", "end": "2022-01-01"},
    ]
    rows = list(queries.court_decisions_between(store, spans))
    assert rows == [
        {"court_code": "CRVB", "ecli": GH, "date": "2021-06-01", "case_number": None},
        {"court_code": "RVS", "ecli": HR2, "date": "2021-01-01", "case_number": "2"},
        # HR2 again for the third span: once, where it came first
        {"court_code": "RVS", "ecli": HR1, "date": "2020-01-01", "case_number": "1"},
        {"court_code": None, "ecli": RB, "date": "2021-06-01", "case_number": None},
    ]
    assert list(queries.court_decisions_between(store, [])) == []


# ── referrals ────────────────────────────────────────────────────────────────


def test_preliminary_rulings(store: GraphStore) -> None:
    ruling = {"type": "Prejudiciële beslissing"}
    _seed(
        store,
        _rs(
            HR2,
            judgment_metadata=ruling,
            paragraphs=[{"text": "a", "nr": "1"}, "b", "c"],
        ),
        _rs(HR1, judgment_metadata=ruling, related_eclis=[RB]),
        _rs(HR3, judgment_metadata={"type": "Cassatie"}),
    )
    rows = list(queries.preliminary_rulings(store, paragraphs=2))
    assert rows == [
        {"ecli": HR1, "related_eclis": [RB], "paragraphs": []},
        {
            "ecli": HR2,
            "related_eclis": [],
            "paragraphs": [{"text": "a", "nr": "1"}, "b"],
        },
    ]
    # the paragraph objects keep the order of their keys
    assert list(rows[1]["paragraphs"][0]) == ["text", "nr"]


# ── series ───────────────────────────────────────────────────────────────────


def test_generic_summaries(store: GraphStore) -> None:
    template = "Uitspraak in de zaak van"
    _seed(
        store,
        _rs(HR1, summary=template, date_eff="2020-01-01"),
        _rs(HR2, summary=template, date_eff="2020-01-01"),
        _rs(HR3, summary=template, date_eff="2020-01-02"),
        _rs(RB, summary=template),  # no date: one more
        _rs(RB2, summary="Eigen samenvatting", date_eff="2020-01-01"),
        _rs(GH, summary=None, date_eff="2020-01-05"),
        _judgment(
            ECHR, source="echr", summary="Eigen samenvatting", date_eff="2021-01-01"
        ),
    )
    assert list(queries.generic_summaries(store, min_dates=3)) == [
        summary_fingerprint(template)
    ]
    assert list(queries.generic_summaries(store, min_dates=1)) == sorted(
        [summary_fingerprint(template), summary_fingerprint("Eigen samenvatting")]
    )
    assert list(queries.generic_summaries(store, min_dates=4)) == []


def _day(ecli: str, **props: Any) -> dict[str, Any]:
    return _rs(ecli, court_code="RBAMS", date_eff="2020-01-01", **props)


def test_judgment_court_days(store: GraphStore) -> None:
    _seed(
        store,
        _day(RB2, tier="eerste", court="Rechtbank Amsterdam"),
        _day(RB, tier="beroep"),
        _day(GH, tier="eerste", court="Rechtbank Amsterdam"),
        _day(HR3, court="Rechtbank Amsterdam (zp)"),
        _rs(HR1, court_code="HR", date_eff="2020-01-01", tier="hoogste"),
        _rs(HR2, court_code="HR", date_eff="2019-01-01"),
        _rs(PHR, court_code="HR", date_eff="2019-01-01", stub=True),
        _judgment(STUB, source="rechtspraak", court_code="HR", date_eff="2019-01-01"),
        _rs(ECHR, date_eff="2019-01-01"),  # no court code
    )
    days = list(queries.judgment_court_days(store))
    assert days == [
        {
            "court_code": "RBAMS",
            "date": "2020-01-01",
            "tier": "eerste",
            # by key: GH, HR3, RB, RB2; RB has no court
            "courts": ["Rechtbank Amsterdam", "Rechtbank Amsterdam (zp)", None],
        }
    ]
    assert list(days[0]) == ["court_code", "date", "tier", "courts"]
    given = list(queries.judgment_court_days(store, eclis=[HR1, HR2, PHR, ECHR]))
    assert given == [
        {"court_code": "HR", "date": "2019-01-01", "tier": None, "courts": [None]},
        {"court_code": "HR", "date": "2020-01-01", "tier": "hoogste", "courts": [None]},
    ]


def test_judgments_of_court_day(store: GraphStore) -> None:
    _seed(
        store,
        _day(
            RB2,
            court="Rechtbank Amsterdam",
            text="tekst",
            summary="sam",
            judgment_metadata={"document_type": "Uitspraak"},
            case_number_keys=["c/13/1"],
            series_id="s1",
            series_size=2,
        ),
        _day(RB),  # no tier, no court
        _day(GH, tier="eerste"),
        _day(HR3, court="Rechtbank Amsterdam", stub=True),
        _day(HR1, court="Elders"),
    )
    rows = list(
        queries.judgments_of_court_day(
            store,
            court_code="RBAMS",
            date="2020-01-01",
            tier=None,
            courts=[None, "Rechtbank Amsterdam"],
            batch_size=1,
        )
    )
    assert rows == [
        {
            "key": _key(RB),
            "ecli": RB,
            "text": None,
            "summary": None,
            "document_type": None,
            "case_number_keys": [],
            "series_id": None,
            "series_size": None,
        },
        {
            "key": _key(RB2),
            "ecli": RB2,
            "text": "tekst",
            "summary": "sam",
            "document_type": "Uitspraak",
            "case_number_keys": ["c/13/1"],
            "series_id": "s1",
            "series_size": 2,
        },
    ]
    tiered = queries.judgments_of_court_day(
        store,
        court_code="RBAMS",
        date="2020-01-01",
        tier="eerste",
        courts=[None],
        batch_size=10,
    )
    assert [r["ecli"] for r in tiered] == [GH]
    named = queries.judgments_of_court_day(
        store,
        court_code="RBAMS",
        date="2020-01-01",
        tier=None,
        courts=["Rechtbank Amsterdam"],
        batch_size=10,
    )
    assert [r["ecli"] for r in named] == [RB2]


def test_judgments_in_series_and_replaced_judgments(store: GraphStore) -> None:
    _seed(
        store,
        _rs(HR2, series_id="s1", replaced_by=HR3),
        _rs(HR1, series_id="s1", same_as=None),
        _rs(HR3, series_id=None, same_as=HR2),
        _rs(RB),
    )
    assert list(queries.judgments_in_series(store)) == [HR1, HR2]
    rows = list(queries.replaced_judgments(store))
    assert rows == [
        {
            "id": _jid(HR2),
            "key": _key(HR2),
            "ecli": HR2,
            "replaced_by": HR3,
            "same_as": None,
        },
        {
            "id": _jid(HR3),
            "key": _key(HR3),
            "ecli": HR3,
            "replaced_by": None,
            "same_as": HR2,
        },
    ]
    assert list(rows[0]) == ["id", "key", "ecli", "replaced_by", "same_as"]


# ── ECHR ─────────────────────────────────────────────────────────────────────


def test_echr_judgments(store: GraphStore) -> None:
    _seed(
        store,
        {
            "_key": "echr-2",
            "type": "judgment",
            "props": {"source": "echr", "conclusion": "Violation of Article 6"},
        },
        {
            "_key": "echr-1",
            "type": "judgment",
            "props": {"source": "echr", "articles": ["6", "P1-1"], "conclusion": None},
        },
        {"_key": "echr-3", "type": "judgment", "props": {"source": "echr"}},
        _rs(HR1, articles=["6"]),
    )
    rows = list(queries.echr_judgments(store))
    assert rows == [
        {
            "j_id": "judgments/echr-1",
            "j_key": "echr-1",
            "articles": ["6", "P1-1"],
            "conclusion": None,
        },
        {
            "j_id": "judgments/echr-2",
            "j_key": "echr-2",
            "articles": None,
            "conclusion": "Violation of Article 6",
        },
    ]


# ── edges and stubs ──────────────────────────────────────────────────────────


def test_procedural_neighbours_either_way(store: GraphStore) -> None:
    a, b, c = _jid(HR1), _jid(HR2), _jid(GH)
    store.bulk_insert_or_update_edges(
        [
            _edge(c, a, "APPEAL_OF", "e3"),
            _edge(a, b, "SAME_AS", "e2"),
            _edge(a, a, "SAME_AS", "e1"),
            _edge(a, c, "REFERS_TO", "e0"),
            _edge(b, c, "SAME_AS", "e4"),
        ]
    )
    relations = ["APPEAL_OF", "SAME_AS"]
    rows = list(queries.procedural_neighbours(store, [a, b], relations))
    assert rows == [[a, a], [a, b], [a, c], [b, a], [b, c]]
    assert list(queries.procedural_neighbours(store, [b, a], relations, chunk=1)) == [
        [b, a],
        [b, c],
        [a, a],
        [a, b],
        [a, c],
    ]
    assert list(queries.procedural_neighbours(store, [], relations)) == []


def test_remove_unreached_judgment_stubs(store: GraphStore) -> None:
    _seed(
        store,
        _rs(HR1),
        _judgment(STUB, stub=True),  # cited: stays
        _judgment(GH, stub=True),  # cites: stays
        _judgment(RB, stub=True),  # nothing: goes
        _judgment(RB2, stub=True),  # nothing: goes
        _judgment(HR2),  # no stub prop, nothing: stays
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(_jid(HR1), _jid(STUB), "REFERS_TO", "e1"),
            _edge(_jid(GH), "articles/x", "REFERS_TO", "e2"),
        ]
    )
    assert queries.remove_unreached_judgment_stubs(store) == 2
    left = store.query("SELECT ecli FROM judgments ORDER BY key")
    assert sorted(left) == sorted([HR1, STUB, GH, HR2])
    assert queries.remove_unreached_judgment_stubs(store) == 0


# ── normalize: translations ──────────────────────────────────────────────────


def test_translated_judgments(store: GraphStore) -> None:
    _seed(
        store,
        # the translation itself carries the case number too
        _rs(
            RB2,
            court_code="RBAMS",
            date_eff="2020-01-01",
            case_number_keys=["c/1"],
            summary_en="English",
        ),
        _rs(
            RB,
            court_code="RBAMS",
            date_eff="2020-01-01",
            case_number_keys=["x", "c/1"],
            summary="Nederlands",
            display_name="RB",
        ),
        _rs(
            GH,
            court_code="RBAMS",
            date_eff="2020-01-01",
            case_number_keys=["c/1"],
            summary="Later by key",
        ),
        _rs(
            HR1,
            court_code="RBAMS",
            date_eff="2020-01-01",
            case_number_keys=["c/2"],
            summary=None,
        ),
        _rs(HR2, date_eff="2020-01-02", case_number_keys=["c/3"], summary="Zonder hof"),
    )
    rows = [
        {"key": "t-3", "court_code": None, "date": "2020-01-02", "case_key": "c/3"},
        {
            "key": _key(RB2),
            "court_code": "RBAMS",
            "date": "2020-01-01",
            "case_key": "c/1",
        },
        {"key": "t-2", "court_code": "RBAMS", "date": "2020-01-01", "case_key": "c/2"},
        {"key": "t-4", "court_code": "RBAMS", "date": "2020-01-02", "case_key": "c/1"},
    ]
    found = list(normalize_queries.translated_judgments(store, rows))
    assert found == [
        {
            "key": "t-3",
            "original": {"key": _key(HR2), "ecli": HR2, "summary": "Zonder hof"},
        },
        {
            "key": _key(RB2),
            # GH sorts before RB by key ("ecli-nl-ghams..." < "ecli-nl-rbams...")
            "original": {"key": _key(GH), "ecli": GH, "summary": "Later by key"},
        },
    ]
    assert [list(f) for f in found] == [["key", "original"]] * 2
    assert list(found[0]["original"]) == ["key", "ecli", "summary"]
    assert list(normalize_queries.translated_judgments(store, [])) == []


def test_update_judgment_props(store: GraphStore) -> None:
    _seed(
        store,
        _rs(RB2, summary_en="English", court_code="RBAMS"),
        _rs(RB, summary="Nederlands", court_code="RBAMS"),
        _rs(HR1, summary="Gelijk", translation_of=None),
    )
    updates = [
        {"key": _key(RB2), "props": {"summary": "Nederlands", "translation_of": RB}},
        {"key": _key(RB), "props": {"summary_en": "English"}},
        # the same as stored: no change (a None for a missing key neither)
        {
            "key": _key(HR1),
            "props": {"summary": "Gelijk", "translation_of": None, "summary_en": None},
        },
        {"key": "missing", "props": {"summary": "x"}},
        # a key twice: written twice, in order
        {
            "key": _key(RB),
            "props": {"summary_en": "English, revised", "nested": {"b": 1, "a": 2}},
        },
    ]
    assert normalize_queries.update_judgment_props(store, updates) == 3
    rb2 = _props(store, RB2)
    assert rb2 == {
        "court_code": "RBAMS",
        "ecli": RB2,
        "source": "rechtspraak",
        "stub": False,
        "summary": "Nederlands",
        "summary_en": "English",
        "translation_of": RB,
    }
    # every key in the order of the collation (D11)
    assert list(rb2) == sorted(rb2)
    rb = _props(store, RB)
    assert list(rb) == [
        "court_code",
        "ecli",
        "nested",
        "source",
        "stub",
        "summary",
        "summary_en",
    ]
    assert rb["summary_en"] == "English, revised"
    # nested objects keep the order of their keys
    assert list(rb["nested"]) == ["b", "a"]
    # untouched: still in the order it was written
    assert list(_props(store, HR1)) == [
        "ecli",
        "source",
        "stub",
        "summary",
        "translation_of",
    ]

    # a None overwrites a value, and is stored as null
    assert (
        normalize_queries.update_judgment_props(
            store,
            [{"key": _key(RB2), "props": {"summary": None, "translation_of": RB}}],
        )
        == 1
    )
    rb2 = _props(store, RB2)
    assert "summary" in rb2 and rb2["summary"] is None
    # numbers compare by value
    store.bulk_insert_or_update_nodes("judgments", [_rs(GH, series_size=2)])
    assert (
        normalize_queries.update_judgment_props(
            store, [{"key": _key(GH), "props": {"series_size": 2.0}}]
        )
        == 0
    )
    assert normalize_queries.update_judgment_props(store, []) == 0


@pytest.mark.parametrize("rows", [[{"key": "nothing", "props": {}}]])
def test_update_with_empty_props_changes_nothing(
    store: GraphStore, rows: list[dict[str, Any]]
) -> None:
    _seed(store, {"_key": "nothing", "type": "judgment", "props": {"a": 1}})
    assert normalize_queries.update_judgment_props(store, rows) == 0
    assert _props_raw(store, "nothing") == {"a": 1}


def _props_raw(store: GraphStore, key: str) -> dict[str, Any]:
    doc = store.get_document("judgments", key)
    assert doc is not None
    return doc["props"]
