"""Normalize pipeline for Dutch Staatsblad AMvB publications: the nota van toelichting."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import RAW_KIND_STB_AMVB, SOURCE_STAATSBLAD
from lawgraph.core.identifiers import STB_ID_PATTERN
from lawgraph.core.xml import extract_section_text
from lawgraph.pipelines.normalize._publication import (
    Parsed,
    PublicationNormalizePipeline,
    PublicationSpec,
)


def _note(root: ET.Element, parsed: Parsed) -> dict[str, Any]:
    # ``nota-toelichting`` in the XML of the repository (an AMvB of 2025: stb-2025-263),
    # the other names in older formats
    text = extract_section_text(
        root, "nota-toelichting", "nota-van-toelichting", "nota_van_toelichting"
    ) or extract_section_text(root, "toelichting")
    return {
        "text": text or "",
        "display_name": f"Nota van toelichting {parsed.identifier}",
    }


class StaatsbladNormalizePipeline(PublicationNormalizePipeline):
    """Staatsblad AMvB XML as documents. ``bwb_id`` is the regulation whose toestand named
    the publication, as retrieve found it (``--mode from-graph``), not the first law its
    text cites."""

    spec = PublicationSpec(
        source=SOURCE_STAATSBLAD,
        raw_kind=RAW_KIND_STB_AMVB,
        publication="Staatsblad",
        pattern=STB_ID_PATTERN,
        key_prefix="stb",
        label="NvT",
        kind="Nota van toelichting",
        own_props=_note,
    )
