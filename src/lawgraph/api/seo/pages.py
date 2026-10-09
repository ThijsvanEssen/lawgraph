"""The server HTML of a readable address: per kind of source its title and description in
the words people search, its canonical address, its structured data (JSON-LD) and its
content with links to the sources it is connected to.

One source for the titles: the SPA shows the same ones (``title`` and ``description`` of
the node, ``api/routes/nodes.py``), from ``title_of``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from typing import Any

from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.readable_paths import BW_BOOKS, book_number, key_ecli, path_of
from lawgraph.core.tk_records import is_motion_or_amendment, submitters

SITE = "Concordans"
# The length a title is cut to before ", Concordans": what a search result shows.
TITLE_MAX = 65
DESCRIPTION_MAX = 155
_BW = set(BW_BOOKS.values())


@dataclass
class Page:
    """What the HTML of a source shows: its title (without the name of the site), its
    description, its canonical path, its breadcrumbs (name, path), its structured data,
    its content (HTML), whether it is indexed and its language."""

    title: str
    description: str
    path: str
    crumbs: list[tuple[str, str]] = field(default_factory=list)
    data: dict[str, Any] | None = None
    body: str = ""
    index: bool = True
    lang: str = "nl"
    # the image of the page when it is shared (``og:image``): one per kind
    image: str = "/og/concordans.png"
    # whether ``title`` is the whole ``<title>`` already (a page of the app), without the
    # name of the site to add
    whole_title: bool = False


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def cut(text: str, length: int) -> str:
    """*text* in one line of at most *length* characters, cut at a word with an ellipsis."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= length:
        return text
    head = text[: length - 1].rsplit(" ", 1)[0].rstrip(",;:.")
    return f"{head}…"


def full_title(title: str) -> str:
    """The ``<title>`` of a page: its title cut to ``TITLE_MAX``, then the site."""
    return f"{cut(title, TITLE_MAX)}, {SITE}" if title else SITE


