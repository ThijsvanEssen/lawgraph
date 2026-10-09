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
    counts = row.get("counts") or {}
    cited = int(counts.get("judgments") or 0) + int(counts.get("papers") or 0)
    description = cut(text, DESCRIPTION_MAX - 40) if text else title
    if cited:
        description = f"{description} Met {cited} uitspraken en Kamerstukken."
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


# The page of each kind of address that has one; the others get the shell.
PAGES = {
    "wet": law_page,
    "artikel": article_page,
    "uitspraak": judgment_page,
    "kamerstuk": paper_page,
    "dossier": dossier_page,
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
    name = _text(props.get("display_name")) or _text(props.get("name")) or key
    return name, cut(name, DESCRIPTION_MAX)
