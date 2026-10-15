"""What the graph refers to and does not hold: the work list of ``retrieve <source> --mode gaps``.

A retrieve pipeline chooses what to fetch in one of three ways: what changed since a date
(``incremental``), everything inside the window (``full``), or what loaded records refer to
and the graph only holds a stub of (``gaps``). This is the work list of the last (its queries
are in ``db/queries/gaps.py``); the report of ``lawgraph gaps`` reads the same one, so it
shows what a run would fetch.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any, cast

from lawgraph.config.constants import (
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_RECHTSPRAAK_CONTENT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.core.case_numbers import REFERRAL_PARAGRAPHS, Referral, read_referrals
from lawgraph.core.dossier_numbers import first_reading_dossiers
from lawgraph.core.identifiers import KST_ID_PATTERN, kamerstuk_identifier
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import Store, raw_key
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import tk as semantic_tk

logger = get_logger(__name__)

# The most gaps of one kind a run fetches; the rest is said out loud and comes next time.
MAX_GAPS_PER_RUN = 50_000

# Keys looked up in one query (as ``GraphStore.existing_keys``).
_KEY_CHUNK = 5000

# A law is fetched when at least this many of its articles are referred to.
DEFAULT_MIN_STUBS = 3


def bwb_gaps(store: Store, *, min_stubs: int = DEFAULT_MIN_STUBS) -> list[str]:
    """BWB ids of the laws that are referred to and not loaded.

    A law of which *min_stubs* articles or more are referred to, and every law a loaded
    regulation is issued under ("Gelet op"): that one is named by the legislator, not
    found in running text, so one mention is enough. (The Wft and the Wwft were named as a
    basis 1,203 and 73 times and were in no list of gaps: a basis whose law is absent made
    no stub.)
    """
    loaded = loaded_bwb_ids(store)
    cited = [
        row["bwb_id"]
        for row in stub_article_counts(store)
        if row["bwb_id"] not in loaded and row["count"] >= min_stubs
    ]
    return list(
        dict.fromkeys([*cited, *(b for b in basis_laws(store) if b not in loaded)])
    )


def basis_laws(store: Store) -> list[str]:
    """BWB ids named as the basis of a loaded regulation, the most named first."""
    return [str(bwb_id) for bwb_id in gap_queries.basis_bwb_ids(store)]


def loaded_bwb_ids(store: Store) -> set[str]:
    return {str(bwb_id) for bwb_id in gap_queries.loaded_bwb_ids(store)}


class Gaps(list):  # type: ignore[type-arg]
    """A work list of gaps; ``note`` says so when it is the first part of a longer one."""

    note: str | None = None

    @classmethod
    def capped(cls, rows: list[Any], what: str, limit: int = MAX_GAPS_PER_RUN) -> Gaps:
        """The first *limit* of *rows*; a longer list is said out loud, and in the ``note``
        the table of ``retrieve all`` shows."""
        if len(rows) <= limit:
            return cls(rows)
        logger.warning(
            "%d %s found; this run takes the first %d (`retrieve all --mode gaps` or "
            "expand-graph again for the rest).",
            len(rows),
            what,
            limit,
        )
        gaps = cls(rows[:limit])
        gaps.note = f"{limit:,} of {len(rows):,} {what}, again for the rest"
        return gaps


def waiting_for_retry(store: Store, source: str, kind: str) -> set[str]:
    """The ids of the *kind* documents *source* answered HTTP 404 for whose
    ``retry_after`` has not passed yet."""
    return {
        str(external_id)
        for external_id in raw_queries.ids_waiting_for_retry(
            store,
            source=source,
            kind=kind + RAW_KIND_MISSING_SUFFIX,
            now_iso=iso_timestamp(dt.datetime.now(dt.UTC)),
        )
    }


def noted(result: PipelineResult, *work: Sequence[Any]) -> PipelineResult:
    """*result*, with the note of each work list that was cut off."""
    result.notes += [w.note for w in work if isinstance(w, Gaps) and w.note]
    return result


def stub_article_counts(store: Store) -> list[dict[str, Any]]:
    """Return stub article groups sorted by reference count descending."""
    return list(gap_queries.stub_article_counts(store))


def rechtspraak_gaps(store: Store) -> Gaps:
    """ECLIs of the Dutch stub judgments, sorted; Rechtspraak has no EU or ECHR judgments."""
    # Those Rechtspraak answered 404 for come out before the cap, not after it: they sort
    # where they sort, and a first 50,000 full of judgments that are not published would
    # keep every later one from ever being asked for.
    missing = waiting_for_retry(store, SOURCE_RECHTSPRAAK, RAW_KIND_RECHTSPRAAK_CONTENT)
    eclis = [
        ecli for ecli in gap_queries.stub_dutch_eclis(store) if ecli not in missing
    ]
    return Gaps.capped(eclis, "stub judgments")


def unanswered_referrals(store: Store) -> list[Referral]:
    """The referrals, by case number and date, of the preliminary rulings that answer no
    decision in the graph: the referring decision is not loaded, and the Rechtspraak can
    only be asked for it through the index of its date."""
    referrals: list[Referral] = []
    for row in gap_queries.unanswered_preliminary_rulings(
        store, paragraphs=REFERRAL_PARAGRAPHS
    ):
        referrals += [
            referral
            for referral in read_referrals(row["paragraphs"])
            if referral.case_numbers and referral.date and referral not in referrals
        ]
    return referrals


def eurlex_gaps(store: Store) -> list[str]:
    """The EU acts BWB regulations name (``props.celex_refs``) that were not retrieved.

    The id is an attribute of the link in the XML, not text of an article, so it is read
    from what ``normalize bwb`` kept on the regulation.
    """
    return cast(list[str], list(gap_queries.unretrieved_celex_refs(store)))


def kamerstuk_gaps(store: Store, kinds: Sequence[str]) -> Gaps:
    """The Tweede Kamer documents whose kind contains one of *kinds*, and whose XML was not
    retrieved.

    Each has the dossier it is numbered in (a document that is no Kamerstuk has no address in
    the repository and is left out) and its ``identifier``, ``kst-<dossier>-<n>``.
    Those the repository answered HTTP 404 for not long ago are left out too, so the report
    of ``lawgraph gaps`` names exactly what a run fetches.
    """
    documents = list(
        gap_queries.papers_with_dossier(store, [kind.lower() for kind in kinds])
    )
    for document in documents:
        document["identifier"] = kamerstuk_identifier(
            document["number"], document.get("suffix"), document["sequence"]
        )
    documents = [p for p in documents if KST_ID_PATTERN.fullmatch(p["identifier"])]
    stored = _with_raw_record(store, documents, RAW_KIND_TK_KAMERSTUK_XML)
    waiting = _with_raw_record(
        store,
        documents,
        RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX,
        retry_ahead=True,
    )
    return Gaps.capped(
        [p for p in documents if p["identifier"] not in stored | waiting],
        "Kamerstukken without XML",
    )


def _with_raw_record(
    store: Store,
    documents: list[dict[str, Any]],
    kind: str,
    *,
    retry_ahead: bool = False,
) -> set[str]:
    """The identifiers of *documents* that have a raw record of *kind*, by primary key.

    With *retry_ahead* only a record of a missing document counts that is not to be asked for
    again yet.
    """
    by_key = {
        raw_key(SOURCE_TK, kind, document["identifier"]): document["identifier"]
        for document in documents
    }
    now = iso_timestamp(dt.datetime.now(dt.UTC)) if retry_ahead else None
    keys = list(by_key)
    found: set[str] = set()
    for start in range(0, len(keys), _KEY_CHUNK):
        chunk = keys[start : start + _KEY_CHUNK]
        rows = gap_queries.existing_raw_keys(store, chunk, retry_after_iso=now)
        found.update(by_key[key] for key in rows)
    return found


def echr_gaps(store: Store) -> list[str]:
    """Return ECLIs (or HUDOC app numbers) of stub ECHR judgment nodes."""
    return [e for e in gap_queries.stub_echr_eclis(store) if e]


def verdragenbank_gaps(store: Store) -> list[str]:
    """Return external IDs of stub verdrag instrument nodes."""
    return [e for e in gap_queries.stub_treaty_ids(store) if e]


def tk_dossier_gaps(store: Store) -> Gaps:
    """The numbers of the dossiers the graph names and has not, or has not in full.

    Named: by the publications that amended or brought into force a version of an article,
    by a change in the Grondwet in its second reading (the first), and by the Tweede Kamer
    documents and cases that are part of it. Not in full: a dossier that lacks a document below
    the highest number it has. A number the Tweede Kamer did not have, or had no more
    documents of, not long ago is left out.
    """
    named = gap_queries.dossiers_named_by_publications(store)
    cited = {
        number
        for memorandum in semantic_tk.second_reading_memoranda(store)
        for number in first_reading_dossiers(memorandum["text"])
    }
    cited -= gap_queries.dossiers_with_numbers(store, sorted(cited))
    by_documents = {
        label.split("-", 1)[0]
        for label in gap_queries.dossiers_named_by_documents(store)
    }
    incomplete = gap_queries.dossiers_missing_documents(store)
    numbers = sorted(
        n for n in set(named) | cited | by_documents | set(incomplete) if n.isdigit()
    )
    candidates = [{"identifier": number} for number in numbers]
    waiting = _with_raw_record(
        store,
        candidates,
        RAW_KIND_TK_DOSSIER + RAW_KIND_MISSING_SUFFIX,
        retry_ahead=True,
    ) | _with_raw_record(
        store,
        candidates,
        RAW_KIND_TK_DOCUMENT + RAW_KIND_MISSING_SUFFIX,
        retry_ahead=True,
    )
    return Gaps.capped(
        [n for n in numbers if n not in waiting], "dossiers named or incomplete"
    )
