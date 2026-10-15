"""A raw kind's constant starts with the key of its source: ``RAW_KIND_RECHTSPRAAK_CONTENT``
is a kind of ``rechtspraak``. The values are stored (``raw_sources.kind``) and keep the
spelling they have."""

from __future__ import annotations

from lawgraph.config import constants
from lawgraph.config.constants import RAW_SOURCE_KINDS


def test_a_raw_kind_is_named_by_its_source() -> None:
    names = {
        value: name
        for name, value in vars(constants).items()
        if name.startswith("RAW_KIND_") and isinstance(value, str)
    }
    found = [
        names[kind]
        for source, kinds in RAW_SOURCE_KINDS.items()
        for kind in kinds
        if not names[kind].startswith(f"RAW_KIND_{source.upper()}_")
    ]
    assert found == []
