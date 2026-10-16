"""A value the test knows is there: what a lookup that may find nothing found."""

from __future__ import annotations


def present[T](value: T | None) -> T:
    """*value*, which a test expects to be found; a test fails here when it is not."""
    assert value is not None
    return value
