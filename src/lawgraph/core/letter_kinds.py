"""The kind of a letter of the government that its subject names: an artikel 100-brief
(``article_100``), the letter by which the government informs the States General of a
deployment of the armed forces (artikel 100 Grondwet), read from its ``Onderwerp``.

The Tweede Kamer gives no kind for it: such a letter is a ``Brief regering`` like any other
(``Document.Soort`` in the OData of gegevensmagazijn.tweedekamer.nl). Its subject names it,
in one of two forms (read over the 63 ``Brief regering`` papers of 2008 to 2026 whose subject
names artikel 100 that the search found in October 2026):

* it opens with the article, after "Aanvullende", "Aanvulling (op de)" or "Kennisgeving" at
  most: "Artikel 100-bijdrage aan EUFOR Althea" (Kamerstuk 29521, nr. 494), "Artikel 100
  brief inzake …", "Artikel-100 Grondwet: Verlenging …", "Aanvullende artikel 100-inzet …",
  "Kennisgeving - Artikel 100-inzet MMU-MRTT boven Irak";
* it closes with the article in parentheses: "Nederlandse bijdrage aan EUNAVFOR MED Sophia in
  2016 (Artikel 100 Grondwet)" (29521, nr. 323), "… (artikel 100-brief)".

A subject that names the article elsewhere is a letter about one ("Toezegging gedaan tijdens
het commissiedebat Artikel 100 …", "Kabinetsreactie op de eindevaluatie … artikel
100-bijdrage …", "Werking van de artikel 100-procedure"), and is none. A letter whose subject
does not name the article (some before 2010) is none either: only its text says so. A letter
about one whose subject closes with the article in parentheses is counted ("Reactie op
verzoek commissie over een briefing over … (artikel 100-brief)", 2019): the subject alone does
not tell them apart.

The rule is one regular expression that Python and PostgreSQL read alike (``~*``), so that a
partial index of the documents holds these letters (``db/schema.py``
``article_100_letter``).
"""

from __future__ import annotations

from typing import Final, Literal

LetterKind = Literal["article_100"]
ARTICLE_100: Final[LetterKind] = "article_100"

# The ``Document.Soort`` of a letter of the government.
GOVERNMENT_LETTER: Final = "Brief regering"

# Its subject, in any case: the article first (after a word of a supplement or a notice at
# most, and not its procedure), or last in parentheses. No ``\b``: PostgreSQL reads it as a
# backspace.
ARTICLE_100_SUBJECT: Final = (
    r"^(?:(?:aanvullende?|aanvulling(?: op de)?|kennisgeving)[\s:–-]*)?"
    r"artikel[\s-]*100(?![0-9])(?![\s-]*procedure)"
    r"|\(artikel[\s-]*100(?![0-9])[^)]*\)\s*$"
)
