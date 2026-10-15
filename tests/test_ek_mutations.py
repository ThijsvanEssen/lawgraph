"""The changes in the composition of the Eerste Kamer, read from its own pages: the items of
``/personele_mutaties``, a faction's own history, and the walk of a term's seats from the
Kiesraad's result to today, checked against today's composition."""

from __future__ import annotations

import json
import re

import pytest

from lawgraph.core import ek_composition as composition
from lawgraph.core import ek_mutations, ek_pages, ek_seat_walk
from lawgraph.core.kiesraad import parse_ek_result
from tests.paths import FIXTURES, fixture_text


def _page(name: str) -> str:
    return fixture_text(name, sub="eerstekamer")


def _articles() -> list[ek_pages.Article]:
    return [
        ek_pages.Article(a["headline"], a["date"], a["text"], a["persons"])
        for a in json.loads(fixture_text("articles_2023.json", sub="eerstekamer"))
    ]


def _by_headline(start: str) -> ek_pages.Article:
    return next(a for a in _articles() if a.headline.startswith(start))


def test_a_term_page_lists_its_items_and_the_terms_before() -> None:
    page = ek_pages.term_page(_page("personele_mutaties_2023.html"))
    assert page.title == "Personele mutaties huidige zittingsperiode"
    assert len(page.items) == 38
    oldest = min(page.items, key=lambda i: i.date)
    assert oldest == ek_pages.Listed(
        "2023-06-27",
        "Van de Sanden (VVD) geïnstalleerd als tijdelijk lid Eerste Kamer",
        "/nieuws/20230627/van_de_sanden_vvd_geinstalleerd",
    )
    assert len(page.terms) == 6  # 1999-2003 … 2019-2023
    assert ek_pages.term_page(_page("personele_mutaties_2019.html")).title == (
        "Personele mutaties zittingsperiode 2019-2023"
    )


def test_an_item_page_is_its_text_after_its_date() -> None:
    item = ek_pages.article(
        _page("nieuws_20260402_senator_van_gasteren_uit_bbb.html"),
        "2026-04-02",
        "Senator Van Gasteren uit BBB-fractie",
    )
    assert item.text.startswith(
        "Senator Robert van Gasteren heeft de BBB-fractie in de Eerste Kamer verlaten"
    )
    assert "Terug naar boven" not in item.text
    assert "/persoon/mr_r_m_j_van_gasteren_llm_fractie" in item.persons


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        # sworn in, and the one succeeded gone that day
        ("Lievense (BBB)", [("beëdiging", "2024-02-06", None, "BBB"),
                            ("vertrek", "2024-02-06", "BBB", None)]),
        # gone on the day the text names, not the item's
        ("Jan Klopman vertrekt", [("vertrek", "2023-07-05", "BBB", None)]),
        ("Senator Schippers verlaat", [("vertrek", "2025-01-14", "VVD", None)]),
        # "tot en met 10 september": gone from the day after
        ("Senator Van den Berg (VVD)", [("vertrek", "2024-09-11", "VVD", None)]),
        # to a faction of their own, named as the Reglement van Orde names it
        ("Senator Visseren-Hamakers", [("afsplitsing", "2025-11-07", "PvdD",
                                         "Fractie-Visseren-Hamakers")]),
        ("Senator Croll van BBB", [("overstap", "2025-06-03", "BBB", "D66")]),
        # the faction left is the one the walk last saw them in
        ("Senator Kemperman naar FVD", [("overstap", "2025-09-09", None, "FVD")]),
        # one succeeded with no item of their own: JA21 one short
        ("Twee nieuwe senatoren", [("beëdiging", "2025-11-18", None, "D66"),
                                   ("beëdiging", "2025-11-18", None, "Fractie-Beukering"),
                                   ("vertrek", "2025-11-18", "D66", None),
                                   ("vertrek", "2025-11-18", "JA21", None)]),
        # succeeded after death: the faction of the one sworn in
        ("Joris Steenkamp (CDA)", [("beëdiging", "2026-05-19", None, "CDA"),
                                   ("vertrek", "2026-05-19", "CDA", None)]),
    ],
)  # fmt: skip
def test_what_an_item_does_to_the_seats(headline: str, expected: list[tuple]) -> None:
    found = ek_mutations.read(_by_headline(headline))
    assert not found.unread
    assert [(c.kind, c.date, c.source, c.to) for c in found.changes] == expected
    assert all(
        c.basis == "tekst" and c.words == found_words(headline) for c in found.changes
    )


def found_words(start: str) -> str:
    return _by_headline(start).headline


