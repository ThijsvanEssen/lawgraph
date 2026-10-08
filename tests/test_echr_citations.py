"""Which decisions of the ECHR a text cites by application number, and which one each names."""

from __future__ import annotations

from lawgraph.core.echr_citations import (
    Cited,
    Unresolved,
    appnos,
    cited_in_dutch,
    cited_in_english,
    decisions_by_appno,
    resolve,
)


def test_a_dutch_judgment_cites_the_court_its_date_and_numbers() -> None:
    text = (
        "Zie EHRM 28 maart 2000, nr. 22492/93 (Kiliç/Turkije) en EHRM (GK) 12 november "
        "2008, nrs. 34503/97 en 34504/97. In zaak nr. 24/6811 oordeelde de rechtbank."
    )
    assert cited_in_dutch(text) == [
        Cited("22492/93", "2000-03-28"),
        Cited("34503/97", "2008-11-12"),
        Cited("34504/97", "2008-11-12"),
    ]
    # a number without "EHRM" before it is a case of another court
    assert cited_in_dutch("de uitspraak in zaak nr. 24/6811") == []


def test_a_number_cited_with_and_without_date_counts_once_with_it() -> None:
    text = "EHRM 28 maart 2000, nr. 22492/93; zie ook EHRM, nr. 22492/93, § 62."
    assert cited_in_dutch(text) == [Cited("22492/93", "2000-03-28")]


def test_the_court_cites_by_number_and_a_date_that_follows() -> None:
    text = (
        "Kılıç v. Turkey, no. 22492/93, § 62, ECHR 2000-III; X v. Y (dec.), "
        "no. 12345/01, 3 May 2005; Z v. W, nos. 1/10 and 2/10. The applicant "
        "(application no. 7481/23)."
    )
    assert cited_in_english(text, own=frozenset({"7481/23"})) == [
        Cited("22492/93"),
        Cited("12345/01", "2005-05-03"),
        Cited("1/10"),
        Cited("2/10"),
    ]


def test_a_citation_names_the_decision_of_its_date_or_the_only_one() -> None:
    decisions = decisions_by_appno(
        [
            {"id": "judgments/a", "appno": "22492/93", "date": "2000-03-28"},
            {"id": "judgments/b", "appno": "22492/93", "date": "1997-01-15"},
            {"id": "judgments/c", "appno": "12345/01;12346/01", "date": "2005-05-03"},
        ]
    )
    assert resolve(Cited("22492/93", "2000-03-28"), decisions) == "judgments/a"
    assert resolve(Cited("22492/93"), decisions) is Unresolved.AMBIGUOUS
    assert resolve(Cited("12346/01"), decisions) == "judgments/c"
    assert resolve(Cited("22492/93", "2001-01-01"), decisions) is Unresolved.MISSING
    assert resolve(Cited("9/99"), decisions) is Unresolved.MISSING
    assert appnos("7481/23; 7493/23") == ["7481/23", "7493/23"] and appnos(None) == []
