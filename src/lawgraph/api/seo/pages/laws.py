"""The pages of a law (of the BWB, an EU act, or a law of the Staatsblad the BWB does not
hold yet), an article and an annex."""

from __future__ import annotations

from html import escape
from typing import Any

from lawgraph.api.schemas.articles import ArticleVersionListedDTO
from lawgraph.api.schemas.common import PublicationDTO
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
from lawgraph.core.bwb_xml import article_label
from lawgraph.core.code_families import book_of, family_of
from lawgraph.core.dossier_numbers import official_number
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
from lawgraph.core.publications import koop_citation, law_key
from lawgraph.core.readable_paths import STB_LAW, path_of
from lawgraph.core.staatsblad_laws import STATUS_ENACTED


def _law_id(props: dict[str, Any]) -> tuple[str, str]:
    """The id a law is known by and its jurisdiction: its BWB id (NL), else the CELEX
    number of an EU act (EU), else the Staatsblad publication that enacted a law the BWB
    does not hold (yet) (NL, ``STB-2026-56``)."""
    bwb = text_of(props.get("bwb_id"))
    if bwb:
        return bwb, "NL"
    celex = text_of(props.get("celex"))
    if celex:
        return celex, "EU"
    official = text_of(props.get("official_id"))
    return (official.upper(), "NL") if official else ("", "EU")


def _law_node(law_id: str) -> str:
    """The node of the law *law_id* (``_law_id``)."""
    key = law_key(law_id.lower()) if STB_LAW.match(law_id) else law_id.lower()
    return node_id(COLLECTION_INSTRUMENTS, key)


def _article_law(law_id: str, eu: bool) -> dict[str, str]:
    """What the address of an article of the law *law_id* is made of besides its number."""
    if STB_LAW.match(law_id):
        return {"official_id": law_id.lower()}
    return {"celex" if eu else "bwb_id": law_id}


def _enacted(props: dict[str, Any]) -> str:
    """ "Vastgesteld, nog niet in werking (Stb. 2026, 56)" of a law of the Staatsblad the
    BWB does not hold (yet); empty for any other law."""
    if props.get("status") != STATUS_ENACTED:
        return ""
    cited = koop_citation(text_of(props.get("official_id")))
    return "Vastgesteld, nog niet in werking" + (f" ({cited})" if cited else "")


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


def _searched(props: dict[str, Any], name: str) -> str:
    """The name the description of a law opens with, with the abbreviation lawyers search
    it by (its title stays the one of the API, ``title_of``, which the app shows):
    ``Burgerlijk Wetboek Boek 7 (BW 7)`` for a book of a code; *name* with the abbreviation
    an EU act is cited by (``abbreviation``, kept by hand: ``Algemene verordening
    gegevensbescherming (AVG)``); else *name*, which has it already
    (``Cyberbeveiligingswet (Cbw)``, ``law_name``)."""
    bwb_id = text_of(props.get("bwb_id"))
    family, book = family_of(bwb_id), book_of(bwb_id)
    full = text_of(props.get("citation_title"))
    if family and book and full:
        return f"{full} ({family} {book})"
    abbreviation = text_of(props.get("abbreviation"))
    if abbreviation and abbreviation.lower() not in name.lower():
        return f"{name} ({abbreviation})"
    return name


def law_page(row: dict[str, Any]) -> Page:
    """A law of the BWB, an EU act or a law of the Staatsblad: its articles; an EU act also
    its whole title and its text on EUR-Lex, a law of the Staatsblad its status and its
    publication in its name (as the law of the BWB of the same name has none). An EU act
    whose text was not read (no articles) is not indexed: its title is all there is."""
    props = row["props"] or {}
    law_id, jurisdiction = _law_id(props)
    law_id = law_id or row["key"].upper()
    eu = jurisdiction == "EU"
    enacted = _enacted(props)
    name = (
        (text_of(props.get("display_name")) if enacted else "")
        or law_name(props)
        or text_of(props.get("display_name"))
        or law_id
    )
    path = path_of(row["id"], props) or f"/wetten/{law_id}"
    since = long_date(props.get("date_in_force"))
    count = len(row["articles"])
    # an EU act by its whole title: what it is about ("NIS 2-richtlijn") is in it alone
    full = text_of(props.get("title")) if eu else ""
    searched = _searched(props, name)
    description = joined(
        ", ",
        full or searched,
        enacted[:1].lower() + enacted[1:],
        f"geldend sinds {since}" if since else "",
        f"{count} artikelen" if count else "",
    )
    short = law_short(props)
    article_law = _article_law(law_id, eu)
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
        + (f"<p>{escape(enacted)}.</p>" if enacted else "")
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
        citation=present(
            citation_title=name,
            citation_date=text_of(props.get("date_in_force")).replace("-", "/"),
            **{"DC.identifier": law_id},
        ),
    )


