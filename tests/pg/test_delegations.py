"""The regulations issued under a law (``/delegated``) and the basis of a regulation
(``/basis``) on a real PostgreSQL: the whole payload of each, and a plan whose work grows
with the number of regulations, not with its square (the Awb has thousands)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_BASED_ON, RELATION_REFERS_TO
from lawgraph.db import GraphStore
from lawgraph.db.queries.delegations import (
    _DELEGATED_BY_LAW_SQL,
    _DELEGATED_SUMMARY_SQL,
    count_expired_delegated,
    get_basis,
    get_delegated_by_law,
)
from tests.pg.plans import explain, plan_nodes

LAW = "BWBR0001000"
OTHER = "BWBR0001001"
REGULATIONS = 60  # BWBR0002000 … BWBR0002059
FIRST = "BWBR0002000"
SUB = "BWBR0003000"  # issued under an article of the first regulation
BOTH = "BWBR0003001"  # issued under the first regulation and under the law itself
REPEALED = "BWBR0003002"  # issued under the law, no longer in force (``date_expired``)
ON_REPEALED = "BWBR0003003"  # names only a repealed article of the law
OLD_LAW = "BWBR0001002"  # no longer in force
UNDER_OLD = "BWBR0003004"  # issued under the old law and under the first law
HUB_REFERRERS = 200  # articles elsewhere that refer to article 1 of the law


def _regulation(n: int) -> str:
    return f"BWBR{2000 + n:07d}"


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": ["BWB"], "props": props}


def _instrument(bwb: str, title: str, kind: str, **props: Any) -> dict[str, Any]:
    return _node(bwb.lower(), "instrument", bwb_id=bwb, title=title, kind=kind, **props)


def _article(bwb: str, number: int, **props: Any) -> dict[str, Any]:
    return _node(
        f"{bwb.lower()}_{number}",
        "article",
        bwb_id=bwb,
        article_number=str(number),
        position=number,
        display_name=f"Artikel {number}",
        text="Tekst van het artikel. " * 40,
        **props,
    )


def _id(bwb: str, number: int | None = None) -> str:
    if number is None:
        return f"instruments/{bwb.lower()}"
    return f"articles/{bwb.lower()}_{number}"


def _edge(key: str, source: str, target: str, relation: str, text: str) -> Any:
    return {
        "key": key,
        "from_id": source,
        "to_id": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {"text": text},
    }


def _seed(store: GraphStore) -> None:
    regulations = [_regulation(n) for n in range(REGULATIONS)]
    extra = (SUB, BOTH, REPEALED, ON_REPEALED)
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _instrument(LAW, "Algemene wet", "wet"),
            _instrument(OTHER, "Andere wet", "wet"),
            _instrument(OLD_LAW, "Oude wet", "wet", date_expired="2020-01-01"),
            _instrument(UNDER_OLD, "Besluit onder oude wet", "amvb"),
        ]
        + [
            _instrument(
                bwb,
                f"Regeling {bwb}",
                "amvb" if i % 2 else "ministeriele-regeling",
                **({"date_expired": "2021-01-01"} if bwb == REPEALED else {}),
            )
            for i, bwb in enumerate(regulations + list(extra))
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [_article(LAW, 1), _article(LAW, 2), _article(LAW, 3, repealed=True)]
        + [_article(OTHER, 5), _article(OLD_LAW, 1)]
        + [
            article
            for bwb in regulations + list(extra)
            for article in (
                _article(bwb, 1),
                _article(bwb, 2),
                _article(bwb, 3, repealed=True),
                _article(bwb, 4, stub=True),
            )
        ]
        + [_article("BWBR0004000", n) for n in range(1, HUB_REFERRERS + 1)],
    )
    edges = []
    for n, bwb in enumerate(regulations):
        basis = 1 + n % 2
        edges += [
            _edge(f"b{n}", _id(bwb), _id(LAW, basis), RELATION_BASED_ON, f"{basis}"),
            # a second edge of the same pair: the lowest key is the one
            _edge(f"c{n}", _id(bwb), _id(LAW, basis), RELATION_BASED_ON, "later"),
            _edge(f"r{n}", _id(bwb, 2), _id(LAW, basis), RELATION_REFERS_TO, "lid 1"),
            # a repealed and a stub article refer as well: neither counts
            _edge(f"s{n}", _id(bwb, 3), _id(LAW, basis), RELATION_REFERS_TO, "x"),
            _edge(f"t{n}", _id(bwb, 4), _id(LAW, basis), RELATION_REFERS_TO, "x"),
            # a reference to the law that is no basis of the regulation
            _edge(f"u{n}", _id(bwb, 1), _id(LAW, 3 - basis), RELATION_REFERS_TO, "y"),
        ]
    edges += [
        _edge("o0", _id(FIRST), _id(OTHER, 5), RELATION_BASED_ON, "5"),
        _edge("d0", _id(SUB), _id(FIRST, 1), RELATION_BASED_ON, "1"),
        _edge("d1", _id(BOTH), _id(FIRST, 1), RELATION_BASED_ON, "1"),
        _edge("d2", _id(BOTH), _id(LAW, 2), RELATION_BASED_ON, "2"),
        _edge("d3", _id(REPEALED), _id(LAW, 1), RELATION_BASED_ON, "1"),
        _edge("d5", _id(UNDER_OLD), _id(OLD_LAW, 1), RELATION_BASED_ON, "1"),
        _edge("d6", _id(UNDER_OLD), _id(LAW, 1), RELATION_BASED_ON, "1"),
        _edge("d4", _id(ON_REPEALED), _id(LAW, 3), RELATION_BASED_ON, "3"),
    ]
    edges += [
        _edge(f"h{n}", _id("BWBR0004000", n), _id(LAW, 1), RELATION_REFERS_TO, "h")
        for n in range(1, HUB_REFERRERS + 1)
    ]
    store.bulk_insert_or_update_edges(edges)
    store.vacuum_analyze()


def _summary(bwb: str) -> dict[str, Any]:
    return {"key": bwb.lower(), "bwb_id": bwb}


def _short(row: dict[str, Any]) -> dict[str, Any]:
    """A row with each instrument as its key and BWB-id, each article as its key, name,
    meta and the articles that refer to it."""

    def instrument(doc: dict[str, Any]) -> dict[str, Any]:
        return {"key": doc["key"], "bwb_id": doc["props"]["bwb_id"]}

    def article(a: dict[str, Any]) -> dict[str, Any]:
        short = {
            "key": a["key"],
            "article_number": a["article_number"],
            "display_name": a["display_name"],
            "meta": a["meta"],
        }
        if "referring" in a:
            short["referring"] = [article(r) for r in a["referring"]]
        return short

    short: dict[str, Any] = {"instrument": instrument(row["instrument"])}
    for part in ("also_based_on", "sub_delegated"):
        if part in row:
            short[part] = [
                {
                    "instrument": instrument(p["instrument"]),
                    "articles": [article(a) for a in p["articles"]],
                }
                for p in row[part]
            ]
    short["articles"] = [article(a) for a in row["articles"]]
    return short


def _named(bwb: str, number: int, text: str, referring: list[Any]) -> dict[str, Any]:
    return {
        "key": f"{bwb.lower()}_{number}",
        "article_number": str(number),
        "display_name": f"Artikel {number}",
        "meta": {"text": text},
        "referring": referring,
    }


def _plain(bwb: str, number: int, text: str) -> dict[str, Any]:
    return {
        "key": f"{bwb.lower()}_{number}",
        "article_number": str(number),
        "display_name": f"Artikel {number}",
        "meta": {"text": text},
    }


def test_the_regulations_issued_under_a_law(store: GraphStore) -> None:
    _seed(store)

    rows = {
        r["instrument"]["props"]["bwb_id"]: _short(r)
        for r in get_delegated_by_law(store, LAW.lower())
    }

    # every regulation in force on an article in force, once; the one issued under the
    # first regulation and the law both is an item of its own
    assert sorted(rows) == sorted(
        [_regulation(n) for n in range(REGULATIONS)] + [BOTH, UNDER_OLD]
    )
    assert rows[FIRST] == {
        "instrument": _summary(FIRST),
        "also_based_on": [
            {"instrument": _summary(OTHER), "articles": [_plain(OTHER, 5, "5")]}
        ],
        "sub_delegated": [
            {"instrument": _summary(SUB), "articles": [_plain(FIRST, 1, "1")]}
        ],
        # the lowest key of the pair, with the article in force of the regulation that
        # refers to it, not its repealed article or its stub
        "articles": [_named(LAW, 1, "1", [_plain(FIRST, 2, "lid 1")])],
    }
    second = _regulation(1)
    assert rows[second] == {
        "instrument": _summary(second),
        "also_based_on": [],
        "sub_delegated": [],
        "articles": [_named(LAW, 2, "2", [_plain(second, 2, "lid 1")])],
    }
    assert rows[BOTH] == {
        "instrument": _summary(BOTH),
        "also_based_on": [
            {"instrument": _summary(FIRST), "articles": [_plain(FIRST, 1, "1")]}
        ],
        "sub_delegated": [],
        "articles": [_named(LAW, 2, "2", [])],
    }
    assert get_delegated_by_law(store, "BWBR0099999") == []


def test_the_basis_of_a_regulation(store: GraphStore) -> None:
    _seed(store)

    rows = [_short(r) for r in get_basis(store, _id(FIRST))]

    # per law, by title: the Algemene wet before the Andere wet
    assert rows == [
        {
            "instrument": _summary(LAW),
            "articles": [_named(LAW, 1, "1", [_plain(FIRST, 2, "lid 1")])],
        },
        {"instrument": _summary(OTHER), "articles": [_named(OTHER, 5, "5", [])]},
    ]
    assert get_basis(store, _id(LAW)) == []


def test_the_work_grows_with_the_regulations_not_their_square(
    store: GraphStore,
) -> None:
    """Each regulation reads its own parts by its indexes. A join of two sets of all the
    regulations, which the planner counts at one row each, loops over the one for every
    row of the other: here some 470,000 rows of CTE scans instead of under 1,000. And the
    references are read from the regulation's articles, never from the article of the
    law they point at: that end is a hub (the 200 articles elsewhere here)."""
    _seed(store)
    params = {
        "bwb": LAW,
        "based_on": RELATION_BASED_ON,
        "refers_to": RELATION_REFERS_TO,
        "today": "2026-10-20",
        "validity": "in_force",
    }
    nodes = list(
        plan_nodes(explain(store, _DELEGATED_BY_LAW_SQL, params, analyze=True))
    )

    scanned = sum(
        n["Actual Rows"] * n["Actual Loops"]
        for n in nodes
        if n["Node Type"] == "CTE Scan"
    )
    assert scanned < 40 * REGULATIONS
    hub_reads = [
        n
        for n in nodes
        if n.get("Index Name") == "edges_to_cover"
        and RELATION_REFERS_TO in (n.get("Index Cond") or "")
    ]
    assert hub_reads == []


def test_the_regulations_no_longer_in_force_by_validity(store: GraphStore) -> None:
    _seed(store)

    def bwbs(validity: str, summary: bool = False) -> set[str]:
        rows = get_delegated_by_law(store, LAW, validity, summary)
        return {r["instrument"]["props"]["bwb_id"] for r in rows}

    in_force = bwbs("in_force")
    assert REPEALED not in in_force
    assert bwbs("expired") == {REPEALED}
    assert bwbs("all") == in_force | {REPEALED}
    assert count_expired_delegated(store, LAW) == 1
    assert count_expired_delegated(store, OTHER) == 0
    # the light form holds the same regulations, whatever the validity
    assert bwbs("all", summary=True) == bwbs("all")
    expired = get_delegated_by_law(store, LAW, "expired")[0]["instrument"]["props"]
    assert expired["date_expired"] == "2021-01-01"


def test_the_light_form_has_the_regulations_under_a_regulation(
    store: GraphStore,
) -> None:
    _seed(store)

    rows = {
        r["instrument"]["props"]["bwb_id"]: r
        for r in get_delegated_by_law(store, LAW, summary=True)
    }

    assert set(rows[FIRST]) == {"instrument", "articles", "sub_delegated"}
    assert [a["key"] for a in rows[FIRST]["articles"]] == [f"{LAW.lower()}_1"]
    assert [a for a in rows[FIRST]["articles"] if "referring" in a] == []
    # also the one issued under the law itself as well: the keten draws both its lines
    assert [
        (s["instrument"]["props"]["bwb_id"], [a["key"] for a in s["articles"]])
        for s in rows[FIRST]["sub_delegated"]
    ] == [(SUB, [f"{FIRST.lower()}_1"]), (BOTH, [f"{FIRST.lower()}_1"])]
    assert rows[_regulation(1)]["sub_delegated"] == []
    params = {
        "bwb": LAW,
        "based_on": RELATION_BASED_ON,
        "refers_to": RELATION_REFERS_TO,
        "today": "2026-10-20",
        "validity": "in_force",
    }
    nodes = list(
        plan_nodes(explain(store, _DELEGATED_SUMMARY_SQL, params, analyze=True))
    )
    scanned = sum(
        n["Actual Rows"] * n["Actual Loops"]
        for n in nodes
        if n["Node Type"] == "CTE Scan"
    )
    assert scanned < 40 * REGULATIONS


def test_the_basis_marks_the_laws_no_longer_in_force(store: GraphStore) -> None:
    _seed(store)

    rows = get_basis(store, _id(FIRST))

    assert [r["expired"] for r in rows] == [False, False]
    both = get_basis(store, _id(UNDER_OLD))
    # by title: the Algemene wet in force, the Oude wet not
    assert [(r["instrument"]["props"]["bwb_id"], r["expired"]) for r in both] == [
        (LAW, False),
        (OLD_LAW, True),
    ]
