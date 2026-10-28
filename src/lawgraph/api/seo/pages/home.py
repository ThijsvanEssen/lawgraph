"""The start page (``/``): what Concordans promises, a search form, three steps and
three questions it answers, as the start page of the app draws them (``home/`` of the
front end). Fixed text, read of nothing: it is the first paint, without a script or a
request. The text is ``start.json`` of the front end, the one source of both (beside its
``index.html``); the text below stands in while that is not there or not whole.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from lawgraph.api.seo.pages.base import Page, link
from lawgraph.config import settings

PUBLISHER = {
    "@type": "Organization",
    "name": "Concordans",
    "email": "concordans@tmve.nl",
}

START: dict[str, Any] = {
    "heading": "Zie hoe wetten, rechtspraak en parlement samenhangen.",
    "lede": (
        "Zoek een wet, uitspraak, Kamerstuk of dossier en lees de officiële tekst. "
        "Zie wie een artikel aanhaalt, hoe de Kamer stemde en wat er in een dossier "
        "gebeurde. Volg de verbindingen in het netwerk en bewaar wat je vindt in een "
        "bundel."
    ),
    "placeholder": "Wet, uitspraak, Kamerstuk, dossier of motie",
    "hint": {
        "intro": "Probeer",
        "examples": [
            "art. 6:162 BW",
            "ECLI:NL:HR:2019:1278",
            "Awb",
        ],
        "outro": "Enter opent de bron direct.",
    },
    "steps": [
        {
            "title": "Zoek",
            "text": "Op nummer, citaat of naam. Je komt in de tekst.",
        },
        {
            "title": "Lees",
            "text": "Rechts staat Verbonden: wie het artikel aanhaalt, met de passage.",
        },
        {
            "title": "Volg",
            "text": "Open het netwerk en ga van artikel naar uitspraak naar Kamerstuk.",
        },
    ],
    "questions": {
        "heading": "Wat kun je ermee?",
        "items": [
            {
                "title": "Wie haalt dit artikel aan?",
                "text": (
                    "Uitspraken, Kamerstukken en andere wetten die naar een artikel "
                    "verwijzen, met de passage."
                ),
                "linkLabel": "Bekijk een artikel, bijvoorbeeld art. 6:162 BW",
                "href": "/wetten/BWBR0005289/artikel/6:162",
            },
            {
                "title": "Hoe stemde de Kamer?",
                "text": (
                    "Per motie en wetsvoorstel: de uitslag, het aantal stemmen en "
                    "welke fracties voor of tegen waren."
                ),
                "linkLabel": "Bekijk de laatste stemmingen",
                "href": "/stemmingen",
            },
            {
                "title": "Wat onderzoek ik?",
                "text": (
                    "Bewaar artikelen, uitspraken en stukken met aantekeningen in een "
                    "bundel en deel de link."
                ),
                "linkLabel": "Begin een bundel",
                "href": "/bundels",
            },
        ],
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


def _hint(hint: dict[str, Any]) -> str:
    tries = ", ".join(
        link(f"/?q={quote(example)}", example) for example in hint["examples"]
    )
    return (
        f'<p class="hint">{escape(hint["intro"])} {tries}. {escape(hint["outro"])}</p>'
    )


def _steps(steps: list[dict[str, Any]]) -> str:
    items = "".join(
        f"<li><b>{escape(step['title'])}</b> {escape(step['text'])}</li>"
        for step in steps
    )
    return f'<ol class="stappen">{items}</ol>'


def _questions(questions: dict[str, Any]) -> str:
    items = "".join(
        '<section class="vraag">'
        f"<h3>{escape(item['title'])}</h3><p>{escape(item['text'])}</p>"
        f"<p>{link(item['href'], item['linkLabel'])}</p></section>"
        for item in questions["items"]
    )
    return (
        '<section class="vragen" aria-labelledby="vragen-kop">'
        f'<h2 id="vragen-kop">{escape(questions["heading"])}</h2>'
        f'<div class="vragen__lijst">{items}</div></section>'
    )


def _body(start: dict[str, Any]) -> str:
    return (
        '<header class="blad__kop intro">'
        f'<h1 class="blad__titel">{escape(start["heading"])}</h1>'
        "</header>"
        f'<p class="lede">{escape(start["lede"])}</p>'
        + _search(start)
        + _hint(start["hint"])
        + _steps(start["steps"])
        + _questions(start["questions"])
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
