"""Which Tweede Kamer person holds a post in a cabinet.

Rijksoverheid names a bewindspersoon by initials and surname (``Drs. S.Th.M. (Sophie)
Hermans``, ``dr. W. Drees``), with the party. The Tweede Kamer has two kinds of ``Persoon``:

- a member of parliament, with ``Achternaam`` (``Hermans``, ``Yeşilgöz-Zegerius``, ``Weel``
  for Van Weel), the full first names and ``Geboortedatum``. A holder is that member when the
  surname words agree, the initials are those of the first names, and the member was of an
  age to hold the post (``match_holder``). Two members that fit (a father and a son of one
  name) are told apart by the faction of the holder's party; if that leaves more than one,
  the holder matches nobody.
- a minister or state secretary who never sat in parliament: a record without name or date,
  known only by the papers they signed (``DocumentActor``: ``J. van Essen``, ``minister van
  …``, on a date). Such a signatory is the holder whose surname is in the signed name and who
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

PARTICLES = frozenset(
    {"van", "de", "der", "den", "het", "ter", "ten", "te", "t", "op", "in", "la", "le"}
    | {"d", "des", "du", "l", "von", "zu", "vander", "vande", "vanden", "aan", "bij"}
)

# A signature on a letter sent just after the post ended still belongs to it.
_SIGNED_AFTER_POST = dt.timedelta(days=14)
# The ages between which one holds a post in a cabinet.
YOUNGEST, OLDEST = 28, 95


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


def _only(keys: Sequence[str]) -> str | None:
    return keys[0] if len(keys) == 1 else None


def initial_letters(first_names: Iterable[str]) -> str:
    """``stm`` of Sophia Theodora Monique; ``ij`` stays one letter (IJsbrand)."""
    return "".join("ij" if n.startswith("ij") else n[:1] for n in first_names)


def _first_names(member: dict[str, Any]) -> list[str]:
    """The first names of a member: the words of the full name before the surname."""
    surname = _surname_words(member.get("family_name")) | PARTICLES
    words = re.findall(r"[a-z]+", _plain(member.get("name")))
    names: list[str] = []
    for word in words:
        if word in surname:
            break
        names.append(word)
    return names


def _age(birth: str | None, day: str) -> int | None:
    if not birth:
        return None
    return int(day[:4]) - int(birth[:4]) - (day[5:] < birth[5:])


def _surnames_agree(holder: str, member: str | None, *, ij: bool, loose: bool) -> bool:
    ours, theirs = _surname_words(holder, ij=ij), _surname_words(member, ij=ij)
    if not ours or not theirs:
        return False
    return ours == theirs or (loose and (ours <= theirs or theirs <= ours))


def _initials_agree(letters: str, member: dict[str, Any], *, loose: bool) -> bool:
    first = _first_names(member)
    if not first or not letters:
        return True
    theirs = initial_letters(first)
    if loose:
        return theirs.startswith(letters) or letters.startswith(theirs)
    return theirs == letters


def _fits(
    holder: dict[str, Any], member: dict[str, Any], *, ij: bool, loose: bool
) -> bool:
    if not _surnames_agree(
        holder["surname"], member.get("family_name"), ij=ij, loose=loose
    ):
        return False
    if not _initials_agree(holder["letters"], member, loose=loose):
        return False
    for day in holder["days"]:
        age = _age(member.get("birth_date"), day)
        if age is not None and not YOUNGEST <= age <= OLDEST:
            return False
    return True


def match_holder(
    holder: dict[str, Any], members: Iterable[dict[str, Any]]
) -> str | None:
    """The key of the member of parliament that *holder* is, or ``None``.

    *holder* is ``{surname, letters, days, factions}``: the surname and initial letters as
    Rijksoverheid writes them, the first days of their posts, the faction keys of their
    parties. *members* are ``{key, family_name, name, birth_date, factions}``.

    First strictly: the same surname words, the initials of all first names. When that finds
    nobody, loosely: a surname that is part of the other (``Bijleveld``,
    ``Bijleveld-Schouten``), initials of which one begins the other (``S.A.`` and the member
    known as ``Stef``; ``M.C.`` and ``M.C.G.``). Each pass tries ``ij`` as ``y`` when the
    spelling finds nobody, and settles a tie by the faction of the holder's party."""
    members = [m for m in members if m.get("family_name")]
    for loose in (False, True):
        for ij in (False, True):
            fits = [m for m in members if _fits(holder, m, ij=ij, loose=loose)]
            if len(fits) > 1 and holder.get("factions"):
                fits = [
                    m
                    for m in fits
                    if set(m.get("factions") or ()) & set(holder["factions"])
                ] or fits
            if fits:
                return _only([m["key"] for m in fits])
    return None


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
    """The ``id`` of the person in *people* (``{id, name, posts}``) who signed
    *signatures*, or ``None``.

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
