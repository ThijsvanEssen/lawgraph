"""The chains between two nodes without a database: their order, which are shown, where the
levels from both ends meet, and which way a step takes."""

from __future__ import annotations

import pytest

from lawgraph.db.queries import chains
from lawgraph.db.queries.chains import (
    Found,
    Label,
    Link,
    Ways,
    add_link,
    chain_of,
    meet,
    options_of,
    pick,
    plan_of,
)

STRONG, WEAK = Link(2.0, 2, False), Link(0.5, 1, False)
ENDS = ("articles/a", "articles/b")


def test_the_weakest_step_ranks_first_then_the_steps_together_then_the_ids() -> None:
    found = [
        Found(("articles/c",), (STRONG, WEAK)),
        Found(("articles/e",), (Link(1.0, 1, False), Link(1.0, 1, False))),
        Found(("articles/d",), (Link(1.0, 1, False), Link(1.5, 1, False))),
        Found(("articles/f",), (Link(1.0, 1, False), Link(1.0, 1, False))),
    ]
    order = [f.between[0][-1] for f in sorted(found, key=Found.rank)]
    assert order == ["d", "e", "f", "c"]


def test_each_source_between_the_ends_is_in_one_chain_picked() -> None:
    found = [
        Found(("c1", "d"), (STRONG,) * 3),
        Found(("c2", "d"), (STRONG,) * 3),
        Found(("c2", "e"), (STRONG,) * 3),
    ]
    taken: set[str] = set()
    assert pick(iter(found), 12, taken) == [found[0], found[2]]
    assert taken == {"c1", "d", "c2", "e"}
    # the limit stops it after the one it takes, not after the one it reads next
    rest = iter(found)
    assert pick(rest, 1, set()) == [found[0]]
    assert next(rest) == found[1]
    assert pick(iter(found), 0, set()) == []


def test_the_levels_meet_at_a_source_once_in_the_chain() -> None:
    from_a = {
        "m": Label(("c", "m"), (STRONG, WEAK)),
        "x": Label(("c", "x"), (STRONG, STRONG)),
    }
    from_b = {
        "m": Label(("d", "m"), (WEAK, STRONG)),
        "x": Label(("c", "x"), (WEAK, WEAK)),
    }
    found, twice = meet(from_a, from_b)
    # a, c, m, d, b: the steps from b turned toward it; through x c would be twice
    assert found == [Found(("c", "m", "d"), (STRONG, WEAK, STRONG, WEAK))]
    assert twice == 1


def test_a_link_adds_the_ways_together() -> None:
    links: dict[str, Link] = {}
    add_link(links, "c", WEAK)
    add_link(links, "c", Link(1.0, 0, True))
    assert links == {"c": Link(1.5, 1, True)}


def test_a_step_takes_the_edge_else_the_node_of_the_fewest_sources() -> None:
    chain = (*ENDS[:1], "articles/c", ENDS[1])
    edge = options_of(
        ENDS, chain, 0, STRONG, Ways("e0", [(2, "documents/p", "x", "y")])
    )
    assert [(s.via, s.edges) for s in edge] == [(None, ("e0",))]
    shared = Ways(
        None,
        [
            (3, "documents/a", "a1", "a2"),
            (2, "documents/z", "z1", "z2"),
            (2, "documents/y", "y1", "y2"),
            (51, "documents/big", "b1", "b2"),
            (2, "articles/c", "c1", "c2"),
        ],
    )
    options = options_of(ENDS, chain, 0, STRONG, shared)
    # over the cap left out, and no source of the chain
    assert [s.via for s in options] == ["documents/y", "documents/z", "documents/a"]
    assert (options[0].edges, options[0].ways, options[0].weight) == (
        ("y1", "y2"),
        2,
        2.0,
    )


def test_an_end_that_is_no_source_counts_among_the_sources_of_what_it_shares() -> None:
    ends = ("judgments/j", "articles/b")
    chain = (ends[0], ends[1])
    ways = Ways(
        None, [(50, "documents/p", "p1", "p2"), (49, "documents/q", "q1", "q2")]
    )
    assert [s.via for s in options_of(ends, chain, 0, WEAK, ways)] == ["documents/q"]


def test_no_node_is_twice_in_a_chain() -> None:
    chain = ("articles/a", "articles/c", "articles/b")
    once = options_of(ENDS, chain, 0, STRONG, Ways(None, [(2, "documents/k", "", "")]))
    twice = options_of(
        ENDS,
        chain,
        1,
        STRONG,
        Ways(None, [(2, "documents/k", "", ""), (3, "documents/m", "", "")]),
    )
    found = chain_of(chain, [once, twice])
    assert found is not None
    assert [s.via for s in found.steps] == ["documents/k", "documents/m"]
    assert chain_of(chain, [once, once]) is None
    assert chain_of(chain, [once, []]) is None


def test_the_table_settles_a_chain_whose_ways_it_names_each_once() -> None:
    chain = ("articles/a", "articles/c", "articles/b")
    edge = Link(1.4, 0, True)
    assert plan_of(chain, (edge, STRONG), [None, "documents/k"]) == [
        None,
        "documents/k",
    ]
    # a step the table names no node for, a node twice, a source of the chain
    assert plan_of(chain, (STRONG, STRONG), [None, "documents/k"]) is None
    assert plan_of(chain, (STRONG, STRONG), ["documents/k", "documents/k"]) is None
    assert plan_of(chain, (STRONG, STRONG), ["articles/b", "documents/k"]) is None


def test_the_warm_up_searches_every_two_of_the_most_cited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        chains, "get_chains", lambda store, ends, steps, limit: asked.append(ends)
    )
    chains.warm_chains(None, [f"articles/{c}" for c in "abcdefgh"])  # type: ignore[arg-type]
    n = chains.WARM_CHAIN_ENDS
    assert len(asked) == n * (n - 1) // 2
    assert all("g" not in a + b for a, b in asked)
    # past its time it stops at once
    asked.clear()
    chains.warm_chains(None, ["articles/a", "articles/b"], seconds=0.0)  # type: ignore[arg-type]
    assert asked == []
