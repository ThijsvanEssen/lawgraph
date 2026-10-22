"""Normalize pipeline for Dutch Staatsblad AMvB publications: the nota van toelichting."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

from lawgraph.config.constants import RAW_KIND_STAATSBLAD_AMVB, SOURCE_STAATSBLAD
from lawgraph.core.identifiers import STB_ID_PATTERN
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.core.raw_records import payload_text
from lawgraph.core.xml import extract_section_text
from lawgraph.db.counting import Store
from lawgraph.db.queries import raw as raw_queries
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


def named_by_toestand(store: Store, claims: Mapping[str, str]) -> set[str]:
    """Of ``{identifier: bwb_id}``, the publications that the stored toestand of their
    regulation names (``staatsblad_ref_from_bwb_xml``), read again from its XML: the
    regulation retrieve kept with a publication may come from an older reading of it (the
    ``Trb. 2018, 100`` of a treaty read as ``Stb. 2018, 100``)."""
    named: dict[str, str | None] = {}
    toestanden = raw_queries.toestanden_of(store, sorted(set(claims.values())))
    for record in store.with_payloads(toestanden):
        xml = payload_text(record)
        try:
            ref = staatsblad_ref_from_bwb_xml(xml) if xml else None
        except ET.ParseError:
            ref = None
        named[record["external_id"]] = f"stb-{ref[0]}-{ref[1]}" if ref else None
    return {
        identifier
        for identifier, bwb_id in claims.items()
        if named.get(bwb_id) == identifier
    }


class StaatsbladNormalizePipeline(PublicationNormalizePipeline):
    """Staatsblad AMvB XML as documents. ``bwb_id`` is the regulation whose toestand named
    the publication, as retrieve found it (``--mode from-graph``) and its stored toestand
    still names it (``named_by_toestand``), else the first law its text cites."""

    spec = PublicationSpec(
        source=SOURCE_STAATSBLAD,
        raw_kind=RAW_KIND_STAATSBLAD_AMVB,
        publication="Staatsblad",
        pattern=STB_ID_PATTERN,
        key_prefix="stb",
        label="NvT",
        kind="Nota van toelichting",
        own_props=_note,
        confirmed=named_by_toestand,
    )
