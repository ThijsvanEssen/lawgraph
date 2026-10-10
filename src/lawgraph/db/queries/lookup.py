"""Exact lookups for ``GET /api/lookup``: the node a readable URL names, or nothing.

Unlike ``resolve.py`` nothing is guessed and nothing falls back: a paper that is not in the
graph is no answer, not its dossier. Each ``find_*`` gives the id of the node or ``None``;
``answer`` reads what a URL is built back from.
"""

from __future__ import annotations

import re
from typing import Any

from psycopg import sql

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core.documents import chamber_of
from lawgraph.core.identifiers import is_bwb_id, parse_celex
from lawgraph.core.models import make_node_key
from lawgraph.core.notation import native_article_number
from lawgraph.db import GraphStore
from lawgraph.db.queries.committees import _committee

# What a URL is built back from, and what says a node is only cited or replaced: each of
# these props the node has. The text of a judgment is not read.
ANSWER_PROPS = (
    "display_name",
    "ecli",
    "bwb_id",
    "celex",
    "article_number",
    "dossier_number",
    "dossier_suffix",
    "number",
    "suffix",
    "sequence",
    "official_id",
    "identifier",
    "stub",
    "replaced_by",
    "same_as",
    "slug",
    "label",
)

# "36600-VIII", "36455-(R2188)", "36799": the number of a dossier and its suffix.
_DOSSIER = re.compile(r"^(?P<number>\d{1,6})(?:-(?P<suffix>.+))?$")
# The ids of officielebekendmakingen.nl a publication and a paper are known by.
_PUBLICATION_ID = re.compile(
    r"^(?P<series>stb|stcrt|trb)-(?P<year>\d{4})-(?P<number>\d+)$"
)
_PAPER_ID = re.compile(
    r"^kst-(?P<dossier>\d{1,6}(?:-[^-]+)?)-(?P<number>[0-9A-Za-z]+)$"
)
SERIES = ("stb", "stcrt", "trb")


def _one(store: GraphStore, statement: str, params: dict[str, Any]) -> str | None:
    return next(iter(store.query(statement, params)), None)


def _exists(store: GraphStore, collection: str, key: str) -> str | None:
    return f"{collection}/{key}" if store.has_node(collection, key) else None


def split_dossier(label: str) -> tuple[str, str] | None:
    """``36600-VIII`` → (``36600``, ``VIII``); None for what is no dossier label."""
    match = _DOSSIER.match(label.strip())
    return (match["number"], match["suffix"] or "") if match else None


def find_dossier(store: GraphStore, label: str) -> str | None:
    parts = split_dossier(label)
    if parts is None:
        return None
    return _exists(store, COLLECTION_DOSSIERS, make_node_key(*[p for p in parts if p]))


def find_document(store: GraphStore, dossier: str, number: str) -> str | None:
    """The paper *number* (a number of the Tweede Kamer, a letter of the Eerste Kamer) that
    is numbered in the dossier *dossier* (``36799``, ``36600-VIII``)."""
    parts = split_dossier(dossier)
    if parts is None:
        return None
    sequence = int(number) if number.isdigit() else None
    return _one(
        store,
        """
        SELECT d.id FROM documents d
        WHERE d.dossier_number = %(number)s
          AND upper(coalesce(lg_str(d.props -> 'dossier_suffix'), '')) = upper(%(suffix)s)
          AND (lg_num(d.props -> 'sequence') = %(sequence)s
               OR upper(coalesce(lg_str(d.props -> 'number'), '')) = upper(%(paper)s))
        ORDER BY d.key
        LIMIT 1
        """,
        {
            "number": parts[0],
            "suffix": parts[1],
            "sequence": sequence,
            "paper": number,
        },
    )


def find_law(store: GraphStore, law: str) -> str | None:
    """The instrument of a BWB id or a CELEX number."""
    law = law.strip().upper()
    column = "bwb_id" if is_bwb_id(law) else "celex" if parse_celex(law) else None
    if column is None:
        return None
    return _one(
        store,
        f"SELECT i.id FROM instruments i WHERE i.{column} = %(law)s ORDER BY i.key LIMIT 1",
        {"law": law},
    )


def find_article(store: GraphStore, law: str, number: str) -> str | None:
    """Article *number* of the law: ``6:162`` and ``162`` under BW Boek 6 alike."""
    law = law.strip().upper()
    column = "bwb_id" if is_bwb_id(law) else "celex" if parse_celex(law) else None
    if column is None:
        return None
    native = (
        native_article_number(law, number.strip()) if column == "bwb_id" else number
    )
    return _one(
        store,
        f"""
        SELECT a.id FROM articles a
        WHERE a.{column} = %(law)s AND a.article_number = %(number)s
        ORDER BY a.key
        LIMIT 1
        """,
        {"law": law, "number": native.strip()},
    )


