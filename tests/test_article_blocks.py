"""The text of an article as blocks per lid, onderdeel and aanhef (``core.article_blocks``)."""

from __future__ import annotations

from typing import NamedTuple

from lawgraph.core.article_blocks import article_blocks


class Part(NamedTuple):
    id: str
    kind: str
    number: str | None
    start: int
    end: int


class Heading(NamedTuple):
    start: int
    end: int


def _parts(text: str, *spans: tuple[str, str, str | None, str, str]) -> list[Part]:
    """Parts of *text* by the words they start and end with."""
    return [
        Part(id, kind, number, text.index(first), text.index(last) + len(last))
        for id, kind, number, first, last in spans
    ]


def _read(text: str, parts: list[Part], headings: list[Heading] | None = None):
    return [
        (b.anchor, b.kind, b.marker, b.within, text[b.start : b.end])
        for b in article_blocks(text, parts, headings or [])
    ]


def test_a_lid_with_an_aanhef_and_onderdelen() -> None:
    text = "1. Een.\n2. Onder:\na. de een;\nb. de ander.\n3. Drie."
    parts = _parts(
        text,
        ("lid-1", "lid", "1", "Een.", "Een."),
        ("lid-2", "lid", "2", "Onder:", "ander."),
        ("lid-2-aanhef", "aanhef", None, "Onder:", "Onder:"),
        ("lid-2-onder-a", "onderdeel", "a", "de een;", "de een;"),
        ("lid-2-onder-b", "onderdeel", "b", "de ander.", "de ander."),
        ("lid-3", "lid", "3", "Drie.", "Drie."),
    )
    assert _read(text, parts) == [
        ("lid-1", "lid", "1.", (), "Een."),
        ("lid-2-aanhef", "aanhef", "2.", ("lid-2",), "Onder:"),
        ("lid-2-onder-a", "onderdeel", "a.", ("lid-2",), "de een;"),
        ("lid-2-onder-b", "onderdeel", "b.", ("lid-2",), "de ander."),
        ("lid-3", "lid", "3.", (), "Drie."),
    ]


def test_the_lines_of_one_part_are_one_block() -> None:
    text = "1. Een.\nNog een zin.\n2. Twee."
    parts = _parts(
        text,
        ("lid-1", "lid", "1", "Een.", "zin."),
        ("lid-2", "lid", "2", "Twee.", "Twee."),
    )
    assert _read(text, parts) == [
        ("lid-1", "lid", "1.", (), "Een.\nNog een zin."),
        ("lid-2", "lid", "2.", (), "Twee."),
    ]


def test_a_part_that_goes_on_after_its_list_repeats_its_anchor() -> None:
    text = "1. Onder:\na. een;\nDaarna.\n2. Twee."
    parts = _parts(
        text,
        ("lid-1", "lid", "1", "Onder:", "Daarna."),
        ("lid-1-onder-a", "onderdeel", "a", "een;", "een;"),
        ("lid-2", "lid", "2", "Twee.", "Twee."),
    )
    assert [(a, m, t) for a, _, m, _, t in _read(text, parts)] == [
        ("lid-1", "1.", "Onder:"),
        ("lid-1-onder-a", "a.", "een;"),
        ("lid-1", None, "Daarna."),
        ("lid-2", "2.", "Twee."),
    ]


def test_an_article_without_parts_is_one_block_without_an_anchor() -> None:
    text = "Een zin.\nNog een."
    assert _read(text, []) == [(None, "tekst", None, (), text)]


def test_a_heading_is_a_block_of_its_own() -> None:
    text = "Eerste kop\nDe tekst.\nTweede kop\nMeer tekst."
    headings = [Heading(0, 10), Heading(21, 31)]
    assert [(k, t) for _, k, _, _, t in _read(text, [], headings)] == [
        ("kop", "Eerste kop"),
        ("tekst", "De tekst."),
        ("kop", "Tweede kop"),
        ("tekst", "Meer tekst."),
    ]
