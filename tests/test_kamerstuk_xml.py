"""The text and the sections of a Kamerstuk XML, on real papers of both dialects."""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest

from lawgraph.core import kamerstuk_xml
from lawgraph.core.kamerstuk_xml import ParsedKamerstuk, Section, parse_kamerstuk

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _paper(name: str) -> ParsedKamerstuk:
    return parse_kamerstuk((FIXTURES / f"{name}.xml").read_text(encoding="utf-8"))


def _by_heading(parsed: ParsedKamerstuk, start: str) -> list[Section]:
    return [s for s in parsed.sections if s.heading.startswith(start)]


def _outline(
    *headings: str, legacy: bool = False, opener: bool = True
) -> list[Section]:
    """The sections of a paper made of *headings* (flat, each with a paragraph)."""
    tag = "tuskop" if legacy else "tussenkop"
    lines = ["Algemeen" if not opener else "II. ARTIKELSGEWIJS", *headings]
    body = "".join(f"<{tag}>{h}</{tag}><al>Tekst bij {h}.</al>" for h in lines)
    if legacy:
        xml = f"<kamerwrk><body><stuk>{body}</stuk></body></kamerwrk>"
    else:
        xml = (
            "<officiele-publicatie><kamerstuk><stuk><algemeen><vrije-tekst>"
            f"{body}</vrije-tekst></algemeen></stuk></kamerstuk></officiele-publicatie>"
        )
    return parse_kamerstuk(xml).sections


def _shape(section: Section) -> tuple[Any, ...]:
    refs = [(r["number"], r["of"]) for r in section.article_refs]
    return (section.kind, section.number, section.number_scheme, refs)


# ── every paper ──────────────────────────────────────────────────────────────

PAPERS = [
    "kst_24138_3",
    "kst_24447_6",
    "kst_24507_3",
    "kst_25823_3",
    "kst_28844_269",
    "kst_31911_3",
    "kst_34468_3",
    "kst_35470_xiv_4",
    "kst_36750_3",
    "kst_37020_x_1",
]


@pytest.mark.parametrize("name", PAPERS)
def test_the_sections_are_offsets_into_the_text_and_nest(name: str) -> None:
    parsed = _paper(name)
    text = parsed.text
    by_id = {s.id: s for s in parsed.sections}
    assert len(by_id) == len(parsed.sections)
    assert [s.id for s in parsed.sections] == [
        f"s-{n}" for n in range(1, len(parsed.sections) + 1)
    ]
    for section in parsed.sections:
        assert 0 <= section.char_start < section.char_end <= len(text)
        assert text[section.char_start :].startswith(section.heading)
        if section.parent is None:
            assert section.level == 1
            continue
        parent = by_id[section.parent]
        assert int(parent.id[2:]) < int(section.id[2:])
        assert section.level == parent.level + 1
        assert parent.char_start < section.char_start
        assert section.char_end <= parent.char_end


@pytest.mark.parametrize("name", PAPERS)
def test_the_text_is_one_collapsed_line_per_block_without_markup(name: str) -> None:
    parsed = _paper(name)
    assert parsed.text and not re.search(r"</?[a-z][\w.-]*[ />]", parsed.text)
    for line in parsed.text.split("\n"):
        assert line and line == line.strip(" ")
        assert "  " not in line and "\xa0" not in line
    assert parsed.dialect in ("kamerwrk", "officiele-publicatie")


