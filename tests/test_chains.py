"""The chains between two nodes without a database: which way a step takes, and the order
of the edges of the last step, read from the far end."""

from __future__ import annotations

from lawgraph.db.queries.chains import _by_id, _chain, _Options


def test_a_step_takes_the_edge_first_then_the_lowest_id() -> None:
    pick = _Options(_by_id).pick(("a", "b"), [{"k2": ("e1", "e2"), None: ("e0",)}])
    assert pick == (None,)


def test_no_node_is_twice_in_a_chain() -> None:
    options = _Options(_by_id)
    # the paper k names a, c and b: the second step takes another
    assert options.pick(("a", "c", "b"), [{"k": ()}, {"k": (), "m": ()}]) == ("k", "m")
    assert options.pick(("a", "c", "b"), [{"k": ()}, {"k": ()}]) is None
    # nor through a source of the chain itself
    assert (
        options.pick(("a", "c", "d", "b"), [{"d": ()}, {None: ()}, {None: ()}]) is None
    )


def test_the_last_step_turns_its_edges_toward_the_far_end() -> None:
    chain = _chain(
        ("a", "c", "b"),
        [{"k": ("ak", "kc")}, {"m": ("bm", "mc")}],
        ("k", "m"),
        weight=3,
    )
    assert [(s.source, s.target, s.edges) for s in chain.steps] == [
        ("a", "c", ("ak", "kc")),
        ("c", "b", ("mc", "bm")),
    ]
    one = _chain(("a", "b"), [{"k": ("ak", "kb")}], ("k",), weight=0)
    assert one.steps[0].edges == ("ak", "kb")
