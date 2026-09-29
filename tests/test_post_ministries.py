"""The ministry of a cabinet post from the official sources, and who a holder is."""

from __future__ import annotations

from collections import Counter

import pytest

from lawgraph.core.cabinet_checks import ministry_report
from lawgraph.core.government import match_by_function, match_holder
from lawgraph.core.post_ministries import (
    MISSING_AMBIGUOUS,
    MISSING_NO_SOURCE,
    SOURCE_STAATSCOURANT,
    SOURCE_TK_COMMITMENTS,
    SOURCE_TK_SIGNATURES,
    commitment_counts,
    post_ministry,
    query_id,
    signature_counts,
    staatscourant_counts,
    staatscourant_query,
)
from lawgraph.pipelines.semantic.tk_government import commitment_props, dossier_props

PLOUMEN = {
    "function": "Minister voor Buitenlandse Handel en Ontwikkelingssamenwerking",
    "post": "minister_zonder_portefeuille",
    "ministry": None,
    "from_date": "2012-11-05",
    "to_date": "2017-10-26",
    "name": "Drs. E.M.J. Ploumen",
}
PALMEN = {
    "function": "Staatssecretaris Herstel en Toeslagen",
    "post": "staatssecretaris",
    "ministry": None,
    "from_date": "2025-09-05",
    "to_date": None,
    "name": "Mr. S.Th.P.H. Palmen-Schlangen",
}


# ── The decision ─────────────────────────────────────────────────────────────


def test_the_first_source_that_names_a_ministry_clearly_decides() -> None:
    evidence = {
        SOURCE_TK_SIGNATURES: Counter(),
        SOURCE_TK_COMMITMENTS: Counter({"fin": 3}),
        SOURCE_STAATSCOURANT: Counter({"szw": 40}),
    }
    assert post_ministry(evidence) == ("fin", SOURCE_TK_COMMITMENTS, None)


def test_sources_that_split_leave_the_post_ambiguous() -> None:
    # Van Veldhoven, Minister voor Milieu en Wonen: IenW 50, BZK 32 in the Staatscourant
    evidence = {SOURCE_STAATSCOURANT: Counter({"ienw": 50, "bzk": 32, "lnv": 11})}
    assert post_ministry(evidence) == (None, None, MISSING_AMBIGUOUS)


def test_too_few_publications_are_no_source() -> None:
    # two publications name "Staatssecretaris Openbaar Vervoer en Milieu": not enough
    evidence = {SOURCE_STAATSCOURANT: Counter({"ienw": 2})}
    assert post_ministry(evidence) == (None, None, MISSING_NO_SOURCE)
    assert post_ministry({}) == (None, None, MISSING_NO_SOURCE)


# ── The evidence ─────────────────────────────────────────────────────────────


def test_the_functions_signed_while_holding_the_post_count() -> None:
    signed = [
        {"function": "staatssecretaris van Financiën", "first": "2025-10-02"},
        {"function": "staatssecretaris van Financiën", "first": "2025-11-03"},
        # another kind of post, and a month before the post
        {"function": "minister van Financiën", "first": "2025-10-02"},
        {
            "function": "staatssecretaris van Justitie en Veiligheid",
            "first": "2025-08-01",
        },
        # a function that names no ministry
        {"function": "staatssecretaris Herstel en Toeslagen", "first": "2025-10-02"},
    ]
    assert signature_counts(PALMEN, signed) == Counter({"fin": 2})


def test_the_commitments_of_the_holder_count_by_the_ministry_the_kamer_gives() -> None:
    commitments = [
        {
            "name": "Palmen-Schlangen, S.Th.P.H.",
            "role": "Staatssecretaris Herstel en Toeslagen",
            "ministry_name": "Financiën",
            "date": "2025-10-01",
        },
        # someone else, and before the post
        {
            "name": "Heijnen, E.H.J.",
            "role": "Staatssecretaris Fiscaliteit",
            "ministry_name": "Financiën",
            "date": "2025-10-01",
        },
        {
            "name": "Palmen-Schlangen, S.Th.P.H.",
            "role": "Staatssecretaris Herstel en Toeslagen",
            "ministry_name": "Sociale Zaken en Werkgelegenheid",
            "date": "2025-08-01",
        },
    ]
    assert commitment_counts(PALMEN, "Palmen-Schlangen", commitments) == Counter(
        {"fin": 1}
    )


def test_the_staatscourant_is_asked_from_1995_about_a_function_that_names_nothing() -> (
    None
):
    query = staatscourant_query(PLOUMEN)
    assert query == {
        "phrase": "minister voor buitenlandse handel en ontwikkelingssamenwerking",
        "from": "2012-11-05",
        "to": "2017-10-26",
    }
    record = {
        "creators": {
            "Ministerie van Buitenlandse Zaken": 358,
            "Ministerie van Financiën": 12,
            "Gemeente Utrecht": 3,
        }
    }
    assert staatscourant_counts(PLOUMEN, {query_id(query): record}) == Counter(
        {"bz": 358, "fin": 12}
    )
    assert staatscourant_query({**PLOUMEN, "to_date": "1989-11-07"}) is None
    assert (
        staatscourant_query({**PLOUMEN, "function": "Minister zonder Portefeuille"})
        is None
    )
    assert staatscourant_query({**PLOUMEN, "ministry": "bz"}) is None
    held = staatscourant_query(PALMEN)
    assert held is not None and query_id(held).endswith("|2025-09-05|")