def test_no_seat_changes_in_a_temporary_member_a_chair_or_a_debate() -> None:
    temporary = ek_mutations.read(
        _by_headline("Van de Sanden (VVD) geïnstalleerd als tijdelijk")
    )
    assert temporary.temporary and not temporary.changes
    for headline in (
        "Mei Li Vos gekozen",
        "Alexander van Hattem nieuwe",
        "Debat samengevat",
    ):
        found = ek_mutations.read(_by_headline(headline))
        assert not found.changes and not found.unread


def test_every_item_of_the_term_is_read_or_no_change() -> None:
    assert [a.headline for a in _articles() if ek_mutations.read(a).unread] == []


def test_a_faction_tells_its_merge_and_its_rename() -> None:
    merged, renamed = ek_mutations.faction_history(
        _page("fractie_progressief_nederland_pro.html")
    )
    assert (merged.kind, merged.date, merged.sources, merged.to) == (
        "samenvoeging",
        "2023-06-13",
        ("GroenLinks", "PvdA"),
        "GroenLinks-PvdA",
    )
    assert (renamed.kind, renamed.date, renamed.source, renamed.to) == (
        "hernoeming",
        "2026-09-09",
        "GroenLinks-PvdA",
        "PRO",
    )
    assert merged.words.startswith("Voor die datum waren er twee fracties")


def test_the_term_from_the_kiesraad_to_today_is_todays_composition() -> None:
    """The hard check: the seats of 2023 as the Kiesraad counted them, walked through every
    change the Kamer's pages tell, are today's seats per faction, exactly."""
    lineage = ek_mutations.faction_history(
        _page("fractie_progressief_nederland_pro.html")
    )
    today = composition.factions(_page("fracties_2026.html"))
    factions = {
        f.abbreviation: ek_seat_walk.aliases(f.abbreviation, f.path) for f in today
    }
    for change in lineage:
        for name in change.sources:
            factions[name] = ek_seat_walk.aliases(name)
    result = parse_ek_result(fixture_text("EK20230530.html", sub="kiesraad"))
    assert result is not None
    seats, unmatched = ek_seat_walk.start_seats(result.seats, factions)
    assert unmatched == []
    changes = [c for a in _articles() for c in ek_mutations.read(a).changes] + lineage
    walked = ek_seat_walk.walk("2023-06-13", seats, changes, "2026-10-10")
    assert walked.checked, walked.mismatches
    end = {
        ek_seat_walk.faction_key(k): v for k, v in walked.stretches[-1].seats.items()
    }
    assert end == {ek_seat_walk.faction_key(f.abbreviation): f.seats for f in today}
    assert sum(end.values()) == 75
    # a stretch per day the seats changed, each from the day after the one before ends
    for before, after in zip(walked.stretches, walked.stretches[1:], strict=False):
        assert before.to_date is not None and before.to_date < after.from_date
        assert after.events


def test_the_term_with_the_names_of_every_term_is_todays_composition() -> None:
    """As the normalizer walks it, with the factions known by the items of every term: a
    senator named with their faction (``Becker (VVD)``, ``Democratie (FVD)``) names no
    other faction, so the FVD's list is the FVD's, not the VVD's."""
    walked = _walk_term("2023-2027")
    first = walked.stretches[0].seats
    assert (first["VVD"], first["FVD"], first["D66"]) == (10, 2, 5)
    assert walked.checked, walked.mismatches
    today = composition.factions(_page("fracties_2026.html"))
    end = {
        ek_seat_walk.faction_key(k): v for k, v in walked.stretches[-1].seats.items()
    }
    assert end == {ek_seat_walk.faction_key(f.abbreviation): f.seats for f in today}


def test_a_name_spelled_for_two_factions_names_neither() -> None:
    known = ek_seat_walk.known_factions(
        {"VVD": {"VVD"}, "FVD": {"FVD"}},
        [],
        [],
        ["Democratie (VVD)", "Forum voor Democratie (FVD)", "Democratie (FVD)"],
    )
    assert "DEMOCRATIE" not in known["VVD"] | known["FVD"]
    assert "FORUM VOOR DEMOCRATIE" in known["FVD"]
    assert "FVD" not in known["VVD"]


def test_a_walk_that_does_not_add_up_is_not_checked() -> None:
    gone = ek_mutations.Change(
        "vertrek", "2024-01-01", "Senator X verlaat", source="ABC", member="X"
    )
    walked = ek_seat_walk.walk(
        "2023-06-13", {"ABC": 0, "DEF": 75}, [gone], "2025-01-01"
    )
    assert not walked.checked
    assert "ABC below 0" in walked.mismatches[0]


