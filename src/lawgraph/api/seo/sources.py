"""The page of each kind of readable address (``core.readable_paths.Pad.soort``): what it
reads (``db/queries/seo.py``), the page it builds of that (``pages/``) and its image when
it is shared. A kind without one, or whose read finds nothing, is the name of its node
(``api/routes/render.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lawgraph.api.seo.pages.base import SITE_IMAGE, Page
from lawgraph.api.seo.pages.government import (
    cabinet_page,
    commitment_page,
    ministry_page,
    publication_page,
)
from lawgraph.api.seo.pages.judgments import judgment_page
from lawgraph.api.seo.pages.laws import annex_page, article_page, law_page
from lawgraph.api.seo.pages.parliament import (
    activity_page,
    case_page,
    committee_page,
    decision_page,
    document_page,
    dossier_page,
    faction_page,
    member_image,
    member_page,
)
from lawgraph.api.seo.paint import (
    article_paint,
    document_paint,
    judgment_paint,
    law_paint,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import seo


@dataclass(frozen=True)
class SourcePage:
    """The read of a kind of page (store, node id → its row, or None), the page it builds
    of the row, its ``og:image`` (or a function of the row to it), and where the front
    end paints it first, what that paint reads (store, row → ``Page.first_paint``;
    ``api/seo/paint``)."""

    read: Callable[[GraphStore, str], dict[str, Any] | None]
    build: Callable[[dict[str, Any]], Page]
    image: str | Callable[[dict[str, Any]], str] = SITE_IMAGE
    paint: Callable[[GraphStore, dict[str, Any]], dict[str, Any] | None] | None = None


SOURCE_PAGES: dict[str, SourcePage] = {
    "wet": SourcePage(seo.law, law_page, "/og/wet.png", paint=law_paint),
    "artikel": SourcePage(
        seo.article, article_page, "/og/artikel.png", paint=article_paint
    ),
    "uitspraak": SourcePage(
        seo.judgment, judgment_page, "/og/uitspraak.png", paint=judgment_paint
    ),
    "kamerstuk": SourcePage(
        seo.paper, document_page, "/og/kamerstuk.png", paint=document_paint
    ),
    "dossier": SourcePage(seo.dossier, dossier_page, "/og/dossier.png"),
    "lid": SourcePage(seo.member, member_page, member_image),
    "fractie": SourcePage(seo.faction, faction_page, "/og/fractie.png"),
    "kabinet": SourcePage(seo.cabinet, cabinet_page, "/og/kabinet.png"),
    "ministerie": SourcePage(seo.ministry, ministry_page, "/og/ministerie.png"),
    "commissie": SourcePage(seo.committee, committee_page, "/og/commissie.png"),
    "publicatie": SourcePage(seo.publication, publication_page, "/og/publicatie.png"),
    "toezegging": SourcePage(seo.commitment, commitment_page, "/og/toezegging.png"),
    "stemming": SourcePage(seo.decision, decision_page, "/og/stemming.png"),
    "bijlage": SourcePage(seo.annex, annex_page, "/og/wet.png"),
    "zaak": SourcePage(seo.case, case_page, "/og/dossier.png"),
    "activiteit": SourcePage(seo.activity, activity_page, "/og/dossier.png"),
}