def test_a_commitment_takes_the_ministry_the_kamer_gives_it() -> None:
    row = {
        "name": "Jetten, R.A.A.",
        "role": "Minister voor Klimaat en Energie",
        "ministry_name": "Economische Zaken en Klimaat",
        "text": "De minister zegt toe ...",
        "date": "2024-03-01",
    }
    assert commitment_props(row, [], [])["ministry"] == "ezk"
    # without it, the ministry of the post the member held that day
    people = [
        {
            "id": "m1",
            "name": "R.A.A. Jetten",
            "posts": [
                {
                    "function": "Minister voor Klimaat en Energie",
                    "ministry": "ezk",
                    "from_date": "2022-01-10",
                    "to_date": "2024-07-02",
                }
            ],
        }
    ]
    props = commitment_props({**row, "ministry_name": None}, people, [])
    assert (props["member_key"], props["ministry"]) == ("m1", "ezk")


def test_a_dossier_brought_in_by_a_minister_without_portfolio_takes_their_post() -> (
    None
):
    people = [
        {
            "id": "m1",
            "posts": [
                {
                    "function": "Minister voor Medische Zorg",
                    "ministry": "vws",
                    "from_date": "2017-10-26",
                    "to_date": "2020-03-23",
                }
            ],
        }
    ]
    first = {
        "date": "2019-05-01",
        "member": "m1",
        "capacity": "bewindspersoon",
        "function": "minister voor Medische Zorg",
    }
    assert dossier_props(first, [], people)["ministry"] == "vws"


# ── Who a holder is ──────────────────────────────────────────────────────────


def _holder(initials: str, letters: str, surname: str, **extra) -> dict:
    return {
        "surname": surname,
        "initials": initials,
        "letters": letters,
        "days": ["1998-08-03"],
        "factions": ["vvd"],
        **extra,
    }


HOOGERVORST = {
    "key": "m-hoogervorst",
    "family_name": "Hoogervorst",
    "name": "Johannes Franciscus Hoogervorst",
    "initials": "JF",
    "birth_date": "1956-04-19",
    "factions": ["vvd"],
}


@pytest.mark.parametrize(
    ("initials", "letters", "member_initials", "full_name", "matched"),
    [
        # the Tweede Kamer writes initials without dots: JF is J.F., not J
        ("J.F.", "jf", "JF", "Johannes Franciscus Jansen", True),
        ("J.H.", "jh", "JF", "Johannes Franciscus Jansen", False),
        # a digraph kept (WTHC) or dropped (TM)
        ("W.Th.C.", "wtc", "WTHC", "Willem Jansen", True),
        ("Th.M.", "tm", "TM", "Jansen", True),
        # IJ as Y
        ("D.IJ.W.", "dijw", "DYW", "Jansen", True),
        # initials the Kamer got wrong, first names of the full name right
        ("J.F.", "jf", "JR", "Jan Frederik Jansen", True),
    ],
)
def test_initials_without_dots(
    initials: str, letters: str, member_initials: str, full_name: str, matched: bool
) -> None:
    member = {
        **HOOGERVORST,
        "family_name": "Jansen",
        "name": full_name,
        "initials": member_initials,
        "birth_date": None,
    }
    holder = _holder(initials, letters, "Jansen")
    assert (match_holder(holder, [member]) == member["key"]) is matched


SIGNED = {
    "m-hoogervorst": [
        {
            "function": "minister van Volksgezondheid, Welzijn en Sport",
            "first": "2004-03-02",
        }
    ]
}
JH = _holder(
    "J.H.",
    "jh",
    "Hoogervorst",
    posts=[
        {
            "function": "Minister van Volksgezondheid, Welzijn en Sport",
            "from_date": "2003-05-27",
            "to_date": "2007-02-22",
        }
    ],
)


def test_a_holder_whose_name_matches_no_one_is_matched_by_what_they_signed() -> None:
    # J.H. Hoogervorst on the pages of Balkenende II and III is J.F. Hoogervorst
    assert match_holder(JH, [HOOGERVORST]) is None
    assert match_by_function(JH, [HOOGERVORST], SIGNED) == "m-hoogervorst"


def test_the_match_by_function_needs_party_period_and_one_candidate() -> None:
    other_party = {**JH, "factions": ["cda"]}
    assert match_by_function(other_party, [HOOGERVORST], SIGNED) is None
    later = {
        **JH,
        "posts": [
            {**JH["posts"][0], "from_date": "2010-01-01", "to_date": "2011-01-01"}
        ],
    }
    assert match_by_function(later, [HOOGERVORST], SIGNED) is None
    namesake = {**HOOGERVORST, "key": "m-namesake"}
    signed = {**SIGNED, "m-namesake": SIGNED["m-hoogervorst"]}
    assert match_by_function(JH, [HOOGERVORST, namesake], signed) is None


def test_verify_counts_where_the_ministry_comes_from_and_why_it_is_missing() -> None:
    posts = [
        {"ministry_source": "page", "name": "A", "function": "Minister van Financiën"},
        {
            "ministry_source": "staatscourant",
            "name": "B",
            "function": "Minister voor X",
        },
        {"ministry_missing": "ambiguous", "name": "C", "function": "Minister voor Y"},
        {"ministry_missing": "no_source", "name": "D", "function": "Minister zonder"},
    ]
    counts, missing = ministry_report([("rutte_iv", posts)])
    assert counts == {"page": 1, "staatscourant": 1, "ambiguous": 1, "no_source": 1}
    assert missing == {
        "ambiguous": ["rutte_iv: C, Minister voor Y"],
        "no_source": ["rutte_iv: D, Minister zonder"],
    }
