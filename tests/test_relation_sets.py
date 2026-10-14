"""The named sets of change relations, and every group built from them, pinned literally:
what a publication does to a regulation is written once, in ``config.constants``."""

from __future__ import annotations

from lawgraph.config import constants
from lawgraph.db.queries import dossiers, feed, feed_relations, overlay


def test_the_named_sets() -> None:
    assert constants.CHANGE_RELATIONS == ("AMENDS", "INTRODUCES", "REPEALS")
    assert constants.ENACTING_RELATIONS == (
        "ESTABLISHES",
        "AMENDS",
        "INTRODUCES",
        "REPEALS",
    )
    assert constants.PUBLICATION_RELATIONS == (
        "ESTABLISHES",
        "AMENDS",
        "INTRODUCES",
        "REPEALS",
        "EXPLAINS",
    )


def test_the_groups_built_from_them() -> None:
    # the hub lists an instrument's ties to a dossier in this order
    assert dossiers.HUB_INSTRUMENT_RELATIONS == (
        "LEGISLATED_IN",
        "ESTABLISHES",
        "AMENDS",
        "INTRODUCES",
        "REPEALS",
    )
    assert dossiers.MUTATION_RELATIONS == (
        "AMENDS",
        "INTRODUCES",
        "REPEALS",
        "REFERS_TO",
    )
    assert overlay._ARTICLE_CITATION_RELATIONS == [
        "REFERS_TO",
        "AMENDS",
        "INTRODUCES",
        "REPEALS",
    ]


def test_the_sql_lists_of_changes() -> None:
    assert feed_relations._CHANGES == "'AMENDS', 'INTRODUCES', 'REPEALS'"
    assert feed._CHANGES == "'AMENDS', 'INTRODUCES', 'REPEALS'"