def _day(iso: Any) -> str:
    """``2019-12-20`` as the Dutch write it: ``20-12-2019``."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", _text(iso))
    return f"{m[3]}-{m[2]}-{m[1]}" if m else ""


def _link(path: str | None, label: str) -> str:
    if not path:
        return escape(label)
    return f'<a href="{escape(path)}">{escape(label)}</a>'


def _list(items: list[str]) -> str:
    return (
        "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"
        if items
        else ""
    )


def _section(title: str, html: str) -> str:
    return f"<section><h2>{escape(title)}</h2>{html}</section>" if html else ""


# ── laws and articles ─────────────────────────────────────────────────────────


def law_name(props: dict[str, Any]) -> str:
    """``Burgerlijk Wetboek Boek 6 (BW 6)``: the citation title, its short title after it."""
    name = _text(props.get("citation_title")) or _text(props.get("title"))
    short = _text(props.get("short_title"))
    return f"{name} ({short})" if short and short.lower() not in name.lower() else name


def _law_short(props: dict[str, Any] | None) -> str:
    """How an article cites its law: ``BW`` for a book of the Burgerlijk Wetboek, else its
    short title, else its citation title."""
    props = props or {}
    if _text(props.get("bwb_id")).upper() in _BW:
        return "BW"
    return (
        _text(props.get("short_title"))
        or _text(props.get("citation_title"))
        or _text(props.get("title"))
    )


def article_name(bwb_id: str | None, number: str, law: str) -> str:
    """``Artikel 6:162 BW``."""
    cited = book_number(bwb_id, number)
    return f"Artikel {cited} {law}".strip()


def law_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    bwb = _text(props.get("bwb_id")) or row["key"].upper()
    name = law_name(props) or bwb
    path = path_of(row["id"], props) or f"/wetten/{bwb}"
    since = _day(props.get("date_in_force"))
    count = len(row["articles"])
    description = ", ".join(
        part
        for part in (
            _text(props.get("citation_title")) or name,
            f"geldend sinds {since}" if since else "",
            f"{count} artikelen" if count else "",
        )
        if part
    )
    short = _law_short(props)
    toc = _list(
        [
            _link(
                path_of(
                    f"articles/{a['key']}",
                    {"bwb_id": bwb, "article_number": a["article_number"]},
                ),
                article_name(bwb, a["article_number"], short),
            )
            for a in row["articles"]
        ]
    )
    body = (
        f"<h1>{escape(name)}</h1>"
        + (f"<p>Geldend sinds {escape(since)}.</p>" if since else "")
        + _section("Inhoud", toc)
    )
    return Page(
        title=name,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=[(name, path)],
        data={
            "@type": "Legislation",
            "name": name,
            "legislationIdentifier": bwb,
            "legislationJurisdiction": "NL",
            **(
                {"legislationDate": props["date_in_force"]}
                if props.get("date_in_force")
                else {}
            ),
        },
        body=body,
        index=not props.get("stub"),
    )


def article_title(props: dict[str, Any], law: dict[str, Any] | None) -> str:
    """``Artikel 6:162 BW: onrechtmatige daad``, with its heading when it has one."""
    number = _text(props.get("article_number"))
    name = (
        article_name(_text(props.get("bwb_id")) or None, number, _law_short(law))
        if number
        else _text(props.get("display_name"))
    )
    heading = _text(props.get("heading"))
    return f"{name}: {heading[:1].lower()}{heading[1:]}" if heading else name


def article_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    law = row.get("law") or {}
    title = article_title(props, law)
    path = path_of(row["id"], props) or ""
    text = _text(props.get("text"))
    # its text alone: the same whether the judgments citing it are kept yet or not
    description = text or title
    law_path = (
        path_of(f"instruments/{_text(law.get('bwb_id')).lower()}", law) if law else None
    )
    law_label = law_name(law) if law else ""
    judgments = _list(
        [
            _link(path_of(j["id"], j.get("light") or {}), _judgment_label(j))
            for j in row.get("judgments") or []
        ]
    )
    paragraphs = "".join(
        f"<p>{escape(p.strip())}</p>" for p in text.split("\n") if p.strip()
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{_link(law_path, law_label)}</p>" if law_label else "")
        + paragraphs
        + _section("Uitspraken die dit artikel aanhalen", judgments)
    )
    crumbs = ([(law_label, law_path)] if law_label and law_path else []) + [
        (title, path)
    ]
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=crumbs,
        data={
            "@type": "Legislation",
            "name": title,
            "legislationIdentifier": f"{_text(props.get('bwb_id'))} artikel "
            f"{_text(props.get('article_number'))}",
            "legislationJurisdiction": "NL",
            **(
                {
                    "isPartOf": {
                        "@type": "Legislation",
                        "name": law_label,
                        "legislationIdentifier": _text(law.get("bwb_id")),
                    }
                }
                if law_label
                else {}
            ),
        },
        body=body,
        index=bool(text) and not props.get("stub"),
    )


# ── judgments ─────────────────────────────────────────────────────────────────


def _judgment_label(row: dict[str, Any]) -> str:
    light = row.get("light") or {}
    return judgment_title(light, row["id"])


def judgment_title(light: dict[str, Any], node_id: str = "") -> str:
    """``ECLI:NL:HR:2019:2006, Hoge Raad 20-12-2019``, with its name (``Urgenda``)."""
    ecli = _text(light.get("ecli")) or key_ecli(node_id.partition("/")[2]) or ""
    court = _text(light.get("court"))
    day = _day(light.get("date"))
    names = light.get("names") or []
    name = _text(names[0]) if isinstance(names, list) and names else ""
    head = ", ".join(
        part for part in (ecli, " ".join(p for p in (court, day) if p)) if part
    )
    return f"{head} ({name})" if name else head or _text(light.get("display_name"))


def judgment_page(row: dict[str, Any]) -> Page:
    light = row.get("light") or {}
    title = judgment_title(light, row["id"])
    path = path_of(row["id"], light) or ""
    summary = _text(row.get("summary")) or _text(light.get("summary"))
    ecli = _text(light.get("ecli"))
    articles = _list(
        [
            _link(
                path_of(a["id"], a),
                article_name(
                    a.get("bwb_id"), _text(a.get("article_number")), _text(a.get("law"))
                ),
            )
            for a in row.get("articles") or []
            if _text(a.get("article_number"))
        ]
    )
    judgments = _list(
        [
            _link(path_of(j["id"], j.get("light") or {}), _judgment_label(j))
            for j in row.get("judgments") or []
        ]
    )
    source = (
        f'<p><a href="https://uitspraken.rechtspraak.nl/details?id={escape(ecli)}">'
        "De uitspraak op rechtspraak.nl</a></p>"
        if ecli.upper().startswith("ECLI:NL:")
        else ""
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(summary)}</p>" if summary else "")
        + source
        + _section("Aangehaalde artikelen", articles)
        + _section("Aangehaalde uitspraken", judgments)
    )
    court = _text(light.get("court"))
    return Page(
        title=title,
        description=cut(summary or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "CreativeWork",
            "name": title,
            "identifier": ecli,
            **({"datePublished": light["date"]} if light.get("date") else {}),
            **({"author": {"@type": "Organization", "name": court}} if court else {}),
            **({"abstract": cut(summary, 500)} if summary else {}),
        },
        body=body,
        index=not light.get("stub"),
        lang="en" if _text(light.get("jurisdiction")).upper() == "ECHR" else "nl",
    )


# ── papers and dossiers ───────────────────────────────────────────────────────

# "Motie van het lid Bolhuis over …", "Amendement van de leden A en B ter …": the
# indieners after the kind, without "van het lid" / "van de leden".
_OF_MEMBERS = re.compile(
    r"^(Motie|Amendement)\s+van\s+(?:het\s+lid|de\s+leden)\s+", re.I
)


def _outcome(decisions: list[dict[str, Any]]) -> str | None:
    """``aangenomen`` or ``verworpen``: the outcome of the last vote on a paper."""
    for decision in reversed(decisions):
        passed = (decision.get("props") or {}).get("passed")
        if passed is not None:
            return "aangenomen" if passed else "verworpen"
    return None


def paper_title(
    row: dict[str, Any], light: dict[str, Any], decisions: list[dict[str, Any]]
) -> str:
    """``Motie Bolhuis over een AI-killswitch (36496-71), aangenomen``; another paper
    ``<kind>: <subject> (36496-71)``."""
    dossier = _text(light.get("dossier_number"))
    suffix = _text(light.get("dossier_suffix"))
    number = light.get("sequence") or light.get("number")
    cite = (
        f"{dossier}{'-' + suffix if suffix else ''}-{number}"
        if dossier and number
        else ""
    )
    subject = _text(row.get("subject")) or _text(light.get("title"))
    kind = _text(row.get("kind")) or _text(light.get("kind"))
    if is_motion_or_amendment(kind):
        title = _OF_MEMBERS.sub(lambda m: f"{m[1].capitalize()} ", subject) or kind
        outcome = _outcome(decisions)
        return (
            title + (f" ({cite})" if cite else "") + (f", {outcome}" if outcome else "")
        )
    head = (
        f"{kind}: {subject}"
        if kind and subject and not subject.startswith(kind)
        else subject or kind
    )
    return head + (f" ({cite})" if cite else "")


def _votes(decision: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The factions that voted for and against, by name."""
    voor = [v["name"] for v in decision.get("votes") or [] if v.get("choice") == "Voor"]
    tegen = [
        v["name"] for v in decision.get("votes") or [] if v.get("choice") == "Tegen"
    ]
    return voor, tegen