@pytest.mark.parametrize("name", PAPERS)
def test_parsing_twice_gives_the_same_result(name: str) -> None:
    xml = (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")
    first, second = parse_kamerstuk(xml), parse_kamerstuk(xml)
    assert first == second
    assert [s.as_dict() for s in first.sections] == [
        s.as_dict() for s in second.sections
    ]


def test_both_dialects_are_recognised() -> None:
    assert _paper("kst_25823_3").dialect == "kamerwrk"
    assert _paper("kst_36750_3").dialect == "officiele-publicatie"


# ── the artikelsgewijs part ──────────────────────────────────────────────────


def test_a_legacy_paper_with_an_opener_and_articles_with_onderdelen() -> None:
    parsed = _paper("kst_25823_3")
    assert parsed.structure_quality == "explicit" and not parsed.budget
    (opener,) = [s for s in parsed.sections if s.kind == "artikelsgewijs"]
    assert opener.heading == "II. ARTIKELSGEWIJZE TOELICHTING" and opener.number == "II"
    (article,) = [s for s in parsed.sections if s.kind == "article"]
    assert _shape(article) == ("article", "I", "roman", [("I", "self")])
    assert article.parent == opener.id and article.level == opener.level + 1
    parts = [s for s in parsed.sections if s.kind == "onderdeel"]
    assert [p.number for p in parts] == list("ABCDEF")
    assert all(p.parent == article.id and p.number_scheme == "letter" for p in parts)
    # the article spans its onderdelen; the last one ends with the paper
    assert article.char_end == parts[-1].char_end == len(parsed.text)
    # the general part is what comes before the opener
    assert parsed.sections[0].kind == "algemeen"
    assert parsed.sections[0].char_end == opener.char_start - 1


def test_a_modern_paper_with_divisies_and_roman_articles() -> None:
    parsed = _paper("kst_36750_3")
    assert parsed.structure_quality == "explicit"
    opener = next(s for s in parsed.sections if s.kind == "artikelsgewijs")
    assert opener.heading == "II. ARTIKELSGEWIJS" and opener.level == 1
    articles = [s for s in parsed.sections if s.kind == "article"]
    assert [a.number for a in articles] == ["I", "II"]
    assert all(a.parent == opener.id for a in articles)
    body = parsed.text[articles[0].char_start : articles[0].char_end]
    assert body.startswith("Artikel I\nDit wetsvoorstel beoogt artikel 2 van de")
    general = [s for s in parsed.sections if s.kind == "algemeen"]
    assert [s.number for s in general] == ["I", "1", "2", "3"]
    assert general[1].parent == general[0].id  # "1. Inleiding" is part of "I. ALGEMEEN"


def test_an_opener_can_be_a_bare_heading_of_a_wijzigingswet() -> None:
    parsed = _paper("kst_24507_3")
    assert parsed.structure_quality == "explicit"
    opener = next(s for s in parsed.sections if s.kind == "artikelsgewijs")
    assert opener.heading == "B. ARTIKELEN"
    article = next(s for s in parsed.sections if s.kind == "article")
    # onderdelen are numbered with bare letters, several to a heading
    parts = [s for s in parsed.sections if s.parent == article.id]
    assert [p.heading for p in parts] == ["A, B, D en F", "C", "E en G"]
    assert all(p.kind == "onderdeel" for p in parts)


def test_a_heading_with_several_articles_gives_several_references() -> None:
    parsed = _paper("kst_24447_6")
    (multi,) = _by_heading(parsed, "Artikelen I, II en III")
    assert _shape(multi) == (
        "article",
        "I",
        "roman",
        [("I", "self"), ("II", "self"), ("III", "self")],
    )
    (two,) = _by_heading(_paper("kst_24138_3"), "Artikelen II en III")
    assert [r["number"] for r in two.article_refs] == ["II", "III"]


def test_arabic_articles_and_the_ranges_and_lists_of_numbers() -> None:
    sections = _outline("Artikel 3", "Artikelen 4 en 5", "Artikelen 6 tot en met 8")
    assert [_shape(s) for s in sections[1:]] == [
        ("article", "3", "arabic", [("3", "self")]),
        ("article", "4", "arabic", [("4", "self"), ("5", "self")]),
        (
            "article",
            "6",
            "arabic",
            [("6", "self"), ("7", "self"), ("8", "self")],
        ),
    ]


def test_roman_arabic_letter_and_book_style_numbers() -> None:
    headings = [
        "Artikel II",
        "ARTIKEL IIA",
        "Artikel 3:159n",
        "Artikel 213kkb",
        "Artikel 1.6.20",
        "Artikel N",
        "Artikel 1a.",
    ]
    schemes = [(s.number, s.number_scheme) for s in _outline(*headings)[1:]]
    assert schemes == [
        ("II", "roman"),
        ("IIA", "roman"),
        ("3:159n", "book_article"),
        ("213kkb", "arabic"),
        ("1.6.20", "book_article"),
        ("N", "letter"),
        ("1a", "arabic"),
    ]
    paper = _paper("kst_31911_3")
    numbers = [
        (s.number, s.number_scheme) for s in paper.sections if s.kind == "article"
    ]
    assert ("I", "roman") in numbers and ("4:33a", "book_article") in numbers


def test_the_law_a_heading_names_and_the_article_it_points_at() -> None:
    parsed = _paper("kst_34468_3")
    (huisvesting,) = _by_heading(parsed, "ARTIKEL II (Huisvestingswet 2014)")
    assert huisvesting.law == "Huisvestingswet 2014"
    assert _shape(huisvesting) == ("article", "II", "roman", [("II", "self")])
    (boek,) = _by_heading(parsed, "ARTIKEL I (Boek 7")
    assert boek.law == "Boek 7 van het Burgerlijk Wetboek"

    (heading,) = _outline("Artikel I, onderdeel B (artikel 1a)")[1:]
    assert _shape(heading) == (
        "article",
        "I",
        "roman",
        [("I", "self"), ("1a", "unknown")],
    )
    (named,) = _outline("Artikel 4 (artikel 1a van de Wet op het toezicht)")[1:]
    assert named.article_refs[-1] == {"number": "1a", "of": "named_law"}
    assert named.law == "Wet op het toezicht"
    (of_law,) = _outline("Artikel 2 van de Woningwet")[1:]
    assert _shape(of_law) == ("article", "2", "arabic", [("2", "named_law")])
    assert of_law.law == "Woningwet"


def test_the_parenthesis_of_an_onderdeel_names_the_article_it_changes() -> None:
    parsed = _paper("kst_24138_3")
    (a,) = _by_heading(parsed, "Onderdeel A (artikel 1)")
    (b,) = _by_heading(parsed, "Onderdeel B (artikelen 29a en 29b)")
    assert [(r["number"], r["of"]) for r in a.article_refs] == [("1", "unknown")]
    assert [r["number"] for r in b.article_refs] == ["29a", "29b"]


def test_leden_onderdelen_and_ad_headings_hang_under_their_article() -> None:
    sections = _outline(
        "Artikel 3", "Eerste lid", "Tweede en derde lid", "Onderdeel a", "Ad b."
    )[1:]
    assert [(s.kind, s.number) for s in sections] == [
        ("article", "3"),
        ("lid", "1"),
        ("lid", "2"),
        ("onderdeel", "a"),
        ("onderdeel", "b"),
    ]
    article = sections[0]
    assert all(s.parent == article.id for s in sections[1:])
    assert all(s.char_end <= article.char_end for s in sections[1:])


def test_a_lid_heading_outside_an_article_is_a_heading_like_any_other() -> None:
    sections = _outline("Eerste lid", "Hoofdstuk 2", "Artikel 9")
    kinds = [s.kind for s in sections]
    assert kinds == ["artikelsgewijs", "other", "chapter", "article"]
    chapter, article = sections[2], sections[3]
    assert chapter.number == "2" and article.parent == chapter.id


def test_the_part_after_the_articles_is_not_one_of_them() -> None:
    sections = _outline("Artikel 1", "Onderdeel A", "Bijlage 1", "Onderdeel B")
    assert [(s.kind, s.parent is None) for s in sections[3:]] == [
        ("other", False),
        ("other", False),
    ]
    assert sections[3].heading == "Bijlage 1"


def test_articles_without_an_opener_are_an_implicit_structure() -> None:
    parsed = parse_kamerstuk(
        "<kamerwrk><body><stuk><tuskop>Artikel 1</tuskop><al>Een.</al>"
        "<tuskop>Artikel 2</tuskop><al>Twee.</al></stuk></body></kamerwrk>"
    )
    assert parsed.structure_quality == "implicit"
    assert [(s.kind, s.number) for s in parsed.sections] == [
        ("article", "1"),
        ("article", "2"),
    ]


def test_a_paper_without_articles_has_text_and_no_articles() -> None:
    parsed = _paper("kst_28844_269")
    assert parsed.structure_quality == "none"
    assert {s.kind for s in parsed.sections} == {"other"}
    assert "Lobbyregister Ierland" in parsed.text and len(parsed.text) > 10_000


# ── text ─────────────────────────────────────────────────────────────────────


def test_footnotes_are_moved_out_of_the_text() -> None:
    parsed = _paper("kst_28844_269")
    assert len(parsed.footnotes) == 15
    assert parsed.footnotes[0] == {"number": "1", "text": "Kamerstuk 28 844, nr. 266."}
    assert "nr. 266" not in parsed.text
    assert "In het debat met de vaste commissie voor Binnenlandse Zaken" in parsed.text


def test_a_legacy_footnote_and_its_marker() -> None:
    parsed = _paper("kst_24138_3")
    assert parsed.footnotes == [
        {
            "number": "1",
            "text": "Ter inzage gelegd bij de afdeling Parlementaire Documentatie.",
        }
    ]
    assert "Ter inzage gelegd" not in parsed.text


def test_tables_are_lines_of_tab_separated_cells_and_lists_are_lines() -> None:
    parsed = _paper("kst_35470_xiv_4")
    lines = parsed.text.split("\n")
    assert "< 50\t1\t2" in lines
    assert any(
        line.startswith("Omvang begrotingsartikel") and "\t" in line for line in lines
    )
    assert (
        "1. de departementale begrotingsstaat van het Ministerie van Landbouw, "
        "Natuur en Voedselkwaliteit;" in lines
    )


def test_the_header_and_the_signature_are_not_text() -> None:
    parsed = _paper("kst_36750_3")
    first = parsed.text.split("\n")[0]
    assert first == "MEMORIE VAN TOELICHTING"
    assert "Tweede Kamer der Staten-Generaal" not in parsed.text


def test_whitespace_and_inline_markup_collapse() -> None:
    parsed = parse_kamerstuk(
        "<kamerwrk><body><stuk><al>Een\n   <nadruk>vet</nadruk>\xa0woord,\n  en <sup>2</sup>"
        "<voetref refid='v1' nr='1'/>.</al><voetnoot nr='1'><al>Noot\n tekst</al></voetnoot>"
        "</stuk></body></kamerwrk>"
    )
    assert parsed.text == "Een vet woord, en 2."
    assert parsed.footnotes == [{"number": "1", "text": "Noot tekst"}]


# ── budget papers ────────────────────────────────────────────────────────────


def test_a_budget_paper_says_so() -> None:
    parsed = _paper("kst_35470_xiv_4")
    assert parsed.budget
    # its "articles" are the policy articles of the budget
    assert any(s.kind == "article" and s.number == "11" for s in parsed.sections)
    assert _paper("kst_37020_x_1").budget
    assert not _paper("kst_36750_3").budget


def test_a_legacy_budget_is_recognised_by_its_chapter_or_title() -> None:
    chapter = parse_kamerstuk(
        "<kamerwrk><frontm><onderw><nummer>27 400 XV</nummer><naam>Iets</naam></onderw>"
        "</frontm><body><stuk><al>Tekst.</al></stuk></body></kamerwrk>"
    )
    title = parse_kamerstuk(
        "<kamerwrk><frontm><onderw><nummer>24 738</nummer><naam>Wijziging van de begroting "
        "van de uitgaven en de ontvangsten van het Ministerie van Defensie</naam></onderw>"
        "</frontm><body><stuk><al>Tekst.</al></stuk></body></kamerwrk>"
    )
    ordinary = parse_kamerstuk(
        "<kamerwrk><frontm><onderw><nummer>25 823</nummer><naam>Wijziging van de Woningwet"
        "</naam></onderw></frontm><body><stuk><al>Tekst.</al></stuk></body></kamerwrk>"
    )
    assert (chapter.budget, title.budget, ordinary.budget) == (True, True, False)


# ── what is not a paper ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "xml",
    [
        "",
        "<html>Bad gateway",
        "<html><body>Bad gateway</body></html>",
        "not xml at all",
        "<kamerwrk><body><stuk><al>Afgebroken",
        '<?xml version="1.0"?><resultaat/>',
    ],
)
def test_what_is_no_kamerstuk_gives_an_empty_result_and_never_raises(xml: str) -> None:
    parsed = parse_kamerstuk(xml)
    assert parsed.text == "" and parsed.sections == []
    assert parsed.structure_quality == "none" and parsed.dialect is None


