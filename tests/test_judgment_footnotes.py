"""The footnotes of a judgment, which are no paragraph, and the paragraph each belongs to;
a citation in one counts for that paragraph."""

from __future__ import annotations

from pathlib import Path

from lawgraph.core.citations import CitationHit
from lawgraph.core.judgments import extract_sections, judgment_text, parse_judgment
from lawgraph.core.mentions import Mention, find_mentions, footnote_paragraphs

# ECLI:NL:RBZWB:2026:1134 (Rechtspraak open data): r.o. 3.1 refers to footnote 1, which
# cites "art. 10:56 BW", the only article it cites.
XML = (
    Path(__file__).parent / "fixtures" / "rechtspraak_rbzwb_2026_1134.xml"
).read_text()


def test_the_footnotes_and_the_paragraph_that_refers_to_each() -> None:
    root = parse_judgment(XML)
    paragraphs, footnotes = judgment_text(root)
    assert paragraphs == extract_sections(root)
    assert footnotes == [
        {
            "label": "1",
            "paragraph_id": "rov-3.1",
            "text": "Echtscheiding: art. 3 Brussel II-ter en art. 10:56 BW.",
        }
    ]
    assert all("10:56" not in p["text"] for p in paragraphs)
    assert all("_footnotes" not in p for p in paragraphs)


def test_a_citation_in_a_footnote_counts_for_its_paragraph() -> None:
    paragraphs = [
        {"id": "rov-3.1", "number": "3.1", "text": "De rechtbank is bevoegd."}
    ]
    notes = footnote_paragraphs(
        paragraphs,
        [
            {"label": "1", "paragraph_id": "rov-3.1", "text": "Zie art. 10:56 BW."},
            {"label": "2", "paragraph_id": None, "text": "Los."},
        ],
    )
    assert [(n["id"], n["number"], n["footnote"]) for n in notes] == [
        ("rov-3.1", "3.1", "1"),
        ("fn-2", None, "2"),
    ]

    def detect(text: str) -> list[CitationHit]:
        start = text.index("art. 10:56 BW")
        return [
            CitationHit(
                kind="article",
                bwb_id="BWBR0030068",
                article_number="56",
                confidence=0.95,
                start=start,
                end=start + len("art. 10:56 BW"),
            )
        ]

    (cited,) = find_mentions([*paragraphs, *notes], detect).values()
    (mention,) = cited.mentions
    assert (mention.paragraph_id, mention.paragraph_number, mention.footnote) == (
        "rov-3.1",
        "3.1",
        "1",
    )
    assert mention.raw_match == "art. 10:56 BW"  # in the text of the footnote
    assert Mention.from_dict(mention.to_dict()) == mention
