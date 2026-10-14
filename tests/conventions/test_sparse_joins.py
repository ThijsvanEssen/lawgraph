"""A join on a sparse index excludes null."""

from __future__ import annotations

import re

from tests.conventions._scan import SRC

_SPARSE_JOIN = re.compile(r"\.props\.(bwb_id|celex|ecli) == (?!@|null\b)[A-Za-z_]")


def test_a_join_on_a_sparse_index_excludes_null() -> None:
    """``i.props.bwb_id == pub.props.bwb_id`` alone is a full scan per outer row.

    The indexes on ``props.bwb_id``, ``props.celex`` and ``props.ecli`` are sparse. Compared
    with a value that is not a bind parameter, ArangoDB only uses one when the query also says
    ``!= null`` (explain: cost 587M against 410K for the Staatscourant join).
    """
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _SPARSE_JOIN.search(line) and "!= null" not in line
    ]
    assert not offenders, offenders
