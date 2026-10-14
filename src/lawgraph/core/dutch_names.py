"""How a Dutch text writes the name of a person or a place: titles, initials, particles
(tussenvoegsels), surnames and places. The readers of judgments, of the Eerste Kamer, of the
government and of a person search build their patterns from these."""

from __future__ import annotations

TITLES = ("mr", "dr", "drs", "prof", "ir", "ing")
# A title before a name: "mr. ", "Mr ", "prof.". "ing" only with its dot: "ING Bank" is none.
TITLE = (
    rf"(?:(?i:{'|'.join(TITLES)})\.\s*|"
    rf"(?i:{'|'.join(t for t in TITLES if t != 'ing')})\s+)"
)

# One initial, without its dot: "A", "IJ", "Th", "Joh".
INITIAL = r"(?:[A-Z]|IJ|Th|Chr|Ph|Ch|Joh|Jac|Fr|Wm)"
# Initials: "P.J. ", "Th.", "Fr.-J.".
INITIALS = rf"(?:{INITIAL}\.\s?(?:-\s?)?)+"

# The particles of a surname, each a word: "in 't Veld" has "in" and "t", "d'Hondt" has "d",
# "vander Laan" has "vander".
PARTICLES = frozenset(
    {
        "van",
        "de",
        "der",
        "den",
        "het",
        "ten",
        "ter",
        "te",
        "t",
        "in",
        "uit",
        "op",
        "aan",
    }
    | {
        "bij",
        "la",
        "le",
        "du",
        "da",
        "di",
        "dos",
        "des",
        "von",
        "zu",
        "el",
        "al",
        "d",
        "l",
    }
    | {"vander", "vande", "vanden"}
)
# A particle as a text writes it before a word of the surname: "van", "'t". The "d" of
# "d'Hondt" is part of its word.
PARTICLE = (
    "(?:"
    + "|".join(
        sorted(
            ("'t" if p == "t" else p for p in PARTICLES if len(p) > 1 or p == "t"),
            key=lambda p: (-len(p), p),
        )
    )
    + r")\b"
)
# A word of a surname: "Gelder", "Pré", "O'Neill", "X" where a text stands in for a name.
WORD = r"[A-ZÀ-ÖØ-Þ][\w'’]*"
# A word of a surname where a lone capital is an initial ("N.V."): "Gelder", "Pré".
LONG_WORD = r"[A-ZÀ-ÖØ-Þ][\w'’]+"


def surname(word: str = WORD, stop: str | None = None) -> str:
    """The pattern of a surname: *word*s with the particles before them, a hyphen between
    two ("van der Meulen", "Witteveen-van den Berg", "in 't Veld"). A word after the first
    that matches *stop* is no part of it ("Spronken Conclusie inzake")."""
    guard = rf"(?!(?i:{stop})\b)" if stop else ""
    return (
        rf"(?:{PARTICLE}\s+)*{word}"
        rf"(?:(?:-|\s+){guard}(?:{PARTICLE}[\s-]+)*{word})*"
    )


# The small words in the name of a place: "Bergen op Zoom", "Alphen a/d Rijn".
_PLACE_WORDS = r"(?:aan|den|de|der|op|bij|in|het|ter|ten|a/d)"
# A place: "Utrecht", "Den Haag", "'s-Gravenhage", "‘s-Hertogenbosch", "'t Zandt",
# "Nieuwerkerk aan den IJssel".
PLACE = (
    rf"(?:['’‘][st][-‑–\s])?[A-Z][\w'’-]*"
    rf"(?:\s+(?:{_PLACE_WORDS}\s+)*[A-Z][\w'’-]*)*"
)
