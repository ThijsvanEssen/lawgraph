"""Which article of which law a section of a memorandum explains (pure, no store)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import RELATION_AMENDS, RELATION_INTRODUCES
from lawgraph.core.kamerstuk_xml import parse_kamerstuk
from lawgraph.core.mvt_articles import (
    CONFIDENCE_BODY_NAMED_LAW,
    CONFIDENCE_HEADING_TARGET,
    CONFIDENCE_INFERRED_LAW,
    CONFIDENCE_OWN_NUMBER,
    MATCH_BODY_NAMED_LAW,
    MATCH_HEADING_TARGET,
    MATCH_INFERRED_LAW,
    MATCH_OWN_NUMBER,
    Change,
    Law,
    Reference,
    article_id,
    explained_targets,
    find_references,
    is_introduction,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

KLIMAATFONDS = "BWBR0044234"
WONINGWET = "BWBR0005068"
HUISVESTINGSWET = "BWBR0035348"
AWB = "BWBR0005537"
NEW_LAW = "BWBR0099999"


def _fixture(name: str) -> tuple[str, list[dict[str, Any]]]:
    parsed = parse_kamerstuk((FIXTURES / f"{name}.xml").read_text(encoding="utf-8"))
    return parsed.text, [s.as_dict() for s in parsed.sections]


def _found(refs: list[Reference]) -> list[tuple[str, str, str, str]]:
    return [(r.section_id, r.bwb_id, r.number, r.match_type) for r in refs]


class _Paper:
    """A paper made of headings and bodies, with the sections the parser would find."""

    def __init__(self) -> None:
        self.text = ""
        self.sections: list[dict[str, Any]] = []

    def add(
        self,
        heading: str,
        body: str,
        *,
        kind: str = "article",
        number: str | None = None,
        scheme: str | None = None,
        refs: list[tuple[str, str]] | None = None,
        law: str | None = None,
        parent: str | None = None,
    ) -> str:
        start = len(self.text) + (1 if self.text else 0)
        block = f"{heading}\n{body}"
        self.text += ("\n" if self.text else "") + block
        section_id = f"s-{len(self.sections)}"
        self.sections.append(
            {
                "id": section_id,
                "heading": heading,
                "level": 2 if parent else 1,
                "parent": parent,
                "kind": kind,
                "number": number,
                "number_scheme": scheme,
                "article_refs": [{"number": n, "of": of} for n, of in refs or []],
                "law": law,
                "char_start": start,
                "char_end": start + len(block),
            }
        )
        return section_id


def test_a_new_law_names_its_own_article_by_number() -> None:
    paper = _Paper()
    paper.add(
        "Artikel 3",
        "Dit artikel regelt de aanvraag.",
        number="3",
        scheme="arabic",
        refs=[("3", "self")],
    )
    paper.add(
        "Artikelen 4 en 5",
        "Twee artikelen.",
        number="4",
        scheme="arabic",
        refs=[("4", "self"), ("5", "self")],
    )

    refs = find_references(paper.text, paper.sections, [], own_bwb_id=NEW_LAW)

    assert _found(refs) == [
        ("s-0", NEW_LAW, "3", MATCH_OWN_NUMBER),
        ("s-1", NEW_LAW, "4", MATCH_OWN_NUMBER),
        ("s-1", NEW_LAW, "5", MATCH_OWN_NUMBER),
    ]
    assert refs[0].confidence == CONFIDENCE_OWN_NUMBER
    assert (refs[0].char_start, refs[0].char_end) == (
        0,
        len(paper.sections[0]["heading"]) + 1 + len("Dit artikel regelt de aanvraag."),
    )


def test_a_roman_article_of_a_bill_is_no_article_of_a_law() -> None:
    paper = _Paper()
    paper.add(
        "Artikel I", "Regelt iets.", number="I", scheme="roman", refs=[("I", "self")]
    )
    paper.add(
        "Artikel F", "Regelt iets.", number="F", scheme="letter", refs=[("F", "self")]
    )

    assert find_references(paper.text, paper.sections, [], own_bwb_id=NEW_LAW) == []


def test_the_target_in_the_heading_names_the_article() -> None:
    paper = _Paper()
    paper.add(
        "Artikel I, onderdeel B (artikel 1a)",
        "Wijziging.",
        number="I",
        scheme="roman",
        refs=[("I", "self"), ("1a", "unknown")],
    )
    paper.add(
        "Onderdeel C (artikel 3 van de Woningwet)",
        "Wijziging.",
        kind="onderdeel",
        number="C",
        scheme="letter",
        refs=[("3", "named_law")],
        law="Woningwet",
    )
    laws = [Law(WONINGWET, ("Woningwet",))]

    refs = find_references(paper.text, paper.sections, laws)

    # the law of the first is the only law the dossier changes, the second names its own
    assert _found(refs) == [
        ("s-0", WONINGWET, "1a", MATCH_HEADING_TARGET),
        ("s-1", WONINGWET, "3", MATCH_HEADING_TARGET),
    ]
    assert refs[0].confidence == CONFIDENCE_HEADING_TARGET


def test_a_target_without_a_law_that_is_known_is_no_target() -> None:
    paper = _Paper()
    paper.add(
        "Artikel I, onderdeel B (artikel 1a)",
        "Wijziging.",
        number="I",
        scheme="roman",
        refs=[("I", "self"), ("1a", "unknown")],
    )
    # two laws are changed and the heading does not say which one
    laws = [Law(WONINGWET, ("Woningwet",)), Law(AWB, ("Algemene wet bestuursrecht",))]

    assert find_references(paper.text, paper.sections, laws) == []


def test_a_law_that_is_named_and_not_known_is_not_guessed() -> None:
    paper = _Paper()
    paper.add(
        "ARTIKEL II (Leegstandwet)",
        "",
        number="II",
        scheme="roman",
        refs=[("II", "self")],
        law="Leegstandwet",
    )
    paper.add(
        "Onderdeel A",
        "In dit onderdeel wordt artikel 5 gewijzigd.",
        kind="onderdeel",
        number="A",
        scheme="letter",
        parent="s-0",
    )

    # the only law that the dossier changes is not the one the enclosing heading names
    assert (
        find_references(paper.text, paper.sections, [Law(WONINGWET, ("Woningwet",))])
        == []
    )


def test_the_body_names_the_article_of_a_law_of_the_dossier() -> None:
    text, sections = _fixture("kst_36750_3")
    laws = [Law(KLIMAATFONDS, ("Tijdelijke wet Klimaatfonds",))]

    refs = find_references(text, sections, laws)

    assert _found(refs) == [("s-6", KLIMAATFONDS, "2", MATCH_BODY_NAMED_LAW)]
    assert refs[0].confidence == CONFIDENCE_BODY_NAMED_LAW
    # Artikel II (inwerkingtreding) names no article
    assert "s-7" not in {r.section_id for r in refs}


def test_a_number_without_a_law_is_of_the_only_law_the_dossier_changes() -> None:
    text, sections = _fixture("kst_25823_3")

    refs = find_references(text, sections, [Law(WONINGWET, ("Woningwet",))])
    assert {(r.section_id, r.number, r.match_type) for r in refs} >= {
        ("s-14", "2", MATCH_INFERRED_LAW),
        ("s-16", "23", MATCH_INFERRED_LAW),
    }
    assert all(r.bwb_id == WONINGWET for r in refs)
    assert CONFIDENCE_INFERRED_LAW < CONFIDENCE_BODY_NAMED_LAW

    # with two laws it is not known which one: only what names its law is left
    two = [Law(WONINGWET, ("Woningwet",)), Law(AWB, ("Awb",))]
    assert {r.match_type for r in find_references(text, sections, two)} == {
        MATCH_BODY_NAMED_LAW
    }


def test_a_heading_with_a_book_number_is_the_article_of_the_law_the_bill_changes() -> (
    None
):
    text, sections = _fixture("kst_31911_3")

    refs = find_references(text, sections, [Law(AWB, ("Algemene wet bestuursrecht",))])

    assert {(r.number, r.match_type) for r in refs} >= {
        ("4:33a", MATCH_INFERRED_LAW),
        ("4:74a", MATCH_INFERRED_LAW),
    }
    # both onderdelen of 4:33a name it: one reference per section
    assert [r.section_id for r in refs if r.number == "4:33a"] == ["s-14", "s-15"]


def test_a_heading_names_the_law_its_onderdelen_are_about() -> None:
    text, sections = _fixture("kst_34468_3")
    laws = [
        Law(HUISVESTINGSWET, ("Huisvestingswet 2014",)),
        Law(WONINGWET, ("Woningwet",)),
    ]

    by_section = {
        (r.section_id, r.bwb_id, r.number): r
        for r in find_references(text, sections, laws)
    }

    # "Onderdeel A" stands under ARTIKEL II (Huisvestingswet 2014); the Woningwet is named
    # in the body of "Onderdeel B", and cited for one article of its own
    assert (("s-9", HUISVESTINGSWET, "1")) in by_section
    assert by_section[("s-9", HUISVESTINGSWET, "1")].match_type == MATCH_BODY_NAMED_LAW
    assert (("s-19", WONINGWET, "2:11")) in by_section  # under ARTIKEL IX (Woningwet)
    assert by_section[("s-19", WONINGWET, "2:11")].match_type == MATCH_INFERRED_LAW


def test_the_law_the_bill_makes_is_not_one_it_changes() -> None:
    paper = _Paper()
    paper.add(
        "Artikel 3",
        "Zie artikel 2 van de Woningwet.",
        number="3",
        scheme="arabic",
        refs=[("3", "self")],
    )

    refs = find_references(
        paper.text, paper.sections, [Law(WONINGWET, ("Woningwet",))], own_bwb_id=NEW_LAW
    )

    assert _found(refs) == [
        ("s-0", NEW_LAW, "3", MATCH_OWN_NUMBER),
        ("s-0", WONINGWET, "2", MATCH_BODY_NAMED_LAW),
    ]


def test_a_section_names_an_article_once_the_surest_way_counts() -> None:
    paper = _Paper()
    paper.add(
        "Onderdeel A (artikel 3 van de Woningwet)",
        "In artikel 3 van de Woningwet staat het.",
        kind="onderdeel",
        number="A",
        scheme="letter",
        refs=[("3", "named_law")],
        law="Woningwet",
    )

    refs = find_references(paper.text, paper.sections, [Law(WONINGWET, ("Woningwet",))])

    assert _found(refs) == [("s-0", WONINGWET, "3", MATCH_HEADING_TARGET)]


def test_a_body_passage_is_the_text_before_the_first_subsection() -> None:
    paper = _Paper()
    parent = paper.add(
        "Artikel I",
        "Wijziging van artikel 2 van de Woningwet.",
        number="I",
        scheme="roman",
        refs=[("I", "self")],
    )
    paper.add(
        "Onderdeel A",
        "Iets anders.",
        kind="onderdeel",
        number="A",
        scheme="letter",
        parent=parent,
    )
    parent_end = paper.sections[0]["char_end"]
    # the parent spans its child: the child is appended after it in the text
    paper.sections[0]["char_end"] = paper.sections[1]["char_end"]

    refs = find_references(paper.text, paper.sections, [Law(WONINGWET, ("Woningwet",))])

    (reference,) = refs
    assert reference.char_end == parent_end  # not the whole of the section


def test_a_name_that_two_laws_share_names_neither() -> None:
    paper = _Paper()
    paper.add(
        "Artikel I",
        "Wijziging van artikel 2 van de Wet voorbeeld.",
        number="I",
        scheme="roman",
        refs=[("I", "self")],
    )
    laws = [
        Law("BWBR0000001", ("Wet voorbeeld",)),
        Law("BWBR0000002", ("Wet voorbeeld",)),
    ]

    assert find_references(paper.text, paper.sections, laws) == []


def test_a_book_of_a_code_is_named_as_it_is_titled() -> None:
    paper = _Paper()
    paper.add(
        "ARTIKEL I (Boek 7 van het Burgerlijk Wetboek)",
        "",
        number="I",
        scheme="roman",
        refs=[("I", "self")],
        law="Boek 7 van het Burgerlijk Wetboek",
    )
    paper.add(
        "Onderdeel A (artikel 1 van Boek 7 van het Burgerlijk Wetboek)",
        "",
        kind="onderdeel",
        number="A",
        scheme="letter",
        refs=[("1", "named_law")],
        law="Boek 7 van het Burgerlijk Wetboek",
    )
    laws = [Law("BWBR0005290", ("Burgerlijk Wetboek Boek 7",))]

    refs = find_references(paper.text, paper.sections, laws)

    assert _found(refs) == [("s-1", "BWBR0005290", "1", MATCH_HEADING_TARGET)]


# ── from the sections to the graph ───────────────────────────────────────────


def _change(
    number: str, *, version: str | None = None, relation: str = RELATION_AMENDS
) -> Change:
    return Change(
        bwb_id=WONINGWET,
        number=number,
        article=article_id(WONINGWET, number),
        version=version,
        relation=relation,
    )


def _reference(number: str, match_type: str, section: str = "s-1") -> Reference:
    return Reference(section, "heading", 2, 10, 20, WONINGWET, number, match_type)


def test_a_reference_points_at_the_version_the_change_created() -> None:
    changes = [_change("2", version="v_2"), _change("3")]
    refs = [
        _reference("2", MATCH_BODY_NAMED_LAW),
        _reference("3", MATCH_BODY_NAMED_LAW, "s-2"),
    ]

    explained = explained_targets(refs, changes, lambda article: False)

    assert set(explained) == {article_id(WONINGWET, "3"), "article_versions/v_2"}
    assert explained["article_versions/v_2"] == [refs[0]]


def test_an_article_that_was_not_changed_is_a_target_when_the_heading_states_it() -> (
    None
):
    refs = [
        _reference("9", MATCH_HEADING_TARGET),
        _reference("8", MATCH_BODY_NAMED_LAW, "s-2"),
        _reference("7", MATCH_HEADING_TARGET, "s-3"),
    ]
    existing = {article_id(WONINGWET, "9")}

    explained = explained_targets(refs, [], existing.__contains__)

    # 8 is only mentioned in the text; 7 does not exist
    assert list(explained) == [article_id(WONINGWET, "9")]


def test_numbers_are_compared_as_articles_are_stored() -> None:
    changes = [_change("1a"), _change("159n")]
    refs = [
        _reference("1A.", MATCH_BODY_NAMED_LAW),
        _reference("3:159n", MATCH_BODY_NAMED_LAW, "s-2"),
    ]

    explained = explained_targets(refs, changes, lambda article: False)

    assert set(explained) == {
        article_id(WONINGWET, "1a"),
        article_id(WONINGWET, "159n"),
    }


def test_a_law_is_new_when_the_dossier_changed_none_of_it_but_to_introduce_it() -> None:
    own = [
        _change("1", relation=RELATION_INTRODUCES),
        _change("2", relation=RELATION_INTRODUCES),
    ]
    assert is_introduction([], WONINGWET)  # a law whose history is not loaded
    assert is_introduction(own, WONINGWET)
    assert not is_introduction([*own, _change("3")], WONINGWET)
    assert is_introduction([_change("3")], "BWBR0000003")  # a change of another law
