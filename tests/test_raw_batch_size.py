"""Every raw kind is read in batches of its own size (``RAW_BATCH_SIZE``)."""

from __future__ import annotations

from lawgraph.config.constants import RAW_BATCH_SIZE, RAW_SOURCE_KINDS


def test_every_raw_kind_has_a_batch_size() -> None:
    kinds = {kind for kinds in RAW_SOURCE_KINDS.values() for kind in kinds}
    assert set(RAW_BATCH_SIZE) == kinds
    assert all(size > 0 for size in RAW_BATCH_SIZE.values())
