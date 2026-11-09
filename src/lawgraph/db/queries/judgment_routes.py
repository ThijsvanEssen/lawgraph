"""The route of a case per area of law (``GET /api/judgments/routes``): the steps from
``data/route_articles.json`` with the article that gives each court its say, the articles of
the Bevoegdheidsregeling bestuursrechtspraak that name a bijzondere bestuursrechter, and the
gaps. The articles of the
regeling (Awb bijlage 2) are articles of the Awb in the graph (``normalize bwb``): each with
its chapter, its heading and the laws its list names (its extrefs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.judgment_course import (
    AREAS,
    route_designations,
    route_gaps,
    route_rules,
)
from lawgraph.db import GraphStore

# The Bevoegdheidsregeling bestuursrechtspraak: bijlage 2 of the Awb, its articles numbered
# "bijlage 2 artikel 1" and keyed ``bwbr0005537_bijlage_2_artikel_1``.
REGELING_BWB_ID = "BWBR0005537"
REGELING_PREFIX = "bijlage 2 artikel "


@dataclass
class Routes:
    """The route per area of law, and the Bevoegdheidsregeling by chapter."""

    areas: list[dict[str, Any]] = field(default_factory=list)
    regeling: list[dict[str, Any]] = field(default_factory=list)


def judgment_routes(store: GraphStore) -> Routes:
    """The routes of ``data/route_articles.json`` per area, and the regeling."""
    designations = route_designations()
    gaps = route_gaps()
    areas = []
    for area in AREAS:
        steps = [
            {
                "tier": tier,
                "procedures": rule["procedures"],
                "basis": _basis(rule),
                "designations": [
                    _basis(d)
                    for d in designations
                    if d["tier"] == tier and d["procedure"] in rule["procedures"]
                ],
            }
            for rule in route_rules()
            if area in rule["areas"]
            for tier in rule["tiers"]
        ]
        areas.append(
            {
                "area": area,
                "steps": steps,
                "gaps": [
                    {"tier": tier, "procedures": g["procedures"], "why": g["why"]}
                    for g in gaps
                    if area in g["areas"]
                    for tier in g["tiers"]
                ],
            }
        )
    return Routes(areas=areas, regeling=regeling_articles(store))


def _basis(rule: dict[str, Any]) -> dict[str, str]:
    return {"bwb_id": rule["bwb_id"], "article_number": rule["article_number"]}


def regeling_articles(store: GraphStore) -> list[dict[str, Any]]:
    """The chapters of the Bevoegdheidsregeling bestuursrechtspraak, each with its articles in
    order: number, key, heading and the laws its list names (BWB id and name, each once, in
    the order of the text; the opening sentence left out). Empty when it is not loaded."""
    rows = store.query(
        """
        SELECT a.key, a.props ->> 'article_number' AS number,
               a.props ->> 'heading' AS heading, a.props -> 'breadcrumb' AS breadcrumb,
               a.props ->> 'text' AS text, a.props -> 'references' AS refs
        FROM articles a
        WHERE a.key LIKE %(prefix)s
        """,
        {"prefix": f"{REGELING_BWB_ID.lower()}_bijlage_2_artikel_%"},
    )
    articles = sorted(
        (r for r in rows if (r["number"] or "").startswith(REGELING_PREFIX)),
        key=lambda r: int(r["number"].removeprefix(REGELING_PREFIX) or 0),
    )
    names = _law_names(store, {i for r in articles for i in _law_ids(r)})
    chapters: dict[str, dict[str, Any]] = {}
    for row in articles:
        label, title = _chapter(row["breadcrumb"])
        chapter = chapters.setdefault(
            label, {"label": label, "title": title, "articles": []}
        )
        chapter["articles"].append(
            {
                "number": row["number"],
                "key": row["key"],
                "heading": row["heading"],
                "laws": [
                    {"bwb_id": i, "name": names.get(i) or _ref_name(row, i)}
                    for i in _law_ids(row)
                ],
            }
        )
    return list(chapters.values())


def _chapter(breadcrumb: list[dict[str, Any]] | None) -> tuple[str, str | None]:
    """The label and title of the division (``Hoofdstuk 2``) an article of the regeling is in."""
    for part in reversed(breadcrumb or []):
        if part.get("type") == "divisie":
            return str(part.get("label") or ""), part.get("title")
    return "", None


def _law_ids(row: dict[str, Any]) -> list[str]:
    """The BWB ids the list of an article names, each once, in order: its extrefs after the
    opening sentence (its first line), the Awb itself left out."""
    opening = (row["text"] or "").find("\n")
    seen: dict[str, None] = {}
    for ref in row["refs"] or []:
        bwb_id = ref.get("bwb_id")
        if (
            bwb_id
            and bwb_id != REGELING_BWB_ID
            and int(ref.get("start") or 0) > opening
        ):
            seen.setdefault(bwb_id, None)
    return list(seen)


def _ref_name(row: dict[str, Any], bwb_id: str) -> str | None:
    """How the text names a law (its first extref to the law as a whole that starts with a
    capital: "Gemeentewet", not "hoofdstuk XVII van de Gemeentewet"), for a law the graph
    does not hold."""
    return next(
        (
            ref.get("text")
            for ref in row["refs"] or []
            if ref.get("bwb_id") == bwb_id
            and not ref.get("article")
            and (ref.get("text") or "")[:1].isupper()
        ),
        None,
    )


def _law_names(store: GraphStore, bwb_ids: set[str]) -> dict[str, str]:
    """The citation title of each law of *bwb_ids* the graph holds, by BWB id."""
    if not bwb_ids:
        return {}
    rows = store.query(
        """
        SELECT i.props ->> 'bwb_id' AS bwb_id,
               coalesce(i.props ->> 'citation_title', i.props ->> 'title') AS name
        FROM instruments i
        WHERE i.key = ANY(%(keys)s::text[])
        """,
        {"keys": sorted(i.lower() for i in bwb_ids)},
    )
    return {r["bwb_id"]: r["name"] for r in rows if r["bwb_id"] and r["name"]}
