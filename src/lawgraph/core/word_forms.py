"""The forms of a searched word that stem apart: the plural and the singular of a word whose
last consonant changes between them ("huurprijs", "huurprijzen"; "brief", "brieven"). The
Dutch stemmer keeps that consonant (``huurprijs`` and ``huurprijz``), so a search for the one
missed the other."""

from __future__ import annotations

# A singular this long or longer gets its plural; a plural this long or longer its singular
# (shorter ones are other words: "leven" is no plural of "lef").
_SINGULAR_MIN = 4
_PLURAL_MIN = 7
_PLURALS = (("s", "zen"), ("f", "ven"))


def word_forms(word: str) -> str:
    """*word* and the forms of it that stem apart, separated by spaces (as ``lg_tokens``
    reads them: the stems of each)."""
    forms = [word]
    for singular, plural in _PLURALS:
        if len(word) >= _SINGULAR_MIN and word.endswith(singular):
            forms.append(word.removesuffix(singular) + plural)
        if len(word) >= _PLURAL_MIN and word.endswith(plural):
            forms.append(word.removesuffix(plural) + singular)
    return " ".join(forms)
