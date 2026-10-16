"""Picking values from an answer (``core/values.py``)."""

from __future__ import annotations

from lawgraph.core.values import first_str, next_page_link


def test_extract_next_link() -> None:
    fn = next_page_link
    assert fn({"n": " http://x "}, "n") == "http://x"
    assert fn({"n": "  "}, "n") is None
    assert fn({"n": 5}, "n") is None
    assert fn({"n": "x"}, None) is None
    assert fn([], "n") is None
    assert fn({}, "n") is None


def test_first_non_none_str_and_first_non_empty() -> None:
    assert first_str([None, "", "x"]) == ""  # empty string counts
    assert first_str([None, 5]) == "5"
    assert first_str([None, None]) is None
    assert first_str([]) is None
    assert first_str([None, " x "]) == " x "  # not stripped
    assert first_str([None, "  ", " x "], skip_blank=True) == "x"
    assert first_str([None, 5], skip_blank=True) == "5"
    assert first_str([None, ""], skip_blank=True) is None
