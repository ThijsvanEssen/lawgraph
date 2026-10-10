"""The page of a motion of the Eerste Kamer (``/motiedossier/…``), read by its structure (pure
functions).

The page opens with a sentence that says what the motion asks ("In deze motie wordt de
regering verzocht …"), links the motion itself as a PDF, and holds its key data in a table of
``<th scope="row">`` and ``<td>``: ``nummer`` (``37.020, M``: the number of its dossier and
its letter), ``ingediend`` (the day), ``bij`` (the debate), ``behandelstatus``
(``verworpen``, ``aangenomen``, ``aangehouden``), ``indiener(s)`` and ``mede ondertekend
door``, each a link to the page of the person (``/persoon/…``) with their name and faction
(``A.J.A. Beukering (Beukering)``). Everything is read as the Kamer writes it.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from lawgraph.core.eerstekamer_votes import dossier_label, text
from lawgraph.core.rijksoverheid import parse_date

_ROW = re.compile(
    r'<th scope="row"[^>]*>\s*([^<]+?)\s*</th>\s*<td[^>]*>(.*?)</td>', re.S
)
_PERSON = re.compile(r'<a href="(/persoon/[^"]+)">([^<]+)</a>')
# ``A.J.A. Beukering (Beukering)``: the name and, in brackets, the faction.
_NAME_FACTION = re.compile(r"^(?P<name>.+?)\s*\((?P<faction>[^()]+)\)\s*$")
_SUMMARY = re.compile(r'<p class="mnone">(.*?)</p>', re.S)
_PDF = re.compile(r'href="([^"]+\.pdf)"')
_NUMBER = re.compile(r"^(?P<number>.+?),\s*(?P<letter>[A-Z]{1,3})$")

ROLE_SUBMITTER = "indiener"
ROLE_COSIGNER = "medeindiener"


@dataclass(frozen=True)
class Signer:
    """One who submitted or co-signed a motion: the page of the person, as the Kamer names
    them, their faction, and whether they submitted it or co-signed it."""

    path: str  # /persoon/bgen_b_d_drs_a_j_a_beukering
    name: str  # A.J.A. Beukering
    faction: str | None  # Beukering
    role: str  # indiener, medeindiener


@dataclass(frozen=True)
class MotionPage:
    """What the page of a motion of the Eerste Kamer says of it."""

    number: str  # 37.020
    letter: str  # M
    label: str  # the dossier label of the Tweede Kamer: 37020
    submitted_on: str | None = None  # YYYY-MM-DD
    debate: str | None = None  # de Algemene Politieke Beschouwingen
    status: str | None = None  # verworpen
    summary: str | None = None
    pdf_path: str | None = None
    signers: list[Signer] = field(default_factory=list)


def _signers(cell: str, role: str) -> list[Signer]:
    found = []
    for path, label in _PERSON.findall(cell):
        named = _NAME_FACTION.match(text(label))
        found.append(
            Signer(
                path=html_lib.unescape(path),
                name=named["name"] if named else text(label),
                faction=named["faction"] if named else None,
                role=role,
            )
        )
    return found


def motion_page(page: str) -> MotionPage | None:
    """The motion the page is of, None for a page without a number of a motion."""
    rows = {text(name).lower(): cell for name, cell in _ROW.findall(page)}
    number = _NUMBER.match(text(rows.get("nummer", "")))
    label = dossier_label(number["number"]) if number else None
    if not number or not label:
        return None
    summary = _SUMMARY.search(page)
    pdf = _PDF.search(page)
    return MotionPage(
        number=number["number"],
        letter=number["letter"],
        label=label,
        submitted_on=parse_date(text(rows.get("ingediend", ""))),
        debate=text(rows.get("bij", "")) or None,
        status=text(rows.get("behandelstatus", "")) or None,
        summary=text(summary[1]) if summary else None,
        pdf_path=html_lib.unescape(pdf[1]) if pdf else None,
        signers=_signers(rows.get("indiener(s)", ""), ROLE_SUBMITTER)
        + _signers(rows.get("mede ondertekend door", ""), ROLE_COSIGNER),
    )
