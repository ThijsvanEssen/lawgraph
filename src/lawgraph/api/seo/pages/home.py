"""The start page (``/``): what Concordans is, a search form and the three ways in, each
with its example, as the start page of the app draws them (``Entrances.svelte``). Fixed
text, read of nothing: it is the first paint, without a script or a request.
"""

from __future__ import annotations

from html import escape
from typing import Any

from lawgraph.api.seo.pages.base import Page, bullets, link
from lawgraph.config import settings
from lawgraph.core.votes import REJECTED, VOTE_AGAINST, VOTE_FOR

HEADING = "Wetten, uitspraken en Kamerstukken in samenhang"
LEAD = (
    "Concordans is een onderzoeksinstrument dat parlementaire informatie verbindt met "
    "wetgeving, officiële publicaties en rechtspraak, om inzicht te geven in de samenhang "
    "rond een onderwerp. Het dient als eenvoudige wettenlezer, met de geldende en eerdere "
    "versies van elk artikel, en als werkplaats voor eigen onderzoek. Wat gevonden is, kan "
    "in een bundel worden bewaard en geordend."
)
PLACEHOLDER = "Zoek een artikel, uitspraak of motie"
PUBLISHER = {"@type": "Organization", "name": "TMvE", "email": "concordans@tmve.nl"}

# Art. 6:162 BW and the parts of its page (``?bronnen=``, the filter of Verbonden).
ARTICLE = "/wetten/BWBR0005289/artikel/6:162"
ARTICLE_PARTS = (
    ("Uitspraken die het aanhalen", "uitspraken"),
    ("Kamerstukken die het noemen", "toelichtingen,wetsvoorstellen,dossiers"),
    ("Artikelen die ernaar verwijzen", "artikelen"),
)
VOTE_TITLE = "Motie De Hoop en Grinwis over de WOZ-cap niet versoepelen"
VOTE = "/kamerstukken/27926/413"
VOTE_DATE = "16 juni 2026, Tweede Kamer"
VOTE_TALLY = "54 voor, 96 tegen"
VOTE_SIDES = (
    (VOTE_FOR, "PRO, PVV, ChristenUnie, DENK, PvdD, SP, 50PLUS, Volt"),
    (
        VOTE_AGAINST,
        "D66, VVD, CDA, JA21, FVD, Groep Markuszower, BBB, SGP, Lid Keijzer",
    ),
)
# The shared example bundel (``example-bundle.ts`` of the front end): its link, its lines
# (citation, place) and the note of its first.
BUNDLE_TITLE = "Aansprakelijkheid werkgever thuiswerk"
BUNDLE = (
    "/gemarkeerd#m=tZLRS8MwEMb_lSPPnW035jQvsomw4fBhogNFSroebdY0KWnaIWP_u1e66cZUfPElcPm-I78v"
    "d1umhSgYZ2Ohq9KKHJVc5xnKBDZo8xQbtOCyWlZtyTwmHRYV469bJhNqE9bJlcLKjzexDYJg2L8OosvhFTmF"
    "I13JpBdSkRvrOvsFjDgZgBQIYbIksTGqlntZEsGpo7Yp2pYKluhigy1Fag2W1HAuwqQ9Rp2nLu_xnWwbdPwI"
    "kERtnHQSSXsxNi2VXGXOA2PyLuwN23m_JgzDQ8LzcOEvscL_CfRJu66TtEDtKh9XSkZaRZmN-uSKRD0YhINz"
    "6ukCCEqbBouYZt16Pbi7nc_4w5xPF7y94OOnffOB85uuU8I_gJSiJfbpj7rN0_4Pz-7ejgf2bIVIOTRCOUDU"
    "sHic9XIlaIAQy_XXsoLRCaEdrdxkSXP9AA"
)
BUNDLE_LINES = (
    ("art. 7:658 lid 1 BW", "/wetten/BWBR0005290/artikel/7:658#lid-1"),
    ("art. 7:611 BW", "/wetten/BWBR0005290/artikel/7:611"),
    (
        "HR 11 november 2005, ECLI:NL:HR:2005:AU3313",
        "/uitspraken/ECLI:NL:HR:2005:AU3313",
    ),
)
BUNDLE_NOTE = "Zorgplicht, ook thuis?"


def _search() -> str:
    """A form that works without scripts: ``/?q=``, the SearchAction."""
    return (
        '<form action="/" method="get" role="search" class="search">'
        f'<input type="search" name="q" placeholder="{escape(PLACEHOLDER)}" '
        f'aria-label="{escape(PLACEHOLDER)}" />'
        "</form>"
    )


def _entrance(key: str, title: str, html: str) -> str:
    return (
        f'<section class="entrance" aria-labelledby="entrance-{key}">'
        f'<h2 id="entrance-{key}">{escape(title)}</h2>{html}</section>'
    )


def _title(path: str, label: str) -> str:
    return f'<a class="title" href="{escape(path)}">{escape(label)}</a>'


def _entrances() -> str:
    article = _title(ARTICLE, "Art. 6:162 BW, Onrechtmatige daad") + bullets(
        [link(f"{ARTICLE}?bronnen={part}", label) for label, part in ARTICLE_PARTS]
    )
    vote = (
        _title(VOTE, VOTE_TITLE)
        + f'<p class="meta">{escape(VOTE_DATE)}</p>'
        + f'<p class="outcome">{REJECTED.capitalize()}, {escape(VOTE_TALLY)}</p>'
        + '<dl class="sides">'
        + "".join(
            f"<dt>{escape(choice)}</dt><dd>{escape(parties)}</dd>"
            for choice, parties in VOTE_SIDES
        )
        + "</dl>"
    )
    bundle = _title(BUNDLE, BUNDLE_TITLE) + bullets(
        [link(path, label) for label, path in BUNDLE_LINES]
        + [f"Aantekening: <em>{escape(BUNDLE_NOTE)}</em>"]
    )
    return (
        '<div class="entrances">'
        + _entrance("article", "Artikel", article)
        + _entrance("vote", "Stemming", vote)
        + _entrance("bundle", "Bundel", bundle)
        + "</div>"
    )


def _website() -> dict[str, Any]:
    return {
        "@type": "WebSite",
        "name": "Concordans",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{settings.SITE_URL}/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
        "publisher": PUBLISHER,
    }


def home_page(title: str, description: str, index: bool) -> Page:
    """The start page with the title and description the app gives it."""
    body = (
        '<header class="blad__kop intro">'
        f'<h1 class="blad__titel">{escape(HEADING)}</h1>'
        f'<p class="lead">{escape(LEAD)}</p>'
        "</header>" + _search() + _entrances()
    )
    return Page(
        title=title,
        description=description,
        path="/",
        data=_website(),
        body=body,
        index=index,
        whole_title=True,
    )