def paper_page(row: dict[str, Any]) -> Page:
    light = row.get("light") or {}
    decisions = row.get("decisions") or []
    title = paper_title(row, light, decisions)
    path = path_of(row["id"], light) or ""
    kind = _text(row.get("kind")) or _text(light.get("kind"))
    people = submitters(kind, row.get("actors") or [])
    names = ", ".join(p["name"] for p in people if p.get("name"))
    day = _day(row.get("date") or light.get("date"))
    voor, tegen = _votes(decisions[-1]) if decisions else ([], [])
    outcome = _outcome(decisions)
    description = (
        "; ".join(
            part
            for part in (
                f"Ingediend door {names}" if names else "",
                day,
                f"{outcome}, voor: {', '.join(voor)}"
                if outcome and voor
                else outcome or "",
            )
            if part
        )
        or title
    )
    dossier_label = "-".join(
        p
        for p in (
            _text(light.get("dossier_number")),
            _text(light.get("dossier_suffix")),
        )
        if p
    )
    dossier_path = path_of(f"dossiers/{dossier_label}") if dossier_label else None
    dictum = _text(light.get("dictum"))
    votes = _list([f"Voor: {escape(', '.join(voor))}"] if voor else []) + _list(
        [f"Tegen: {escape(', '.join(tegen))}"] if tegen else []
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(kind)}, {escape(day)}</p>" if kind and day else "")
        + (f"<p>Indieners: {escape(names)}</p>" if names else "")
        + (
            f"<p>Dossier {_link(dossier_path, dossier_label)}</p>"
            if dossier_label
            else ""
        )
        + (f"<blockquote>{escape(dictum)}</blockquote>" if dictum else "")
        + _section(f"Stemming: {outcome}" if outcome else "Stemming", votes)
    )
    crumbs = ([(f"Dossier {dossier_label}", dossier_path)] if dossier_path else []) + [
        (title, path)
    ]
    return Page(
        title=title,
        description=cut(description, DESCRIPTION_MAX),
        path=path,
        crumbs=crumbs,
        data={
            "@type": "CreativeWork",
            "name": title,
            **({"datePublished": row["date"]} if row.get("date") else {}),
            **(
                {"author": [{"@type": "Person", "name": p["name"]} for p in people]}
                if people
                else {}
            ),
        },
        body=body,
    )


