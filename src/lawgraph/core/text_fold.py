"""Text folded to compare and to name by: lower case without accents, and slugs of it."""

from __future__ import annotations

import re
import unicodedata

# The accents NFKD splits off a letter (U+0300-U+036F). The SQL function ``lg_fold`` and
# the explorer's division anchors take the same marks off.
ACCENTS = re.compile("[̀-ͯ]")


def fold(text: str | None) -> str:
    """*text* in lower case without accents: ``Yeşilgöz`` is ``yesilgoz``, ``ĳ`` is ``ij``.
    A letter with no accent to take off (ß, æ, ø) stays."""
    return ACCENTS.sub("", unicodedata.normalize("NFKD", text or "")).lower()


def slug(text: str | None, sep: str = "-", keep: str = "") -> str:
    """The runs of letters and digits (and of the characters in *keep*) of the folded
    *text*, joined by *sep*: ``staats-en-bestuursrecht``. A letter with no accent to take
    off parts two runs (``Straße`` is ``stra-e``)."""
    return re.sub(f"[^a-z0-9{re.escape(keep)}]+", sep, fold(text)).strip(sep)


def plain_words(text: str | None) -> str:
    """The words of the folded *text*, one space between them: ``minister voor
    ontwikkelingssamenwerking``."""
    return slug(text, " ")


def ascii_slug(text: str | None, sep: str = "-") -> str:
    """``slug`` in ASCII: a letter with no accent to take off is left out (``Straße`` is
    ``strae``). Node keys and member slugs are made so."""
    return slug(fold(text).encode("ascii", "ignore").decode(), sep)
