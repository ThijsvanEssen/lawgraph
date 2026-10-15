"""The pages of the Kamer: a paper (with its text), a dossier, a zaak, an activity and a
vote; a member, a faction and a committee."""

from __future__ import annotations

from collections.abc import Iterator
from html import escape
from typing import Any

from lawgraph.api.seo.pages.base import (
    DESCRIPTION_MAX,
    LINKS,
    Page,
    bullets,
    capped,
    cut,
    link,
    member_link,
    period,
    present,
    section,
    source_links,
    trail,
    votes_list,
)
from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
)
from lawgraph.core.dossier_numbers import official_number
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.member_role import has_role
from lawgraph.core.models import node_id
from lawgraph.core.names import (
    activity_title,
    case_title,
    chamber,
    commitment_title,
    committee_title,
    decision_outcome,
    decision_title,
    document_title,
    dossier_title,
    faction_title,
    joined,
    member_name,
    member_role,
    member_title,
    text_of,
    years,
)
from lawgraph.core.readable_paths import path_of
from lawgraph.core.tk_records.actors import submitters
from lawgraph.core.tk_records.kinds import is_motion_or_amendment
from lawgraph.core.votes import VOTE_AGAINST, VOTE_FOR, vote_outcome

TK = "Tweede Kamer der Staten-Generaal"
EK = "Eerste Kamer der Staten-Generaal"


def document_links(rows: list[dict[str, Any]]) -> str:
    """The papers of *rows* (``id`` and ``light``), each by its title."""
    return bullets(
        [
            link(
                path_of(p["id"], p.get("light") or {}),
                document_title(p, p.get("light") or {}),
            )
            for p in rows
        ]
    )


def _dossier_links(numbers: Any) -> str:
    """``Dossier 36600 VIII``, for each dossier number."""
    return bullets(
        [
            link(path_of("dossiers/x", {"label": n}), f"Dossier {official_number(n)}")
            for n in numbers or []
            if isinstance(n, str)
        ]
    )


