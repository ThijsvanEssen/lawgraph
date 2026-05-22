"""Shared XML helpers for normalize pipelines."""

from __future__ import annotations

import xml.etree.ElementTree as ET


def local_name(tag: str) -> str:
    """Return the local part of an XML tag, stripping any Clark-notation namespace."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_text(elem: ET.Element, *local_names: str) -> str | None:
    """Return the stripped text of the first descendant whose local name matches."""
    for child in elem.iter():
        if local_name(child.tag) in local_names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


def extract_section_text(elem: ET.Element, *section_names: str) -> str | None:
    """Return all itertext from the first descendant whose local name matches."""
    for child in elem.iter():
        if local_name(child.tag) in section_names:
            text = " ".join(child.itertext()).strip()
            return text if text else None
    return None