# The changes of an article its page lists, the newest first: all of 99 in 100 (p99 6,
# lawgraph_small 30 Oct); the rest are counted.
HISTORY = 10
# The length the title of a dossier of a change is cut to, without a short title of its own.
DOSSIER_TITLE_MAX = 80
# What a version did to the article (``change``), as its line says it.
_CHANGE_WORDS = {
    "establishes": "vastgesteld",
    "introduces": "ingevoegd",
    "amends": "gewijzigd",
    "repeals": "vervallen",
    "republishes": "opnieuw geplaatst",
}


def _publication(publication: PublicationDTO) -> str:
    """ "Stb. 2023, 123" (to the publication), then each Kamerstukdossier it came from by
    its short title: to its page when the data holds it, else its number alone."""
    label = (
        koop_citation(publication.id or "")
        or joined(
            " ",
            publication.kind or "",
            joined(", ", str(publication.year or ""), publication.number or ""),
        )
        or "publicatie"
    )
    dossiers = [
        link(
            d.path,
            joined(
                ", ",
                f"Kamerstukken {official_number(d.number)}",
                d.short_title or cut(d.title or "", DOSSIER_TITLE_MAX),
            ),
        )
        for d in publication.dossiers
    ]
    return ", ".join([link(publication.official_url, label), *dossiers])


def _change_line(version: ArticleVersionListedDTO, first: bool) -> str:
    """ "1 januari 2024: gewijzigd bij Stb. 2023, 123, Kamerstukken 36 123 …"; a version
    without its publication says so."""
    word = _CHANGE_WORDS.get(version.change or "", "geldend" if first else "gewijzigd")
    head = joined(": ", escape(long_date(version.valid_from)), word)
    if version.amended_by is None:
        return f"{head}, publicatie niet bekend"
    return f"{head} bij {_publication(version.amended_by)}"


def _changes(
    versions: list[ArticleVersionListedDTO] | None,
) -> list[ArticleVersionListedDTO]:
    """The versions that changed the text of an article after its first, newest first."""
    return [v for v in (versions or [])[1:] if v.text_changed][::-1]


def _history(versions: list[ArticleVersionListedDTO] | None) -> str:
    """Its changes, newest first, and the first version the BWB holds, ``HISTORY`` at
    most; an article without a change since says so (not "never": the history begins at
    the oldest version the BWB gives). Empty without versions: no block."""
    if not versions:
        return ""
    lines = _changes(versions) + [versions[0]]
    shown = [_change_line(v, v is versions[0]) for v in lines[:HISTORY]]
    since = long_date(versions[0].valid_from)
    unchanged = len(lines) == 1 and since
    more = len(lines) - HISTORY
    return (
        (f"<p>Sinds {escape(since)} niet gewijzigd.</p>" if unchanged else "")
        + bullets(shown)
        + (
            f"<p>En {more} eerdere " + ("versie" if more == 1 else "versies") + ".</p>"
            if more > 0
            else ""
        )
    )


def _changed_by(versions: list[ArticleVersionListedDTO] | None) -> list[dict[str, Any]]:
    """The publications that changed an article as its page lists them, as legislation
    that changes it (JSON-LD, ``@reverse``)."""
    return [
        {
            "@type": "Legislation",
            "name": koop_citation(v.amended_by.id or "") or v.amended_by.id,
            **present(url=v.amended_by.official_url),
        }
        for v in _changes(versions)[:HISTORY]
        if v.amended_by is not None and v.amended_by.id
    ]


