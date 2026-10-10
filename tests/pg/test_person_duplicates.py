"""Two ``Persoon`` records of the Tweede Kamer of one person (``semantic
tk-person-duplicates``): the bare one is ``SAME_AS`` the one with a role, on birth date,
surname and initials."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.pipelines.semantic.tk_person_duplicates import (
    TKPersonDuplicatesSemanticPipeline,
)

SEAT = [{"faction_id": "factions/vvd", "faction_key": "vvd", "from_date": "2010-06-17"}]


def _member(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "member", "labels": ["TK"], "props": props}


def _same_as(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'SAME_AS'"
            " AND source = 'tk-person-duplicates'"
        )
    }


def test_a_bare_record_is_the_member_with_a_role(store: GraphStore) -> None:
    straus = {"birth_date": "1971-04-06", "family_name": "Straus"}
    wijk = {"birth_date": "1962-08-23", "family_name": "Wijk"}
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _member("straus", initials="K.C.J.", faction_memberships=SEAT, **straus),
            # the bare record the Kamer made for her seat in the Eerste Kamer
            _member("straus_ek", initials="KCJ", **straus),
            # another initial: someone else
            _member("straus_other", initials="KCM", **straus),
            # two bare records: neither has a role, no edge
            _member("wijk_1", initials="APM", **wijk),
            _member("wijk_2", initials="APM", **wijk),
            # two members with a role it could be: left alone
            _member("vries_a", initials="J.", family_name="Vries", birth_date="1950-01-01",
                    faction_memberships=SEAT),
            _member("vries_b", initials="J.", family_name="Vries", birth_date="1950-01-01",
                    government_functions=[{"function": "Minister"}]),
            _member("vries_bare", initials="J", family_name="Vries", birth_date="1950-01-01"),
        ],
    )  # fmt: skip
    TKPersonDuplicatesSemanticPipeline(store=store).run()
    assert _same_as(store) == {("members/straus_ek", "members/straus")}

    # derived in full: when the bare record gains a role of its own, the edge goes
    store.bulk_insert_or_update_nodes(
        "members", [_member("straus_ek", ek_faction_memberships=[{"faction": "VVD"}])]
    )
    TKPersonDuplicatesSemanticPipeline(store=store).run()
    assert _same_as(store) == set()
