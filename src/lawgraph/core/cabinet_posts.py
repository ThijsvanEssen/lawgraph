"""Who held which post in a cabinet, and when: the posts of a Rijksoverheid cabinet page.

A post is held in a **seat**: the ministry, the kind of post and, where the source names
one, the portfolio. ``minister van Infrastructuur en Waterstaat`` is one seat (``ienw/minister``),
``minister voor Buitenlandse Handel en Ontwikkelingshulp`` beside it another
(``bz/minister_zonder_portefeuille/buitenlandse-handel-en-ontwikkelingshulp``),
``staatssecretaris Rechtsbescherming`` another (``jenv/staatssecretaris/rechtsbescherming``).
The minister-president is minister of Algemene Zaken: one seat, ``az/minister-president``.
Every viceminister-president sits in the one shared seat ``viceminister-president``: a
cabinet has one per coalition partner.

``cabinet_posts`` turns the seats of a page (``core.rijksoverheid.parse_page``) into posts,
then applies the rules of a seat:

- **Dates.** A holder line without a start held the post from the start of the cabinet, one
  without an end until its end; ``from_date_source`` and ``to_date_source`` keep what the
  source gave (``None`` where it gave nothing).
- **One seat per heading.** The holders of one heading who follow one another hold one
  seat, the one the heading names, even where their own lines name the post otherwise (a
  portfolio renamed on the way: that name in ``also_named``); holders of one heading at the
  same time hold seats of their own.
- **Double listings.** Two posts of one person in one seat on the same days are one post; the
  other name is kept in ``also_named`` (``Minister-president, minister van Algemene Zaken``).
- **Ending at the successor, starting at the predecessor.** In a named seat, a post whose end
  the source does not give ends where the next holder begins; a post whose start the source
  does not give begins where a holder with a given end stopped (``Deze taken werden
  vervolgens opgedragen aan:``). ``corrected`` says which date was set so.
- **Unnamed seats.** Where the source names no portfolio (``Staatssecretarissen /
  Buitenlandse Zaken`` with two names, ``Minister zonder Portefeuille`` twice), it does not
  say which holder followed which: the holders are put in lanes by date, ``#2`` for the
  second one, and no date is changed.
- **Stand-ins.** A post is ``acting`` when the source says so (``acting_reason``
  ``source``, with its words in ``acting_basis``: ``a.i.``, ``tijdelijke voorziening: …``,
  ``beheer portefeuille overgenomen door de minister van …``), or when its holder held
  another seat through the whole period and the period ends where the next holder of the
  seat begins (``held_other_seat``, that seat in ``acting_other_seat``).
- **Overlaps.** Two holders of one named seat at the same time after these rules are not
  hidden: both get ``overlaps_with``.

A holder is a person by ``person_key``: initials and surname as written, which the
pipeline then matches to a member.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from lawgraph.core.ministries import (
    MINISTRY_BY_KEY,
    POST_DEPUTY_PRIME_MINISTER,
    POST_MINISTER,
    POST_MINISTER_WITHOUT_PORTFOLIO,
    POST_PRIME_MINISTER,
    POST_STATE_SECRETARY,
    classify_function,
    current_on,
    ministry_named,
    ministry_of,
)
from lawgraph.core.rijksoverheid import (
    DAY,
    SECTION_STATE_SECRETARIES,
    parse_date,
    parse_holder,
    split_name,
)

SEAT_DEPUTY = "viceminister-president"
SEAT_PRIME_MINISTER = "az/minister-president"
# A seat nobody held for longer than this inside the cabinet's period has a gap.
GAP_DAYS = 14

# Why a post is acting: the source says so, or the holder held another seat throughout.
ACTING_SOURCE = "source"
ACTING_HELD_OTHER_SEAT = "held_other_seat"
# What the source says, as ``acting_basis``.
BASIS_AI = "a.i."
BASIS_TEMPORARY = "tijdelijke voorziening"
BASIS_TAKEN_OVER = "beheer portefeuille overgenomen door de"

CORRECTED_BY_SUCCESSOR = "to_date: start of the next holder"
CORRECTED_BY_PREDECESSOR = "from_date: end of the previous holder"
CORRECTED_TO_CABINET = "clipped to the cabinet's period"


def slug(text: str | None) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return "-".join(re.findall(r"[a-z0-9]+", plain))


def person_key(name: str) -> str:
    """``stm hermans`` of ``Drs. S.Th.M. (Sophie) Hermans``: the initials and the surname,
    which is how Rijksoverheid names one person on every page."""
    parts = split_name(name)
    return f"{parts['letters']} {slug(parts['surname']).replace('-', ' ')}".strip()


# ── Headings ─────────────────────────────────────────────────────────────────

_DEPUTY = re.compile(r"^vice-?\s?minister-?\s?president", re.IGNORECASE)
_QUALIFIER = re.compile(
    rf"(?:,\s*|\(\s*)?\b(tot|vanaf|per|sinds|met ingang van)\s+({DAY})\s*\)?",
    re.IGNORECASE,
)
_BARE_QUALIFIER = re.compile(rf"\(\s*({DAY})\s*\)")
# Where a heading names a further post: ``, minister``, `` en minister``, ``, tevens minister``,
# `` en vanaf 11 okt. 1947 tevens minister``, ``; minister``.
_NEXT_PART = re.compile(
    rf"(?:,|;|\s+en)\s+(?=(?:(?:vanaf|tot|sinds|per)\s+{DAY}\s+)?(?:tevens\s+|ook\s+)?"
    r"(?:vice-?\s?)?minister\b)",
    re.IGNORECASE,
)
_RENAMED = re.compile(
    rf"\((?:vanaf|met ingang van)\s+{DAY}\s+(?:aangeduid met:\s*)?([^)]*)\)",
    re.IGNORECASE,
)
_CHARGED_WITH = re.compile(
    r"\(?\s*belast met\s+(?:de\s+|het\s+)?([^)]*)\)?", re.IGNORECASE
)
_MINISTRY_HINT = re.compile(r"\(([^()]*)\)\s*$")


def _qualifiers(text: str) -> tuple[str, str | None, str | None]:
    """*text* without its ``tot``/``vanaf`` days, and those days: ``(text, from, to)``."""
    start = end = None
    for match in _QUALIFIER.finditer(text):
        day = parse_date(match.group(2))
        if match.group(1).lower() == "tot":
            end = day
        else:
            start = day
    text = _QUALIFIER.sub(" ", text)
    bare = _BARE_QUALIFIER.search(text)
    if bare:
        start = parse_date(bare.group(1))
        text = _BARE_QUALIFIER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" ,.;"), start, end


def heading_parts(heading: str, section: str) -> list[dict[str, Any]]:
    """The posts a heading names: ``{function, also_named, portfolio, hint, from_date,
    to_date, renamed}``. ``Minister-president, minister van Algemene Zaken`` is two parts
    (one seat, merged later); ``Minister van Uniezaken en Overzeese Rijksdelen, vanaf 1 jan.
    1953 minister van Overzeese Rijksdelen`` is one, renamed."""
    if section == SECTION_STATE_SECRETARIES:
        text = heading.strip(" .")
        if not text.lower().startswith("staatssecretaris"):
            text = f"staatssecretaris van {text}"
        return [_part(text)]
    parts: list[dict[str, Any]] = []
    for raw in _NEXT_PART.split(heading.strip(" .")):
        renaming = bool(re.match(rf"^(?:vanaf|per)\s+{DAY}\s+minister", raw, re.I))
        part = _part(re.sub(r"^(?:tevens|ook)\s+", "", raw.strip(), flags=re.I))
        if (
            renaming
            and parts
            and parts[-1]["function"].lower().startswith("minister van")
        ):
            parts[-1]["also_named"].append(part["function"])
            continue
        parts.append(part)
    return parts


def _part(raw: str) -> dict[str, Any]:
    also: list[str] = []
    renamed = _RENAMED.search(raw)
    if renamed:
        also.append(renamed.group(1).strip())
        raw = _RENAMED.sub(" ", raw)
    text, start, end = _qualifiers(raw)
    text = re.sub(r"^(?:tevens|ook)\s+", "", text, flags=re.IGNORECASE)
    portfolio = None
    charged = _CHARGED_WITH.search(text)
    if charged:
        portfolio = charged.group(1).strip(" .")
        text = _CHARGED_WITH.sub(" ", text).strip()
    hint = None
    bracket = _MINISTRY_HINT.search(text)
    if bracket:
        hint = bracket.group(1).strip()
        text = text[: bracket.start()].strip()
    return {
        "function": re.sub(r"\s+", " ", text).strip(" ,."),
        "also_named": also,
        "portfolio": portfolio,
        "hint": hint,
        "from_date": start,
        "to_date": end,
    }


def seat_of(
    function: str, portfolio: str | None, hint: str | None, on: str | None
) -> dict[str, Any]:
    """``{seat, post, ministry, portfolio, named}`` of a post as its heading names it.

    ``named`` is false for a seat whose portfolio the source does not name (a
    staatssecretaris of a ministry, a minister without portfolio)."""
    plain = function.lower()
    if _DEPUTY.match(plain):
        return {
            "seat": SEAT_DEPUTY,
            "post": POST_DEPUTY_PRIME_MINISTER,
            "ministry": None,
            "portfolio": None,
            "named": True,
        }
    post, ministry = classify_function(function, on=on)
    if post == POST_MINISTER and ministry == "az" or post == POST_PRIME_MINISTER:
        return {
            "seat": SEAT_PRIME_MINISTER,
            "post": POST_PRIME_MINISTER,
            "ministry": "az",
            "portfolio": None,
            "named": True,
        }
    if hint:
        ministry = ministry_of(hint, on=on) or ministry
    if post == POST_MINISTER_WITHOUT_PORTFOLIO:
        own = re.sub(
            r"^minister\s+(?:voor|zonder portefeuille)\s*", "", function, flags=re.I
        ).strip()
        portfolio = portfolio or own or None
    elif post == POST_STATE_SECRETARY and portfolio is None:
        own = re.sub(
            r"^staatssecretaris\s*(?:van\s+|voor\s+)?", "", function, flags=re.I
        ).strip()
        if own and not ministry_named(own):
            portfolio = own
    elif post == POST_MINISTER:
        # ``Minister van Werk en Participatie``: a portfolio under a ministry, no ministry
        own = re.sub(r"^minister\s+van\s+", "", function, flags=re.I).strip()
        if not ministry_named(own):
            portfolio = own
    seat = f"{ministry or '-'}/{post or 'onbekend'}"
    if portfolio:
        seat = f"{seat}/{slug(portfolio)}"
    named = post == POST_MINISTER or (portfolio is not None)
    return {
        "seat": seat,
        "post": post,
        "ministry": ministry,
        "portfolio": portfolio,
        "named": named,
    }


# ── Posts of one page ────────────────────────────────────────────────────────


def _within(day: str | None, start: str, end: str | None) -> str | None:
    if day is None:
        return None
    if day < start:
        return start
    if end and day > end:
        return end
    return day


def _post(
    holder: dict[str, Any],
    period: dict[str, Any],
    part: dict[str, Any],
    cabinet: dict[str, Any],
    item: dict[str, Any],
    heading: tuple[int, int] = (0, 0),
) -> dict[str, Any]:
    start, end = cabinet["from_date"], cabinet["to_date"]
    temporary = item.get("temporary")
    given_from = (
        period["from_date"]
        or part["from_date"]
        or (temporary["from_date"] if temporary else None)
    )
    given_to = (
        period["to_date"]
        or part["to_date"]
        or (temporary["to_date"] if temporary else None)
    )
    from_date = _within(given_from, start, end) or start
    to_date = _within(given_to, start, end) or end
    corrected = []
    if (given_from and from_date != given_from) or (given_to and to_date != given_to):
        corrected.append(CORRECTED_TO_CABINET)
    own = (
        re.sub(r"^staatssecretaris\s+", "", holder["portfolio"], flags=re.I)
        if holder["portfolio"]
        else None
    )
    seat = seat_of(part["function"], own or part["portfolio"], part["hint"], from_date)
    acting_basis = None
    if holder["acting"]:
        acting_basis = BASIS_AI
    elif temporary:
        acting_basis = f"{BASIS_TEMPORARY}: {temporary['note']}"
    reason = ACTING_SOURCE if acting_basis else None
    return {
        **seat,
        "function": part["function"],
        "also_named": list(part["also_named"]),
        "name": holder["name"],
        "person": person_key(holder["name"]),
        "party": holder["party"],
        "from_date": from_date,
        "to_date": to_date,
        "from_date_source": given_from,
        "to_date_source": given_to,
        "ended": period.get("ended"),
        "corrected": corrected,
        "acting": acting_basis is not None,
        "acting_reason": reason,
        "acting_basis": acting_basis,
        "acting_other_seat": None,
        "absent": holder.get("absent"),
        "taken_over_by": holder.get("taken_over_by"),
        "overlaps_with": [],
        # where the post stands on the page, for ``_one_seat_per_heading``
        _HEADING: heading,
        _HEADING_SEAT: seat_of(
            part["function"], part["portfolio"], part["hint"], from_date
        ),
        _OWN_NAME: holder["portfolio"] if own else None,
    }


def _split_definitive(post: dict[str, Any], day: str | None) -> list[dict[str, Any]]:
    """An ``a.i.`` post that became ``definitief`` on *day*: acting until then."""
    if not day or not (post["from_date"] < day < (post["to_date"] or "9999")):
        return [post]
    acting = {**post, "to_date": day, "to_date_source": day}
    held = {
        **post,
        "from_date": day,
        "from_date_source": day,
        "acting": False,
        "acting_reason": None,
        "acting_basis": None,
        "acting_other_seat": None,
    }
    return [acting, held]


def _deputy(post: dict[str, Any], part: dict[str, Any] | None) -> dict[str, Any]:
    start = max(post["from_date"], (part or {}).get("from_date") or post["from_date"])
    return {
        **post,
        **seat_of("viceminister-president", None, None, start),
        "function": part["function"] if part else "viceminister-president",
        "also_named": [],
        "from_date": start,
        "from_date_source": (part or {}).get("from_date") or post["from_date_source"],
        "acting": False,
        "acting_reason": None,
        "acting_basis": None,
        "acting_other_seat": None,
        "taken_over_by": None,
    }


def page_posts(page: dict[str, Any], cabinet: dict[str, Any]) -> list[dict[str, Any]]:
    """Every post the seats of *page* name, before the rules of a seat: one per part of
    the heading, holder and period."""
    posts: list[dict[str, Any]] = []
    for n, item in enumerate(page["seats"]):
        parts = heading_parts(item["heading"], item["section"])
        deputies = [p for p in parts if _DEPUTY.match(p["function"])]
        offices = [p for p in parts if not _DEPUTY.match(p["function"])]
        for line in item["lines"]:
            holder = parse_holder(line)
            if holder is None:
                continue
            for period in holder["periods"]:
                held = [
                    post
                    for i, part in enumerate(offices)
                    for post in _split_definitive(
                        _post(holder, period, part, cabinet, item, (n, i)),
                        holder["until_acting"],
                    )
                ]
                if not held:
                    continue
                posts.extend(held)
                for part in deputies:
                    posts.append(_deputy(held[-1], part))
                if holder["also_deputy"]:
                    posts.append(_deputy(held[-1], None))
    return posts


# ── The rules of a seat ──────────────────────────────────────────────────────


def _days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["from_date"] < (b["to_date"] or "9999") and b["from_date"] < (
        a["to_date"] or "9999"
    )


# Where a post stands on the page: its heading, the seat the heading names and the name
# the holder's own line gives the post; dropped when the rules of a seat are done.
_HEADING = "_heading"
_HEADING_SEAT = "_heading_seat"
_OWN_NAME = "_own_name"


def _concurrent(posts: list[dict[str, Any]]) -> bool:
    """Whether two people among *posts* held them at the same time."""
    return any(
        a["person"] != b["person"] and _overlap(a, b)
        for i, a in enumerate(posts)
        for b in posts[i + 1 :]
    )


def _one_seat_per_heading(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A heading of the page names one seat, and a seat has one holder at a time. Where
    the holders of a heading follow one another but their own lines name the post
    otherwise (``Staatssecretaris Fiscaliteit, Belastingdienst en Douane``, held before as
    ``staatssecretaris Fiscaliteit en Belastingdienst``), or the ministry was renamed
    between them (Economische Zaken, Landbouw en Innovatie, Economische Zaken from 2013),
    they hold the seat the heading names on the day of the last of them, the name of their
    line in ``also_named``. Holders of one heading at the same time
    (two ministers without portfolio, two state secretaries of one ministry) hold seats of
    their own."""
    by_heading: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        if post["seat"] != SEAT_DEPUTY and post.get(_HEADING) is not None:
            by_heading[post[_HEADING]].append(post)
    for held in by_heading.values():
        if len({p["seat"] for p in held}) < 2 or _concurrent(held):
            continue
        # the seat as the heading names it on the day of its last holder: a ministry
        # renamed during the cabinet (ELI to EZ, 2013) names the seat by its later name
        target = max(held, key=lambda p: p["from_date"])[_HEADING_SEAT]
        for post in held:
            if post["seat"] == target["seat"]:
                continue
            own = post.get(_OWN_NAME)
            if own and own not in post["also_named"] and own != post["function"]:
                post["also_named"].append(own)
            post["seat"], post["named"] = target["seat"], target["named"]
    return posts


