"""Normalize pipeline for Dutch Staatscourant ministeriële regelingen."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_STAATSCOURANT_REGELING,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.display import shorten
from lawgraph.core.identifiers import STCRT_ID_PATTERN
from lawgraph.core.time import iso_date
from lawgraph.core.xml import find_text, text_of
from lawgraph.pipelines.normalize._publication import (
    Parsed,
    PublicationNormalizePipeline,
    PublicationSpec,
)


def _regulation(root: ET.Element, parsed: Parsed) -> dict[str, Any]:
    text = find_text(root, "tekst", "body", "inhoud") or text_of(root, " ")[:100000]
    props: dict[str, Any] = {
        "text": text or "",
        "display_name": (
            f"Stcrt. {parsed.year}/{parsed.number}: {shorten(parsed.title, 100)}"
            if parsed.title
            else parsed.identifier
        ),
    }
    if date := iso_date(find_text(root, "publicatiedatum", "datum")):
        props["date"] = date
    return props


class StaatscourantNormalizePipeline(PublicationNormalizePipeline):
    """Staatscourant ministeriële regelingen XML as documents."""

    spec = PublicationSpec(
        source=SOURCE_STAATSCOURANT,
        raw_kind=RAW_KIND_STAATSCOURANT_REGELING,
        publication="Staatscourant",
        pattern=STCRT_ID_PATTERN,
        key_prefix="stcrt",
        label="Regeling",
        kind="Ministeriële regeling",
        own_props=_regulation,
    )
