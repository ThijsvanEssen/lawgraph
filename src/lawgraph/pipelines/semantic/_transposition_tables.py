"""The stored transposition tables, each read and checked against the laws it names: what
``semantic tk-transposition-tables`` writes and ``lawgraph succession-gaps`` reports.

A table is placed when the graph holds both laws:

* the new law: the law a publication of the table's dossier enacted (``LEGISLATED_IN`` the
  dossier, ``ESTABLISHES`` its articles) whose citation title is the name the table gives it;
* the old law: the one law of the BWB of the name the table gives it, not the new law.

Otherwise the table places nothing and says why (``TableResult.problem``).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pypdf.errors import PyPdfError

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.models import make_node_key, node_id
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.succession import LawArticle, Placed, place
from lawgraph.core.transposition_tables import pdf_pages, read_table, source_rows
from lawgraph.db.counting import Store
from lawgraph.db.queries import successions as queries


@dataclass(frozen=True)
class TableResult:
    """One stored table: its laws and what it places, or why it places nothing."""

    identifier: str  # blg-1081574
    dossier: str
    problem: str | None = None
    old_law: str | None = None  # instruments/bwbr0001903
    new_law: str | None = None  # instruments/wet_stb_2026_56
    placed: Placed | None = None


def read_tables(store: Store) -> Iterator[TableResult]:
    """Every stored table, by identifier."""
    for record in queries.transposition_tables(store):
        yield _read(store, record)


def _read(store: Store, record: dict[str, Any]) -> TableResult:
    identifier = str(record.get("external_id") or "")
    dossier = str(meta(record).get("dossier") or "")
    laws = (
        queries.laws_of_dossier(
            store, node_id(COLLECTION_DOSSIERS, make_node_key(dossier))
        )
        if dossier
        else []
    )
    if not laws:
        return TableResult(identifier, dossier, f"no law of dossier {dossier or '?'}")
    try:
        pages = pdf_pages(base64.b64decode(payload_text(record) or "", validate=True))
    except PyPdfError, binascii.Error, ValueError:
        return TableResult(identifier, dossier, "the PDF does not read")
    table = read_table(pages)
    if table is None:
        return TableResult(
            identifier, dossier, "no page headed 'Huidig <law> Nieuw <law>'"
        )
    new = [
        law["id"]
        for law in laws
        if str(law.get("citation_title") or "").lower() == table.new_law.lower()
    ]
    if len(new) != 1:
        return TableResult(
            identifier,
            dossier,
            f"{len(new)} laws of dossier {dossier} named {table.new_law!r}",
        )
    old = [law for law in queries.bwb_laws_named(store, table.old_law) if law != new[0]]
    if len(old) != 1:
        return TableResult(
            identifier, dossier, f"{len(old)} laws of the BWB named {table.old_law!r}"
        )
    placed = place(
        source_rows(table), _articles(store, old[0]), _articles(store, new[0])
    )
    return TableResult(identifier, dossier, None, old[0], new[0], placed)


def _articles(store: Store, law_id: str) -> dict[str, LawArticle]:
    return {
        row["number"]: LawArticle(
            row["id"],
            row["number"],
            frozenset(row["leden"] or ()),
            bool(row["repealed"]),
        )
        for row in queries.law_articles(store, law_id)
    }
