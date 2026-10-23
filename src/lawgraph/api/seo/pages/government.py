"""The pages of the government: a cabinet, a commitment of a minister and a publication in
the Staatsblad or the Tractatenblad."""

from __future__ import annotations

from html import escape
from typing import Any

from lawgraph.api.seo.pages.base import (
    DESCRIPTION_MAX,
    Page,
    bullets,
    cut,
    link,
    member_link,
    period,
    present,
    section,
)
from lawgraph.api.seo.pages.parliament import document_links
from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MINISTRIES,
)
from lawgraph.core.dossier_numbers import official_number
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.models import key_of, node_id
from lawgraph.core.names import (
    RELATION_VERBS,
    cabinet_name,
    cabinet_title,
    commitment_title,
    joined,
    ministry_title,
    publication_title,
    text_of,
)
from lawgraph.core.official_urls import instrument_url, publication_url
from lawgraph.core.provenance import BASIS_AGENDA
from lawgraph.core.publications import instrument_key, publication_indexed
from lawgraph.core.readable_paths import path_of
from lawgraph.core.tk_records.commitments import due_date


def _functions(member: dict[str, Any]) -> str:
    """``: Minister-president; Minister van Algemene Zaken``: the posts a member held in a
    cabinet."""
    posts = member.get("posts")
    if not isinstance(posts, list) or not posts:
        return ""
    functions = dict.fromkeys(
        text_of(p.get("function"))
        for p in posts
        if isinstance(p, dict) and text_of(p.get("function"))
    )
    return ": " + escape("; ".join(functions))


def cabinet_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    name = cabinet_name(props, key)
    title = cabinet_title(props, key)
    path = path_of(row["id"], props) or ""
    span = period(props.get("from_date"), props.get("to_date"))
    factions = row.get("factions") or []
    parties = [
        text_of(p.get("short"))
        for p in props.get("parties") or []
        if isinstance(p, dict)
    ]
    parties = [p for p in parties if p] or [n for _, n in factions]
    pm = row.get("prime_minister") or {}
    description = joined(
        ", ",
        name,
        span,
        ", ".join(parties),
        f"minister-president {text_of(pm.get('name'))}" if pm.get("name") else "",
    )
    phases = bullets(
        [
            escape(
                joined(
                    ", ",
                    text_of(ph.get("label")) or text_of(ph.get("kind")),
                    period(ph.get("from_date"), ph.get("to_date")),
                )
            )
            for ph in props.get("phases") or []
            if isinstance(ph, dict)
        ]
    )
    served = bullets(
        [
            member_link(m) + _functions(m)
            for m in row.get("served") or []
            if text_of(m.get("name"))
        ]
    )
    previous = row.get("previous")
    before = (
        link(
            path_of(node_id(COLLECTION_CABINETS, previous[0])),
            cabinet_name({"name": previous[1]}, previous[0]),
        )
        if previous
        else ""
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(span[:1].upper() + span[1:])}</p>" if span else "")
        + (f"<p>Minister-president: {member_link(pm)}</p>" if pm.get("name") else "")
        + (f"<p>Vorig kabinet: {before}</p>" if before else "")
        + section(
            "Partijen",
            bullets(
                [link(path_of(node_id(COLLECTION_FACTIONS, k)), n) for k, n in factions]
            ),
        )
        + section("Fasen", phases)
        + section("Bewindspersonen", served)
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "GovernmentOrganization",
            "name": name,
            **present(
                foundingDate=props.get("from_date"),
                dissolutionDate=props.get("to_date"),
            ),
        },
        body=body,
    )


def ministry_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    name = text_of(props.get("name")) or key
    title = ministry_title(props, key)
    path = path_of(row["id"], props) or ""
    periods = [
        period(p.get("from_date"), p.get("to_date"))
        for p in props.get("periods") or []
        if isinstance(p, dict)
    ]
    spans = [p for p in periods if p]

    def names(pairs: list[tuple[str, str | None]]) -> str:
        return ", ".join(
            link(path_of(node_id(COLLECTION_MINISTRIES, k)), n or k) for k, n in pairs
        )

    before, after = names(row.get("before") or []), names(row.get("after") or [])
    served = bullets(
        [
            member_link(m) + _functions(m)
            for m in row.get("served") or []
            if text_of(m.get("name"))
        ]
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + bullets([escape(s[:1].upper() + s[1:]) for s in spans])
        + (f"<p>Voortgezet als: {after}</p>" if after else "")
        + (f"<p>Voortzetting van: {before}</p>" if before else "")
        + section("Bewindspersonen", served)
    )
    return Page(
        title=title,
        description=cut(joined(", ", title, *spans), DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "GovernmentOrganization",
            "name": f"Ministerie van {name}",
            **present(alternateName=text_of(props.get("abbreviation"))),
        },
        body=body,
    )


