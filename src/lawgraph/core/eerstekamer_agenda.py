"""The agendas of the Eerste Kamer, as eerstekamer.nl shows them (pure functions).

* A plenary sitting (``/plenaire_vergadering/<yyyymmdd>``): its agenda, block by block, each
  with an id of the site's own, its time (``13.30 - 13.35 uur``), its title (``Hamerstukken``,
  ``Eerste termijn Kamer …``) and the bills and notes it is about, each named with its number
  (``Wet digitale aanvraag rijbewijzen (36.937)``).
* A day of committee meetings (``/commissievergaderingen_op``): every meeting
  (``/commissievergadering/<yyyymmdd>_<committees>``) with the committees, its kind
  (``mondeling overleg``), its time and its decision points (``besluitpunten``), each with an
  id of the site's own, its number, the papers it is about (``28.973 / 29.683 / 32.793, AA``),
  its subject and the decision as the committee words it.

Both link the sitting or day before and after (``eerdere`` / ``latere``). Only the page
structure and its labelled parts are read; a decision is kept as the committee words it, not
read. The site gives no status of an activity (planned, held) as data.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from lawgraph.core.eerstekamer_bills import label
from lawgraph.core.eerstekamer_composition import text

PLENARY_PATH = "/menukeuze_plenair"  # forwards to the next plenary sitting
COMMITTEE_DAYS_PATH = "/commissievergaderingen_op"  # the next day of committee meetings

_EARLIER = re.compile(r'<div class="eerder"><a href="([^"]+)"')
_LATER = re.compile(r'<div class="recenter"><a href="([^"]+)"')
_PLENARY_DATE = re.compile(r"/plenaire_vergadering/(\d{4})(\d{2})(\d{2})")
_BLOCK = re.compile(
    r'<div id="([a-z0-9]+)"><div class="agendablok"><h3[^>]*>(.*?)</h3>\s*'
    r'<div class="zaken">(.*?)</div></div></div>(?=<div id="|</div>)',
    re.S,
)
_TIME = re.compile(r"^(\d{1,2}\.\d{2}\s*-\s*\d{1,2}\.\d{2})\s*uur\s*(.*)$")
_NUMBERED = re.compile(r"\(([0-9.]+(?:\s+[A-Za-z0-9-]+)?)\)\s*$")
_LINKED_PAPER = re.compile(r'<a href="(/[^"]+)" class="grid-x">(.*?)</a>', re.S)
_MEETING = re.compile(
    r'<li class="d-flex grid-y nowr">(.*?)</li>\s*(?=<li class="d-flex|</ul>)', re.S
)
_MEETING_LINK = re.compile(
    r'<a href="(/commissievergadering/(\d{4})(\d{2})(\d{2})_[^"/]+)">.*?'
    r'<div class="i-plan_t[^"]*">(.*?)</div>',
    re.S,
)
_KIND = re.compile(r'<em class="d-block">([^<]*)</em>')
_HOUR = re.compile(r'<span class="d-block">([^<]*)</span>')
_POINT = re.compile(
    r'<span class="apnum">([^<]*)</span>.*?'
    r'<span class="kop_agenda_kamerleden_tekst" id="[a-z0-9]+_([a-z0-9]+)">([^<]*)</span>'
    r'(.*?)(?=<h2 class="fs-normaal|$)',
    re.S,
)
_SUBJECT = re.compile(r'<span id="header_[a-z0-9]+">(.*?)</span>', re.S)
_DECISION = re.compile(r'<span id="u5h_[a-z0-9]+">(.*?)</span>', re.S)


@dataclass(frozen=True)
class AgendaItem:
    """A block of the agenda of a plenary sitting."""

    id: str  # the site's own
    time: str | None  # 13.30 - 13.35
    title: str
    dossiers: list[str] = field(default_factory=list)  # labels: 36937, 36945-XXII


@dataclass(frozen=True)
class Plenary:
    date: str | None  # YYYY-MM-DD
    items: list[AgendaItem]
    earlier: str | None
    later: str | None


@dataclass(frozen=True)
class DecisionPoint:
    """A decision point of a committee meeting."""

    id: str  # the site's own
    number: str  # 1.
    reference: str  # 28.973 / 29.683 / 32.793, AA
    dossiers: list[str]  # labels: 28973, 29683, 32793
    subject: str | None
    decision: str | None  # as the committee words it


@dataclass(frozen=True)
class Meeting:
    path: str  # /commissievergadering/20260929_lnv_en_vws
    date: str
    committees: str  # Commissies voor Landbouw, … (LNV) en voor … (VWS)
    kind: str | None  # mondeling overleg; none for some
    time: str | None  # 14.15 uur
    points: list[DecisionPoint] = field(default_factory=list)


@dataclass(frozen=True)
class CommitteeDay:
    meetings: list[Meeting]
    earlier: str | None
    later: str | None


def _nav(page: str) -> tuple[str | None, str | None]:
    earlier, later = _EARLIER.search(page), _LATER.search(page)
    return (
        html_lib.unescape(earlier[1]) if earlier else None,
        html_lib.unescape(later[1]) if later else None,
    )


def reference_dossiers(reference: str) -> list[str]:
    """``28.973 / 29.683 / 32.793, AA`` -> the dossiers ``28973``, ``29683``, ``32793``."""
    numbers, _, _letter = reference.partition(",")
    return [label(part) for part in numbers.split("/") if part.strip()]


def plenary(path: str, page: str) -> Plenary:
    """A plenary sitting from its path and page."""
    day = _PLENARY_DATE.search(path)
    items = []
    for block_id, heading, papers in _BLOCK.findall(page):
        head = text(heading)
        timed = _TIME.match(head)
        items.append(
            AgendaItem(
                id=block_id,
                time=timed[1].replace(" ", "") if timed else None,
                title=(timed[2] if timed else head).strip(),
                dossiers=[
                    label(number[1])
                    for _, name in _LINKED_PAPER.findall(papers)
                    if (number := _NUMBERED.search(text(name)))
                ],
            )
        )
    earlier, later = _nav(page)
    return Plenary(
        date=f"{day[1]}-{day[2]}-{day[3]}" if day else None,
        items=items,
        earlier=earlier,
        later=later,
    )


def _meeting(block: str) -> Meeting | None:
    link = _MEETING_LINK.search(block)
    if link is None:
        return None
    kind, hour = _KIND.search(block), _HOUR.search(block)
    points = []
    for number, point_id, reference, rest in _POINT.findall(block):
        subject, decision = _SUBJECT.search(rest), _DECISION.search(rest)
        ref = text(reference)
        points.append(
            DecisionPoint(
                id=point_id,
                number=text(number),
                reference=ref,
                dossiers=reference_dossiers(ref),
                subject=text(subject[1]) or None if subject else None,
                decision=text(decision[1]) or None if decision else None,
            )
        )
    return Meeting(
        path=link[1],
        date=f"{link[2]}-{link[3]}-{link[4]}",
        committees=text(link[5]),
        kind=text(kind[1]) or None if kind else None,
        time=text(hour[1]) or None if hour else None,
        points=points,
    )


def committee_day(page: str) -> CommitteeDay:
    """A day of committee meetings."""
    meetings = [m for b in _MEETING.findall(page) if (m := _meeting(b)) is not None]
    earlier, later = _nav(page)
    return CommitteeDay(meetings=meetings, earlier=earlier, later=later)
