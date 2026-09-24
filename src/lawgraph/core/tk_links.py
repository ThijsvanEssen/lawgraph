"""Links to the pages of tweedekamer.nl, derived from a node's props when a response is built.

The site finds a document by its document number (``Document.DocumentNummer``,
``2026D44984``) and an activity by its number (``Activiteit.Nummer``, ``2026A02571``), never by
the GUID of the record. A link is not stored, so a wrong template is fixed by a release and
never frozen into the database.

Checked by hand on 24 September 2026, with a browser user agent: the document page answers 200
for every ``Document.Soort``; both activity pages answer 200 for every ``Activiteit.Soort``,
planned, held or cancelled, and 404 for a number that does not exist. The two differ only in
the part of the site they are shown in, so a plenary kind gets the plenary page.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lawgraph.core.models import NodeType

_SITE = "https://www.tweedekamer.nl"
DOCUMENT_PAGE = _SITE + "/kamerstukken/detail?id={number}&did={number}"
COMMITTEE_ACTIVITY_PAGE = (
    _SITE + "/debat_en_vergadering/commissievergaderingen/details?id={number}"
)
PLENARY_ACTIVITY_PAGE = (
    _SITE
    + "/debat_en_vergadering/plenaire_vergaderingen/details/activiteit?id={number}"
)

# Activiteit.Soort, lowercased, of what happens in the plenary hall: "Plenair debat
# (wetgeving)", "Plenair debat (tweeminutendebat)", ... and the sittings of the Kamer itself.
# Every activity has a Voortouwcommissie, also a plenary one, so the kind is what tells.
_PLENARY_KINDS = (
    "plenair debat",
    "stemmingen",
    "hamerstukken",
    "regeling van werkzaamheden",
    "vragenuur",
)


def document_page(document_number: str | None) -> str | None:
    """The page of a Tweede Kamer document, or None without a document number."""
    return DOCUMENT_PAGE.format(number=document_number) if document_number else None


def activity_page(number: str | None, kind: str | None) -> str | None:
    """The page of a Tweede Kamer activity, or None without an activity number."""
    if not number:
        return None
    plenary = (kind or "").strip().lower().startswith(_PLENARY_KINDS)
    template = PLENARY_ACTIVITY_PAGE if plenary else COMMITTEE_ACTIVITY_PAGE
    return template.format(number=number)


def tk_url(node_type: str | None, props: Mapping[str, Any]) -> str | None:
    """The page on tweedekamer.nl of a document or activity node, or None.

    A document of the Eerste Kamer has no document number and so no page here: its own page
    is its ``url``.
    """
    if node_type == NodeType.DOCUMENT.value:
        return document_page(props.get("document_number"))
    if node_type == NodeType.ACTIVITY.value:
        return activity_page(props.get("number"), props.get("kind"))
    return None
