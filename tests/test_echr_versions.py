"""``semantic echr-versions``: which ECHR nodes are one decision, and which version is kept."""

from __future__ import annotations

from lawgraph.pipelines.semantic.echr_versions import decision_of, versions_kept


def _row(key: str, appno: str, date: str | None, language: str | None) -> dict:
    return {
        "id": f"judgments/{key}",
        "key": key,
        "appno": appno,
        "date": date,
        "item_id": key,
        "language": language,
    }


def test_the_versions_of_a_decision_share_its_numbers_and_date() -> None:
    # 7481/23 in English and French, the same day; its decision on admissibility another day
    english = _row("echr_001_252192", "7481/23", "2026-03-10", "ENG")
    french = _row("echr_001_252409", "7481/23", "2026-03-10", "FRE")
    admissibility = _row("echr_001_200000", "7481/23", "2024-01-15", "ENG")
    alone = _row("echr_001_1", "1/99", "2000-01-01", "FRE")
    assert versions_kept([french, admissibility, english, alone]) == {
        "judgments/echr_001_252409": english
    }


def test_the_numbers_in_any_order_and_without_a_language_the_lowest_key() -> None:
    a = _row("echr_b", "2/20; 1/20", "2020-05-05", None)
    b = _row("echr_a", "1/20;2/20", "2020-05-05", None)
    assert decision_of(a) == decision_of(b) == (("1/20", "2/20"), "2020-05-05")
    assert versions_kept([a, b]) == {"judgments/echr_b": b}
    # no date or no number: no decision to share
    assert decision_of(_row("x", "1/20", None, "ENG")) is None
    assert decision_of(_row("y", " ", "2020-05-05", "ENG")) is None