def test_a_byte_order_mark_does_not_matter() -> None:
    xml = (FIXTURES / "kst_36750_3.xml").read_text(encoding="utf-8")
    assert parse_kamerstuk("﻿" + xml) == parse_kamerstuk(xml)


def test_a_paper_without_text_has_no_text() -> None:
    assert parse_kamerstuk("<kamerwrk><body><stuk/></body></kamerwrk>").text == ""


def test_odd_headings_do_not_break_the_parser() -> None:
    parsed = parse_kamerstuk(
        "<kamerwrk><body><stuk><tuskop></tuskop><tuskop>  </tuskop><tuskop>§</tuskop>"
        "<tuskop>Artikel</tuskop><tuskop>Artikel 99999999999999999999</tuskop>"
        "<tuskop>Onderdeel</tuskop><tuskop>I.</tuskop><tuskop>Ad</tuskop>"
        "</stuk></body></kamerwrk>"
    )
    assert parsed.text and parsed.dialect == "kamerwrk"


def test_a_failure_in_the_structure_keeps_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: Any) -> list[Section]:
        raise RuntimeError("a paper nobody expected")

    monkeypatch.setattr(kamerstuk_xml, "_sections", broken)
    parsed = _paper("kst_36750_3")
    assert parsed.text.startswith("MEMORIE VAN TOELICHTING")
    assert parsed.sections == [] and parsed.structure_quality == "none"
    assert parsed.dialect == "officiele-publicatie"