def dossier_title(props: dict[str, Any], key: str) -> str:
    """``36496 Wet betaalbare huur: dossier, moties en stemmingen``."""
    label = _text(props.get("label")) or key
    title = _text(props.get("title"))
    name = short_title(title) or title
    return (
        f"{label} {name}: dossier, moties en stemmingen" if name else f"Dossier {label}"
    )


def dossier_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    title = dossier_title(props, row["key"])
    path = path_of(row["id"], props) or ""
    total = int(row.get("total") or 0)
    phase = _text(props.get("current_phase"))
    last = _day(props.get("last_activity"))
    description = ", ".join(
        part
        for part in (
            _text(props.get("title")),
            f"fase: {phase}" if phase else "",
            f"{total} stukken" if total else "",
            f"laatste activiteit {last}" if last else "",
        )
        if part
    )
    papers = _list(
        [
            _link(
                path_of(p["id"], p.get("light") or {}),
                paper_title(p, p.get("light") or {}, []),
            )
            for p in row.get("papers") or []
        ]
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(_text(props.get('title')))}</p>" if props.get("title") else "")
        + (f"<p>Fase: {escape(phase)}</p>" if phase else "")
        + _section(f"Stukken ({total})" if total else "Stukken", papers)
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "CreativeWork",
            "name": _text(props.get("title")) or title,
            "identifier": _text(props.get("label")) or row["key"],
        },
        body=body,
    )


# ── members, factions, cabinets and committees ────────────────────────────────

TK = "Tweede Kamer der Staten-Generaal"
EK = "Eerste Kamer der Staten-Generaal"


def _period(start: Any, end: Any) -> str:
    """``sinds 02-07-2024``, or ``02-07-2024 tot 05-07-2024``: as the source dates it."""
    first, last = _day(start), _day(end)
    if first and last:
        return f"{first} tot {last}"
    return f"sinds {first}" if first else (f"tot {last}" if last else "")