ELECTIONS = {
    "2003-2007": "EK20030526",
    "2007-2011": "EK20070529",
    "2011-2015": "EK20110523",
    "2015-2019": "EK20150526",
    "2019-2023": "EK20190527",
    "2023-2027": "EK20230530",
}
TERM_STARTS = [
    "2003-06-10",
    "2007-06-12",
    "2011-06-07",
    "2015-06-09",
    "2019-06-11",
    "2023-06-13",
    "2026-10-10",
]


def _walk_term(term: str) -> ek_seat_walk.Walk:
    """A term walked as the normalizer walks it: from the Kiesraad's result through the
    changes of every item, with the factions named as today's list, the term's lists and
    the texts of every term name them."""
    items = json.loads(fixture_text("articles_2003_2023.json", sub="eerstekamer"))
    items += json.loads(fixture_text("articles_2023.json", sub="eerstekamer"))
    articles = [
        ek_pages.Article(a["headline"], a["date"], a["text"], a["persons"])
        for a in items
    ]
    lineage = ek_mutations.faction_history(
        _page("fractie_progressief_nederland_pro.html")
    )
    changes = [c for a in articles for c in ek_mutations.read(a).changes] + lineage
    spelled = [n for a in articles for n in ek_mutations.spelled_out(a.text)]
    today = composition.factions(_page("fracties_2026.html"))
    known = {
        f.abbreviation or f.name: ek_seat_walk.aliases(f.abbreviation or f.name, f.path)
        for f in today
    }
    code = ELECTIONS[term]
    result = parse_ek_result(
        (FIXTURES / "kiesraad" / f"{code}.html").read_text("utf-8")
    )
    assert result is not None
    factions = ek_seat_walk.known_factions(known, result.seats, changes, spelled)
    seats, unmatched = ek_seat_walk.start_seats(result.seats, factions)
    assert unmatched == []
    n = list(ELECTIONS).index(term)
    start, after = TERM_STARTS[n], TERM_STARTS[n + 1]
    return ek_seat_walk.walk(
        start, seats, ek_seat_walk.canonical(changes, factions), after
    )


@pytest.mark.parametrize("term", ["2003-2007", "2007-2011", "2011-2015", "2019-2023"])
def test_an_earlier_term_adds_up(term: str) -> None:
    walked = _walk_term(term)
    assert walked.checked, walked.mismatches
    assert sum(walked.stretches[-1].seats.values()) == 75


def test_a_term_with_a_seat_the_pages_do_not_explain_is_not_checked() -> None:
    """Teunissen came back on 12 March 2019; no item tells who left for her."""
    walked = _walk_term("2015-2019")
    assert not walked.checked
    assert walked.mismatches[0].startswith("2019-03-12: more than 75 seats")


def test_older_items_in_their_own_words() -> None:
    every = [
        ek_pages.Article(a["headline"], a["date"], a["text"], a["persons"])
        for a in json.loads(fixture_text("articles_2003_2023.json", sub="eerstekamer"))
    ]
    items = {a.headline: a for a in reversed(every)}  # the first of a headline

    def seen(headline: str) -> list[tuple]:
        return [
            (c.kind, c.date, c.source, c.to)
            for c in ek_mutations.read(items[headline]).changes
        ]

    # "Hun lidmaatschap … is geëindigd", the faction spelled out in full
    assert seen("Senatoren De Graaf en Klever maken overstap naar Tweede Kamer") == [
        ("vertrek", "2012-09-20", "Partij voor de Vrijheid", None),
        ("vertrek", "2012-09-20", "Partij voor de Vrijheid", None),
    ]
    # one standing in for a member on leave changes no seat
    standing_in = items["Hermans (FVD) beëdigd als lid van de Eerste Kamer"]
    assert standing_in.date == "2019-09-10"
    assert (
        ek_mutations.read(standing_in).changes == []
        and ek_mutations.read(standing_in).temporary
    )
    # a list of the sworn and of those they follow
    vijf = seen("Vijf senatoren beëdigd")
    assert [k for k, *_ in vijf].count("beëdiging") == 5
    assert ("vertrek", "2017-03-23", "50PLUS", None) in vijf
    # five who split off together, by the list of the new faction's members
    split = seen("Vijf senatoren stappen uit FVD-fractie")
    assert {(k, d, t) for k, d, _, t in split} == {
        ("afsplitsing", "2020-11-29", "Fractie-Van Pareren")
    }
    assert len(split) == 5


def test_a_day_in_a_pattern_captures_nothing() -> None:
    """The patterns that hold a day number their groups as if it were not there."""
    from lawgraph.core.dutch_dates import DATE_YEAR_OPTIONAL

    assert re.compile(DATE_YEAR_OPTIONAL).groups == 0
