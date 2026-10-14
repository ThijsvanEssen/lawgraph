"""The page of each kind of readable address (``core.readable_paths.Pad.soort``): what it
reads (``db/queries/seo.py``), the page it builds of that (``pages.py``) and its image when
it is shared. A kind without one, or whose read finds nothing, is the name of its node
(``api/routes/render.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lawgraph.api.seo import pages
from lawgraph.api.seo.pages import SITE_IMAGE, Page
from lawgraph.db import GraphStore
from lawgraph.db.queries import seo


@dataclass(frozen=True)
class SourcePage:
    """The read of a kind of page (store, node id → its row, or None), the page it builds
    of the row, and its ``og:image``."""

    read: Callable[[GraphStore, str], dict[str, Any] | None]
    build: Callable[[dict[str, Any]], Page]
    image: str = SITE_IMAGE


SOURCE_PAGES: dict[str, SourcePage] = {
    "wet": SourcePage(seo.law, pages.law_page, "/og/wet.png"),
    "artikel": SourcePage(seo.article, pages.article_page, "/og/artikel.png"),
    "uitspraak": SourcePage(seo.judgment, pages.judgment_page, "/og/uitspraak.png"),
    "kamerstuk": SourcePage(seo.paper, pages.paper_page, "/og/kamerstuk.png"),
    "dossier": SourcePage(seo.dossier, pages.dossier_page, "/og/dossier.png"),
    "lid": SourcePage(seo.member, pages.member_page),
    "fractie": SourcePage(seo.faction, pages.faction_page),
    "kabinet": SourcePage(seo.cabinet, pages.cabinet_page),
    "commissie": SourcePage(seo.committee, pages.committee_page),
    "publicatie": SourcePage(seo.publication, pages.publication_page),
    "toezegging": SourcePage(seo.commitment, pages.commitment_page),
    "stemming": SourcePage(seo.decision, pages.decision_page),
    "bijlage": SourcePage(seo.annex, pages.annex_page, "/og/wet.png"),
    "zaak": SourcePage(seo.case, pages.case_page, "/og/dossier.png"),
    "activiteit": SourcePage(seo.activity, pages.activity_page, "/og/dossier.png"),
}
