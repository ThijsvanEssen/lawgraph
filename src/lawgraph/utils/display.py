"""Deterministic node display name helpers."""

from __future__ import annotations

from typing import Any

from lawgraph.models import NodeType


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
        suffix = bwb_id or celex
        if suffix:
            return f"{title} ({suffix})"
        return title
    if bwb_id:
        return f"BWB {bwb_id}"
    if celex:
        return f"EU {celex}"
    return "Instrument"


def _article_display_name(props: dict[str, Any]) -> str:
    article_number = _first_prop(props, "article_number")
    if article_number:
        return f"Art. {article_number}"
    return "Artikel"


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
