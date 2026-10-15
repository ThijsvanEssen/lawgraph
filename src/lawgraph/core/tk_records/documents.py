"""Document: a paper (Kamerstuk)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import SOURCE_TK
from lawgraph.core.display import shorten
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records._payload import (
    Payload,
    Record,
    dicts,
    distinct,
    first_text,
    id_of,
)
from lawgraph.core.tk_records.actors import document_actors
from lawgraph.core.tk_records.cases import case_ids, case_kinds, dossier_numbers
from lawgraph.core.tk_records.dossiers import dossier_label
from lawgraph.core.tk_records.kinds import (
    is_named_by_subject,
    own_subject,
    starts_with_kind,
)


def document_title(payload: Payload, cases: list[Payload]) -> str:
    """The title of a Document: its ``Titel``, but the own subject of a paper named by it.

    The ``Titel`` of a motie, an amendement or a letter is its dossier's; what names it is
    its ``Onderwerp`` (``own_subject``), else the ``Onderwerp`` of its Zaak.
    """
    kind = payload.get("Soort") or ""
    if is_named_by_subject(kind):
        own = own_subject(payload) or next(
            (subject for c in cases if (subject := own_subject(c))), ""
        )
        if own:
            return own
    return first_text(payload, "Titel", "Onderwerp") or kind


def own_dossier(payload: Payload) -> tuple[str, str | None] | None:
    """``(Nummer, Toevoeging)`` of the Kamerstukdossier a Document is numbered in; ``None``
    for a paper that is no Kamerstuk (a nader rapport sent along with a bill).

    A Document is a Kamerstuk of at most one dossier. Its cases may reach several: the
    report of one consultation on five bills is part of all five and nr. 11 of one.
    """
    dossier = next(dicts(payload.get("Kamerstukdossier")), None)
    if dossier is None or not dossier.get("Nummer"):
        return None
    return str(dossier["Nummer"]), dossier.get("Toevoeging") or None


def document(payload: Payload) -> Record | None:
    """Node key and props for a Document (Kamerstuk) record; ``None`` without an id.

    A Document reaches dossiers through Zaak → Kamerstukdossier, and one document may
    reach several; its number (``sequence``) is that in its own dossier
    (``dossier_number``, ``dossier_suffix``).
    """
    external_id = id_of(payload)
    if not external_id:
        return None

    cases = list(dicts(payload.get("Zaak")))
    own = own_dossier(payload)
    own_label = dossier_label(*own) if own else None
    dossiers = distinct([*dossier_numbers(cases), own_label or ""])
    kind = payload.get("Soort") or ""
    title = document_title(payload, cases)
    sequence = payload.get("Volgnummer")  # -1 marks a non-Kamerstuk

    return make_node_key(external_id), {
        "source": SOURCE_TK,
        "external_id": external_id,
        "raw": payload,
        "dossier_numbers": dossiers,
        "dossier_number": own[0] if own else None,
        "dossier_suffix": own[1] if own else None,
        "case_ids": case_ids(cases),
        "case_kinds": case_kinds(cases),
        "sequence": sequence if (sequence or 0) > 0 else None,
        "kind": kind,
        "title": title,
        # The Titel of a paper named by its own subject: the title of its dossier, which
        # says which law an amendement changes (``semantic tk-amends``).
        "dossier_title": (
            first_text(payload, "Titel") or None if is_named_by_subject(kind) else None
        ),
        "subject": payload.get("Onderwerp") or "",
        "date": iso_date(payload.get("Datum") or payload.get("DatumRegistratie")),
        "session_year": payload.get("Vergaderjaar") or "",
        # What tweedekamer.nl finds the document by (``2026D44984``); see ``core.tk_links``.
        "document_number": payload.get("DocumentNummer") or None,
        "display_name": document_display_name(own_label, sequence, kind, title),
        "actors": document_actors(payload),
        **document_links(payload),
    }


def document_links(payload: Payload) -> dict[str, list[str]]:
    """The links of a Document, as TK ids: ``activity_ids`` (``Activiteit``: the debate a
    stenogram is the record of), ``attachment_ids`` (``BijlageDocument``: the attachments
    of a letter) and ``attached_to_ids`` (``BronDocument``: the letters it is an attachment
    of). Read from a Document record and from one of ``retrieve tk-document-links``."""

    def ids(field: str) -> list[str]:
        return distinct(
            [str(item.get("Id") or "") for item in dicts(payload.get(field))]
        )

    return {
        "activity_ids": ids("Activiteit"),
        "attachment_ids": ids("BijlageDocument"),
        "attached_to_ids": ids("BronDocument"),
    }


def document_display_name(
    dossier_number: str | None,
    sequence: Any,
    kind: str,
    title: str,
) -> str:
    """``Kamerstuk 29684, nr. 7. Amendement: <title>``, or ``Kamerstuk 29684, nr. 7: Motie
    van de leden …`` when the title names its kind. No dash: it is a heading."""
    if dossier_number and (sequence or 0) > 0:
        name = f"Kamerstuk {dossier_number}, nr. {sequence}"
    elif dossier_number:
        name = f"Kamerstuk {dossier_number}"
    else:
        name = ""
    if not title or title == kind:
        return f"{name}. {kind}" if name and kind else name or kind or "Document"
    title = shorten(title, 120)
    if starts_with_kind(title, kind) or not kind:
        return f"{name}: {title}" if name else title
    return f"{name}. {kind}: {title}" if name else f"{kind}: {title}"
