"""Whether a member has a role in the sources (pure): a seat in a faction of the Tweede Kamer
(``faction_memberships``), a post in a cabinet (``government_functions``), a seat in the
Eerste Kamer (``ek``, its composition) or a period in one of its factions
(``ek_faction_memberships``, their page). A member without one is a person of the Tweede
Kamer's records only (``Persoon``) whose seat the data does not hold: their page is not
indexed, the sitemap leaves them out, and search lists them after the members with one.

``db.queries.member_role.has_role`` is the same test in SQL; a test keeps the two equal.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# the props that are a role when they hold a list with something in it
ROLE_LISTS = (
    "faction_memberships",
    "government_functions",
    "ek_faction_memberships",
)


def has_role(props: Mapping[str, Any]) -> bool:
    """Whether *props* (of a member) hold a seat or a post."""
    return any(
        isinstance(props.get(field), list) and len(props[field]) > 0
        for field in ROLE_LISTS
    ) or isinstance(props.get("ek"), dict)
