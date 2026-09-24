"""Which Tweede Kamer person a Wikidata person is, and the cabinet posts they held.

Wikidata knows a person by a name (``Rob Jetten``) and a date of birth; the Tweede Kamer by
``Persoon.Achternaam`` (``Jetten``, ``Yeşilgöz-Zegerius``, ``Burg`` for Van der Burg) and
``Geboortedatum``. Two people are one when the date of birth is the same and a part of the
surname is a word of the name. The date alone is not enough: among thousands of people many
share one. A date that Wikidata knows only to the year is compared by its year, and then the
surname must single out one person of that year.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

# wikibase:timePrecision of a date known to the day.
PRECISION_DAY = 11


def _words(text: str | None) -> set[str]:
    """The words of *text*, lower case and without accents: ``Yeşilgöz`` is ``yesilgoz``."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return set(re.findall(r"[a-z]+", plain))


def _names_agree(person_name: str | None, family_name: str | None) -> bool:
    surname = {w for w in _words(family_name) if len(w) > 1}
    return bool(surname & _words(person_name))


def match_member(
    person: dict[str, Any], members: Iterable[dict[str, Any]]
) -> str | None:
    """The key of the member that *person* (a record of ``WikidataClient.cabinet_posts``)
    is, or ``None``. *members* are ``{key, family_name, birth_date}``."""
    birth = person.get("birth_date")
    if not birth:
        return None
    exact = (person.get("birth_precision") or 0) >= PRECISION_DAY
    candidates = [
        m["key"]
        for m in members
        if m.get("birth_date")
        and (m["birth_date"] == birth if exact else m["birth_date"][:4] == birth[:4])
        and _names_agree(person.get("name"), m.get("family_name"))
    ]
    return candidates[0] if len(candidates) == 1 else None


def government_functions(person: dict[str, Any]) -> list[dict[str, Any]]:
    """The posts of *person* as a member stores them, oldest first."""
    return [
        {
            "function": post.get("function"),
            "cabinet": post.get("cabinet"),
            "from_date": post.get("from_date"),
            "to_date": post.get("to_date"),
            "position_id": post.get("position_id"),
            "cabinet_id": post.get("cabinet_id"),
        }
        for post in sorted(
            person.get("posts") or [], key=lambda p: p.get("from_date") or ""
        )
    ]
