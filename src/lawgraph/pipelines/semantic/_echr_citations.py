"""``REFERS_TO`` to the ECHR decisions a text cites by application number, for the steps that
read texts (``rechtspraak-citations``: Dutch judgments; ``echr``: judgments of the Court).

``core.echr_citations`` reads the citations and resolves them: a number and a date to that
decision, a number alone only to the one decision of it. What is left is counted, so the log
says how many citations a level of the case (all its decisions) would add.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.echr_citations import Cited, Unresolved, decisions_by_appno, resolve
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import EdgeWriter, Store
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.db.store import edge_key

logger = get_logger(__name__)

# A citation that names the date is the decision of that day; one by number alone, the only
# decision of its number.
CONFIDENCE_DATED = 0.9
CONFIDENCE_NUMBER = 0.8


def decisions_index(store: Store) -> dict[str, list[tuple[str | None, str]]]:
    """Application number -> ``(date, id)`` of each ECHR decision of it, read once."""
    return decisions_by_appno(list(semantic_rechtspraak.echr_decisions(store)))


def link(
    store: Store,
    cited: Iterable[tuple[str, Cited]],
    decisions: dict[str, list[tuple[str | None, str]]],
    *,
    source: str,
    result: PipelineResult,
) -> dict[str, set[str]]:
    """Write ``REFERS_TO`` from each citing node to the decision it cites; the keys of the
    edges written, per citing node. A citation of the citing decision itself is none."""
    kept: dict[str, set[str]] = {}
    left: Counter[str] = Counter()
    edges = EdgeWriter(store, what=None)
    for from_id, citation in cited:
        to_id = resolve(citation, decisions)
        if isinstance(to_id, Unresolved):
            left[to_id.value] += 1
            continue
        if to_id == from_id:
            continue
        meta: dict[str, str] = {"cited_appno": citation.appno}
        if citation.date:
            meta["cited_date"] = citation.date
        if edges.add(
            from_id,
            to_id,
            RELATION_REFERS_TO,
            source=source,
            confidence=CONFIDENCE_DATED if citation.date else CONFIDENCE_NUMBER,
            meta=meta,
        ):
            kept.setdefault(from_id, set()).add(
                edge_key(from_id, RELATION_REFERS_TO, to_id)
            )
    edges.flush_into(result)
    logger.info(
        "ECHR decisions cited by application number: %d linked; %d not loaded; %d "
        "ambiguous (several decisions of the number and no date to choose).",
        sum(len(keys) for keys in kept.values()),
        left[Unresolved.MISSING.value],
        left[Unresolved.AMBIGUOUS.value],
    )
    return kept
