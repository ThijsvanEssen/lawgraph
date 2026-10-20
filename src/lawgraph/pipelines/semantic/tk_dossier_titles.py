"""``lawgraph semantic tk-dossier-titles``: the title and opening date of every dossier without.

``normalize tk-dossiers`` gives the dossiers of its run a title from their papers when the
Kamer gives none, and an opening date. A dossier another source made (a stub of the Eerste
Kamer, of a reference) is not one of its run. This step reads every dossier without a title,
the source of its title or an opening date, and fills them from its papers and activities
(``dossier_signals``), as normalize does: the title of its bill, else of its memorandum, else
of any paper (``title_source`` ``document``), a title of its own keeps ``title_source``
``dossier``; ``opened_on`` the date of nr. 1 of its own numbering, else of its Koninklijke
boodschap, else of its earliest record. Writes only what changes.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_stages import opened_on
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.core.tk_records.dossiers import title_from_documents
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.db.queries.semantic import tk as semantic_tk

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Dossiers whose signals are read in one query.
_CHUNK = 500


def filled(props: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """What a dossier with *props* lacks of its title and opening date, from its signals
    *row*; empty when it lacks nothing that its papers give."""
    docs = row.get("docs") or []
    found: dict[str, Any] = {}
    if not props.get("title"):
        found |= title_from_documents(props, docs) or {}
    elif not props.get("title_source"):
        found["title_source"] = "dossier"
    if not props.get("opened_on"):
        day, basis = opened_on(
            props.get("number"), props.get("suffix"), docs, row.get("activities") or []
        )
        if day:
            found |= {"opened_on": day, "opened_on_basis": basis}
    return found


class TKDossierTitlesSemanticPipeline(SemanticPipelineBase):
    """Write ``title``, ``title_source``, ``display_name`` and ``opened_on`` on every
    dossier that lacks them and whose papers give them."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        dossiers = list(semantic_tk.dossiers_to_fill(self.store))
        for chunk in self._track(chunked(dossiers, _CHUNK), "dossier chunks"):
            signals = {
                row["dossier_id"]: row
                for row in normalize_tk.dossier_signals(
                    self.store, [d["id"] for d in chunk]
                )
            }
            changed = [
                {
                    "key": d["key"],
                    "type": NodeType.DOSSIER.value,
                    "labels": [],
                    "props": found,
                }
                for d in chunk
                if (found := filled(d["props"], signals.get(d["id"]) or {}))
            ]
            if changed:
                self.store.bulk_insert_or_update_nodes(COLLECTION_DOSSIERS, changed)
            result.updated += len(changed)
            result.unchanged += len(chunk) - len(changed)
        logger.info(
            "%d dossiers lacked a title or an opening date; %d filled.",
            len(dossiers),
            result.updated,
        )
        return result
