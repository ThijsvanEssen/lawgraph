"""Generic XML helpers (pure) shared by every source that parses XML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator

XML_TAG_RE = re.compile(r"<[^>]+>")  # any markup tag, for stripping tags from text


def local_name(tag: str) -> str:
    """Local part of an XML tag, without a Clark-notation namespace (``{ns}tag``)."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def collapse_ws(text: str | None) -> str:
    """Collapse every run of whitespace to one space and strip ('' for None)."""
    return " ".join(text.split()) if text else ""


def text_of(element: ET.Element | None, sep: str = "") -> str:
    """Stripped text content of *element* and all its descendants ('' for None).

    *sep* is put between the text fragments. The default ``""`` glues them
    together (inline markup stays inside the word); ``" "`` keeps fragments of
    adjacent block elements apart.
    """
    if element is None:
        return ""
    return sep.join(element.itertext()).strip()


def find_descendant(element: ET.Element, name: str) -> ET.Element | None:
    """First descendant (not *element* itself) whose local name is *name*."""
    for node in element.iter():
        if node is not element and local_name(node.tag) == name:
            return node
    return None


def iter_named(element: ET.Element, *names: str) -> Iterator[ET.Element]:
    """Every descendant-or-self whose local name is one of *names*, in document order."""
    for node in element.iter():
        if local_name(node.tag) in names:
            yield node


def first_named(element: ET.Element, *names: str) -> ET.Element | None:
    """First descendant-or-self whose local name is one of *names* (document order)."""
    return next(iter_named(element, *names), None)


def find_text(
    element: ET.Element,
    *names: str,
    sep: str = "",
    collapse: bool = False,
    skip_empty: bool = True,
) -> str | None:
    """Text of the first descendant-or-self whose local name is one of *names*.

    With ``skip_empty`` (default) matches without text are passed over and the
    next match is tried; with ``skip_empty=False`` the first match decides, so
    an empty first match gives ``None``. ``collapse`` folds inner whitespace
    (see ``collapse_ws``). *sep* is forwarded to ``text_of``.
    """
    for node in iter_named(element, *names):
        text = text_of(node, sep)
        if collapse:
            text = collapse_ws(text)
        if text or not skip_empty:
            return text or None
    return None


def find_own_text(element: ET.Element, name: str) -> str | None:
    """Stripped ``.text`` (no descendants) of the first descendant-or-self *name*.

    The first match decides: if it has no text of its own the result is ``None``
    even when a later match has text.
    """
    node = first_named(element, name)
    if node is None:
        return None
    return (node.text or "").strip() or None


def extract_section_text(element: ET.Element, *names: str) -> str | None:
    """All text of the first matching descendant-or-self, fragments joined by a space.

    The first match decides: an empty first match gives ``None``.
    """
    return text_of(first_named(element, *names), " ") or None
