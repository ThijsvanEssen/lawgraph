"""The page of a judgment: its summary, its whole text with its headings and the numbers of
its considerations, and the sources it cites, that cite it and of its case."""

from __future__ import annotations

from collections.abc import Iterator
from html import escape
from typing import Any

from lawgraph.api.seo.pages.base import (
    DESCRIPTION_MAX,
    Page,
    bullets,
    capped,
    cut,
    lines,
    link,
    present,
    section,
    source_links,
)
from lawgraph.config.constants import SOURCE_ECHR
from lawgraph.core.names import (
    article_name,
    judgment_title,
    text_of,
)
from lawgraph.core.official_urls import judgment_url
from lawgraph.core.readable_paths import path_of


def _blocks(paragraphs: Any) -> Iterator[tuple[str, str]]:
    """The paragraphs of a judgment (``docs/data-model.md#judgment``) as HTML: a heading as a
    heading, the kop (the first, a subheading) and every other paragraph as a paragraph, a
    consideration with its number and its id (``rov-5.3``); not a table of contents."""
    for n, paragraph in enumerate(paragraphs if isinstance(paragraphs, list) else []):
        if not isinstance(paragraph, dict) or paragraph.get("kind") == "toc":
            continue
        text = text_of(paragraph.get("text"))
        if not text:
            continue
        kind = paragraph.get("kind")
        number = text_of(paragraph.get("number"))
        numbered = f"{number} {text}" if number else text
        if kind == "heading" or (kind == "subheading" and n > 0):
            tag = "h3" if kind == "heading" else "h4"
            yield f"<{tag}>{escape(numbered)}</{tag}>", numbered
            continue
        anchor = text_of(paragraph.get("id"))
        at = f' id="{escape(anchor)}"' if anchor and number else ""
        yield f"<p{at}>{lines(numbered)}</p>", numbered


def _judgment_links(rows: list[dict[str, Any]]) -> str:
    return bullets(
        [
            link(
                path_of(j["id"], j.get("light") or {}),
                judgment_title(j.get("light") or {}, j["id"]),
            )
            for j in rows
            if not (j.get("light") or {}).get("stub")
        ]
    )


def judgment_page(row: dict[str, Any]) -> Page:
    light = row.get("light") or {}
    title = judgment_title(light, row["id"])
    path = path_of(row["id"], light) or ""
    summary = text_of(row.get("summary")) or text_of(light.get("summary"))
    articles = bullets(
        [
            link(
                path_of(a["id"], a),
                article_name(
                    a.get("bwb_id"),
                    text_of(a.get("article_number")),
                    text_of(a.get("law")),
                ),
            )
            for a in row.get("articles") or []
            if text_of(a.get("article_number"))
        ]
    )
    echr = light.get("source") == SOURCE_ECHR
    official = judgment_url({**light, "external_id": row.get("external_id")})
    source = (
        f'<a href="{escape(official)}">De uitspraak op '
        f"{'HUDOC' if echr else 'rechtspraak.nl'}</a>"
        if official
        else ""
    )
    text = capped(
        _blocks(row.get("paragraphs")),
        f"<p>De tekst gaat verder: {source}</p>" if source else "",
    )
    links = row.get("links") or {}
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(summary)}</p>" if summary else "")
        + (f"<p>{source}</p>" if source else "")
        + section("Tekst", text)
        + section("Aangehaalde artikelen", articles)
        + section("Aangehaalde uitspraken", _judgment_links(row.get("judgments") or []))
        + section("Aangehaald in", _judgment_links(row.get("cited_by") or []))
        + section("Verbonden uitspraken", source_links(links.get("case") or []))
    )
    court = text_of(light.get("court"))
    return Page(
        title=title,
        description=cut(summary or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "CreativeWork",
            "name": title,
            "identifier": text_of(light.get("ecli")),
            **present(
                datePublished=light.get("date"),
                author={"@type": "Organization", "name": court} if court else None,
                abstract=cut(summary, 500) if summary else None,
            ),
        },
        body=body,
        index=not light.get("stub"),
        lang="en" if echr else "nl",
    )