def votes_of(decision: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The factions that voted for and against, by name."""
    votes = decision.get("votes") or []
    return (
        [v["name"] for v in votes if v.get("choice") == VOTE_FOR],
        [v["name"] for v in votes if v.get("choice") == VOTE_AGAINST],
    )


def _outcome(decisions: list[dict[str, Any]]) -> str | None:
    """``aangenomen`` or ``verworpen``: the outcome of the last vote on a paper."""
    for decision in reversed(decisions):
        outcome = vote_outcome((decision.get("props") or {}).get("passed"))
        if outcome:
            return outcome
    return None


def _text_blocks(text: str, sections: Any) -> Iterator[tuple[str, str]]:
    """The text of a paper (a line per heading, paragraph, list item or table row) as HTML:
    a line where one of its ``sections`` starts as a heading of its level, every other line
    as a paragraph (``docs/data-model.md``, Text and sections of a Kamerstuk)."""
    levels = {
        s["char_start"]: s.get("level") or 1
        for s in (sections if isinstance(sections, list) else [])
        if isinstance(s, dict) and isinstance(s.get("char_start"), int)
    }
    at = 0
    for line in text.split("\n"):
        start, at = at, at + len(line) + 1
        words = line.strip()
        if not words:
            continue
        level = levels.get(start)
        if isinstance(level, int):
            tag = f"h{min(level + 2, 6)}"
            yield f"<{tag}>{escape(words)}</{tag}>", words
        else:
            yield f"<p>{escape(words)}</p>", words


# The sections of the sources a paper links by its edges (``seo.DOCUMENT_LINKS``), in order.
_DOCUMENT_SECTIONS = (
    ("case", "Zaak"),
    ("signed_by", "Ondertekend door"),
    ("attached_to", "Bijlage bij"),
    ("attachments", "Bijlagen"),
    ("made_in", "Behandeld in"),
    ("answers", "Antwoord op"),
    ("answered_by", "Beantwoord in"),
    ("explains", "Licht toe"),
    ("refers_to", "Verwijst naar"),
    ("cited_in", "Aangehaald in"),
)


def document_page(row: dict[str, Any]) -> Page:
    light = row.get("light") or {}
    decisions = row.get("decisions") or []
    title = document_title(row, light)
    path = path_of(row["id"], light) or ""
    kind = text_of(row.get("kind")) or text_of(light.get("kind"))
    people = submitters(kind, row.get("actors") or [])
    names = ", ".join(p["name"] for p in people if p.get("name"))
    day = long_date(row.get("date") or light.get("date"))
    voor, tegen = votes_of(decisions[-1]) if decisions else ([], [])
    outcome = _outcome(decisions)
    description = (
        joined(
            "; ",
            f"Ingediend door {names}" if names else "",
            day,
            f"{outcome}, voor: {', '.join(voor)}"
            if outcome and voor
            else outcome or "",
        )
        or title
    )
    dossier_label = joined(
        "-", text_of(light.get("dossier_number")), text_of(light.get("dossier_suffix"))
    )
    # by its label (36600-VIII): the key of a dossier with a suffix is no label
    dossier_path = (
        path_of("dossiers/x", {"label": dossier_label}) if dossier_label else None
    )
    dictum = text_of(light.get("dictum"))
    text = capped(
        _text_blocks(row.get("text") or "", row.get("sections")),
        "<p>De tekst gaat verder in Concordans.</p>",
    )
    links = row.get("links") or {}
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(kind)}, {escape(day)}</p>" if kind and day else "")
        + (f"<p>Indieners: {escape(names)}</p>" if names else "")
        + (
            f"<p>Dossier {link(dossier_path, official_number(dossier_label))}</p>"
            if dossier_label
            else ""
        )
        + (f"<blockquote>{escape(dictum)}</blockquote>" if dictum else "")
        + section("Tekst", text)
        + section(
            f"Stemming: {outcome}" if outcome else "Stemming", votes_list(voor, tegen)
        )
        + "".join(
            section(heading, source_links(links.get(name) or []))
            for name, heading in _DOCUMENT_SECTIONS
        )
        + section("In dit dossier", document_links(row.get("beside") or []))
    )
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=trail(
            f"Dossier {official_number(dossier_label)}", dossier_path, title, path
        ),
        data={
            "@type": "CreativeWork",
            "name": title,
            **present(
                datePublished=row.get("date"),
                author=[{"@type": "Person", "name": p["name"]} for p in people],
            ),
        },
        body=body,
    )


def dossier_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    title = dossier_title(props, row["key"])
    path = path_of(row["id"], props) or ""
    total = int(row.get("total") or 0)
    phase = text_of(props.get("current_phase"))
    last = long_date(props.get("last_activity"))
    description = joined(
        ", ",
        text_of(props.get("title")),
        f"fase: {phase}" if phase else "",
        f"{total} stukken" if total else "",
        f"laatste activiteit {last}" if last else "",
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (
            f"<p>{escape(text_of(props.get('title')))}</p>"
            if props.get("title")
            else ""
        )
        + (f"<p>Fase: {escape(phase)}</p>" if phase else "")
        + section(
            f"Stukken ({total})" if total else "Stukken",
            document_links(row.get("papers") or []),
        )
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "CreativeWork",
            "name": text_of(props.get("title")) or title,
            "identifier": text_of(props.get("label")) or row["key"],
        },
        body=body,
        # a dossier without a paper in the data has its title alone
        index=total > 0,
    )


def case_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    number = text_of(props.get("number")) or row["key"]
    title = case_title(props, row["key"])
    path = path_of(row["id"], props) or ""
    kind = text_of(props.get("kind"))
    started = long_date(props.get("started_on"))
    dossier = row.get("dossier") or {}
    label = text_of(dossier.get("label"))
    dossier_path = path_of(dossier["id"], {"label": label}) if label else None
    decisions = [d.get("props") or {} for d in row.get("decisions") or []]
    outcome = next(
        (decision_outcome(d) for d in reversed(decisions) if decision_outcome(d)), ""
    )
    description = joined(
        ", ",
        text_of(props.get("title")) or text_of(props.get("citation_title")),
        f"zaak {number}",
        kind,
        f"gestart {started}" if started else "",
        f"dossier {official_number(label)}" if label else "",
        outcome,
        "afgedaan" if props.get("done") is True else "",
    )
    votes = bullets(
        [
            link(path_of(d["id"]), decision_title(d.get("props") or {}))
            for d in row.get("decisions") or []
        ]
    )
    dossier_name = joined(" ", official_number(label), text_of(dossier.get("title")))
    body = (
        f"<h1>{escape(title)}</h1>"
        + (
            f"<p>{escape(kind)}, gestart {escape(started)}</p>"
            if kind and started
            else ""
        )
        + (f"<p>Dossier {link(dossier_path, dossier_name)}</p>" if label else "")
        + section("Stukken", document_links(row.get("papers") or []))
        + section("Stemmingen", votes)
    )
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=trail(f"Dossier {official_number(label)}", dossier_path, title, path),
        data={
            "@type": "CreativeWork",
            "name": title,
            "identifier": number,
            **present(
                dateCreated=props.get("started_on"),
                isPartOf={"@type": "CreativeWork", "name": dossier_name}
                if dossier_name
                else None,
            ),
        },
        body=body,
        # of a motion or an amendment the page of its paper is the one to find
        index=not is_motion_or_amendment(kind),
    )


def activity_page(row: dict[str, Any]) -> Page:
    props = row.get("props") or {}
    records = row.get("records") or {}
    title = activity_title(props, row["key"])
    path = path_of(row["id"], props) or ""
    committee = row.get("committee") or {}
    led = (
        link(
            path_of(node_id(COLLECTION_COMMITTEES, committee["key"]), committee),
            text_of(committee.get("name")),
        )
        if committee.get("name")
        else ""
    )
    dossiers = bullets(
        [
            link(
                path_of(node_id(COLLECTION_DOSSIERS, n), {"label": n}),
                f"Dossier {official_number(n)}",
            )
            for n in props.get("dossier_numbers") or []
            if isinstance(n, str)
        ]
    )

    def documents(kind: str) -> str:
        rows = (records.get(kind) or [])[:LINKS]
        return document_links([{"id": p["id"], "light": p} for p in rows])

    commitments = bullets(
        [
            link(path_of(c["id"], c), commitment_title(c, c["key"]))
            for c in (records.get("commitments") or [])[:LINKS]
        ]
    )
    decisions = bullets(
        [
            link(path_of(d["id"]), decision_title(d))
            for d in (records.get("decisions") or [])[:LINKS]
        ]
    )
    held = bool(
        records.get("documents") or records.get("motions") or records.get("commitments")
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>Geleid door {led}</p>" if led else "")
        + section("Dossiers", dossiers)
        + section("Verslag en stenogram", documents("documents"))
        + section("Ingediende moties", documents("motions"))
        + section("Toezeggingen", commitments)
        + section("Besluiten", decisions)
    )
    return Page(
        title=title,
        description=cut(title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "Event",
            "name": title,
            **present(
                identifier=props.get("number"),
                startDate=props.get("date"),
                organizer={"@type": "Organization", "name": committee["name"]}
                if committee.get("name")
                else None,
            ),
        },
        body=body,
        # a page with something to read: a record, a motion or a commitment made in it
        index=held,
    )


def _sides(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Who voted for and against: the votes cast (``VOTED``), else the factions the Eerste
    Kamer lists."""
    if row.get("votes"):
        return votes_of(row)
    props = row["props"] or {}

    def names(field: str) -> list[str]:
        return [text_of(n) for n in props.get(field) or [] if text_of(n)]

    return names("factions_for"), names("factions_against")


def decision_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    title = decision_title(props)
    path = path_of(row["id"], props) or ""
    outcome = decision_outcome(props)
    voor, tegen = _sides(row)
    description = joined(
        "; ",
        title,
        f"voor: {', '.join(voor)}" if voor else "",
        f"tegen: {', '.join(tegen)}" if tegen else "",
    )
    decided = text_of(props.get("decision_text"))
    documents = row.get("papers") or []
    # a vote on one motion or amendment is found on the page of that paper
    (motion,) = documents if len(documents) == 1 else (None,)
    canonical = (
        path_of(motion["id"], motion.get("light") or {})
        if motion is not None
        and is_motion_or_amendment(
            text_of(motion.get("kind"))
            or text_of((motion.get("light") or {}).get("kind"))
        )
        else None
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(decided)}</p>" if decided else "")
        + section("Gestemd over", document_links(documents))
        + section("Dossiers", _dossier_links(props.get("dossier_numbers")))
        + section(
            f"Stemming: {outcome}" if outcome else "Stemming", votes_list(voor, tegen)
        )
    )
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "CreativeWork",
            "name": title,
            **present(dateCreated=props.get("date")),
        },
        body=body,
        # the page of the one motion or amendment it is about holds the vote, and is the
        # one to find; a vote on several papers is found on none
        canonical=canonical or "",
        index=bool(canonical),
    )


