"""The title of each kind of source, from its props (pure): the server HTML, the API (``title``
of a node, ``api/schemas/nodes.py``) and the app show the same one."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from lawgraph.config.constants import (
    RELATION_AMENDS,
    RELATION_ESTABLISHES,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
)
from lawgraph.core.code_families import book_of, cited_number, family_of
from lawgraph.core.dossier_names import dossier_own_name
from lawgraph.core.dossier_numbers import official_number
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.ecli import ecli_of_key
from lawgraph.core.judgment_cite import cite_of
from lawgraph.core.models import key_of, parse_node_id
from lawgraph.core.publications import (
    koop_citation,
    official_of_instrument_key,
    official_of_note_key,
    own_title,
    parse_koop_id,
)
from lawgraph.core.tk_records.kinds import is_motion_or_amendment
from lawgraph.core.votes import vote_outcome


def text_of(value: Any) -> str:
    """*value* stripped when it is a string, else empty."""
    return value.strip() if isinstance(value, str) else ""


def joined(separator: str, *parts: str) -> str:
    """The parts that say something, joined by *separator*."""
    return separator.join(part for part in parts if part)


def years(start: Any, end: Any) -> str:
    """``2022–2024``, or ``2024–`` while it lasts."""
    first, last = text_of(start)[:4], text_of(end)[:4]
    if not first:
        return ""
    return f"{first}–{last}" if last != first else first


# ── laws and articles ─────────────────────────────────────────────────────────


def law_name(props: dict[str, Any]) -> str:
    """``Opiumwet (Ow)``: the citation title, its short title after it; a book of a code as
    it is cited, ``Boek 6 BW``."""
    bwb_id = text_of(props.get("bwb_id"))
    family, book = family_of(bwb_id), book_of(bwb_id)
    if family and book:
        return f"Boek {book} {family}"
    name = text_of(props.get("citation_title")) or text_of(props.get("title"))
    short = text_of(props.get("short_title"))
    return f"{name} ({short})" if short and short.lower() not in name.lower() else name


def law_short(props: dict[str, Any] | None) -> str:
    """How an article cites its law: ``BW`` for a book of the Burgerlijk Wetboek, else its
    short title, else its citation title."""
    props = props or {}
    return (
        family_of(text_of(props.get("bwb_id")))
        or text_of(props.get("short_title"))
        or text_of(props.get("citation_title"))
        or text_of(props.get("title"))
    )


def article_name(bwb_id: str | None, number: str, law: str) -> str:
    """``Artikel 6:162 BW``."""
    cited = cited_number(bwb_id, number)
    return f"Artikel {cited} {law}".strip()


def version_title(props: dict[str, Any]) -> str:
    """``Grondwet, geldend van 21 maart 2002 tot 8 februari 2005``: a version of a law by the
    citation title of its law (``instrument_citation_title``, which the node route adds) and
    the days it held; ``geldend vanaf`` for the current one."""
    name = text_of(props.get("instrument_citation_title")) or text_of(
        props.get("bwb_id")
    )
    since = long_date(props.get("valid_from"))
    until = long_date(props.get("valid_until"))
    if since and until:
        return f"{name}, geldend van {since} tot {until}"
    return f"{name}, geldend vanaf {since}" if since else name


def article_title(props: dict[str, Any], law: dict[str, Any] | None) -> str:
    """``Art. 6:162 BW, Onrechtmatige daad``: as an article is cited, with what it is
    about, its heading or else its ``caption`` (the title of the division it stands in,
    ``semantic bwb-captions``)."""
    number = text_of(props.get("article_number"))
    name = (
        f"Art. {cited_number(text_of(props.get('bwb_id')) or None, number)} "
        f"{law_short(law)}".strip()
        if number
        else text_of(props.get("display_name"))
    )
    about = text_of(props.get("heading")) or text_of(props.get("caption"))
    return f"{name}, {about[:1].upper()}{about[1:]}" if about else name


def annex_title(props: dict[str, Any], law: dict[str, Any] | None) -> str:
    """``Bijlage II Opiumwet: lijst II``, with its title when it has one."""
    name = joined(" ", "Bijlage", text_of(props.get("label")), law_short(law))
    title = text_of(props.get("title"))
    return f"{name}: {title[:1].lower()}{title[1:]}" if title else name


# ── judgments ─────────────────────────────────────────────────────────────────


def judgment_title(light: dict[str, Any], node_id: str) -> str:
    """``HR 20 december 2019 (Urgenda), ECLI:NL:HR:2019:2006``: as a lawyer cites it
    (``core.judgment_cite``), with the names it is known by, a translation said so."""
    ecli = text_of(light.get("ecli")) or ecli_of_key(key_of(node_id)) or ""
    cite = cite_of({**light, "ecli": ecli})
    if cite is None:
        return text_of(light.get("display_name"))
    names = [
        n.strip() for n in light.get("names") or [] if isinstance(n, str) and n.strip()
    ]
    head = f"{cite.short} ({', '.join(names)})" if names else cite.short
    translation = ", vertaling" if text_of(light.get("translation_of")) else ""
    return f"{head}{translation}, {ecli.upper()}"


# ── the records of the Kamer ──────────────────────────────────────────────────

# The kind a subject opens with ("Motie", "Gewijzigde motie", "Nader gewijzigd
# amendement") and the "van het lid" / "van de leden" after it.
_DOCUMENT_KIND = re.compile(
    r"^(?:(?:nader\s+)?gewijzigde?\s+)?(?:motie|amendement)\b", re.I
)
_OF_MEMBERS_AFTER = re.compile(r"^\s*van\s+(?:het\s+lid|de\s+leden)\s+", re.I)


def _motion_head(subject: str) -> tuple[str, str] | None:
    """``Motie van het lid Bolhuis over …`` as (``Motie``, ``Bolhuis over …``): the kind it
    opens with, and its submitters and subject without "van het lid"; None for a subject
    that opens with no kind."""
    match = _DOCUMENT_KIND.match(subject)
    if not match:
        return None
    rest = _OF_MEMBERS_AFTER.sub("", subject[match.end() :]).strip()
    return match[0].strip().capitalize(), rest


def document_title(row: dict[str, Any], light: dict[str, Any]) -> str:
    """``Motie 36496-71 Bolhuis over een AI-killswitch``: a motion or an amendment by its
    kind and number, then its submitters and its subject (its outcome, which a vote
    changes, is in the description); another paper ``<kind>: <subject> (36496-71)``."""
    dossier = text_of(light.get("dossier_number"))
    suffix = text_of(light.get("dossier_suffix"))
    number = light.get("sequence") or light.get("number")
    cite = (
        f"{dossier}{'-' + suffix if suffix else ''}-{number}"
        if dossier and number
        else ""
    )
    subject = text_of(row.get("subject")) or text_of(light.get("title"))
    kind = text_of(row.get("kind")) or text_of(light.get("kind"))
    if is_motion_or_amendment(kind):
        motion = _motion_head(subject)
        if not motion:
            return f"{kind} {cite}".strip() + (f" {subject}" if subject else "")
        head, rest = motion
        return f"{f'{head} {cite}'.strip()} {rest}".strip()
    head = (
        f"{kind}: {subject}"
        if kind and subject and not subject.startswith(kind)
        else subject or kind
    )
    return head + (f" ({cite})" if cite else "")


def dossier_title(props: dict[str, Any], key: str) -> str:
    """``36496 Wet betaalbare huur``, ``36600 VII Begroting Binnenlandse Zaken en
    Koninkrijksrelaties 2025``, ``36889 wijziging van Archiefwet 1995``: its number and the
    name it goes by (``core.dossier_names``, with its ``official_short`` where the props
    have it), else its title."""
    label = official_number(text_of(props.get("label")) or key)
    name = dossier_own_name(props) or text_of(props.get("title"))
    return f"{label} {name}" if name else f"Dossier {label}"


def case_title(props: dict[str, Any], key: str) -> str:
    """``Motie Bolhuis over een AI-killswitch (2025Z15468)``; another zaak by its title
    (``Brief van de tijdelijke commissie … (2025Z15468)``), its kind only when it has
    none: the kind is the source's category (``Brief van lid/fractie/commissie``), which
    the reader leaves out too."""
    number = text_of(props.get("number")) or key
    subject = text_of(props.get("title")) or text_of(props.get("citation_title"))
    kind = text_of(props.get("kind"))
    if is_motion_or_amendment(kind):
        motion = _motion_head(subject)
        head = joined(" ", *motion) if motion else subject or kind
    else:
        head = subject or kind or "Zaak"
    return f"{head} ({number})"


def activity_title(props: dict[str, Any], key: str) -> str:
    """``Wetgevingsoverleg van 23 maart 2026: Cyberbeveiligingswet (36764)``: its kind and
    day, then its subject; ``Activiteit 2026A01323`` without either."""
    kind = text_of(props.get("kind"))
    subject = text_of(props.get("agenda_title"))
    head = joined(" van ", kind, long_date(props.get("date")))
    if head and subject and subject != kind:
        return f"{head}: {subject}"
    return head or subject or f"Activiteit {text_of(props.get('number')) or key}"


def commitment_title(props: dict[str, Any], key: str) -> str:
    """``Toezegging TZ202609-124: <its text>`` (cut with the rest of the title)."""
    number = text_of(props.get("number")) or key
    text = text_of(props.get("text"))
    return f"Toezegging {number}: {text}" if text else f"Toezegging {number}"


def decision_outcome(props: dict[str, Any]) -> str:
    """``aangenomen`` or ``verworpen``; the result of the Eerste Kamer as its page writes
    it; else what was decided (``uitstellen``), as the Kamer writes it."""
    outcome = vote_outcome(props.get("passed"))
    if outcome:
        return outcome
    result = text_of(props.get("result"))
    if result:
        return result
    kind = text_of(props.get("decision_kind"))
    return kind.split(" - ", 1)[1] if " - " in kind else kind


def decision_title(props: dict[str, Any]) -> str:
    """``Stemming over <subject>, 8 september 2026: aangenomen``."""
    subject = text_of(props.get("subject")) or text_of(props.get("agenda_item_subject"))
    day, outcome = long_date(props.get("date")), decision_outcome(props)
    head = f"Stemming over {subject}" if subject else "Stemming"
    head = f"{head}, {day}" if day else head
    return f"{head}: {outcome}" if outcome else head


# ── members, factions, cabinets and committees ────────────────────────────────


def member_name(props: dict[str, Any]) -> str:
    return (
        text_of(props.get("name"))
        or text_of(props.get("full_name"))
        or text_of(props.get("display_name"))
    )


def _own(name: str, faction: str) -> str:
    """*faction*, unless it is named after the member *name* (a group of one: ``Lid
    Keijzer``, ``Groep Markuszower``), which says the name again: then nothing, as the
    explorer leaves it out (``eigenFractie``)."""
    surname = (name.split() or [""])[-1].lower()
    words = re.split(r"[\s-]+", faction.lower())
    return "" if surname and surname in words else faction


def member_role(props: dict[str, Any]) -> str:
    """What a member is now, in the words of the source: the post they hold in a cabinet
    as the source names it, else a seat in a chamber; ``oud-Kamerlid`` only for one whose
    seats in the Tweede Kamer all ended; nothing for anyone else."""
    posts = [f for f in props.get("government_functions") or [] if isinstance(f, dict)]
    held = [f for f in posts if not f.get("to_date") and text_of(f.get("function"))]
    if held:
        return text_of(held[-1].get("function"))
    seats = [m for m in props.get("faction_memberships") or [] if isinstance(m, dict)]
    now = [m for m in seats if not m.get("to_date")]
    name = member_name(props)
    if now:
        party = _own(
            name, text_of(now[-1].get("abbreviation")) or text_of(now[-1].get("name"))
        )
        return f"Tweede Kamerlid ({party})" if party else "Tweede Kamerlid"
    ek = props.get("ek") if isinstance(props.get("ek"), dict) else {}
    if ek and not ek.get("observed_until"):
        party = _own(name, text_of(ek.get("abbreviation")))
        return f"Eerste Kamerlid ({party})" if party else "Eerste Kamerlid"
    if seats and all(m.get("to_date") for m in seats):
        return "oud-Kamerlid"
    return ""


def member_title(props: dict[str, Any]) -> str:
    """``Rob Jetten, Minister-president``: the name, and what they are now when known."""
    name, role = member_name(props), member_role(props)
    return f"{name}, {role}" if name and role else name


def chamber(props: dict[str, Any], key: str) -> str:
    """``EK`` for a faction or committee of the Eerste Kamer, else ``TK``."""
    return "EK" if props.get("chamber") == "EK" or key.startswith("ek_") else "TK"


def faction_title(props: dict[str, Any], key: str) -> str:
    """``D66, fractie in de Tweede Kamer``; ``D66-fractie in de Eerste Kamer`` (its name as
    its page writes it)."""
    if chamber(props, key) == "EK":
        name = text_of(props.get("name")) or text_of(props.get("abbreviation")) or key
        return f"{name} in de Eerste Kamer"
    name = text_of(props.get("abbreviation")) or text_of(props.get("name")) or key
    return f"{name}, fractie in de Tweede Kamer"


def cabinet_name(props: dict[str, Any], key: str) -> str:
    """``Kabinet-Rutte IV``: the name as Rijksoverheid writes it, with a capital."""
    name = text_of(props.get("name")) or key.replace("_", " ")
    return name[:1].upper() + name[1:]


def cabinet_title(props: dict[str, Any], key: str) -> str:
    """``Kabinet-Rutte IV (2022–2024)``."""
    name = cabinet_name(props, key)
    span = years(props.get("from_date"), props.get("to_date"))
    return f"{name} ({span})" if span else name


def committee_title(props: dict[str, Any], key: str) -> str:
    """``Vaste commissie voor Sociale Zaken en Werkgelegenheid (SZW)``, with ``, Eerste
    Kamer`` for one of the Eerste Kamer."""
    name = text_of(props.get("title")) or text_of(props.get("name")) or key
    abbreviation = text_of(props.get("abbreviation"))
    title = (
        f"{name} ({abbreviation})"
        if abbreviation and abbreviation not in name
        else name
    )
    return f"{title}, Eerste Kamer" if chamber(props, key) == "EK" else title


# What a publication or its nota van toelichting does to a regulation, in the words the app
# writes it with (``verbonden/hoe.ts`` of the explorer).
RELATION_VERBS = {
    RELATION_ESTABLISHES: "stelt vast",
    RELATION_INTRODUCES: "voegt in",
    RELATION_AMENDS: "wijzigt",
    RELATION_REPEALS: "trekt in",
    RELATION_EXPLAINS: "licht toe",
}


# ── publications ──────────────────────────────────────────────────────────────


def _publication_name(props: dict[str, Any], note: dict[str, Any], key: str) -> str:
    """``Stb. 2026, 94``: the name the BWB gives it, else made of its identifier."""
    name = text_of(props.get("citation_title"))
    if name:
        return name
    official = text_of(note.get("identifier")) or official_of_note_key(key)
    return koop_citation(official) or official


def publication_title(props: dict[str, Any], note: dict[str, Any], key: str) -> str:
    """``Stb. 2026, 94: Besluit van … tot wijziging van …``; the name alone without one."""
    name, title = _publication_name(props, note, key), own_title(note.get("title"))
    return f"{name}: {title}" if title else name


# ── the title of a node ───────────────────────────────────────────────────────

# The title of a node of each collection from its props and key.
_TITLED: dict[str, Callable[[dict[str, Any], str], str]] = {
    "instrument_versions": lambda props, key: version_title(props),
    "cases": case_title,
    "factions": faction_title,
    "cabinets": cabinet_title,
    "committees": committee_title,
    "decisions": lambda props, key: decision_title(props),
    "activities": activity_title,
    "documents": lambda props, key: document_title(
        {"subject": props.get("subject"), "kind": props.get("kind")}, props
    ),
    "dossiers": dossier_title,
    "commitments": commitment_title,
}


def law_of(props: dict[str, Any]) -> dict[str, Any]:
    """The law of an article or an annex as its own props name it."""
    return {
        "bwb_id": props.get("bwb_id"),
        "short_title": props.get("instrument_abbreviation"),
        "citation_title": props.get("instrument_citation_title"),
    }


def publication_of(key: str, props: dict[str, Any]) -> str | None:
    """``stb-2025-263``: the publication an instrument of *key* is; None for a regulation."""
    official = text_of(props.get("official_id")) or official_of_instrument_key(key)
    return official if parse_koop_id(official) else None


def title_of(
    node_id: str,
    props: dict[str, Any],
    law: dict[str, Any] | None = None,
    note: dict[str, Any] | None = None,
) -> str:
    """The title of a node from its own props alone, as its page has it (without what a
    page reads beside them: the outcome of a motion): ``title`` of a node in the API and
    the ``<title>`` of its page. *law*: of an article or an annex, its law as its page
    reads it (``seo.law_of``); *note*: of a publication, its nota van toelichting
    (``seo.note_of``), so that both name it alike."""
    collection, key = parse_node_id(node_id)
    if collection in _TITLED:
        return _TITLED[collection](props, key)
    if collection == "instruments":
        if official := publication_of(key, props):
            return publication_title(
                props, {"identifier": official, **(note or {})}, key
            )
        return law_name(props) or text_of(props.get("display_name"))
    if collection == "articles":
        return article_title(props, law or law_of(props))
    if collection == "annexes":
        return annex_title(props, law or law_of(props))
    if collection == "judgments":
        light = {**props, "date": props.get("date") or props.get("date_eff")}
        return judgment_title(light, node_id)
    if collection == "members":
        return member_title(props) or text_of(props.get("display_name")) or key
    return text_of(props.get("display_name")) or text_of(props.get("name")) or key
