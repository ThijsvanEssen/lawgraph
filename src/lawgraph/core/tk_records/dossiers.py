"""Kamerstukdossier: the dossier a document is numbered in."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import SOURCE_TK
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.dossier_stages import select_title
from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records._payload import (
    Payload,
    id_of,
)


def dossier_label(number: Any, suffix: Any) -> str:
    """``37020-XV`` for Nummer 37020 with Toevoeging XV, ``37020`` without one.

    ``make_node_key`` of the label is the key of the dossier node.
    """
    number_str = str(number or "")
    return f"{number_str}-{suffix}" if number_str and suffix else number_str


def dossier_display_name(number: str, suffix: str | None, title: str) -> str:
    """``Kamerstukdossier 36554-I: <title>``."""
    suffix = f"-{suffix}" if suffix else ""
    return f"Kamerstukdossier {number}{suffix}: {title}"


def title_from_papers(
    props: dict[str, Any], docs: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The title of a dossier without a real one of its own, from its papers
    (``select_title``): ``title``, ``title_source`` and ``display_name``; None when its own
    stands or no paper has one."""
    title, source = select_title(props, docs)
    if source != "document":
        return None
    return {
        "title": title,
        "title_source": source,
        "display_name": dossier_display_name(
            props.get("number") or "", props.get("suffix"), title or ""
        ),
    }


def dossier(payload: Payload) -> tuple[str, str, dict[str, Any]] | None:
    """``(node key, dossier number label, props)`` for a Kamerstukdossier; ``None``
    without an id or a number."""
    external_id = id_of(payload)
    number = payload.get("Nummer")
    if not external_id or number is None:
        return None

    number_str = str(number)
    suffix = payload.get("Toevoeging") or ""
    label = dossier_label(number_str, suffix)
    # A dossier with neither Titel nor Citeertitel keeps title None, so the
    # backfill can take one from a voorstel-van-wet document instead of
    # storing a title that only looks valid.
    title = payload.get("Titel") or payload.get("Citeertitel") or None

    # The record says nothing about how far the dossier got: ``Afgesloten`` is false on
    # every dossier, also on those whose law was published years ago. When it was opened
    # and whether and how it ended are derived from the graph (the stage backfill and
    # ``semantic tk-dossier-outcomes``), so they are not written here, where a run would
    # blank them.
    props: dict[str, Any] = {
        "external_id": external_id,
        "number": number_str,
        "suffix": suffix,
        "label": label,
        "order": dossier_order(number_str, suffix),
        "title": title,
        "title_source": "dossier" if title else None,
        "display_name": dossier_display_name(number_str, suffix, title or ""),
        # the Tweede Kamer's: takes over a dossier written from the documents of the Eerste
        # Kamer before the Kamer delivered it (``normalize eerstekamer``)
        "source": SOURCE_TK,
    }

    return make_node_key(label), label, props
