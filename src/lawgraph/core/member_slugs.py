"""The slug of a member: a stable name for a readable URL (``/leden/rob-jetten``), pure.

A member is named as the API names them (``name``, else ``known_as``, else
``government_name``), in lower-case ASCII with hyphens. A slug once given is never changed:
a namesake who comes later gets the year they were born (``jan-de-vries-1971``), else their
number of the Tweede Kamer (``Persoon.Nummer``), else a number of its own; namesakes who come
together all get one, so none of them is the bare name by the order they were read in.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Any

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str | None) -> str:
    """``Rob Jetten`` -> ``rob-jetten``; ``Yeşilgöz-Zegerius`` -> ``yesilgoz-zegerius``."""
    ascii_name = (
        unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    )
    return _NOT_SLUG.sub("-", ascii_name.lower()).strip("-")


def _name(member: dict[str, Any]) -> str | None:
    return member.get("name") or member.get("known_as") or member.get("government_name")


def _candidates(base: str, member: dict[str, Any]) -> Iterator[str]:
    """The slugs a namesake tries, in order."""
    year = (member.get("birth_date") or "")[:4]
    if year.isdigit():
        yield f"{base}-{year}"
    if member.get("number"):
        yield f"{base}-{member['number']}"
    n = 2
    while True:
        yield f"{base}-{n}"
        n += 1


def new_slugs(members: Iterable[dict[str, Any]]) -> dict[str, str]:
    """key -> slug for every member of *members* (``key``, ``slug``, ``name``,
    ``known_as``, ``government_name``, ``birth_date``, ``number``) that has none and a
    name; the slugs they have stay theirs."""
    members = list(members)
    taken = {m["slug"] for m in members if m.get("slug")}
    wanting: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        base = slugify(_name(member))
        if base and not member.get("slug"):
            wanting.setdefault(base, []).append(member)
    found: dict[str, str] = {}
    for base, group in sorted(wanting.items()):
        if base not in taken and len(group) == 1:
            found[group[0]["key"]] = base
            taken.add(base)
            continue
        for member in sorted(
            group, key=lambda m: (m.get("birth_date") or "", m["key"])
        ):
            slug = next(c for c in _candidates(base, member) if c not in taken)
            found[member["key"]] = slug
            taken.add(slug)
    return found
