"""The laws a title names: "Wijziging van het Wetboek van Strafrecht en het Wetboek van
Strafvordering in verband met ...", "Wijziging van de Vreemdelingenwet 2000", "Wijziging van
de Algemene wet bestuursrecht". The names are read by their form, so a law the graph has
not loaded is named too.
"""

from __future__ import annotations

import re

# "Wetboek van Strafvordering", "Burgerlijk Wetboek"; "Algemene wet bestuursrecht", "Wet op
# de rechterlijke organisatie", "Wet van 2 juli ..."; a compound ending in "wet"
# ("Vreemdelingenwet 2000", "Opiumwet", "Participatiewet").
_LAW_NAME = re.compile(
    r"\b(?:"
    r"Wetboek\s+van\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
    r"|Burgerlijk\s+Wetboek(?:\s+Boek\s+\d+[A-Z]?)?"
    r"|Algemene\s+wet\s+(?:[a-z]+\s+){0,3}?[a-z]+?(?=\s+(?:en|in|ter|tot|met)\b|[,.;)]|$)"
    r"|Wet\s+(?:op|op\s+het|op\s+de|inzake|tot)\s+(?:[A-Za-z]+\s+){0,4}?[A-Za-z]+?"
    r"(?=\s+(?:en|in|ter|tot|met)\b|[,.;)]|$)"
    # "Uitvoeringswet Algemene verordening gegevensbescherming": a compound, its year or
    # the capitalised name it goes on with
    r"|[A-Z][a-z]+(?:-[A-Za-z]+)*wet(?:\s+(?:19|20)\d{2}"
    r"|\s+[A-Z][a-z]+(?:\s+[a-z]+){0,3}?(?=\s+(?:en|in|ter|tot|met)\b|[,.;)]|$))?"
    r")"
)


# A kind of law, not a name: "een Verzamelwet", "de Uitvoeringswet" without what it carries
# out.
_KINDS = frozenset(
    {
        "aanpassingswet",
        "aanvullingswet",
        "evaluatiewet",
        "herstelwet",
        "implementatiewet",
        "instellingswet",
        "invoeringswet",
        "kaderwet",
        "overgangswet",
        "reparatiewet",
        "rijkswet",
        "spoedreparatiewet",
        "uitvoeringswet",
        "veegwet",
        "verzamelwet",
        "wijzigingswet",
    }
)


def laws_in_title(title: str | None) -> list[str]:
    """The names of the laws *title* names, in its order, each once. A name that goes on
    past "in", "en", "met", "ter" or "tot" ("Wet op de beroepen in de individuele
    gezondheidszorg") ends there."""
    names: list[str] = []
    for match in _LAW_NAME.finditer(title or ""):
        name = " ".join(match.group(0).split())
        if name.lower() in _KINDS:
            continue
        if name not in names:
            names.append(name)
    return names
