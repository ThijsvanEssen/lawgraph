"""Edges a test makes with meta their model does not allow, on purpose.

The run holds the meta of every edge to the model of its relation (``tests/conftest.py``).
A test that makes a reader survive what no writer can write any more says so here, with
its reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from lawgraph.db.edges import strict_meta


@contextmanager
def off_the_model(reason: str) -> Iterator[None]:
    """The edges made inside are not held to their model, for *reason*."""
    assert reason, "say why the meta is off its model"
    with strict_meta():
        yield