def find_annex(store: GraphStore, law: str, label: str) -> str | None:
    """The annex *label* (``II``, ``2``, ``A``) of the law of the BWB id *law*; its key is
    made of both (``core/annex_xml.annex_node_key``), whatever their case."""
    law, label = law.strip(), label.strip()
    if not is_bwb_id(law.upper()) or not label:
        return None
    return _exists(store, COLLECTION_ANNEXES, make_node_key(law, "annex", label))


def find_case(store: GraphStore, number: str) -> str | None:
    """The zaak of the Tweede Kamer numbered *number* (``2025Z15468``)."""
    return _one(
        store,
        f"SELECT c.id FROM {COLLECTION_CASES} c"
        " WHERE lg_str(c.props -> 'number') = %(number)s"
        " ORDER BY c.key LIMIT 1",
        {"number": number.strip().upper()},
    )


def find_judgment(store: GraphStore, ecli: str) -> str | None:
    return _one(
        store,
        "SELECT j.id FROM judgments j WHERE j.ecli = %(ecli)s ORDER BY j.key LIMIT 1",
        {"ecli": ecli.strip().upper()},
    )


def find_publication(
    store: GraphStore, series: str, year: str, number: str
) -> str | None:
    """A publication in the Staatsblad, Staatscourant or Tractatenblad: the instrument the
    BWB names (``stb_2016_288``), else the document of its own source (``stb_stb_…``)."""
    official = f"{series}-{year}-{int(number)}"
    return _exists(store, COLLECTION_INSTRUMENTS, make_node_key(official)) or _exists(
        store, "documents", make_node_key(series, official)
    )


def find_official(store: GraphStore, official_id: str) -> str | None:
    """The node of an id of officielebekendmakingen.nl: ``stb-2026-94``, ``kst-36799-31``.
    A Handelingen id (``h-tk-…``) is no node of the graph."""
    official_id = official_id.strip().lower()
    if publication := _PUBLICATION_ID.match(official_id):
        return find_publication(
            store, publication["series"], publication["year"], publication["number"]
        )
    if paper := _PAPER_ID.match(official_id):
        return find_document(store, paper["dossier"], paper["number"])
    return None


def find_commitment(store: GraphStore, number: str) -> str | None:
    return _one(
        store,
        "SELECT c.id FROM commitments c WHERE c.number = %(number)s ORDER BY c.key LIMIT 1",
        {"number": number.strip().upper()},
    )


def find_faction(store: GraphStore, key: str) -> str | None:
    return _exists(store, COLLECTION_FACTIONS, key.strip())


def find_committee(store: GraphStore, slug: str) -> str | None:
    committee = _committee(store, slug.strip())
    return committee["_id"] if committee else None


def find_member(store: GraphStore, slug: str) -> str | None:
    """The member of *slug* (``rob-jetten``, ``jan-de-vries-1971``)."""
    return _one(
        store,
        f"SELECT m.id FROM {COLLECTION_MEMBERS} m"
        " WHERE lg_str(m.props -> 'slug') = %(slug)s"
        " ORDER BY m.key ASC NULLS FIRST LIMIT 1",
        {"slug": slug.strip().lower()},
    )


def find_cabinet(store: GraphStore, key: str) -> str | None:
    return _exists(store, COLLECTION_CABINETS, key.strip())


def answer(store: GraphStore, node_id: str) -> dict[str, Any]:
    """``{id, key, collection, type, chamber, props}`` of the node, its props only those of
    ``ANSWER_PROPS`` it has."""
    collection, _ = node_id.split("/", 1)
    picked = sql.SQL(", ").join(
        sql.SQL("{name}, t.props -> {name}").format(name=sql.Literal(name))
        for name in ANSWER_PROPS
    )
    statement = sql.SQL(
        "SELECT t.id, t.key, t.type, t.labels, json_build_object({picked}) AS props"
        " FROM {table} t WHERE t.id = %(id)s"
    ).format(picked=picked, table=sql.Identifier(collection))
    row = next(iter(store.query(statement, {"id": node_id})))
    props = {k: v for k, v in (row["props"] or {}).items() if v is not None}
    return {
        "id": row["id"],
        "key": row["key"],
        "collection": collection,
        "type": row["type"],
        "chamber": chamber_of(row["labels"]),
        "props": props,
    }