def _delegated(rows: list[dict[str, Any]] | None, path: str) -> str:
    """The regulations based on an article its page names (``CHAIN``), then how many more
    there are, to them in the app (its Verbonden of ``BASED_ON``)."""
    if not rows:
        return ""
    more = rows[0]["listed"] - len(rows)
    rest = link(
        f"{path}?relatie=BASED_ON",
        f"En {more} andere " + ("regeling" if more == 1 else "regelingen"),
    )
    return bullets(
        [link(path_of(r["id"], r["props"]), _regulation(r)) for r in rows]
    ) + (f"<p>{rest}</p>" if more > 0 else "")


def _regulation(row: dict[str, Any]) -> str:
    props = row["props"] or {}
    return law_name(props) or text_of(props.get("display_name")) or row["id"]


def _based_on(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The regulations based on an article as legislation based on it (JSON-LD,
    ``@reverse``: it is the regulation that ``isBasedOn`` the article)."""
    return [
        {
            "@type": "Legislation",
            "name": _regulation(r),
            **present(legislationIdentifier=text_of((r["props"] or {}).get("bwb_id"))),
        }
        for r in rows or []
    ]


def _counted(count: int, one: str, more: str) -> str:
    """ "312 uitspraken", "1.194 uitspraken", "1 uitspraak"; empty for none."""
    if not count:
        return ""
    return f"{count:,}".replace(",", ".") + " " + (one if count == 1 else more)


def _article_description(text: str, counts: dict[str, Any], explained: bool) -> str:
    """The description of an article: the start of its text, then what the page has
    besides (``Met 312 uitspraken, wetsgeschiedenis en 45 verwijzingen.``), together at
    most ``DESCRIPTION_MAX``; only what there is (*counts*: ``seo_links.ARTICLE_COUNTS``)."""
    besides = [
        part
        for part in (
            _counted(counts.get("judgments_counted") or 0, "uitspraak", "uitspraken"),
            "wetsgeschiedenis" if explained else "",
            _counted(
                counts.get("references_counted") or 0, "verwijzing", "verwijzingen"
            ),
        )
        if part
    ]
    if not besides:
        return cut(text, DESCRIPTION_MAX)
    listed = (
        ", ".join(besides[:-1]) + " en " + besides[-1] if besides[1:] else besides[0]
    )
    tail = f"Met {listed}."
    return f"{cut(text, DESCRIPTION_MAX - len(tail) - 1)} {tail}"


def article_page(row: dict[str, Any]) -> Page:
    props = row["props"] or {}
    law = row.get("law") or {}
    title = article_title(props, law)
    path = path_of(row["id"], props) or ""
    text = text_of(props.get("text"))
    law_id, jurisdiction = _law_id(law or props)
    law_path = path_of(_law_node(law_id), law) if law else None
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
    versions, delegated = row.get("versions"), row.get("delegated")
    description = _article_description(
        text or title,
        row,
        bool(links.get("explained_by")) or bool(_changes(versions)),
    )
    body = (
        f"<h1>{escape(title)}</h1>"
        + (f"<p>{link(law_path, law_label)}</p>" if law_label else "")
        + paragraphs
        + section("Verwijst naar", source_links(links.get("refers_to") or []))
        + section(
            "Artikelen die hiernaar verwijzen",
            source_links(links.get("referred_by") or []),
        )
        + section("Uitgewerkt in", _delegated(delegated, path))
        + section("Toelichting", source_links(links.get("explained_by") or []))
        + section("Wetsgeschiedenis", _history(versions))
        + section("Uitspraken die dit artikel aanhalen", judgments)
        + section("Vorige artikelen", beside(row.get("before") or []))
        + section("Volgende artikelen", beside(row.get("after") or []))
    )
    return Page(
        title=title,
        description=description,
        path=path,
        crumbs=trail(law_label, law_path, title, path),
        data={
            "@type": "Legislation",
            "name": title,
            "legislationIdentifier": f"{law_id} "
            + article_label(text_of(props.get("article_number"))),
            "legislationJurisdiction": jurisdiction,
            **_part_of(law_label, law_id),
            **present(
                **{
                    "@reverse": present(
                        legislationChanges=_changed_by(versions),
                        isBasedOn=_based_on(delegated),
                    )
                }
            ),
        },
        body=body,
        index=bool(text) and not props.get("stub"),
        citation=present(
            citation_title=f"{title}, {law_label}" if law_label else title,
            **{
                "DC.identifier": f"{law_id} {article_label(text_of(props.get('article_number')))}"
            },
        ),
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
