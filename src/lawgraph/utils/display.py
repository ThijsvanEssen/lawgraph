"""Deterministic node display name helpers."""

from __future__ import annotations

from typing import Any

from lawgraph.models import NodeType

# Known abbreviations for Dutch national legislation (uppercase BWB ID → shorthand).
BWB_SHORTHANDS: dict[str, str] = {
    "BWBR0001854": "Sr.",
    "BWBR0001903": "Sv.",
    "BWBR0005289": "BW",
    "BWBR0003045": "Sr BES",
    "BWBR0006622": "WVW",
    "BWBR0008804": "WWM",
    "BWBR0001941": "OW",
    "BWBR0020438": "Pbw",
    "BWBR0011756": "Sv BES",
}


def make_display_name(node_type: NodeType, props: dict[str, Any]) -> str:
    """Return a human-friendly display_name for the given node type."""
    if node_type == NodeType.INSTRUMENT:
        return _instrument_display_name(props)
    if node_type == NodeType.ARTICLE:
        return _article_display_name(props)
    if node_type == NodeType.JUDGMENT:
        return _judgment_display_name(props)
    if node_type == NodeType.PUBLICATION:
        return _publication_display_name(props)
    if node_type == NodeType.PROCEDURE:
        return _procedure_display_name(props)
    if node_type == NodeType.TOPIC:
        return _topic_display_name(props)
    return _generic_display_name(node_type, props)


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text:
        return text
    return None


def _first_prop(props: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = props.get(key)
        text = _coerce_str(candidate)
        if text:
            return text
    return None


def _instrument_display_name(props: dict[str, Any]) -> str:
    title = _first_prop(props, "title", "official_title")
    bwb_id = _first_prop(props, "bwb_id")
    celex = _first_prop(props, "celex")

    if title:
        return title
    if bwb_id:
        return f"BWB {bwb_id}"
    if celex:
        return f"EU {celex}"
    return "Instrument"


# Known shorthands for EU/CoE instruments (uppercase CELEX → shorthand).
CELEX_SHORTHANDS: dict[str, str] = {
    "21970A0718(02)": "EVRM",
    "32010L0064": "Richtlijn 2010/64/EU",
    "32012L0013": "Richtlijn 2012/13/EU",
    "32013L0048": "Richtlijn 2013/48/EU",
    "32002F0584": "Kaderbesluit 2002/584/JBZ",
    "32016L0343": "Richtlijn 2016/343/EU",
    "32016L0800": "Richtlijn 2016/800/EU",
    "32016L1919": "Richtlijn 2016/1919/EU",
    "32017L0541": "Richtlijn 2017/541/EU",
    "32011L0093": "Richtlijn 2011/93/EU",
}


def _article_display_name(props: dict[str, Any]) -> str:
    """Return a display name for an article node.

    Priority for the law suffix:
    1. Hardcoded shorthand (BWB_SHORTHANDS / CELEX_SHORTHANDS) — e.g. "Sr.", "EVRM"
    2. instrument_citation_title stored on the article — e.g. "Awb"
    3. No suffix — bare "Artikel {number}"
    """
    article_number = _first_prop(props, "article_number")
    if not article_number:
        return "Artikel"

    bwb_id = (_first_prop(props, "bwb_id") or "").upper()
    law = BWB_SHORTHANDS.get(bwb_id)
    if law:
        return f"Artikel {article_number} {law}"

    celex = (_first_prop(props, "celex") or "").upper()
    eu_law = CELEX_SHORTHANDS.get(celex)
    if eu_law:
        return f"Artikel {article_number} {eu_law}"

    # Fall back to the citation title stored on the article itself (populated by
    # the normalization pipelines so every article carries its parent law's name).
    ct = _first_prop(props, "instrument_citation_title")
    if ct:
        return f"Artikel {article_number} {ct}"

    return f"Artikel {article_number}"


def _judgment_display_name(props: dict[str, Any]) -> str:
    ecli = _first_prop(props, "ecli")
    title = _first_prop(props, "title", "case_title", "zaaknaam")
    case_number = _first_prop(props, "zaaknummer", "case_number")

    if ecli and title:
        return f"{title} ({ecli})"
    if ecli:
        return ecli
    if case_number:
        return f"Uitspraak {case_number}"
    return "Uitspraak"


def _publication_display_name(props: dict[str, Any]) -> str:
    title = _first_prop(props, "title")
    identifier = _first_prop(props, "kamerstuknummer", "document_number")

    if title and identifier:
        return f"{title} ({identifier})"
    if title:
        return title
    return "Publicatie"


def _procedure_display_name(props: dict[str, Any]) -> str:
    title = _first_prop(props, "title")
    identifier = _first_prop(props, "procedure_id", "external_id")

    if title:
        return title
    if identifier:
        return f"Procedure {identifier}"
    return "Procedure"


def _topic_display_name(props: dict[str, Any]) -> str:
    label = _first_prop(props, "label", "name")
    slug = _first_prop(props, "slug")
    code = _first_prop(props, "code")
    if label:
        return label
    if slug:
        return slug
    if code:
        return code
    return "Topic"


def _generic_display_name(node_type: NodeType, props: dict[str, Any]) -> str:
    name = _first_prop(props, "name", "label", "title")
    if name:
        return name
    return node_type.value.capitalize()
