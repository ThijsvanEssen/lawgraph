"""The start page (``/``): what Concordans is, a search form and the three ways in, each
with its example, as the start page of the app draws them (``Entrances.svelte``). Fixed
text, read of nothing: it is the first paint, without a script or a request. The text is
``start.json`` of the front end, the one source of both (beside its ``index.html``); the
text below stands in while that is not there or not whole.
"""

from __future__ import annotations

from html import escape
from typing import Any

from lawgraph.api.seo.pages.base import Page, bullets, link
from lawgraph.config import settings
from lawgraph.core.votes import REJECTED, VOTE_AGAINST, VOTE_FOR

PUBLISHER = {"@type": "Organization", "name": "TMvE", "email": "concordans@tmve.nl"}

# Art. 6:162 BW and the parts of its page (``?bronnen=``, the filter of Verbonden), a
# motion and its vote, and the shared example bundel (``example-bundle.ts``).
ARTICLE = "/wetten/BWBR0005289/artikel/6:162"
START: dict[str, Any] = {
    "heading": "Wetten, uitspraken en Kamerstukken in samenhang",
    "lead": (
        "Concordans is een onderzoeksinstrument dat parlementaire informatie verbindt "
        "met wetgeving, officiële publicaties en rechtspraak, om inzicht te geven in de "
        "samenhang rond een onderwerp. Het dient als eenvoudige wettenlezer, met de "
        "geldende en eerdere versies van elk artikel, en als werkplaats voor eigen "
        "onderzoek. Wat gevonden is, kan in een bundel worden bewaard en geordend."
    ),
    "placeholder": "Zoek een artikel, uitspraak of motie",
    "article": {
        "heading": "Artikel",
        "title": "Art. 6:162 BW, Onrechtmatige daad",
        "href": ARTICLE,
        "parts": [
            {"label": "Uitspraken die het aanhalen", "bronnen": "uitspraken"},
            {
                "label": "Kamerstukken die het noemen",
                "bronnen": "toelichtingen,wetsvoorstellen,dossiers",
            },
            {"label": "Artikelen die ernaar verwijzen", "bronnen": "artikelen"},
        ],
    },
    "vote": {
        "heading": "Stemming",
        "title": "Motie De Hoop en Grinwis over de WOZ-cap niet versoepelen",
        "href": "/kamerstukken/27926/413",
        "date": "16 juni 2026, Tweede Kamer",
        "outcome": REJECTED.capitalize(),
        "tally": "54 voor, 96 tegen",
        "sides": [
            {
                "choice": VOTE_FOR,
                "parties": "PRO, PVV, ChristenUnie, DENK, PvdD, SP, 50PLUS, Volt",
            },
            {
                "choice": VOTE_AGAINST,
                "parties": (
                    "D66, VVD, CDA, JA21, FVD, Groep Markuszower, BBB, SGP, Lid Keijzer"
                ),
            },
        ],
    },
    "bundle": {
        "heading": "Bundel",
        "title": "Aansprakelijkheid werkgever thuiswerk",
        "href": (
            "/gemarkeerd#m=tZLRS8MwEMb_lSPPnW035jQvsomw4fBhogNFSroebdY0KWnaIWP_u1e66cZUfPElc"
            "Pm-I78vd1umhSgYZ2Ohq9KKHJVc5xnKBDZo8xQbtOCyWlZtyTwmHRYV469bJhNqE9bJlcLKjzexDYJg"
            "2L8OosvhFTmFI13JpBdSkRvrOvsFjDgZgBQIYbIksTGqlntZEsGpo7Yp2pYKluhigy1Fag2W1HAuwqQ9"
            "Rp2nLu_xnWwbdPwIkERtnHQSSXsxNi2VXGXOA2PyLuwN23m_JgzDQ8LzcOEvscL_CfRJu66TtEDtKh9X"
            "SkZaRZmN-uSKRD0YhINz6ukCCEqbBouYZt16Pbi7nc_4w5xPF7y94OOnffOB85uuU8I_gJSiJfbpj7rN"
            "0_4Pz-7ejgf2bIVIOTRCOUDUsHic9XIlaIAQy_XXsoLRCaEdrdxkSXP9AA"
        ),
        "lines": [
            {
                "label": "art. 7:658 lid 1 BW",
                "href": "/wetten/BWBR0005290/artikel/7:658#lid-1",
            },
            {"label": "art. 7:611 BW", "href": "/wetten/BWBR0005290/artikel/7:611"},
            {
                "label": "HR 11 november 2005, ECLI:NL:HR:2005:AU3313",
                "href": "/uitspraken/ECLI:NL:HR:2005:AU3313",
            },
        ],
        "noteLabel": "Aantekening",
        "note": "Zorgplicht, ook thuis?",
    },
}


def _search(start: dict[str, Any]) -> str:
    """A form that works without scripts: ``/?q=``, the SearchAction."""
    placeholder = escape(start["placeholder"])
    return (
        '<form action="/" method="get" role="search" class="search">'
        f'<input type="search" name="q" placeholder="{placeholder}" '
        f'aria-label="{placeholder}" />'
        "</form>"
    )


def _entrance(key: str, part: dict[str, Any], html: str) -> str:
    title = (
        f'<a class="title" href="{escape(part["href"])}">{escape(part["title"])}</a>'
    )
    return (
        f'<section class="entrance" aria-labelledby="entrance-{key}">'
        f'<h2 id="entrance-{key}">{escape(part["heading"])}</h2>{title}{html}</section>'
    )


def _entrances(start: dict[str, Any]) -> str:
    article, vote, bundle = start["article"], start["vote"], start["bundle"]
    parts = bullets(
        [
            link(f"{article['href']}?bronnen={part['bronnen']}", part["label"])
            for part in article["parts"]
        ]
    )
    sides = "".join(
        f"<dt>{escape(side['choice'])}</dt><dd>{escape(side['parties'])}</dd>"
        for side in vote["sides"]
    )
    tally = (
        f'<p class="meta">{escape(vote["date"])}</p>'
        f'<p class="outcome"><span class="uitkomst">{escape(vote["outcome"])}</span> '
        f"<span>{escape(vote['tally'])}</span></p>"
        f'<dl class="sides">{sides}</dl>'
    )
    note = (
        f'<li class="note"><span class="note-label">{escape(bundle["noteLabel"])}</span> '
        f"{escape(bundle['note'])}</li>"
    )
    lines = (
        "<ul>"
        + "".join(
            f"<li>{link(line['href'], line['label'])}</li>" for line in bundle["lines"]
        )
        + note
        + "</ul>"
    )
    return (
        '<div class="entrances">'
        + _entrance("article", article, parts)
        + _entrance("vote", vote, tally)
        + _entrance("bundle", bundle, lines)
        + "</div>"
    )


def _body(start: dict[str, Any]) -> str:
    return (
        '<header class="blad__kop intro">'
        f'<h1 class="blad__titel">{escape(start["heading"])}</h1>'
        f'<p class="lead">{escape(start["lead"])}</p>'
        "</header>" + _search(start) + _entrances(start)
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


def home_page(
    title: str, description: str, index: bool, start: dict[str, Any] | None = None
) -> Page:
    """The start page with the title and description the app gives it, its text from
    *start* (``start.json``), or the text above where that is missing or not whole."""
    try:
        body = _body(start or START)
    except KeyError, TypeError, AttributeError:
        body = _body(START)
    return Page(
        title=title,
        description=description,
        path="/",
        data=_website(),
        body=body,
        index=index,
        whole_title=True,
    )
