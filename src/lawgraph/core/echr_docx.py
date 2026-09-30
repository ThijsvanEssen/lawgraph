"""The text and paragraphs of an ECHR judgment, from the ``word/document.xml`` of its DOCX.

HUDOC serves every judgment as a Word document written with the Court's templates, and the
style of a paragraph says what it is. Two families of styles are in use: ``Ju…``/``Opi…``/
``Dec…`` (the judgment, a separate opinion, a decision; ``JuHHead`` a section heading,
``JuHIRoman``, ``JuHA``, ``JuH1``, ``JuHa`` the levels below it, ``JuPara`` a paragraph,
``JuQuot`` a quotation) and ``ECHR…`` (``ECHRHeading1`` to ``ECHRHeading6``, ``ECHRPara``,
``ECHRParaQuote``). A table of contents (``TOC1``…) is left out.

A paragraph of the Court is numbered in its text ("12.  The applicant …") and cited as
§ 12. Headings number by Word's list numbering in newer judgments, which the body does not
hold, so only a number that is text ("I.  ALLEGED VIOLATION …", "(a) On the …") is read.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

from lawgraph.core.judgments import KIND_BODY, KIND_HEADING, KIND_SUBHEADING
from lawgraph.core.xml import local_name

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# ``JuHHead``, ``OpiHHead``, ``DecHHead``, ``ECHRHeading1``: a section heading.
_HEADING = re.compile(r"^(?:(?:ju|opi|dec)hhead|echrheading1)$", re.I)
# ``JuHIRoman``, ``JuHA``, ``JuH1``, ``OpiHa``, ``DecHTitle``, ``ECHRHeading2``: below it.
# ``JuHeader`` is the running header of a page, not a heading.
_SUBHEADING = re.compile(r"^(?:(?:ju|opi|dec)h(?!eader)\w*|echrheading[2-9])$", re.I)
_TABLE_OF_CONTENTS = re.compile(r"^toc", re.I)

# "12.  The applicant …": a paragraph of the Court, in a style of paragraphs (``JuPara``,
# ``OpiPara``, ``ECHRPara``), not a quotation or a list item (the operative part numbers its
# points "1. Holds that …").
_PARAGRAPH_NUMBER = re.compile(r"^(\d+)\.\s+")
# "I.  ALLEGED VIOLATION", "A. The applicant's complaint", "1. General principles",
# "(a) On the existence …", "(i) …"
_HEADING_NUMBER = re.compile(r"^(?:([IVXLC]+|[A-Za-z]|\d+)\.|\(([a-z]+|\d+)\))\s+")


def _is_paragraph_style(style: str) -> bool:
    lower = style.lower()
    return "para" in lower and "quot" not in lower


def _kind(style: str) -> str:
    if _HEADING.match(style):
        return KIND_HEADING
    if _SUBHEADING.match(style):
        return KIND_SUBHEADING
    return KIND_BODY


def _paragraphs(element: ET.Element) -> Iterator[ET.Element]:
    """Every ``<w:p>`` in reading order, also in tables and text boxes; the fallback copy of
    a drawing (``mc:Fallback``) left out, since its ``mc:Choice`` holds the same text."""
    for child in element:
        name = local_name(child.tag)
        if name == "Fallback":
            continue
        if name == "p":
            yield child
        yield from _paragraphs(child)


def _runs_text(element: ET.Element) -> Iterator[str]:
    """The text of a paragraph's own runs: not that of a paragraph inside it (a text box)."""
    for child in element:
        name = local_name(child.tag)
        if name in ("p", "Fallback"):
            continue
        if name == "t" and child.text:
            yield child.text
        elif name in ("tab", "br", "cr"):
            yield " "
        elif name == "noBreakHyphen":
            yield "-"
        else:
            yield from _runs_text(child)


def _style(paragraph: ET.Element) -> str:
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    return style.get(f"{_W}val", "") if style is not None else ""


class _Numbering:
    """Ids unique in the judgment: a number that repeats one before it (a separate opinion
    numbers from 1 again) gets ``_<n>``, its occurrence."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._seen: dict[str, int] = {}

    def add(self, kind: str, number: str | None, text: str) -> None:
        if number:
            slug = re.sub(r"[^0-9a-z]", "", number.lower())
            base = f"{'par' if kind == KIND_BODY else 'kop'}-{slug}"
        else:
            base = f"p-{len(self.entries) + 1}"
        self._seen[base] = self._seen.get(base, 0) + 1
        seen = self._seen[base]
        self.entries.append(
            {
                "id": base if seen == 1 else f"{base}_{seen}",
                "number": number,
                "kind": kind,
                "text": text,
            }
        )


def _split(kind: str, style: str, text: str) -> tuple[str | None, str]:
    """``(number, text without it)`` of a paragraph that opens with its number."""
    if kind == KIND_BODY:
        match = _PARAGRAPH_NUMBER.match(text) if _is_paragraph_style(style) else None
        return (match[1], text[match.end() :]) if match else (None, text)
    match = _HEADING_NUMBER.match(text)
    return (match[1] or match[2], text[match.end() :]) if match else (None, text)


def read_judgment(xml_text: str) -> tuple[str | None, list[dict[str, Any]]]:
    """``(text, paragraphs)`` of the ``word/document.xml`` of a HUDOC judgment.

    ``paragraphs`` is the body in reading order, each ``{id, number, kind, text}`` as for a
    Rechtspraak judgment: ``kind`` ``heading``, ``subheading`` or ``body``; ``number`` as
    printed without its dot, and not in ``text``; ``id`` ``par-12`` for paragraph 12,
    ``kop-i`` for a numbered heading, ``p-<n>`` (its position) for the rest. ``text`` is every
    paragraph as printed, a blank line between; ``None`` for a document without any.
    ``ValueError`` when *xml_text* is not XML.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc
    body = root.find(f"{_W}body")
    if body is None:
        return None, []
    printed: list[str] = []
    numbering = _Numbering()
    for paragraph in _paragraphs(body):
        style = _style(paragraph)
        if _TABLE_OF_CONTENTS.match(style):
            continue
        text = re.sub(r"\s+", " ", "".join(_runs_text(paragraph))).strip()
        if not text:
            continue
        printed.append(text)
        kind = _kind(style)
        numbering.add(kind, *_split(kind, style, text))
    return ("\n\n".join(printed) or None), numbering.entries
