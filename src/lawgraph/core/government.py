"""Which Tweede Kamer person a Wikidata person is, and the cabinet posts they held.

Wikidata knows a person by a name (``Rob Jetten``) and a date of birth. The Tweede Kamer has
two kinds of ``Persoon``:

- a member of parliament, with ``Achternaam`` (``Jetten``, ``Yeşilgöz-Zegerius``, ``Burg`` for
  Van der Burg) and ``Geboortedatum``. Two people are one when the date of birth is the same
  and a word of the surname is a word of the name (``match_member``). The date alone is not
  enough: among thousands of people many share one. A date that Wikidata knows only to the
  year is compared by its year, and then the surname must single out one person of that year.
  A date that differs in one of year, month or day (two years at most) is a slip in one of
  the sources when the surname and the first name agree as well and only one member fits.
- a minister or state secretary who never sat in parliament: a record without name or date,
  known only by the papers they signed (``DocumentActor``: ``J. van Essen``, ``minister van
  …``, on a date). Such a signatory is the person whose surname is in the signed name and who
  held a post of the same kind (minister, state secretary) on a date they signed
  (``match_signatory``).

Particles (``van``, ``de``, ``der`` …) are no surname words: ``Wallis de Vries`` is not
``Kappeyne van de Coppello``. A surname spelled with ``ij`` in one source and ``y`` in the
other (``Gruijters``, ``Gruyters``) agrees only when the exact spelling finds nobody.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

# wikibase:timePrecision of a date known to the day.
PRECISION_DAY = 11

PARTICLES = frozenset(
    {"van", "de", "der", "den", "het", "ter", "ten", "te", "t", "op", "in", "la", "le"}
    | {"d", "des", "du", "l", "von", "zu", "vander", "vande", "vanden", "aan", "bij"}
)

# A signature on a letter sent just after the post ended still belongs to it.
_SIGNED_AFTER_POST = dt.timedelta(days=14)


def _plain(text: str | None) -> str:
    """*text* lower case and without accents: ``Yeşilgöz`` is ``yesilgoz``."""
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _words(text: str | None, *, ij: bool = False) -> set[str]:
    plain = _plain(text)
    if ij:
        plain = plain.replace("ij", "y")
    return set(re.findall(r"[a-z]+", plain))


def _surname_words(family_name: str | None, *, ij: bool = False) -> set[str]:
    return {w for w in _words(family_name, ij=ij) if len(w) > 1 and w not in PARTICLES}


def _names_agree(person_name: str | None, family_name: str | None, *, ij: bool) -> bool:
    return bool(_surname_words(family_name, ij=ij) & _words(person_name, ij=ij))


def _first_name(name: str | None) -> str:
    words = re.findall(r"[a-z]+", _plain(name))
    return words[0] if words else ""


def _one_slip(a: str, b: str) -> bool:
    """Whether two ``YYYY-MM-DD`` dates differ in exactly one part, the year by two at most."""
    parts = list(zip(a.split("-"), b.split("-"), strict=False))
    if len(parts) != 3:
        return False
    differ = [i for i, (x, y) in enumerate(parts) if x != y]
    if len(differ) != 1:
        return False
    return differ[0] != 0 or abs(int(parts[0][0]) - int(parts[0][1])) <= 2


def _born_alike(person: dict[str, Any], member: dict[str, Any]) -> bool:
    birth, other = person.get("birth_date"), member.get("birth_date")
    if not birth or not other:
        return False
    if (person.get("birth_precision") or 0) >= PRECISION_DAY:
        return bool(other == birth)
    return bool(other[:4] == birth[:4])


def _first_names_agree(person: dict[str, Any], member: dict[str, Any]) -> bool:
    """The first two letters of the first names, when the member has first names.

    ``first_names`` is the member's full name; a name that is only a surname (``Hoekzema``,
    ``van der Stee``) has none."""
    surname = _surname_words(member.get("family_name")) | PARTICLES
    names = [
        w
        for w in re.findall(r"[a-z]+", _plain(member.get("first_names")))
        if w not in surname
    ]
    return not names or names[0][:2] == _first_name(person.get("name"))[:2]


def _only(keys: Sequence[str]) -> str | None:
    return keys[0] if len(keys) == 1 else None


def match_member(
    person: dict[str, Any], members: Iterable[dict[str, Any]]
) -> str | None:
    """The key of the member of parliament that *person* (a record of
    ``WikidataClient.cabinet_posts``) is, or ``None``. *members* are ``{key, family_name,
    first_names, birth_date}``: pass every member, or at least those born within two years."""
    if not person.get("birth_date"):
        return None
    members = [m for m in members if m.get("birth_date")]
    name = person.get("name")
    for ij in (False, True):
        exact = [
            m["key"]
            for m in members
            if _born_alike(person, m)
            and _names_agree(name, m.get("family_name"), ij=ij)
        ]
        if exact:
            return _only(exact)
    if (person.get("birth_precision") or 0) < PRECISION_DAY:
        return None
    slipped = [
        m["key"]
        for m in members
        if _one_slip(person["birth_date"], m["birth_date"])
        and _names_agree(name, m.get("family_name"), ij=False)
        and _first_names_agree(person, m)
    ]
    return _only(slipped)


def _post_kind(function: str | None) -> str:
    """``staatssecretaris`` or ``minister``: what a post or a signature is, by its name."""
    return "staatssecretaris" if "staatssecretaris" in _plain(function) else "minister"


def _held_on(post: dict[str, Any], day: str) -> bool:
    start, end = post.get("from_date"), post.get("to_date")
    if not start or day < start:
        return False
    if not end:
        return True
    return dt.date.fromisoformat(day) <= dt.date.fromisoformat(end) + _SIGNED_AFTER_POST


def _signed_as(person: dict[str, Any], signature: dict[str, Any]) -> bool:
    """Whether *person* held a post of the signature's kind on one of its dates."""
    kind = _post_kind(signature.get("function"))
    days = [d for d in (signature.get("first"), signature.get("last")) if d]
    return any(
        _post_kind(post.get("function")) == kind and _held_on(post, day)
        for post in person.get("posts") or []
        for day in days
    )


def match_signatory(
    signatures: Iterable[dict[str, Any]], people: Iterable[dict[str, Any]]
) -> str | None:
    """The Q-id of the person who signed *signatures*, or ``None``.

    *signatures* are one Tweede Kamer person's signatures as a minister or state secretary,
    grouped by signed name and function: ``{name, function, first, last}`` (the first and last
    date). A group that fits nobody (a misspelt name) or several says nothing; the groups that
    fit one person must all fit the same one.
    """
    people = list(people)
    found: set[str] = set()
    for signature in signatures:
        surname = _surname_words(signature.get("name"))
        fits = [
            p["id"]
            for p in people
            if surname & _words(p.get("name")) and _signed_as(p, signature)
        ]
        if len(fits) == 1:
            found.update(fits)
    return _only(sorted(found))


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
