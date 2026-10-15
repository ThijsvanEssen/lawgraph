"""What an amendment is for, as its Toelichting opens (``core/amendment_explanation.py``)."""

from __future__ import annotations

from lawgraph.core.amendment_explanation import EXPLANATION_CHARS, read_explanation

INSTRUCTIONS = """AMENDEMENT VAN HET LID KATHMANN
Ontvangen 7 april 2026
De ondergetekende stelt het volgende amendement voor:
I
In artikel 21 wordt na het eerste lid een lid ingevoegd, luidende:
2. De minister kan …
"""


def _document(toelichting: str) -> tuple[str, list[dict[str, object]]]:
    text = INSTRUCTIONS + "Toelichting\n" + toelichting + "\nKathmann"
    start = len(INSTRUCTIONS)
    return text, [
        {"heading": "Toelichting", "char_start": start, "char_end": len(text)}
    ]


def test_the_explanation_is_the_first_paragraph_of_the_toelichting() -> None:
    text, sections = _document(
        "Dit amendement regelt dat de minister kan ingrijpen.\nDe indiener vindt dat nodig."
    )
    assert read_explanation(text, sections) == (
        "Dit amendement regelt dat de minister kan ingrijpen."
    )


def test_a_long_paragraph_keeps_its_whole_sentences_that_fit() -> None:
    first = "Dit amendement regelt een evaluatie. "
    text, sections = _document(first + "Zo " * EXPLANATION_CHARS + "einde.")
    assert read_explanation(text, sections) == first.strip()
    text, sections = _document("woord " * EXPLANATION_CHARS)
    explanation = read_explanation(text, sections)
    assert explanation is not None and explanation.endswith("woord…")
    assert len(explanation) <= EXPLANATION_CHARS


def test_a_paper_without_the_form_of_an_amendment_has_none() -> None:
    text = "Nota van wijziging\nToelichting\nDe regering wijzigt het voorstel."
    sections = [{"heading": "Toelichting", "char_start": 19, "char_end": len(text)}]
    assert read_explanation(text, sections) is None
    assert read_explanation(INSTRUCTIONS, []) is None
