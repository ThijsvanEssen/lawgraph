"""Delegation formulas in the text of an article, and which regulations fill them."""

from __future__ import annotations

from lawgraph.core.delegations import (
    DelegationClause,
    delegation_clauses,
    fills,
    kind_rank,
)

_TEXT = (
    "1. Bij of krachtens algemene maatregel van bestuur wordt het CSIRT aangewezen.\n"
    "2. Bij ministeriële regeling kunnen regels worden gesteld over:\n"
    "a. de melding.\n"
    "3. Het handelen in strijd met de bij algemene maatregel van bestuur gestelde regels "
    "is verboden."
)


def _parts(text: str) -> list[dict[str, object]]:
    first = text.index("1.") + 3
    second = text.index("2.")
    onder = text.index("a. de")
    third = text.index("3.")
    return [
        {
            "id": "lid-1",
            "kind": "lid",
            "number": "1.",
            "start": first,
            "end": second - 1,
        },
        {
            "id": "lid-2",
            "kind": "lid",
            "number": "2.",
            "start": second + 3,
            "end": third - 1,
        },
        {
            "id": "lid-2-onder-a",
            "kind": "onderdeel",
            "number": "a.",
            "start": onder + 3,
            "end": third - 1,
        },
        {
            "id": "lid-3",
            "kind": "lid",
            "number": "3.",
            "start": third + 3,
            "end": len(text),
        },
    ]


def test_the_formulas_of_an_article_with_their_lid() -> None:
    clauses = delegation_clauses(_TEXT, _parts(_TEXT))

    assert [(c.text, c.kind, c.krachtens, c.part, c.lid) for c in clauses] == [
        (
            "Bij of krachtens algemene maatregel van bestuur",
            "amvb",
            True,
            "lid-1",
            "1",
        ),
        ("Bij ministeriële regeling", "ministeriele_regeling", False, "lid-2", "2"),
    ]
    assert all(_TEXT[c.start : c.end] == c.text for c in clauses)


def test_rules_already_made_delegate_nothing() -> None:
    assert (
        delegation_clauses(
            "de bij of krachtens algemene maatregel van bestuur vastgestelde eisen"
        )
        == []
    )
    assert (
        delegation_clauses("de bij regeling van Onze Minister gegeven voorschriften")
        == []
    )
    assert [
        c.kind
        for c in delegation_clauses("bij regeling van Onze Minister te stellen regels")
    ] == ["ministeriele_regeling"]


def test_variants_of_the_formula() -> None:
    text = (
        "Bij algemene maatregel van rijksbestuur, bij een algemene maatregel van bestuur "
        "en bij ministeriele regeling; niet bij koninklijk besluit."
    )
    assert [c.kind for c in delegation_clauses(text)] == [
        "amvb",
        "amvb",
        "ministeriele_regeling",
    ]
    # without parts: no part, no lid
    assert delegation_clauses(text)[0].part is None
    assert delegation_clauses(None) == []


def _clause(
    kind: str, *, krachtens: bool = False, lid: str | None = "1"
) -> DelegationClause:
    return DelegationClause(0, 1, "x", kind, krachtens, "lid-1", lid)  # type: ignore[arg-type]


def test_a_regulation_fills_a_clause_of_its_type_and_lid() -> None:
    amvb = _clause("amvb")
    assert fills(amvb, "AMvB", ["1", "7"])
    assert fills(amvb, "AMvB", [])  # the whole article
    assert not fills(amvb, "AMvB", ["2"])
    assert not fills(amvb, "ministeriele-regeling", [])
    assert fills(_clause("amvb", krachtens=True), "ministeriele-regeling", ["1"])
    assert not fills(_clause("ministeriele_regeling"), "AMvB", [])
    assert fills(
        _clause("ministeriele_regeling", lid=None), "ministeriele-regeling", ["3"]
    )
    assert not fills(amvb, "KB", [])


def test_amvbs_come_first() -> None:
    assert sorted(["KB", "ministeriele-regeling", "AMvB", None], key=kind_rank) == [
        "AMvB",
        "ministeriele-regeling",
        "KB",
        None,
    ]