# ── members, factions and committees ──────────────────────────────────────────


def _posts(props: dict[str, Any]) -> list[dict[str, Any]]:
    """The posts of a member in a cabinet, newest first."""
    posts = [f for f in props.get("government_functions") or [] if isinstance(f, dict)]
    return sorted(posts, key=lambda f: text_of(f.get("from_date")), reverse=True)


def _post_line(post: dict[str, Any]) -> str:
    """``Minister-president in kabinet-Jetten (2026)``, of a post in the description."""
    return joined(
        " ",
        text_of(post.get("function")),
        f"in {text_of(post.get('cabinet'))}" if post.get("cabinet") else "",
        f"({years(post.get('from_date'), post.get('to_date'))})"
        if post.get("from_date")
        else "",
    )


def _post_item(post: dict[str, Any]) -> str:
    cabinet_key = post.get("cabinet_key")
    return joined(
        ", ",
        escape(text_of(post.get("function"))),
        link(
            path_of(node_id(COLLECTION_CABINETS, cabinet_key))
            if isinstance(cabinet_key, str)
            else None,
            text_of(post.get("cabinet")),
        )
        if post.get("cabinet")
        else "",
        escape(period(post.get("from_date"), post.get("to_date"))),
    )


def _seat_item(seat: dict[str, Any]) -> str:
    faction_key = seat.get("faction_key")
    return joined(
        ", ",
        link(
            path_of(node_id(COLLECTION_FACTIONS, faction_key))
            if isinstance(faction_key, str)
            else None,
            text_of(seat.get("name")) or text_of(seat.get("abbreviation")),
        ),
        escape(text_of(seat.get("role"))),
        escape(period(seat.get("from_date"), seat.get("to_date"))),
    )


