"""The dossier a publication names by its number: the Staatsblad, the BWB and the
Verdragenbank name a Rijkswet's dossier without the number of the Rijkswet (``33440`` for
``33440-(R1990)``, ``core.dossier_numbers.published_number``)."""

from __future__ import annotations

from collections.abc import Iterable

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.dossier_numbers import published_number
from lawgraph.core.models import make_node_key
from lawgraph.db.counting import Store


def dossier_keys(store: Store, numbers: Iterable[str]) -> dict[str, str]:
    """The key of the dossier each of *numbers* (``36200-VII``, ``33440``) names, for those
    the graph holds: the dossier of that label, else, for a bare number, the one dossier of
    a Rijkswet of that number."""
    wanted = {number: make_node_key(number) for number in numbers}
    held = store.existing_keys(COLLECTION_DOSSIERS, set(wanted.values()))
    found = {number: key for number, key in wanted.items() if key in held}
    bare = sorted(n for n in wanted if n not in found and n.isdigit())
    if bare:
        found |= rijkswet_dossiers(store, bare)
    return found


def rijkswet_dossiers(store: Store, numbers: list[str]) -> dict[str, str]:
    """Per number of *numbers* (``33440``) the key of the one dossier of a Rijkswet of that
    number (``33440-(R1990)``); none for a number with no such dossier, or with several."""
    keys: dict[str, list[str]] = {}
    for row in store.query(
        f"""
        SELECT d.label, d.key FROM {COLLECTION_DOSSIERS} d
        WHERE d.number = ANY(%(numbers)s::text[]) AND d.label IS NOT NULL
        ORDER BY d.key
        """,
        {"numbers": numbers},
    ):
        number = published_number(row["label"])
        if number != row["label"]:
            keys.setdefault(number, []).append(row["key"])
    return {number: found[0] for number, found in keys.items() if len(found) == 1}
