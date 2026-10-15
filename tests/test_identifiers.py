"""The publication ids and the cleaning of retrieved ids (``core/identifiers.py``)."""

from __future__ import annotations

from lawgraph.core.identifiers import STB_ID_PATTERN, STCRT_ID_PATTERN, clean_ids


def test_publication_id_patterns() -> None:
    assert STB_ID_PATTERN.search("x STB-2015-134 y").groups() == ("2015", "134")  # type: ignore[union-attr]
    assert STCRT_ID_PATTERN.search("STCRT-2020-55").groups() == ("2020", "55")  # type: ignore[union-attr]
    assert STCRT_ID_PATTERN.search("stb-2020-55") is None
    assert STB_ID_PATTERN.search("stcrt-2020-55") is None


def test_clean_ids() -> None:
    norm = clean_ids
    assert norm(None) == []
    assert norm([]) == []
    assert norm([" A ", "", None, "B", "A", "  "]) == ["A", "B"]  # type: ignore[list-item]
