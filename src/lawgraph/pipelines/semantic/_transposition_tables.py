"""The stored transposition tables, each read and checked against the laws it names: what
``semantic tk-transposition-tables`` writes and ``lawgraph succession-gaps`` reports.

A table comes from one of two sources: a bijlage that is a PDF of its own (``retrieve
tk-transposition-tables``, read by ``core.transposition_tables``), or a table in the XML of an
explanatory memorandum with a heading that names one (``retrieve tk-content``, read by
``core.transposition_xml``). Its laws are found by the names it gives them:

* the new law: of that name, the law a publication of the table's dossier enacted or put
  articles in (``LEGISLATED_IN`` the dossier, ``ESTABLISHES`` or ``INTRODUCES`` its
  articles), else the one law of the BWB; a table that names none (``Huidig naar nieuw``),
  the one law of its dossier;
* the old law: the one law of the BWB of that name that is not the new law; a table that
  names none, the one of the new law's name (the current text of a law recodified).

A table whose laws are not found places nothing and says why (``Table.problem``). The tables
between the same two laws are checked together (``Succession``): an article of the old law
one table leaves out may be in another.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from pypdf.errors import PyPdfError

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.identifiers import KST_ID_PATTERN
from lawgraph.core.models import make_node_key, node_id
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.succession import LawArticle, Placed, SourceRow, place
from lawgraph.core.transposition_tables import pdf_pages, read_table, source_rows
from lawgraph.core.transposition_xml import TABLE_WORDS
from lawgraph.core.transposition_xml import read_tables as read_xml_tables
from lawgraph.db.counting import Store
from lawgraph.db.queries import successions as queries

# A heading of a memorandum that names a table (a regular expression).
_TABLE_HEADING = "|".join(TABLE_WORDS)


@dataclass(frozen=True)
class Table:
    """One table of a source: its laws and rows, or why it places nothing."""

    identifier: str  # the source: blg-1081574, kst-34986-3
    dossier: str
    name: str = ""  # the table in its source: "h. Transponeringstabel Waterwet"
    problem: str | None = None
    old_law: str | None = None  # instruments/bwbr0001903
    new_law: str | None = None  # instruments/wet_stb_2026_56
    rows: tuple[SourceRow, ...] = ()

    @property
    def title(self) -> str:
        return f"{self.identifier} {self.name}".strip()


@dataclass(frozen=True)
class Succession:
    """An old law and a new one, with what the tables between them place."""

    old_law: str
    new_law: str
    tables: tuple[Table, ...]
    placed: Placed


def read_successions(store: Store) -> tuple[list[Table], list[Succession]]:
    """The tables that place nothing, and per pair of laws what the others place."""
    problems: list[Table] = []
    by_laws: dict[tuple[str, str], list[Table]] = {}
    for table in _tables(store):
        if table.old_law and table.new_law:
            by_laws.setdefault((table.old_law, table.new_law), []).append(table)
        else:
            problems.append(table)
    successions = [
        Succession(
            old,
            new,
            tuple(own),
            place(
                [row for table in own for row in table.rows],
                _articles(store, old),
                _articles(store, new),
            ),
        )
        for (old, new), own in by_laws.items()
    ]
    return problems, successions


def _tables(store: Store) -> Iterator[Table]:
    """Every stored table: the PDFs, then the tables of the memoranda, by identifier."""
    for record in queries.transposition_tables(store):
        yield _pdf_table(store, record)
    for record in queries.kamerstukken_with_tables(store, _TABLE_HEADING):
        yield from _xml_tables(store, record)


def _pdf_table(store: Store, record: dict[str, Any]) -> Table:
    identifier = str(record.get("external_id") or "")
    found = Table(identifier, str(meta(record).get("dossier") or ""))
    try:
        pages = pdf_pages(base64.b64decode(payload_text(record) or "", validate=True))
    except PyPdfError, binascii.Error, ValueError:
        return replace(found, problem="the PDF does not read")
    table = read_table(pages)
    if table is None:
        return replace(found, problem="no page headed 'Huidig <law> Nieuw <law>'")
    rows = tuple(source_rows(table, identifier))
    return _with_laws(store, replace(found, rows=rows), table.old_law, table.new_law)


def _xml_tables(store: Store, record: dict[str, Any]) -> Iterator[Table]:
    identifier = str(record.get("external_id") or "")
    match = KST_ID_PATTERN.fullmatch(identifier)
    dossier = match.group(1) if match else ""
    for table in read_xml_tables(payload_text(record) or "", identifier):
        found = Table(identifier, dossier, table.name, table.problem, rows=table.rows)
        yield (
            found
            if table.problem
            else _with_laws(store, found, table.old_law, table.new_law)
        )


def _with_laws(
    store: Store, table: Table, old_name: str | None, new_name: str | None
) -> Table:
    """*table* with the laws of these names (``None``: as the module docstring says), or
    with the reason they are not found."""
    laws = (
        queries.laws_of_dossier(
            store, node_id(COLLECTION_DOSSIERS, make_node_key(table.dossier))
        )
        if table.dossier
        else []
    )
    if new_name is None:
        new = laws
        named = f"of dossier {table.dossier or '?'}"
    else:
        new = [law for law in laws if _same(law.get("citation_title"), new_name)] or [
            {"id": law_id, "citation_title": new_name}
            for law_id in queries.bwb_laws_named(store, new_name)
        ]
        named = f"named {new_name!r}"
    if len(new) != 1:
        return replace(table, problem=f"{len(new)} laws {named}", rows=())
    new_id = str(new[0]["id"])
    old_name = old_name or str(new[0].get("citation_title") or "")
    old = [law for law in queries.bwb_laws_named(store, old_name) if law != new_id]
    if len(old) != 1:
        return replace(
            table,
            problem=f"{len(old)} laws of the BWB named {old_name!r}",
            rows=(),
        )
    return replace(table, old_law=old[0], new_law=new_id)


def _same(title: Any, name: str) -> bool:
    """Whether the citation title *title* is *name*, as ``successions.bwb_laws_named``
    compares them: in any case, without spaces, hyphens and other marks."""
    return _folded(str(title or "")) == _folded(name)


def _folded(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


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