def _ek_item(ek: dict[str, Any]) -> str:
    faction_key = text_of(ek.get("faction"))
    return joined(
        ", ",
        "Eerste Kamer",
        link(
            path_of(node_id(COLLECTION_FACTIONS, faction_key)) if faction_key else None,
            text_of(ek.get("abbreviation")),
        )
        if ek.get("abbreviation")
        else "",
        escape(period(ek.get("observed_from"), ek.get("observed_until"))),
    )


def member_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    name = member_name(props)
    title = member_title(props)
    path = path_of(row["id"], props) or ""
    posts = _posts(props)
    party = text_of(props.get("party"))
    description = joined(
        ", ",
        name + (f" ({party})" if party and party not in name else ""),
        *(_post_line(f) for f in posts[:3]),
    )
    seats = [m for m in props.get("faction_memberships") or [] if isinstance(m, dict)]
    seat_items = [_seat_item(m) for m in reversed(seats)]
    ek = props.get("ek") if isinstance(props.get("ek"), dict) else {}
    if ek:
        seat_items.insert(0, _ek_item(ek))
    role = member_role(props)
    body = (
        f"<h1>{escape(name)}</h1>"
        + (f"<p>{escape(role)}</p>" if role else "")
        + section("Functies in een kabinet", bullets([_post_item(f) for f in posts]))
        + section("Fracties", bullets(seat_items))
        + section("Stukken", document_links(row.get("papers") or []))
    )
    organisations = [
        text_of(m.get("name")) for m in seats if text_of(m.get("name"))
    ] + [text_of(f.get("cabinet")) for f in posts if text_of(f.get("cabinet"))]
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(name, path)],
        data={
            "@type": "Person",
            "name": name,
            **present(
                jobTitle=role,
                memberOf=[
                    {"@type": "Organization", "name": o}
                    for o in dict.fromkeys(organisations)
                ],
            ),
        },
        body=body,
        # a person of the Tweede Kamer's records whose seat the data does not hold
        index=bool(name and path) and has_role(props),
    )