def _years(start: Any, end: Any) -> str:
    """``2022–2024``, or ``2024–`` while it lasts."""
    first, last = _text(start)[:4], _text(end)[:4]
    if not first:
        return ""
    return f"{first}–{last}" if last != first else first


def _member_link(row: dict[str, Any]) -> str:
    name = _text(row.get("name"))
    return _link(path_of(row["id"], {"slug": row.get("slug")}), name) if name else ""


def member_name(props: dict[str, Any]) -> str:
    return (
        _text(props.get("name"))
        or _text(props.get("full_name"))
        or _text(props.get("display_name"))
    )


def member_role(props: dict[str, Any]) -> str:
    """What a member is now, in the words of the source: the post they hold in a cabinet
    as the source names it, else a seat in a chamber; ``oud-Kamerlid`` only for one whose
    seats in the Tweede Kamer all ended; nothing for anyone else."""
    posts = [f for f in props.get("government_functions") or [] if isinstance(f, dict)]
    held = [f for f in posts if not f.get("to_date") and _text(f.get("function"))]
    if held:
        return _text(held[-1].get("function"))
    seats = [m for m in props.get("faction_memberships") or [] if isinstance(m, dict)]
    now = [m for m in seats if not m.get("to_date")]
    if now:
        party = _text(now[-1].get("abbreviation")) or _text(now[-1].get("name"))
        return f"Tweede Kamerlid ({party})" if party else "Tweede Kamerlid"
    ek = props.get("ek") if isinstance(props.get("ek"), dict) else {}
    if ek and not ek.get("observed_until"):
        party = _text(ek.get("abbreviation"))
        return f"Eerste Kamerlid ({party})" if party else "Eerste Kamerlid"
    if seats and all(m.get("to_date") for m in seats):
        return "oud-Kamerlid"
    return ""


def member_title(props: dict[str, Any]) -> str:
    """``Rob Jetten, Minister-president``: the name, and what they are now when known."""
    name, role = member_name(props), member_role(props)
    return f"{name}, {role}" if name and role else name


def _posts(props: dict[str, Any]) -> list[dict[str, Any]]:
    """The posts of a member in a cabinet, newest first."""
    posts = [f for f in props.get("government_functions") or [] if isinstance(f, dict)]
    return sorted(posts, key=lambda f: _text(f.get("from_date")), reverse=True)


