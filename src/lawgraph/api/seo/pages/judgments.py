"""The page of a judgment."""

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
)
from lawgraph.api.seo.pages.parliament import document_links
from lawgraph.config.constants import SOURCE_ECHR
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.models import judgment_id
from lawgraph.core.names import (
    article_name,
    judgment_title,
    text_of,
)
from lawgraph.core.official_urls import judgment_url
from lawgraph.core.readable_paths import path_of


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
    judgments = bullets(
        [
            link(
                path_of(j["id"], j.get("light") or {}),
                judgment_title(j.get("light") or {}, j["id"]),
            )
            for j in row.get("judgments") or []
        ]
    )
    echr = light.get("source") == SOURCE_ECHR
    official = judgment_url({**light, "external_id": row.get("external_id")})
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(summary)}</p>" if summary else "")
        + (
            f'<p><a href="{escape(official)}">De uitspraak op '
            f"{'HUDOC' if echr else 'rechtspraak.nl'}</a></p>"
            if official
            else ""
        )
        + section("Aangehaalde artikelen", articles)
        + section("Aangehaalde uitspraken", judgments)
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


def withdrawn_page(row: dict[str, Any]) -> Page:
    """The page of a judgment the Rechtspraak withdrew (``seo.withdrawn_judgment``): its
    court and date, that it was withdrawn and when, the ECLI the source names instead (of
    an ECLI given in error, when it names one), and what refers to it. Not indexed."""
    light = row.get("light") or {}
    props = row.get("props") or {}
    title = judgment_title({**props, **light}, row["id"])
    path = path_of(row["id"], props) or ""
    when = long_date(props.get("withdrawn_on"))
    on = f" op {when}" if when else ""
    if props.get("withdrawn") == "ecli":
        status = f"ECLI vervallen{on}."
        new = text_of(props.get("replaced_by"))
        if new:
            new_id = judgment_id(new)
            status += f" Vervangen door {link(path_of(new_id, {'ecli': new}), new)}."
        else:
            status = escape(status)
    else:
        status = escape(f"Ingetrokken door de bron{on}.")
    facts = ", ".join(
        escape(part)
        for part in (
            text_of(props.get("court")),
            long_date(props.get("date_eff")),
            text_of(props.get("case_number")),
        )
        if part
    )
    citing = bullets(
        [
            link(
                path_of(j["id"], j.get("light") or {}),
                judgment_title(j.get("light") or {}, j["id"]),
            )
            for j in row.get("judgments") or []
        ]
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{facts}</p>" if facts else "")
        + f"<p>{status}</p>"
        + section("Verwijzingen", citing)
        + section(
            "Kamerstukken die ernaar verwijzen",
            document_links(row.get("documents") or []),
        )
    )
    return Page(
        title=title,
        description=cut(f"{title}. Ingetrokken door de bron{on}.", DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        body=body,
        index=False,
        focus=row["id"],
    )
