"""``lawgraph semantic tk-dossier-eu``: the EU proposal a dossier is about and the EU acts it
implements.

``eu_ref``: per COM number its title names, ``{com, celex}``, with the CELEX of that document
when the graph holds it (``retrieve eurlex --mode com``), else null. ``implements``:
``{celex, bases}`` of the EU acts its title says it implements (basis ``title``) and of those
the laws it legislated implement (the bases of their ``IMPLEMENTS``:
``national_implementing_measure``, ``considerans``). Both from ``core/dossier_eu.py``, over
every dossier, after ``bwb-implements`` and ``tk-dossier-titles``; writes only what changes,
and null where nothing is left.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core import dossier_eu
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.db.queries.semantic import dossier_eu as queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Dossiers written in one statement.
_CHUNK = 500


def derived(row: dict[str, Any], in_graph: set[str]) -> dict[str, Any]:
    """``eu_ref`` and ``implements`` of the dossier *row*, with the CELEX numbers of the
    graph *in_graph*."""
    legislated: dict[str, set[str]] = {}
    for celex, bases in row.get("legislated") or []:
        legislated.setdefault(celex, set()).update(bases or [])
    return {
        "eu_ref": dossier_eu.eu_ref(row.get("title"), in_graph),
        "implements": dossier_eu.implements(row.get("title"), legislated),
    }


class TKDossierEUSemanticPipeline(SemanticPipelineBase):
    """Write ``eu_ref`` and ``implements`` on every dossier whose title or laws give them."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = list(queries.dossiers_with_eu(self.store))
        candidates = sorted(
            {
                celex
                for row in rows
                for com in dossier_eu.com_numbers(row.get("title"))
                for celex in dossier_eu.com_celex_candidates(com)
            }
        )
        in_graph = queries.celex_in_graph(self.store, candidates)
        changed = [
            {
                "key": row["key"],
                "type": NodeType.DOSSIER.value,
                "labels": [],
                "props": found,
            }
            for row in rows
            if (found := derived(row, in_graph))
            != {"eu_ref": row.get("eu_ref"), "implements": row.get("implements")}
        ]
        for chunk in self._track(chunked(changed, _CHUNK), "dossier chunks"):
            self.store.bulk_insert_or_update_nodes(COLLECTION_DOSSIERS, chunk)
        result.updated = len(changed)
        result.unchanged = len(rows) - len(changed)
        logger.info(
            "%d dossiers; %d with a new eu_ref or implements.", len(rows), len(changed)
        )
        return result