def member_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    name = member_name(props)
    title = member_title(props)
    path = path_of(row["id"], props) or ""
    posts = _posts(props)
    party = _text(props.get("party"))
    description = ", ".join(
        part
        for part in (
            name + (f" ({party})" if party and party not in name else ""),
            *(
                " ".join(
                    p
                    for p in (
                        _text(f.get("function")),
                        f"in {_text(f.get('cabinet'))}" if f.get("cabinet") else "",
                        f"({_years(f.get('from_date'), f.get('to_date'))})"
                        if f.get("from_date")
                        else "",
                    )
                    if p
                )
                for f in posts[:3]
            ),
        )
        if part
    )
    post_items = [
        ", ".join(
            p
            for p in (
                escape(_text(f.get("function"))),
                _link(
                    path_of(f"cabinets/{f['cabinet_key']}")
                    if isinstance(f.get("cabinet_key"), str)
                    else None,
                    _text(f.get("cabinet")),
                )
                if f.get("cabinet")
                else "",
                escape(_period(f.get("from_date"), f.get("to_date"))),
            )
            if p
        )
        for f in posts
    ]
    seats = [m for m in props.get("faction_memberships") or [] if isinstance(m, dict)]
    seat_items = [
        ", ".join(
            p
            for p in (
                _link(
                    path_of(f"factions/{m['faction_key']}")
                    if isinstance(m.get("faction_key"), str)
                    else None,
                    _text(m.get("name")) or _text(m.get("abbreviation")),
                ),
                escape(_text(m.get("role"))),
                escape(_period(m.get("from_date"), m.get("to_date"))),
            )
            if p
        )
        for m in reversed(seats)
    ]
    ek = props.get("ek") if isinstance(props.get("ek"), dict) else {}
    if ek:
        faction_key = _text(ek.get("faction"))
        seat_items.insert(
            0,
            ", ".join(
                p
                for p in (
                    "Eerste Kamer",
                    _link(
                        path_of(f"factions/{faction_key}") if faction_key else None,
                        _text(ek.get("abbreviation")),
                    )
                    if ek.get("abbreviation")
                    else "",
                    escape(_period(ek.get("observed_from"), ek.get("observed_until"))),
                )
                if p
            ),
        )
    papers = _list(
        [
            _link(
                path_of(p["id"], p.get("light") or {}),
                paper_title(p, p.get("light") or {}, []),
            )
            for p in row.get("papers") or []
        ]
    )
    role = member_role(props)
    body = (
        f"<h1>{escape(name)}</h1>"
        + (f"<p>{escape(role)}</p>" if role else "")
        + _section("Functies in een kabinet", _list(post_items))
        + _section("Fracties", _list(seat_items))
        + _section("Stukken", papers)
    )
    organisations = [_text(m.get("name")) for m in seats if _text(m.get("name"))] + [
        _text(f.get("cabinet")) for f in posts if _text(f.get("cabinet"))
    ]
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(name, path)],
        data={
            "@type": "Person",
            "name": name,
            **({"jobTitle": role} if role else {}),
            **(
                {
                    "memberOf": [
                        {"@type": "Organization", "name": o}
                        for o in dict.fromkeys(organisations)
                    ]
                }
                if organisations
                else {}
            ),
        },
        body=body,
        index=bool(name and path),
    )


def _chamber(props: dict[str, Any], key: str) -> str:
    """``EK`` for a faction or committee of the Eerste Kamer, else ``TK``."""
    return "EK" if props.get("chamber") == "EK" or key.startswith("ek_") else "TK"


def faction_title(props: dict[str, Any], key: str) -> str:
    """``D66, fractie in de Tweede Kamer``; ``D66-fractie in de Eerste Kamer`` (its name as
    its page writes it)."""
    if _chamber(props, key) == "EK":
        name = _text(props.get("name")) or _text(props.get("abbreviation")) or key
        return f"{name} in de Eerste Kamer"
    name = _text(props.get("abbreviation")) or _text(props.get("name")) or key
    return f"{name}, fractie in de Tweede Kamer"


def _role(meta: Any) -> str:
    meta = meta if isinstance(meta, dict) else {}
    role = _text(meta.get("role"))
    if meta.get("substitute"):
        return f"plaatsvervangend lid{', ' + role if role else ''}"
    return role


def _members(rows: list[dict[str, Any]]) -> str:
    return _list(
        [
            _member_link(r)
            + (f", {escape(_role(r.get('meta')))}" if _role(r.get("meta")) else "")
            for r in rows
            if _text(r.get("name"))
        ]
    )


def faction_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    title = faction_title(props, key)
    path = path_of(row["id"], props) or ""
    name = _text(props.get("name"))
    abbreviation = _text(props.get("abbreviation"))
    ek = _chamber(props, key) == "EK"
    active = _period(props.get("active_from"), props.get("active_until"))
    description = ", ".join(
        part
        for part in (
            name
            + (f" ({abbreviation})" if abbreviation and abbreviation != name else ""),
            "fractie in de Eerste Kamer" if ek else "fractie in de Tweede Kamer",
            f"actief {active}" if active else "",
        )
        if part
    )
    seats = props.get("seats")
    board = [b for b in props.get("board") or [] if isinstance(b, dict)]
    board_items = [
        ", ".join(
            p
            for p in (
                escape(_text(b.get("function"))),
                escape(_text(b.get("name"))),
            )
            if p
        )
        for b in board
    ]
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(name)}</p>" if name and name not in title else "")
        + (f"<p>Actief {escape(active)}</p>" if active else "")
        + (
            f"<p>Zetels: {seats}</p>"
            if isinstance(seats, int) and not isinstance(seats, bool) and seats
            else ""
        )
        + _section("Fractiebestuur", _list(board_items))
        + _section("Leden", _members(row.get("members") or []))
        + (
            f'<p><a href="{escape(_text(props.get("url")))}">De fractie op '
            "eerstekamer.nl</a></p>"
            if ek and _text(props.get("url")).startswith("https://")
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
            **({"alternateName": abbreviation} if abbreviation else {}),
            "parentOrganization": {
                "@type": "GovernmentOrganization",
                "name": EK if ek else TK,
            },
        },
        body=body,
        index=bool(name or abbreviation),
    )


