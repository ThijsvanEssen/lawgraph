"""The slug of a member: a stable name for a readable URL (``/leden/rob-jetten``), pure.

A member is named as the API names them (``name``, else ``known_as``, else
``government_name``), in lower-case ASCII with hyphens. A slug once given is never changed:
a namesake who comes later gets the year they were born (``jan-de-vries-1971``), else their
number of the Tweede Kamer (``Persoon.Nummer``), else a number of its own; namesakes who come
together all get one, so none of them is the bare name by the order they were read in.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.core.slugs import claim, numbered
from lawgraph.core.text_fold import ascii_slug


def _name(member: dict[str, Any]) -> str | None:
    return member.get("name") or member.get("known_as") or member.get("government_name")


def _candidates(base: str, member: dict[str, Any]) -> Iterator[str]:
    """The slugs a namesake tries, in order."""
    year = (member.get("birth_date") or "")[:4]
    if year.isdigit():
        yield f"{base}-{year}"
    if member.get("number"):
        yield f"{base}-{member['number']}"
    yield from numbered(base)


def new_slugs(members: Iterable[dict[str, Any]]) -> dict[str, str]:
    """key -> slug for every member of *members* (``key``, ``slug``, ``name``,
    ``known_as``, ``government_name``, ``birth_date``, ``number``) that has none and a
    name; the slugs they have stay theirs."""
    members = list(members)
    taken = {m["slug"] for m in members if m.get("slug")}
    wanting: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        base = ascii_slug(_name(member))
        if base and not member.get("slug"):
            wanting.setdefault(base, []).append(member)
    found: dict[str, str] = {}
    for base, group in sorted(wanting.items()):
        if base not in taken and len(group) == 1:
            found[group[0]["key"]] = claim([base], taken)
            continue
        for member in sorted(
            group, key=lambda m: (m.get("birth_date") or "", m["key"])
        ):
            found[member["key"]] = claim(_candidates(base, member), taken)
    return found