# ── the cap ──────────────────────────────────────────────────────────────────


def test_a_paper_over_the_cap_is_cut_at_a_line_and_says_so() -> None:
    whole = _paper("kst_36750_3")
    assert not whole.truncated and len(whole.text) < kamerstuk_xml.MAX_TEXT_CHARS
    xml = (FIXTURES / "kst_36750_3.xml").read_text(encoding="utf-8")
    cut = parse_kamerstuk(xml, max_chars=8000)
    assert cut.truncated and 0 < len(cut.text) <= 8000
    assert whole.text.startswith(cut.text)
    assert whole.text[len(cut.text)] == "\n"  # whole lines only
    assert cut.sections and all(s.char_end <= len(cut.text) for s in cut.sections)
    # the articles are past the cut
    assert not [s for s in cut.sections if s.kind == "article"]


def test_the_cap_is_above_the_longest_paper_seen() -> None:
    assert kamerstuk_xml.MAX_TEXT_CHARS > 1_100_000


def test_a_long_heading_is_read_in_linear_time() -> None:
    """A line read as an article heading can be a whole table row: ", " parts with spaces
    around them and no "van de" made the law pattern try every way to split it (minutes on
    kst-34939-3 and kst-33161-3)."""
    import time

    from lawgraph.core.kamerstuk_xml import _law_and_refs

    rest = "".join(f" ,  deel  {i}  " for i in range(60))
    started = time.perf_counter()
    refs, law = _law_and_refs(rest, ["1"])
    assert time.perf_counter() - started < 0.5
    assert law is None and refs == [{"number": "1", "of": "self"}]
    named = _law_and_refs(", eerste lid, van de Huisvestingswet 2014", ["9"])[1]
    assert named == "Huisvestingswet 2014"


def test_the_article_a_part_of_a_bill_makes_is_read_from_its_parenthesis() -> None:
    from lawgraph.core.kamerstuk_xml import _law_and_refs

    refs, _ = _law_and_refs(" (nieuw artikel 13)", ["II"])
    assert refs == [{"number": "II", "of": "self"}, {"number": "13", "of": "unknown"}]
    assert _law_and_refs(" (gewijzigd artikel 23, vierde lid)", ["I"])[0][-1] == {
        "number": "23",
        "of": "unknown",
    }