def cabinet_name(props: dict[str, Any], key: str) -> str:
    """``Kabinet-Rutte IV``: the name as Rijksoverheid writes it, with a capital."""
    name = _text(props.get("name")) or key.replace("_", " ")
    return name[:1].upper() + name[1:]


def cabinet_title(props: dict[str, Any], key: str) -> str:
    """``Kabinet-Rutte IV (2022–2024)``."""
    name = cabinet_name(props, key)
    years = _years(props.get("from_date"), props.get("to_date"))
    return f"{name} ({years})" if years else name


def cabinet_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    name = cabinet_name(props, key)
    title = cabinet_title(props, key)
    path = path_of(row["id"], props) or ""
    period = _period(props.get("from_date"), props.get("to_date"))
    factions = row.get("factions") or []
    parties = [
        _text(p.get("short")) for p in props.get("parties") or [] if isinstance(p, dict)
    ]
    parties = [p for p in parties if p] or [n for _, n in factions]
    pm = row.get("prime_minister") or {}
    description = ", ".join(
        part
        for part in (
            name,
            period,
            ", ".join(parties),
            f"minister-president {_text(pm.get('name'))}" if pm.get("name") else "",
        )
        if part
    )
    phases = _list(
        [
            escape(
                ", ".join(
                    p
                    for p in (
                        _text(ph.get("label")) or _text(ph.get("kind")),
                        _period(ph.get("from_date"), ph.get("to_date")),
                    )
                    if p
                )
            )
            for ph in props.get("phases") or []
            if isinstance(ph, dict)
        ]
    )
    served = _list(
        [
            _member_link(m)
            + (
                ": "
                + escape(
                    "; ".join(
                        dict.fromkeys(
                            _text(p.get("function"))
                            for p in m["posts"]
                            if isinstance(p, dict) and _text(p.get("function"))
                        )
                    )
                )
                if isinstance(m.get("posts"), list) and m["posts"]
                else ""
            )
            for m in row.get("served") or []
            if _text(m.get("name"))
        ]
    )
    previous = row.get("previous")
    before = (
        _link(
            path_of(f"cabinets/{previous[0]}"),
            cabinet_name({"name": previous[1]}, previous[0]),
        )
        if previous
        else ""
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(period[:1].upper() + period[1:])}</p>" if period else "")
        + (f"<p>Minister-president: {_member_link(pm)}</p>" if pm.get("name") else "")
        + (f"<p>Vorig kabinet: {before}</p>" if before else "")
        + _section(
            "Partijen",
            _list([_link(path_of(f"factions/{k}"), n) for k, n in factions]),
        )
        + _section("Fasen", phases)
        + _section("Bewindspersonen", served)
    )
    return Page(
        title=title,
        description=cut(description or title, DESCRIPTION_MAX),
        path=path,
        crumbs=[(title, path)],
        data={
            "@type": "GovernmentOrganization",
            "name": name,
            **({"foundingDate": props["from_date"]} if props.get("from_date") else {}),
            **({"dissolutionDate": props["to_date"]} if props.get("to_date") else {}),
        },
        body=body,
    )