def _role(meta: Any) -> str:
    meta = meta if isinstance(meta, dict) else {}
    role = text_of(meta.get("role"))
    if meta.get("substitute"):
        return f"plaatsvervangend lid{', ' + role if role else ''}"
    return role


def _members(rows: list[dict[str, Any]]) -> str:
    return bullets(
        [
            member_link(r)
            + (f", {escape(_role(r.get('meta')))}" if _role(r.get("meta")) else "")
            for r in rows
            if text_of(r.get("name"))
        ]
    )


def _house(ek: bool) -> dict[str, Any]:
    """The chamber a faction or a committee is part of."""
    return {"@type": "GovernmentOrganization", "name": EK if ek else TK}


def faction_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    title = faction_title(props, key)
    path = path_of(row["id"], props) or ""
    name = text_of(props.get("name"))
    abbreviation = text_of(props.get("abbreviation"))
    ek = chamber(props, key) == "EK"
    active = period(props.get("active_from"), props.get("active_until"))
    description = joined(
        ", ",
        name + (f" ({abbreviation})" if abbreviation and abbreviation != name else ""),
        "fractie in de Eerste Kamer" if ek else "fractie in de Tweede Kamer",
        f"actief {active}" if active else "",
    )
    seats = props.get("seats")
    board = [
        joined(", ", escape(text_of(b.get("function"))), escape(text_of(b.get("name"))))
        for b in props.get("board") or []
        if isinstance(b, dict)
    ]
    url = text_of(props.get("url"))
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(name)}</p>" if name and name not in title else "")
        + (f"<p>Actief {escape(active)}</p>" if active else "")
        + (
            f"<p>Zetels: {seats}</p>"
            if isinstance(seats, int) and not isinstance(seats, bool) and seats
            else ""
        )
        + section("Fractiebestuur", bullets(board))
        + section("Leden", _members(row.get("members") or []))
        + (
            f'<p><a href="{escape(url)}">De fractie op eerstekamer.nl</a></p>'
            if ek and url.startswith("https://")
            else ""
        )
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "Organization",
            "name": name or title,
            **present(alternateName=abbreviation),
            "parentOrganization": _house(ek),
        },
        body=body,
        index=bool(name or abbreviation),
    )


def committee_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    title = committee_title(props, key)
    path = path_of(row["id"], props) or ""
    ek = chamber(props, key) == "EK"
    name = text_of(props.get("title")) or text_of(props.get("name")) or key
    kind = text_of(props.get("kind"))
    active = period(props.get("started_on"), props.get("ended_on"))
    description = joined(
        ", ",
        name,
        kind if kind and kind.lower() not in name.lower() else "",
        "Eerste Kamer" if ek else "Tweede Kamer",
        f"actief {active}" if active else "",
    )
    url = text_of(props.get("url"))
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(kind)}</p>" if kind else "")
        + (f"<p>Actief {escape(active)}</p>" if active else "")
        + section("Leden", _members(row.get("members") or []))
        + (
            f'<p><a href="{escape(url)}">De commissie op eerstekamer.nl</a></p>'
            if ek and url.startswith("https://")
            else ""
        )
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "Organization",
            "name": name,
            **present(alternateName=props.get("abbreviation")),
            "parentOrganization": _house(ek),
        },
        body=body,
        index=bool(text_of(props.get("name")) or text_of(props.get("title"))),
    )
