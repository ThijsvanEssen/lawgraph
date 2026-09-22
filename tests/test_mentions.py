"""Where a judgment cites an article: every citation of every paragraph, with its span."""

from __future__ import annotations

from typing import Any

from lawgraph.core.citations import CitationHit
from lawgraph.core.mentions import (
    MAX_MENTIONS_PER_EDGE,
    Mention,
    find_mentions,
)
from lawgraph.pipelines.semantic._detection import build_extractor, detect_in_text

_EXTRACTOR = build_extractor({"Sr": "BWBR0001854", "Awb": "BWBR0005537"}, {})


def _detect(text: str) -> list[CitationHit]:
    hits = detect_in_text(text, _EXTRACTOR, every_occurrence=True)
    return [hit for hit in hits if hit.kind == "article"]


def _paragraph(
    paragraph_id: str, text: str, number: str | None = None
) -> dict[str, Any]:
    return {"id": paragraph_id, "number": number, "kind": "body", "text": text}


def test_a_hit_per_citation_carries_its_span() -> None:
    text = "Art. 287 Sr, en later art. 287, tweede lid, Sr."

    hits = _EXTRACTOR.extract(text, every_occurrence=True)

    assert [text[h.start : h.end] for h in hits] == [h.raw_match for h in hits]
    assert [h.raw_match for h in hits] == ["Art. 287 Sr", "art. 287, tweede lid, Sr"]
    assert (
        len(_EXTRACTOR.extract(text)) == 1
    )  # by default the first citation stands for all


def test_a_repeated_citation_is_a_mention_at_each_place() -> None:
    text = "Art. 287 Sr is aan de orde. Anders dan art. 287, derde lid, Sr."

    ((key, cited),) = find_mentions(
        [_paragraph("rov-5.3", text, "5.3")], _detect
    ).items()

    assert key == ("BWBR0001854", None, "287")
    assert (
        cited.count == 2 and cited.confidence == 0.95 and cited.reason == "bwb_article"
    )
    first, second = cited.mentions
    assert (first.start, first.end) == (0, 11)
    assert text[second.start : second.end] == "art. 287, derde lid, Sr"
    assert second.start > first.end
    assert (first.parts.leden, second.parts.leden) == ((), ("3",))
    assert second.qualifier == "derde lid"
    assert first.paragraph_id == second.paragraph_id == "rov-5.3"
    assert first.paragraph_number == "5.3"
    assert second.snippet == text


def test_each_mention_is_placed_in_its_own_paragraph() -> None:
    paragraphs = [
        _paragraph("rov-1", "Zie art. 287 Sr.", "1"),
        _paragraph("p-2", "Geen citaat."),
        _paragraph(
            "rov-2", "Ook art. 36f Sr en art. 287, eerste lid, onder b, Sr.", "2"
        ),
    ]

    found = find_mentions(paragraphs, _detect)

    assert list(found) == [
        ("BWBR0001854", None, "287"),
        ("BWBR0001854", None, "36f"),
    ]
    sr287 = found[("BWBR0001854", None, "287")]
    assert [(m.paragraph_id, m.paragraph_number) for m in sr287.mentions] == [
        ("rov-1", "1"),
        ("rov-2", "2"),
    ]
    last = sr287.mentions[1]
    assert paragraphs[2]["text"][last.start : last.end] == last.raw_match
    assert (last.parts.leden, last.parts.onderdelen) == (("1",), ("b",))


def test_a_citation_that_runs_over_a_paragraph_break_is_no_citation() -> None:
    found = find_mentions(
        [_paragraph("p-1", "Volgens artikel 287"), _paragraph("p-2", "Sr is dat zo.")],
        _detect,
    )

    assert found == {}


def test_a_law_named_before_is_the_law_meant_in_the_next_paragraph() -> None:
    found = find_mentions(
        [
            _paragraph("p-1", "Artikel 8:29 Awb geldt."),
            _paragraph("p-2", "Ook artikel 8:30 van die wet geldt."),
        ],
        _detect,
    )

    second = found[("BWBR0005537", None, "8:30")]
    assert second.mentions[0].paragraph_id == "p-2"
    assert second.confidence == 0.7


def test_an_eu_article_is_a_mention_too() -> None:
    (cited,) = find_mentions(
        [_paragraph("p-1", "Zie artikel 6 van Richtlijn 2010/64/EU voor meer.")],
        _detect,
    ).values()

    assert cited.celex == "32010L0064" and cited.article_number == "6"
    assert cited.reason == "celex_article"


def test_the_mentions_are_capped_and_counted() -> None:
    many = " ".join("art. 287 Sr." for _ in range(MAX_MENTIONS_PER_EDGE + 30))

    (cited,) = find_mentions([_paragraph("p-1", many)], _detect).values()

    assert len(cited.mentions) == MAX_MENTIONS_PER_EDGE
    assert cited.count == MAX_MENTIONS_PER_EDGE + 30
    assert cited.meta()["mention_count"] == cited.count
    assert len(cited.meta()["mentions"]) == MAX_MENTIONS_PER_EDGE


def test_the_confidence_of_the_edge_is_the_strongest_mention() -> None:
    (cited,) = find_mentions(
        [
            _paragraph("p-1", "Artikel 8:29 Awb en later artikel 8:29 van die wet."),
        ],
        _detect,
    ).values()

    assert [m.confidence for m in cited.mentions] == [0.95, 0.7]
    assert cited.confidence == 0.95


def test_a_mention_is_stored_and_read_back() -> None:
    (cited,) = find_mentions(
        [_paragraph("rov-5.3", "Zie art. 287, derde lid, Sr.", "5.3")], _detect
    ).values()
    (mention,) = cited.mentions

    stored = mention.to_dict()

    assert stored["leden"] == ["3"] and stored["paragraph_number"] == "5.3"
    assert Mention.from_dict(stored) == mention
    assert Mention.from_dict({"paragraph_id": "x"}) is None
    assert Mention.from_dict("nonsense") is None
