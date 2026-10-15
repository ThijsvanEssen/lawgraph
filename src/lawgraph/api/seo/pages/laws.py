"""The pages of a law (of the BWB, or an EU act), an article and an annex."""

from __future__ import annotations

from html import escape
from typing import Any

from lawgraph.api.seo.pages.base import (
    DESCRIPTION_MAX,
    Page,
    bullets,
    cut,
    link,
    present,
    section,
    source_links,
    trail,
)
from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.models import node_id
from lawgraph.core.names import (
    annex_title,
    article_name,
    article_title,
    joined,
    judgment_title,
    law_name,
    law_short,
    text_of,
)
from lawgraph.core.official_urls import instrument_url
from lawgraph.core.readable_paths import path_of


def _law_id(props: dict[str, Any]) -> tuple[str, str]:
    """The id a law is known by and its jurisdiction: its BWB id (NL), else the CELEX
    number of an EU act (EU)."""
    bwb = text_of(props.get("bwb_id"))
    return (bwb, "NL") if bwb else (text_of(props.get("celex")), "EU")


def _part_of(name: str, identifier: str) -> dict[str, Any]:
    """The law an article or an annex is part of, when it has a name."""
    return present(
        isPartOf={
            "@type": "Legislation",
            "name": name,
            "legislationIdentifier": identifier,
        }
        if name
        else None
    )


def law_page(row: dict[str, Any]) -> Page:
    """A law of the BWB or an EU act: its articles; an EU act also its whole title and its
    text on EUR-Lex. An EU act whose text was not read (no articles) is not indexed: its
    title is all there is."""
    props = row["props"] or {}
    law_id, jurisdiction = _law_id(props)
    law_id = law_id or row["key"].upper()
    eu = jurisdiction == "EU"
    name = law_name(props) or text_of(props.get("display_name")) or law_id
    path = path_of(row["id"], props) or f"/wetten/{law_id}"
    since = long_date(props.get("date_in_force"))
    count = len(row["articles"])
    # an EU act by its whole title: what it is about ("NIS 2-richtlijn") is in it alone
    full = text_of(props.get("title")) if eu else ""
    description = joined(
        ", ",
        full or text_of(props.get("citation_title")) or name,
        f"geldend sinds {since}" if since else "",
        f"{count} artikelen" if count else "",
    )
    short = law_short(props)
    article_law = {"celex" if eu else "bwb_id": law_id}
    toc = bullets(
        [
            link(
                path_of(
                    node_id(COLLECTION_ARTICLES, a["key"]),
                    {**article_law, "article_number": a["article_number"]},
                ),
                article_name(law_id, a["article_number"], short),
            )
            for a in row["articles"]
        ]
    )
    eur_lex = instrument_url(props) if eu else None
    body = (
        f"<h1>{escape(name)}</h1>"
        + (f"<p>{escape(full)}</p>" if full else "")
        + (f"<p>Geldend sinds {escape(since)}.</p>" if since else "")
        + (
            f'<p><a href="{escape(eur_lex)}">De tekst op EUR-Lex</a></p>'
            if eur_lex
            else ""
        )
        + section("Inhoud", toc)
    )
    return Page(
        title=name,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=[(name, path)],
        data={
            "@type": "Legislation",
            "name": name,
            "legislationIdentifier": law_id,
            "legislationJurisdiction": jurisdiction,
            **present(legislationDate=props.get("date_in_force")),
        },
        body=body,
        index=not props.get("stub") and (not eu or count > 0),
    )


def article_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    law = row.get("law") or {}
    title = article_title(props, law)
    path = path_of(row["id"], props) or ""
    text = text_of(props.get("text"))
    # its text alone: the same whether the judgments citing it are kept yet or not
    description = text or title
    law_id, jurisdiction = _law_id(law or props)
    law_path = (
        path_of(node_id(COLLECTION_INSTRUMENTS, law_id.lower()), law) if law else None
    )
    law_label = law_name(law) if law else ""
    judgments = bullets(
        [
            link(
                path_of(j["id"], j.get("light") or {}),
                judgment_title(j.get("light") or {}, j["id"]),
            )
            for j in row.get("judgments") or []
        ]
    )
    paragraphs = "".join(
        f"<p>{escape(p.strip())}</p>" for p in text.split("\n") if p.strip()
    )
    short = law_short(law or props)

    def beside(rows: list[dict[str, Any]]) -> str:
        return bullets(
            [
                link(
                    path_of(a["id"], a),
                    article_name(law_id, text_of(a.get("article_number")), short),
                )
                for a in rows
            ]
        )

    links = row.get("links") or {}
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{link(law_path, law_label)}</p>" if law_label else "")
        + paragraphs
        + section("Verwijst naar", source_links(links.get("refers_to") or []))
        + section(
            "Artikelen die hiernaar verwijzen",
            source_links(links.get("referred_by") or []),
        )
        + section("Toelichting", source_links(links.get("explained_by") or []))
        + section("Uitspraken die dit artikel aanhalen", judgments)
        + section("Vorige artikelen", beside(row.get("before") or []))
        + section("Volgende artikelen", beside(row.get("after") or []))
    )
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=trail(law_label, law_path, title, path),
        data={
            "@type": "Legislation",
            "name": title,
            "legislationIdentifier": f"{law_id} artikel "
            f"{text_of(props.get('article_number'))}",
            "legislationJurisdiction": jurisdiction,
            **_part_of(law_label, law_id),
        },
        body=body,
        index=bool(text) and not props.get("stub"),
    )


def _entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    name, description = text_of(entry.get("name")), text_of(entry.get("description"))
    if name and description:
        return f"<strong>{escape(name)}</strong>: {escape(description)}"
    return escape(name or description)


def annex_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    law = row.get("law") or {}
    title = annex_title(props, law)
    path = path_of(row["id"], props) or ""
    bwb = text_of(props.get("bwb_id")) or text_of(law.get("bwb_id"))
    law_path = path_of(node_id(COLLECTION_INSTRUMENTS, bwb.lower())) if bwb else None
    law_label = law_name(law) if law else ""
    description = text_of(props.get("description"))
    entries = [e for e in (_entry(x) for x in props.get("entries") or []) if e]
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{link(law_path, law_label)}</p>" if law_label else "")
        + (f"<p>{escape(description)}</p>" if description else "")
        + bullets(entries)
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=trail(law_label, law_path, title, path),
        data={
            "@type": "Legislation",
            "name": title,
            "legislationIdentifier": f"{bwb} bijlage {text_of(props.get('label'))}",
            "legislationJurisdiction": "NL",
            **_part_of(law_label, bwb),
        },
        body=body,
        index=bool(description or entries) and not props.get("stub"),
    )
