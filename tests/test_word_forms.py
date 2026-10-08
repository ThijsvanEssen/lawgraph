"""The forms of a searched word that stem apart (``core/word_forms.py``)."""

from __future__ import annotations

import pytest

from lawgraph.core.word_forms import word_forms


@pytest.mark.parametrize(
    ("word", "forms"),
    [
        # a singular and its plural whose last consonant changes
        ("huurprijs", "huurprijs huurprijzen"),
        ("huurprijzen", "huurprijzen huurprijs"),
        ("brief", "brief brieven"),
        ("brieven", "brieven brief"),
        # a word without such a pair: as it is
        ("diefstal", "diefstal"),
        ("noodweer", "noodweer"),
        # too short to tell: "leven" is no plural of "lef", "is" no singular
        ("leven", "leven"),
        ("is", "is"),
    ],
)
def test_the_forms_of_a_word(word: str, forms: str) -> None:
    assert word_forms(word) == forms
