"""Where a citation the TK linker reads stands in what the document detail serves."""

from __future__ import annotations

from lawgraph.core.paper_text import PaperText, section_at

# The MvT of 33328 (Wet open overheid) cites the VIR-BI in its footnotes only.
NOTE_71 = (
    "Toelichting op artikel 1 van het Besluit voorschrift informatiebeveiliging "
    "rijksdienst – bijzondere informatie (Virbi)."
)
NOTE_77 = (
    "Artikel 3 lid 3 Besluit voorschrift informatiebeveiliging rijksdienst – bijzondere "
    "informatie, Stscrt. 2004, 47 (Virbi)."
)
PROPS = {
    "title": "Memorie van toelichting",
    "text": "ALGEMEEN\nDe Wob regelt de openbaarheid.\nArtikel 2\nZie artikel 10 Gw.",
    "sections": [
        {"id": "s-1", "char_start": 0, "char_end": 39},
        {"id": "s-2", "char_start": 40, "char_end": 67},
    ],
    "footnotes": [
        {"number": "1", "text": "Kamerstukken II 1986/87, 19 859, nr. 3."},
        "not a footnote",
        {"number": "71", "text": NOTE_71, "at": 30},
        {"number": "1", "text": NOTE_77},  # a label repeats in a legacy paper
    ],
}


def _place(read: PaperText, words: str) -> dict | None:
    start = read.text.index(words)
    return read.place(start, start + len(words))[0]


def test_the_text_read_is_the_parts_one_per_line() -> None:
    read = PaperText.of({**PROPS, "raw": {"Titel": "VVD"}})  # not the record
    assert read.text == "\n".join(
        [
            PROPS["title"],
            PROPS["text"],
            f"Kamerstukken II 1986/87, 19 859, nr. 3.\n{NOTE_71}\n{NOTE_77}",
        ]
    )


def test_a_citation_in_a_footnote_names_it_and_its_offsets() -> None:
    read = PaperText.of(PROPS)
    words = "Artikel 3 lid 3 Besluit voorschrift informatiebeveiliging rijksdienst"
    start = read.text.index(words)
    place, snippet = read.place(start, start + len(words))
    assert place == {
        "part": "footnote",
        "start": 0,
        "end": len(words),
        "footnote": "1",
        "footnote_id": "fn-4",
    }
    assert NOTE_77[place["start"] : place["end"]] == words
    assert snippet == NOTE_77  # of the footnote alone, not its neighbours

    first = _place(read, "artikel 1 van het Besluit")
    assert first is not None
    assert (first["footnote"], first["footnote_id"]) == ("71", "fn-3")


def test_a_citation_in_the_text_names_its_innermost_section() -> None:
    read = PaperText.of(PROPS)
    place = _place(read, "artikel 10 Gw")
    assert place is not None
    assert (place["part"], place["section_id"]) == ("text", "s-2")
    assert PROPS["text"][place["start"] : place["end"]] == "artikel 10 Gw"


def test_a_citation_in_the_title_or_over_two_parts() -> None:
    read = PaperText.of(PROPS)
    assert _place(read, "Memorie") == {"part": "title", "start": 0, "end": 7}
    start = read.text.index("toelichting\nALGEMEEN")
    assert read.place(start, start + 20) == (None, None)
    assert read.place(None, None) == (None, None)


def test_a_text_with_whitespace_around_it_keeps_its_offsets() -> None:
    read = PaperText.of({"text": "  Zie artikel 1 Sr. "})
    place = _place(read, "artikel 1 Sr")
    assert place is not None
    assert "  Zie artikel 1 Sr. "[place["start"] : place["end"]] == "artikel 1 Sr"


def test_the_innermost_section() -> None:
    sections = [
        {"id": "s-1", "char_start": 0, "char_end": 100},
        {"id": "s-2", "char_start": 10, "char_end": 50},
        {"id": "s-3", "char_start": 60, "char_end": 100},
    ]
    assert section_at(sections, 20) == "s-2"
    assert section_at(sections, 55) == "s-1"
    assert section_at(sections, 100) is None
