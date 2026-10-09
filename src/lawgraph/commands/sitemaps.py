"""``lawgraph sitemaps``: the sitemaps of Concordans, for the search engines.

    lawgraph sitemaps [--out DIR] [--base URL]

Writes ``sitemap.xml`` and its parts (``core/sitemaps.py``) into ``--out`` (default
``LAWGRAPH_SITEMAP_DIR``), each address on ``--base`` (default ``LAWGRAPH_SITE_URL``):

- ``wetten``: every law with a BWB id that is no stub;
- ``artikelen``: the articles in force of the 150 laws whose articles are cited most;
- ``moties``, ``amendementen``: those with a decision since 2018;
- ``dossiers``: every dossier;
- ``leden``: the members who sat in a chamber or held a post in a cabinet;
- ``fracties``, ``kabinetten``, ``commissies``: every one (a committee with a slug);
- ``paginas``: the pages of the app (``spa-routes.json`` beside ``LAWGRAPH_SPA_INDEX``).

Each by its readable address (``core/readable_paths.py``); a node without one is left out.
``scripts/daily.sh`` runs it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from lawgraph.api.seo import shell
from lawgraph.config import settings
from lawgraph.core import sitemaps
from lawgraph.core.models import PipelineResult
from lawgraph.core.readable_paths import path_of
from lawgraph.db import GraphStore
from lawgraph.db.queries import sitemaps as queries
from lawgraph.pipelines.command import command_parser, docstring_title


def entries(
    rows: Iterable[dict[str, Any]], today: str | None = None
) -> Iterator[sitemaps.Entry]:
    """The pages of *rows* (``id``, ``props``, ``lastmod``) that have a readable address,
    each once."""
    today = today or dt.date.today().isoformat()
    seen: set[str] = set()
    for row in rows:
        path = path_of(row["id"], row.get("props") or {})
        if path and path not in seen:
            seen.add(path)
            yield sitemaps.Entry(path, sitemaps.day(row.get("lastmod"), today))


def kinds(store: GraphStore) -> dict[str, Iterable[sitemaps.Entry]]:
    return {
        "wetten": entries(queries.laws(store)),
        "artikelen": entries(queries.articles(store)),
        "moties": entries(queries.decided_papers(store, "Motie")),
        "amendementen": entries(queries.decided_papers(store, "Amendement")),
        "dossiers": entries(queries.dossiers(store)),
        "leden": entries(queries.members(store)),
        "fracties": entries(queries.factions(store)),
        "kabinetten": entries(queries.cabinets(store)),
        "commissies": entries(queries.committees(store)),
        "paginas": [sitemaps.Entry(path) for path in shell.shell().routes],
    }


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument("--out", type=Path, default=settings.SITEMAP_DIR)
    parser.add_argument("--base", default=settings.SITE_URL)
    args = parser.parse_args(argv)
    counts = sitemaps.write(args.out, args.base.rstrip("/"), kinds(GraphStore()))
    for kind, n in counts.items():
        print(f"{n:8d}  {kind}")
    print(f"Wrote {args.out / sitemaps.INDEX}.")
    return PipelineResult(updated=sum(counts.values()))