def commitment_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    number = text_of(props.get("number")) or row["key"]
    title = commitment_title(props, row["key"])
    path = path_of(row["id"], props) or ""
    text = text_of(props.get("text"))
    made = long_date(props.get("made_on"))
    activity = row.get("activity") or {}
    held = long_date(activity.get("date"))
    debate = (
        link(
            path_of(activity["id"], activity),
            joined(" van ", text_of(activity.get("kind")).lower(), held),
        )
        if held
        else ""
    )
    member = row.get("member") or {}
    who = (
        member_link(member)
        if member.get("name")
        else escape(text_of(props.get("minister_name")))
    )
    expected = long_date(due_date(props.get("expected_resolution")))
    cabinet = row.get("cabinet") or {}
    facts = [
        joined(
            ", ",
            f"Toegezegd in het {debate}" if debate else "",
            f"door {who}" if who else "",
            escape(text_of(props.get("minister_role"))),
            escape(text_of(props.get("ministry_name"))),
        ),
        (
            "Kabinet: "
            + link(
                path_of(node_id(COLLECTION_CABINETS, cabinet["key"])),
                cabinet_name({"name": cabinet.get("name")}, cabinet["key"]),
            )
            if cabinet.get("key")
            else ""
        ),
        f"Geregistreerd op {escape(made)}" if made else "",
        f"Status: {escape(text_of(props.get('status')))}"
        if props.get("status")
        else "",
        f"Verwachte afdoening: {escape(expected)}" if expected else "",
    ]
    about = row.get("dossiers") or []
    dossiers = bullets(
        [
            link(
                path_of(d["id"], d.get("props") or {}),
                joined(
                    " ",
                    official_number(
                        text_of((d.get("props") or {}).get("label")) or d["key"]
                    ),
                    text_of(d.get("title")),
                ),
            )
            for d in about
        ]
    )
    # on the agenda of its debate alone: discussed there, not what it is about
    on_agenda = bool(about) and all(d.get("basis") == BASIS_AGENDA for d in about)
    body = (
        f"<h1>Toezegging {escape(number)}</h1>"
        + (f"<p>{escape(text)}</p>" if text else "")
        + "".join(f"<p>{fact}</p>" for fact in facts if fact)
        + section("Besproken in het debat over" if on_agenda else "Dossiers", dossiers)
        + section("Brieven die haar nakomen", document_links(row.get("letters") or []))
    )
    minister = text_of(member.get("name")) or text_of(props.get("minister_name"))
    return Page(
        title=title,
        description=cut(text or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(f"Toezegging {number}", path)],
        data={
            "@type": "CreativeWork",
            "name": f"Toezegging {number}",
            "identifier": number,
            **present(
                text=text,
                dateCreated=activity.get("date") or props.get("made_on"),
                author={"@type": "Person", "name": minister} if minister else None,
            ),
        },
        body=body,
        index=bool(text),
    )


def _verb(law: dict[str, Any]) -> str:
    relations = law.get("relations") or []
    return next(
        (verb for relation, verb in RELATION_VERBS.items() if relation in relations), ""
    )


def publication_page(row: dict[str, Any]) -> Page:
    props, note = row["props"] or {}, row.get("note") or {}
    key = key_of(row["id"])
    title = publication_title(props, note, key)
    path = (
        path_of(row["id"], props)
        or path_of(
            node_id(
                COLLECTION_INSTRUMENTS, instrument_key(text_of(note.get("identifier")))
            ),
            {},
        )
        or ""
    )
    laws = row.get("laws") or []
    published = long_date(props.get("date_published"))
    signed = long_date(props.get("date_signed"))
    description = joined(
        "; ",
        title,
        f"gepubliceerd {published}" if published else "",
        "over " + ", ".join(law["name"] for law in laws[:3]) if laws else "",
    )
    year = props.get("publication_year") or note.get("year")
    official = text_of(props.get("official_id")) or text_of(note.get("identifier"))
    url = instrument_url(props) or publication_url(
        {"id": official, "year": int(str(year))}
        if official and str(year).isdigit()
        else None
    )
    dossiers = [n for n in props.get("dossier_numbers") or [] if isinstance(n, str)]
    dates = joined(
        ", ",
        f"Ondertekend {signed}" if signed else "",
        f"gepubliceerd {published}" if published else "",
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(dates)}</p>" if dates else "")
        + section(
            "Regelingen",
            bullets(
                [
                    link(path_of(law["id"], law.get("props") or {}), law["name"])
                    + (f" ({escape(_verb(law))})" if _verb(law) else "")
                    for law in laws
                ]
            ),
        )
        + section(
            "Dossiers",
            bullets(
                [
                    link(path_of("dossiers/x", {"label": n}), official_number(n))
                    for n in dossiers
                ]
            ),
        )
        + (
            f'<p><a href="{escape(url)}">De publicatie op officielebekendmakingen.nl</a></p>'
            if url
            else ""
        )
    )
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "Legislation",
            "name": title,
            "legislationJurisdiction": "NL",
            **present(
                legislationIdentifier=official,
                datePublished=props.get("date_published"),
            ),
        },
        body=body,
        index=publication_indexed(note.get("title"), bool(laws)),
    )
