"""Shared XML helpers for normalize pipelines."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_NS_STRIP = re.compile(r"\{[^}]+\}")


def strip_ns(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


def find_text(elem: ET.Element, *local_names: str) -> str | None:
    """Return the stripped text of the first descendant whose local name matches."""
    for child in elem.iter():
        if strip_ns(child.tag) in local_names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


def extract_section_text(elem: ET.Element, *section_names: str) -> str | None:
    """Return all itertext from the first descendant whose local name matches."""
    for child in elem.iter():
        if strip_ns(child.tag) in section_names:
            text = " ".join(child.itertext()).strip()
            return text if text else None
    return None
