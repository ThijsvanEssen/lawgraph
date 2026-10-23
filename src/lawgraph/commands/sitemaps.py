"""``lawgraph sitemaps``: the sitemaps of Concordans, for the search engines.

    lawgraph sitemaps [--out DIR] [--base URL]

Writes ``sitemap.xml`` and its parts (``core/sitemaps.py``) into ``--out`` (default
``LAWGRAPH_SITEMAP_DIR``), each address on ``--base`` (default ``LAWGRAPH_SITE_URL``):

- ``wetten``: every law with a BWB id that is no stub, and every EU act with an article;
- ``artikelen``: the articles in force with a text of the 150 laws whose articles are
  cited most;
- ``uitspraken``: the judgments, no stub, that the page of one of those articles lists (the
  20 most cited that cite it);
- ``bijlagen``: the annexes of the laws listed, with a label and something to read;
- ``moties``, ``amendementen``: those with a decision since 2018 and a text or a dictum;
- ``zaken``: the zaken but motions and amendments with a decision since 2018;
- ``dossiers``: every dossier with a paper;
- ``leden``: the members who sat in a chamber or held a post in a cabinet;
- ``fracties``, ``kabinetten``, ``commissies``: every one with a name (a committee with a
  slug); ``ministeries``: every ministry name;
- ``publicaties``: in the Staatsblad and the Tractatenblad since 2018 whose page is
  indexed: a title of their own or a regulation they change by name;
- ``toezeggingen``: those made since 2018 that have a text;
- ``activiteiten``: those held since 2018 with a document or a commitment made in them;
- ``paginas``: the pages of the app (``spa-routes.json`` beside ``LAWGRAPH_SPA_INDEX``),
  but those that say ``"index": false`` and a pattern (``/bundels/[id]``).

Each by its readable address (``core/readable_paths.py``); a node without one is left out,
and so is a page that is not indexed or has nothing to read.
``scripts/daily.sh`` runs it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from lawgraph.api.seo import shell
from lawgraph.config import settings
from lawgraph.core import sitemaps
from lawgraph.core.models import PipelineResult
from lawgraph.core.readable_paths import path_of
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import sitemaps as queries
from lawgraph.pipelines.command import command_parser, docstring_title


def entries(
    rows: Iterable[dict[str, Any]], today: str | None = None
) -> Iterator[sitemaps.Entry]:
    """The pages of *rows* (``id``, ``props``, ``lastmod``) that have a readable address,
    each once."""
    today = today or dutch_today().isoformat()
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
        "bijlagen": entries(queries.annexes(store)),
        "uitspraken": entries(queries.judgments(store)),
        "moties": entries(queries.decided_documents(store, "Motie")),
        "amendementen": entries(queries.decided_documents(store, "Amendement")),
        "zaken": entries(queries.decided_cases(store)),
        "dossiers": entries(queries.dossiers(store)),
        "leden": entries(queries.members(store)),
        "fracties": entries(queries.factions(store)),
        "kabinetten": entries(queries.cabinets(store)),
        "ministeries": entries(queries.ministries(store)),
        "commissies": entries(queries.committees(store)),
        "publicaties": entries(queries.publications(store)),
        "toezeggingen": entries(queries.commitments(store)),
        "activiteiten": entries(queries.activities(store)),
        "paginas": [
            sitemaps.Entry(path)
            for path, route in shell.shell().routes.items()
            if shell.indexed(route) and not shell.is_pattern(path)
        ],
    }


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(docstring_title(__doc__))
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.SITEMAP_DIR,
        help="The directory written to. Default: LAWGRAPH_SITEMAP_DIR.",
    )
    parser.add_argument("--base", default=settings.SITE_URL)
    args = parser.parse_args(argv)
    counts = sitemaps.write(args.output, args.base.rstrip("/"), kinds(GraphStore()))
    for kind, n in counts.items():
        print(f"{n:8d}  {kind}")
    print(f"Wrote {args.output / sitemaps.INDEX}.")
    return PipelineResult(updated=sum(counts.values()))