def _seats_by_their_last_name(
    posts: list[dict[str, Any]], cabinet: dict[str, Any]
) -> None:
    """A seat is named by the name its ministry had when the seat ended: a ministry renamed
    during the cabinet (Economische Zaken, Landbouw en Innovatie, named Economische Zaken
    from 1 January 2013) holds one seat, ``ez/minister``, however its posts began. Each post
    keeps the ``ministry`` of its own first day."""
    ends: dict[str, str] = {}
    for post in posts:
        end = post["to_date"] or cabinet.get("to_date") or dt.date.today().isoformat()
        last = (dt.date.fromisoformat(end) - dt.timedelta(days=1)).isoformat()
        last = max(last, post["from_date"])
        ends[post["seat"]] = max(ends.get(post["seat"], ""), last)
    for post in posts:
        ministry, slash, rest = post["seat"].partition("/")
        if not slash or ministry not in MINISTRY_BY_KEY:
            continue
        named = current_on(ministry, ends[post["seat"]])
        if named and named != ministry:
            post["seat"] = f"{named}/{rest}"


def merge_double_listings(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One post per person, seat and days; the names of the others in ``also_named``."""
    kept: dict[tuple[Any, ...], dict[str, Any]] = {}
    for post in posts:
        key = (post["person"], post["seat"], post["from_date"], post["to_date"])
        if key not in kept:
            kept[key] = post
            continue
        first = kept[key]
        for name in [post["function"], *post["also_named"]]:
            if name != first["function"] and name not in first["also_named"]:
                first["also_named"].append(name)
        first["acting"] = first["acting"] and post["acting"]
        if not first["acting"]:
            first.update(acting_reason=None, acting_basis=None, acting_other_seat=None)
    return list(kept.values())


def _link_named_seat(posts: list[dict[str, Any]]) -> None:
    """Predecessor and successor in one named seat, where the source leaves a date out."""
    for later in posts:
        if later["from_date_source"]:
            continue
        ended = [
            p
            for p in posts
            if p is not later
            and p["to_date_source"]
            and p["from_date"] <= later["from_date"] < p["to_date_source"]
        ]
        if ended:
            later["from_date"] = max(p["to_date"] for p in ended)
            later["corrected"].append(CORRECTED_BY_PREDECESSOR)
    ordered = sorted(posts, key=lambda p: (p["from_date"], p["to_date"] or "9999"))
    for post in ordered:
        if post["to_date_source"]:
            continue
        nexts = [
            p
            for p in ordered
            if p["from_date"] > post["from_date"]
            and p["from_date"] < (post["to_date"] or "9999")
        ]
        if nexts:
            post["to_date"] = min(p["from_date"] for p in nexts)
            post["corrected"].append(CORRECTED_BY_SUCCESSOR)


def _lanes(posts: list[dict[str, Any]]) -> None:
    """Holders of a seat the source does not name, in lanes by date: ``#2``, ``#3``."""
    lanes: list[str] = []  # the end of the last post in each lane
    for post in sorted(posts, key=lambda p: (p["from_date"], p["to_date"] or "9999")):
        for i, end in enumerate(lanes):
            if end <= post["from_date"]:
                lanes[i] = post["to_date"] or "9999"
                break
        else:
            i = len(lanes)
            lanes.append(post["to_date"] or "9999")
        if i:
            post["seat"] = f"{post['seat']}#{i + 1}"


def _stand_ins(posts: list[dict[str, Any]]) -> None:
    """``acting`` by the rule: the holder held another seat through the whole period, and
    the period ended where the next holder of this seat began."""
    by_seat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        by_seat[post["seat"]].append(post)
    for seat, held in by_seat.items():
        if seat == SEAT_DEPUTY:
            continue
        for post in held:
            if post["acting"] or not post["to_date"]:
                continue
            nexts = [
                p
                for p in held
                if p["from_date"] == post["to_date"] and p["person"] != post["person"]
            ]
            others = [
                p
                for p in posts
                if p["person"] == post["person"]
                and p["seat"] not in (seat, SEAT_DEPUTY)
                and p["from_date"] <= post["from_date"]
                and (p["to_date"] or "9999") >= post["to_date"]
            ]
            if nexts and others:
                post["acting"] = True
                post["acting_reason"] = ACTING_HELD_OTHER_SEAT
                post["acting_other_seat"] = {
                    "seat": others[0]["seat"],
                    "function": others[0]["function"],
                }


def _taken_over(posts: list[dict[str, Any]], cabinet: dict[str, Any]) -> None:
    """``beheer portefeuille overgenomen door de minister van X``: the holder of X then
    stands in, from the day the post ended until the next holder of it began."""
    added = []
    for post in posts:
        by = post.get("taken_over_by")
        if not by or not post["to_date"]:
            continue
        seat = seat_of(by, None, None, post["to_date"])["seat"]
        holders = [
            p
            for p in posts
            if p["seat"] == seat
            and p["from_date"] <= post["to_date"] < (p["to_date"] or "9999")
        ]
        if len(holders) != 1:
            continue
        nexts = [
            p["from_date"]
            for p in posts
            if p["seat"] == post["seat"]
            and p["from_date"] >= post["to_date"]
            and p is not post
        ]
        end = min(nexts) if nexts else cabinet["to_date"]
        if end is not None and end <= post["to_date"]:
            continue
        added.append(
            {
                **holders[0],
                **{
                    k: post[k]
                    for k in (
                        "seat",
                        "post",
                        "ministry",
                        "portfolio",
                        "named",
                        "function",
                    )
                },
                "also_named": [],
                "from_date": post["to_date"],
                "to_date": end,
                "from_date_source": post["to_date"],
                "to_date_source": None,
                "corrected": [],
                "acting": True,
                "acting_reason": ACTING_SOURCE,
                "acting_basis": f"{BASIS_TAKEN_OVER} {by}",
                "acting_other_seat": None,
                "taken_over_by": None,
                "overlaps_with": [],
            }
        )
    posts.extend(added)


def _overlaps(posts: list[dict[str, Any]]) -> None:
    by_seat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        if post["seat"] != SEAT_DEPUTY:
            by_seat[post["seat"]].append(post)
    for held in by_seat.values():
        for i, a in enumerate(held):
            for b in held[i + 1 :]:
                if a["person"] != b["person"] and _overlap(a, b):
                    a["overlaps_with"].append(b["person"])
                    b["overlaps_with"].append(a["person"])


def cabinet_posts(
    page: dict[str, Any], cabinet: dict[str, Any]
) -> list[dict[str, Any]]:
    """Every post of the cabinet *cabinet* (``{from_date, to_date}``) that *page* names,
    after the rules of a seat, in order of seat and start."""
    posts = _one_seat_per_heading(page_posts(page, cabinet))
    posts = merge_double_listings(posts)
    by_seat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        by_seat[post["seat"]].append(post)
    for seat, held in by_seat.items():
        if seat == SEAT_DEPUTY:
            continue
        if held[0]["named"]:
            _link_named_seat(held)
        else:
            _lanes(held)
    _taken_over(posts, cabinet)
    posts = merge_double_listings(posts)
    _stand_ins(posts)
    _overlaps(posts)
    _seats_by_their_last_name(posts, cabinet)
    for post in posts:
        for key in (_HEADING, _HEADING_SEAT, _OWN_NAME):
            post.pop(key, None)
    return sorted(posts, key=lambda p: (p["seat"], p["from_date"], p["person"]))


# ── What a cabinet's seats show ──────────────────────────────────────────────


def seat_gaps(posts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """``{seat, from_date, to_date}`` of every stretch longer than ``GAP_DAYS`` between two
    holders of one seat."""
    by_seat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        if post["seat"] != SEAT_DEPUTY:
            by_seat[post["seat"]].append(post)
    gaps = []
    for seat, held in sorted(by_seat.items()):
        ordered = sorted(held, key=lambda p: p["from_date"])
        reach = ordered[0]["to_date"] or "9999"
        for post in ordered[1:]:
            if reach < post["from_date"] and _days(reach, post["from_date"]) > GAP_DAYS:
                gaps.append(
                    {"seat": seat, "from_date": reach, "to_date": post["from_date"]}
                )
            reach = max(reach, post["to_date"] or "9999")
    return gaps


def ministry_name(key: str | None) -> str | None:
    return MINISTRY_BY_KEY[key].name if key in MINISTRY_BY_KEY else None
