"""Props of a member, and whether they hold a role (``core.member_role``): the cases the
Python rule and its SQL are both held to."""

from __future__ import annotations

from typing import Any

# props of a member, and whether they hold a role
CASES: list[tuple[dict[str, Any], bool]] = [
    ({"faction_memberships": [{"faction_key": "d66"}]}, True),
    ({"government_functions": [{"function": "Minister-president"}]}, True),
    ({"ek_faction_memberships": [{"faction": "PvdA"}]}, True),
    ({"ek": {"faction": "ek_d66"}}, True),
    ({}, False),
    ({"faction_memberships": [], "government_functions": []}, False),
    ({"ek": None, "ek_faction_memberships": None}, False),
    ({"faction_memberships": "d66"}, False),  # not a list
]
