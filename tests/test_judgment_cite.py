"""A judgment as a lawyer cites it, one row per court code of the ECLI (pure)."""

from __future__ import annotations

import pytest

from lawgraph.core.judgment_cite import Cite, cite_of

CASES = [
    # (props, short)
    ({"ecli": "ECLI:NL:HR:2019:2006", "date": "2019-12-20"}, "HR 20 december 2019"),
    (
        {
            "ecli": "ECLI:NL:PHR:2020:1",
            "date": "2020-05-08",
            "advocate_general": "T. Hartlief",
            "advocate_general_role": "advocaat-generaal",
        },
        "Conclusie A-G Hartlief 8 mei 2020",
    ),
    (
        {
            "ecli": "ECLI:NL:PHR:2019:900",
            "date": "2019-09-13",
            "advocate_general": "mr. F.F. Langemeijer",
            "advocate_general_role": "plaatsvervangend procureur-generaal",
        },
        "Conclusie P-G Langemeijer 13 september 2019",
    ),
    (
        {"ecli": "ECLI:NL:PHR:2020:2", "advocate_general": "Wattel"},
        "Conclusie A-G Wattel",
    ),
    ({"ecli": "ECLI:NL:RVS:2020:1", "date": "2020-01-08"}, "ABRvS 8 januari 2020"),
    ({"ecli": "ECLI:NL:CRVB:2021:3", "date": "2021-02-01"}, "CRvB 1 februari 2021"),
    ({"ecli": "ECLI:NL:CBB:2022:4", "date": "2022-03-01"}, "CBb 1 maart 2022"),
    (
        {"ecli": "ECLI:NL:GHAMS:2026:2", "date": "2026-09-22"},
        "Hof Amsterdam 22 september 2026",
    ),
    (
        {"ecli": "ECLI:NL:RBDHA:2026:1", "court": "Rechtbank Den Haag"},
        "Rb. Den Haag",
    ),
    # the place from the name of the code when the props name no court (a row of the feed)
    (
        {"ecli": "ECLI:NL:RBMNE:2026:5", "date_eff": "2026-07-06"},
        "Rb. Midden-Nederland 6 juli 2026",
    ),
    ({"ecli": "ECLI:EU:C:2020:1", "date": "2020-01-01"}, "HvJ EU 1 januari 2020"),
    ({"ecli": "ECLI:EU:T:2020:1"}, "Gerecht EU"),
    ({"ecli": "ECLI:CE:ECHR:2020:1", "date": "2020-01-01"}, "EHRM 1 januari 2020"),
]


@pytest.mark.parametrize(("props", "short"), CASES)
def test_a_judgment_is_cited_by_its_court_code(
    props: dict[str, str], short: str
) -> None:
    assert cite_of(props) == Cite(short, f"{short}, {props['ecli'].upper()}")


def test_a_judgment_without_an_ecli_has_no_cite() -> None:
    assert cite_of({"date": "2020-01-01"}) is None


def test_a_judgment_in_the_feed_and_the_lists_is_cited_by_its_columns() -> None:
    """A row of the feed and of the lists has the court code and ``date_eff``, not the
    court's name: the place comes from the code."""
    from lawgraph.api.schemas.feed import _judgment
    from lawgraph.api.schemas.instruments import InstrumentJudgmentItem
    from lawgraph.api.schemas.judgments import JudgmentListItemDTO

    conclusion = {
        "ecli": "ECLI:NL:PHR:2019:900",
        "court_code": "PHR",
        "date_eff": "2019-09-13",
        "advocate_general": "F.F. Langemeijer",
        "advocate_general_role": "plaatsvervangend procureur-generaal",
    }
    short = "Conclusie P-G Langemeijer 13 september 2019"
    feed = _judgment(conclusion).cite
    assert feed is not None and (feed.short, feed.full) == (
        short,
        f"{short}, ECLI:NL:PHR:2019:900",
    )
    row = {"judgment": {"id": "judgments/x", "key": "x", "props": conclusion}}
    cited = InstrumentJudgmentItem.from_row(row).cite
    assert cited is not None and cited.short == short
    listed = JudgmentListItemDTO.from_document(
        {
            "id": "judgments/y",
            "key": "y",
            "ecli": "ECLI:NL:RBDHA:2026:1",
            "court_code": "RBDHA",
            "date": "2026-07-06",
        }
    ).cite
    assert listed is not None and listed.short == "Rb. Den Haag 6 juli 2026"
