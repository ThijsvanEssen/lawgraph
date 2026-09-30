"""The names of an EU act (core.eu_titles): the citation title of its era, and the title and
short title from the printed title. The printed titles are those of real acts."""

from __future__ import annotations

import pytest

from lawgraph.core.eu_titles import act_names, citation_title


@pytest.mark.parametrize(
    ("celex", "adopted", "title"),
    [
        # EEG before the Treaty of Maastricht, two-digit years before 1999
        ("31987L0102", "1986-12-22", "Richtlijn 87/102/EEG"),
        ("31991R0295", "1991-02-04", "Verordening (EEG) nr. 295/91"),
        ("31993L0013", "1993-04-05", "Richtlijn 93/13/EEG"),
        # EG from 1 November 1993 (Richtlijn 93/104/EG of 23 November 1993)
        ("31993L0104", "1993-11-23", "Richtlijn 93/104/EG"),
        ("31995L0046", "1995-10-24", "Richtlijn 95/46/EG"),
        ("31998L0027", "1998-05-19", "Richtlijn 98/27/EG"),
        ("31999L0093", "1999-12-13", "Richtlijn 1999/93/EG"),
        ("32001R0044", "2000-12-22", "Verordening (EG) nr. 44/2001"),
        ("32009L0110", "2009-09-16", "Richtlijn 2009/110/EG"),
        # EU from 1 December 2009, the Treaty of Lisbon
        ("32009R1286", "2009-12-22", "Verordening (EU) nr. 1286/2009"),
        ("32010R1093", "2010-11-24", "Verordening (EU) nr. 1093/2010"),
        ("32011L0083", "2011-10-25", "Richtlijn 2011/83/EU"),
        # the domain before year/number from 2015
        ("32015R2120", "2015-11-25", "Verordening (EU) 2015/2120"),
        ("32016R0679", "2016-04-27", "Verordening (EU) 2016/679"),
        ("32019L1937", "2019-10-23", "Richtlijn (EU) 2019/1937"),
        ("32002F0584", "2002-06-13", "Kaderbesluit 2002/584/JBZ"),
        ("32011D0024", None, "Besluit 2011/24/EU"),
        ("32011C0024", None, None),
        ("nonsense", None, None),
    ],
)
def test_the_citation_title_has_the_form_of_its_era(
    celex: str, adopted: str | None, title: str | None
) -> None:
    assert citation_title(celex, adopted=adopted) == title


def test_without_a_date_the_year_counts_from_its_first_day() -> None:
    assert citation_title("31993L0104") == "Richtlijn 93/104/EEG"
    assert citation_title("32009R1286") == "Verordening (EG) nr. 1286/2009"


def test_the_word_the_title_starts_with_is_the_designation() -> None:
    names = act_names(
        "32000D0520",
        ["Beschikking 2000/520/EG van de Commissie van 26 juli 2000 op grond van …"],
    )
    assert names.citation_title == "Beschikking 2000/520/EG"

    delegated = act_names(
        "32019R0980",
        [
            "GEDELEGEERDE VERORDENING (EU) 2019/980 VAN DE COMMISSIE",
            "van 14 maart 2019",
            "tot aanvulling van Verordening (EU) 2017/1129",
        ],
    )
    assert delegated.citation_title == "Gedelegeerde Verordening (EU) 2019/980"
    assert delegated.title == (
        "Gedelegeerde Verordening (EU) 2019/980 van de Commissie van 14 maart 2019 tot "
        "aanvulling van Verordening (EU) 2017/1129"
    )


def test_a_title_in_capitals_is_written_with_the_citation_title() -> None:
    names = act_names(
        "32014L0017",
        [
            # the "Е" of "ЕU" is Cyrillic in the Official Journal
            "RICHTLIJN 2014/17/ЕU VAN HET EUROPEES PARLEMENT EN DE RAAD",
            "van 4 februari 2014",
            "inzake kredietovereenkomsten voor consumenten",
            "(Voor de EER relevante tekst)",
        ],
    )
    assert names.citation_title == "Richtlijn 2014/17/EU"
    assert names.title == (
        "Richtlijn 2014/17/EU van het Europees Parlement en de Raad van 4 februari 2014 "
        "inzake kredietovereenkomsten voor consumenten"
    )
    assert names.short_title is None


def test_a_name_between_brackets_that_names_the_kind_is_the_short_title() -> None:
    gdpr = act_names(
        "32016R0679",
        [
            "VERORDENING (EU) 2016/679 VAN HET EUROPEES PARLEMENT EN DE RAAD",
            "van 27 april 2016",
            "betreffende … en tot intrekking van Richtlijn 95/46/EG (algemene verordening "
            "gegevensbescherming)",
        ],
    )
    assert gdpr.short_title == "Algemene verordening gegevensbescherming"

    ecommerce = act_names(
        "32000L0031",
        [
            "Richtlijn 2000/31/EG van het Europees Parlement en de Raad van 8 juni 2000 "
            'betreffende … in de interne markt ("Richtlijn inzake elektronische handel")'
        ],
    )
    assert ecommerce.short_title == "Richtlijn inzake elektronische handel"

    recast = act_names(
        "32013L0036",
        [
            "RICHTLIJN 2013/36/EU VAN DE RAAD",
            "van 26 juni 2013",
            "betreffende … (herschikking)",
        ],
    )
    assert recast.short_title is None


def test_the_old_format_writes_ij_as_a_ligature() -> None:
    names = act_names(
        "32003L0098",
        [
            "Richtlĳn 2003/98/EG van het Europees Parlement en de Raad van 17 november 2003"
        ],
    )
    assert names.citation_title == "Richtlijn 2003/98/EG"
    assert names.title is not None and names.title.startswith("Richtlijn 2003/98/EG")


def test_an_act_without_a_printed_title_has_its_citation_title() -> None:
    names = act_names("31995L0046", [])
    assert names == type(names)(None, "Richtlijn 95/46/EG", None)
