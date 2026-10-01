"""AQL that the queries still on ArangoDB share; it goes with the last of them."""

from __future__ import annotations


def sorted_merge(left: str, right: str) -> str:
    """AQL for ``MERGE(left, right)`` with every key in the order of the collation.

    MERGE keeps the keys of *left* and adds those only *right* has in the order of a hash
    map, which differs from one execution to the next: the props of a node the API serves
    would come out in another order after every run. Sorted, they do not (D11). The names
    of its variables are its own, so it can go into a query that has ``names``."""
    return (
        f"(FOR sorted_merged IN [MERGE({left}, {right})]"
        " LET sorted_names = ATTRIBUTES(sorted_merged, false, true)"
        " RETURN ZIP(sorted_names, sorted_names[* RETURN sorted_merged[CURRENT]]))[0]"
    )