def committee_title(props: dict[str, Any], key: str) -> str:
    """``Vaste commissie voor Sociale Zaken en Werkgelegenheid (SZW)``, with ``, Eerste
    Kamer`` for one of the Eerste Kamer."""
    name = _text(props.get("title")) or _text(props.get("name")) or key
    abbreviation = _text(props.get("abbreviation"))
    title = (
        f"{name} ({abbreviation})"
        if abbreviation and abbreviation not in name
        else name
    )
    return f"{title}, Eerste Kamer" if _chamber(props, key) == "EK" else title


def committee_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    key = row["key"]
    title = committee_title(props, key)
    path = path_of(row["id"], props) or ""
    ek = _chamber(props, key) == "EK"
    name = _text(props.get("title")) or _text(props.get("name")) or key
    kind = _text(props.get("kind"))
    active = _period(props.get("started_on"), props.get("ended_on"))
    description = ", ".join(
        part
        for part in (
            name,
            kind if kind and kind.lower() not in name.lower() else "",
            "Eerste Kamer" if ek else "Tweede Kamer",
            f"actief {active}" if active else "",
        )
        if part
    )
    url = _text(props.get("url"))
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{escape(kind)}</p>" if kind else "")
        + (f"<p>Actief {escape(active)}</p>" if active else "")
        + _section("Leden", _members(row.get("members") or []))
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
            **(
                {"alternateName": props["abbreviation"]}
                if props.get("abbreviation")
                else {}
            ),
            "parentOrganization": {
                "@type": "GovernmentOrganization",
                "name": EK if ek else TK,
            },
        },
        body=body,
        index=bool(_text(props.get("name")) or _text(props.get("title"))),
    )


# The page of each kind of address that has one; the others get the shell.
PAGES = {
    "wet": law_page,
    "artikel": article_page,
    "uitspraak": judgment_page,
    "kamerstuk": paper_page,
    "dossier": dossier_page,
    "lid": member_page,
    "fractie": faction_page,
    "kabinet": cabinet_page,
    "commissie": committee_page,
}


def title_of(node_id: str, props: dict[str, Any]) -> tuple[str, str]:
    """The title and description of a node from its own props alone, as its page has them
    (without what a page reads beside them: the outcome of a motion, the counts of an
    article): what the SPA shows when it opens a node in the app."""
    collection, _, key = node_id.partition("/")
    if collection == "instruments":
        name = law_name(props) or _text(props.get("display_name"))
        since = _day(props.get("date_in_force"))
        return name, cut(
            f"{name}, geldend sinds {since}" if since else name, DESCRIPTION_MAX
        )
    if collection == "articles":
        law = {
            "bwb_id": props.get("bwb_id"),
            "short_title": props.get("instrument_abbreviation"),
            "citation_title": props.get("instrument_citation_title"),
        }
        title = article_title(props, law)
        return title, cut(_text(props.get("text")) or title, DESCRIPTION_MAX)
    if collection == "judgments":
        light = {**props, "date": props.get("date") or props.get("date_eff")}
        title = judgment_title(light, node_id)
        return title, cut(_text(props.get("summary")) or title, DESCRIPTION_MAX)
    if collection == "documents":
        row = {"subject": props.get("subject"), "kind": props.get("kind")}
        title = paper_title(row, props, [])
        return title, cut(title, DESCRIPTION_MAX)
    if collection == "dossiers":
        title = dossier_title(props, key)
        return title, cut(_text(props.get("title")) or title, DESCRIPTION_MAX)
    if collection == "members":
        title = member_title(props) or _text(props.get("display_name")) or key
        return title, cut(title, DESCRIPTION_MAX)
    if collection == "factions":
        title = faction_title(props, key)
        return title, cut(title, DESCRIPTION_MAX)
    if collection == "cabinets":
        title = cabinet_title(props, key)
        return title, cut(title, DESCRIPTION_MAX)
    if collection == "committees":
        title = committee_title(props, key)
        return title, cut(title, DESCRIPTION_MAX)
    name = _text(props.get("display_name")) or _text(props.get("name")) or key
    return name, cut(name, DESCRIPTION_MAX)
