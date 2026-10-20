"""The ``text``, ``paragraphs`` and ``tables`` parts of the ``completeness`` of a paper of
the Tweede Kamer: what ``retrieve tk-content`` and ``normalize tk-content`` wrote of it.

A paper numbered in a dossier is a Kamerstuk, with an address in the KOOP repository
(``kst-<dossier>-<number>``); ``retrieve tk-content`` keeps its XML in raw_sources, or a
record that the repository answered HTTP 404, and ``normalize tk-content`` writes its text,
paragraphs and tables on the Document. A new paper is a PDF only ("Onopgemaakt") until its
XML follows, within days and now and then a week or more: such a paper is asked for again the
next night, an older one after a month.

A paper of the Eerste Kamer is in the repository too; the graph takes in the Eerste Kamer's
record of it, not its text.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import CHAMBER_EK, CHAMBER_TK
from lawgraph.core.completeness import Coverage, Part, Reason
from lawgraph.core.identifiers import KST_ID_PATTERN, kamerstuk_identifier

# How long after its date the XML of a paper may still be on its way.
FRESH_FOR_DAYS = 14


@dataclass(frozen=True)
class XmlRetrieval:
    """What raw_sources holds of the XML of one Kamerstuk, each a ``fetched_at`` (ISO):
    *stored* its XML, *missing* the last answer of HTTP 404; *normalized_until* when the
    last complete ``normalize all`` began (``pipeline_state`` ``normalize``), which read
    every record fetched before."""

    stored: str | None = None
    missing: str | None = None
    normalized_until: str | None = None


def kamerstuk_address(number: object, suffix: object, sequence: object) -> str | None:
    """``kst-37020-X-53``, the address in the repository of the paper numbered *sequence* in
    dossier *number* (*suffix* its addition); None when it has none."""
    if number in (None, "") or sequence in (None, ""):
        return None
    identifier = kamerstuk_identifier(
        str(number), str(suffix) if suffix else None, str(sequence)
    )
    return identifier if KST_ID_PATTERN.fullmatch(identifier) else None


def document_address(props: Mapping[str, Any]) -> str | None:
    """The address in the repository of a paper with these *props*, or None."""
    return kamerstuk_address(
        props.get("dossier_number"), props.get("dossier_suffix"), props.get("sequence")
    )


def is_fresh(date: object, today: dt.date) -> bool:
    """Whether the XML of a paper dated *date* (ISO) may still be on its way on *today*."""
    try:
        published = dt.date.fromisoformat(str(date)[:10])
    except ValueError:
        return False
    return today - published <= dt.timedelta(days=FRESH_FOR_DAYS)


def needs_retrieval(props: Mapping[str, Any], labels: Sequence[str]) -> bool:
    """Whether the state of the text of a paper turns on what raw_sources holds of it: a
    Kamerstuk of the Tweede Kamer without text."""
    return (
        CHAMBER_TK in labels
        and not props.get("text")
        and document_address(props) is not None
    )


def document_text_parts(
    props: Mapping[str, Any],
    labels: Sequence[str],
    retrieval: XmlRetrieval | None,
    *,
    today: dt.date,
) -> dict[str, dict[str, Any]] | None:
    """``text``, ``paragraphs`` and ``tables`` of a paper of the Tweede Kamer with these
    *props*; *retrieval* what raw_sources holds of its XML (``needs_retrieval``). Of a paper
    of the Eerste Kamer all three ``not_fetched``; None of any other.

    With text: ``done``; its paragraphs and tables ``done``, ``none`` when the read found
    none, ``pending`` when it was read before they were kept. Without, all three alike: a
    paper that is no Kamerstuk is ``not_in_source``; of a Kamerstuk, XML read by a complete
    normalize is ``none`` (it does not read, or holds no text), XML not read yet ``pending``
    as of its fetching (``awaiting_normalize``); a 404 ``pending`` as of the last ask while
    the XML may be on its way (``source_pdf_only``), ``not_in_source`` after; nothing asked
    yet ``pending``."""
    if CHAMBER_TK in labels and props.get("text"):
        return {
            Part.TEXT.value: {"state": Coverage.DONE.value},
            Part.PARAGRAPHS.value: _read_part(props, "paragraphs"),
            Part.TABLES.value: _read_part(props, "tables"),
        }
    if CHAMBER_TK in labels:
        part = _text_part(props, retrieval or XmlRetrieval(), today)
    elif CHAMBER_EK in labels:
        part = {"state": Coverage.NOT_FETCHED.value}
    else:
        return None
    return {p.value: dict(part) for p in (Part.TEXT, Part.PARAGRAPHS, Part.TABLES)}


def _read_part(props: Mapping[str, Any], prop: str) -> dict[str, Any]:
    """``paragraphs`` or ``tables`` of a paper with text: the prop is written by every read
    that keeps it, null or empty when it found none."""
    if prop not in props:
        return {"state": Coverage.PENDING.value}
    return {"state": (Coverage.DONE if props[prop] else Coverage.NONE).value}


def _text_part(
    props: Mapping[str, Any], retrieval: XmlRetrieval, today: dt.date
) -> dict[str, Any]:
    if document_address(props) is None:
        return {"state": Coverage.NOT_IN_SOURCE.value}
    if retrieval.stored is not None:
        read = retrieval.normalized_until is not None and _at(retrieval.stored) < _at(
            retrieval.normalized_until
        )
        if read:
            return {"state": Coverage.NONE.value, "as_of": retrieval.stored}
        return {
            "state": Coverage.PENDING.value,
            "as_of": retrieval.stored,
            "reason": Reason.AWAITING_NORMALIZE.value,
        }
    if retrieval.missing is not None:
        if not is_fresh(props.get("date"), today):
            return {"state": Coverage.NOT_IN_SOURCE.value, "as_of": retrieval.missing}
        return {
            "state": Coverage.PENDING.value,
            "as_of": retrieval.missing,
            "reason": Reason.SOURCE_PDF_ONLY.value,
        }
    return {"state": Coverage.PENDING.value}


def _at(moment: str) -> dt.datetime:
    at = dt.datetime.fromisoformat(moment)
    return at if at.tzinfo else at.replace(tzinfo=dt.UTC)
