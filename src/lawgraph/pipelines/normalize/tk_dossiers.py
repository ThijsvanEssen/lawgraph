"""Normalize the parliamentary records of the Tweede Kamer into the graph.

The pipeline is the order in which the nodes must exist:

  1. committees, members, factions, dossiers  — no dependencies
  2. activities, decisions, commitments, documents
  3. edges, which need both endpoints stored

Node building lives next door, one module per part of the model:
``tk_members`` (committees, members, factions), ``tk_votes`` (decisions and
the votes on them) and ``tk_cases`` (activities, commitments, documents and
what they are about). The dossier itself — its title, its stage, when it opened —
is what this module keeps; whether and how it ended is ``semantic tk-dossier-outcomes``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RELATION_ABOUT,
    RELATION_PART_OF,
    SOURCE_TK,
)
from lawgraph.core import tk_records
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_stages import (
    classify_track_kind,
    dossier_display_name,
    dossier_stages,
    select_title,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.progress import Progress
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize import _tk_members as tk_members
from lawgraph.pipelines.normalize import _tk_votes as tk_votes
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, RawRecords

logger = get_logger(__name__)

EDGE_SOURCE = "tk-dossiers"

RAW_KINDS = [
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
]

# Dossiers whose signals are gathered in one query. The join over documents,
# cases, activities and decisions is heavy enough that asking for every
# dossier at once outruns the cursor lifetime.
_BACKFILL_CHUNK = 500


class TKDossiersNormalizePipeline(NormalizePipelineBase):
    """Turn raw TK parliamentary records into parliament nodes and edges."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> dict[str, Iterable[dict[str, Any]]]:
        """The records per kind, streamed when they are walked: 360K payloads are not kept."""
        self._incremental = since is not None
        raw: dict[str, Iterable[dict[str, Any]]] = {
            kind: RawRecords(
                self, source=SOURCE_TK, kinds=[kind], since=since, batch_size=1000
            )
            for kind in RAW_KINDS
        }
        if since is not None:
            raw[RAW_KIND_TK_STEMMING] = self._rows_of_decisions_voted_since(since)
        return raw

    def _rows_of_decisions_voted_since(
        self, since: dt.datetime
    ) -> Iterator[dict[str, Any]]:
        """Every Stemming row of the decisions that have a row in the window.

        A decision is its rows together (the tally, who voted): one corrected vote must
        not turn it into a decision of one.
        """
        decisions = raw_queries.decisions_voted_since(self.store, iso_timestamp(since))
        progress = Progress(f"{RAW_KIND_TK_STEMMING} records")
        yield from progress.track(
            raw_queries.vote_rows_of_decisions(self.store, decisions)
            if decisions
            else ()
        )

    def normalize_nodes(
        self,
        raw: dict[str, Iterable[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        store = self.store
        votes = tk_votes.read_votes(raw[RAW_KIND_TK_STEMMING])
        vote_labels = votes.faction_labels
        if self._incremental:
            # The factions are written again with the spellings votes gave them: those of
            # the window alone would take away what earlier votes taught.
            vote_labels = vote_labels | self._stored_faction_aliases()

        normalized: dict[str, Any] = {
            "committees": tk_members.normalize_committees(
                store, raw[RAW_KIND_TK_COMMISSIE]
            ),
            "members": tk_members.normalize_members(store, raw[RAW_KIND_TK_PERSOON]),
            "factions": tk_members.normalize_factions(
                store, raw[RAW_KIND_TK_FRACTIE], vote_labels
            ),
            "dossiers": self._normalize_dossiers(raw[RAW_KIND_TK_DOSSIER]),
            "activities": tk_cases.normalize_activities(
                store, raw[RAW_KIND_TK_ACTIVITEIT]
            ),
            "commitments": tk_cases.normalize_commitments(
                store, raw[RAW_KIND_TK_TOEZEGGING]
            ),
            "documents": tk_cases.normalize_documents(store, raw[RAW_KIND_TK_DOCUMENT]),
            "votes": votes.by_decision,
        }
        normalized["decisions"] = tk_votes.normalize_decisions(store, votes)
        self._refresh_case_kinds(normalized["activities"])
        return normalized

    def build_edges(
        self,
        raw: dict[str, Iterable[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> None:
        store = self.store
        tk_cases.link_cases_to_dossiers(store, source=EDGE_SOURCE)
        tk_cases.link_subjects(
            store,
            normalized["documents"].values(),
            RELATION_PART_OF,
            source=EDGE_SOURCE,
        )
        tk_cases.link_subjects(
            store, normalized["activities"].values(), RELATION_ABOUT, source=EDGE_SOURCE
        )
        tk_cases.link_subjects(
            store, normalized["decisions"].values(), RELATION_ABOUT, source=EDGE_SOURCE
        )
        tk_cases.link_activities_to_committees(
            store, normalized["activities"], source=EDGE_SOURCE
        )
        # An incremental run holds the records of its window only. What a record of the
        # window points to may have been loaded earlier (`retrieve all` skips the members
        # and factions on incremental runs), so those come from the database.
        tk_cases.link_commitments(
            store,
            normalized["commitments"],
            {
                **self._stored(COLLECTION_ACTIVITIES, NodeType.ACTIVITY),
                **normalized["activities"],
            },
            source=EDGE_SOURCE,
        )
        tk_cases.link_authors(store, normalized["documents"], source=EDGE_SOURCE)
        tk_members.link_members_to_committees(
            store, raw[RAW_KIND_TK_COMMISSIE], source=EDGE_SOURCE
        )
        tk_members.link_members_to_factions(
            store,
            raw[RAW_KIND_TK_FRACTIEZETELPERSOON],
            normalized["members"],
            normalized["factions"],
            source=EDGE_SOURCE,
        )
        tk_votes.link_votes(
            store,
            normalized["votes"],
            normalized["decisions"],
            {
                **self._stored(COLLECTION_FACTIONS, NodeType.FACTION),
                **normalized["factions"],
            },
            source=EDGE_SOURCE,
        )

        # Once the edges exist, each dossier's documents can be walked to
        # derive its title and stage, so reads stay O(1).
        self._backfill_titles_and_stages(normalized["dossiers"])

    def _stored_faction_aliases(self) -> set[str]:
        return set(normalize_queries.faction_aliases(self.store))

    def _stored(self, collection: str, node_type: NodeType) -> dict[str, Node]:
        """The stored nodes of *collection* by TK ``Id``, with the props the edges read."""
        rows = normalize_queries.nodes_by_external_id(
            self.store, collection, list(tk_cases.LINK_PROPS)
        )
        return {
            row["id"]: Node(
                collection=collection,
                type=node_type,
                key=row["key"],
                props=row["props"],
                _skip_validation=True,
            )
            for row in rows
        }

    # ── Dossiers ──────────────────────────────────────────────────────────────

    def _normalize_dossiers(
        self, raw_records: Iterable[dict[str, Any]]
    ) -> dict[str, Node]:
        """Kamerstukdossier nodes, keyed by TK ``Id`` *and* by dossier number."""
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            parsed = tk_records.dossier(self._payload_json(raw))
            if parsed is None:
                continue
            key, label, props = parsed
            node = Node(
                collection=COLLECTION_DOSSIERS,
                type=NodeType.DOSSIER,
                key=key,
                labels=["TK"],
                props=props,
            )
            nodes[props["external_id"]] = node
            nodes[label] = node

        unique = _unique(nodes)
        self._upsert_nodes(unique)
        logger.info("Normalized %d dossiers.", len(unique))
        return nodes

    def _refresh_case_kinds(self, activity_nodes: dict[str, Node]) -> None:
        """Roll the ``Zaak.Soort`` values reachable per dossier onto the dossier.

        That list feeds both the kind-of-dossier and the stage classifier in
        the backfill, which is the only writer of ``current_stage``,
        ``track_kind`` and ``stages_present``; writing them here too would
        blank the previous answer for the span between the two steps.
        """
        wanted: dict[str, set[str]] = {}
        for node in activity_nodes.values():
            by_dossier = node.props.get("case_kinds_by_dossier") or {}
            for number, kinds in by_dossier.items():
                wanted.setdefault(make_node_key(number), set()).update(kinds)
        sorted_kinds = {key: sorted(kinds) for key, kinds in wanted.items()}

        stored: dict[str, Any] = {}
        for keys in chunked(sorted_kinds, 5000):
            for row in normalize_queries.dossier_case_kinds(self.store, keys):
                stored[row["key"]] = row["case_kinds"]

        if self._incremental:
            # The activities of the window add to what earlier ones gave the dossier.
            sorted_kinds = {
                key: sorted(set(kinds) | set(stored.get(key) or []))
                for key, kinds in sorted_kinds.items()
            }

        changed = [
            {
                "_key": key,
                "type": NodeType.DOSSIER.value,
                "labels": [],
                "props": {"case_kinds": kinds},
            }
            for key, kinds in sorted_kinds.items()
            if key in stored and stored[key] != kinds
        ]
        if changed:
            self.store.bulk_insert_or_update_nodes(COLLECTION_DOSSIERS, changed)
        logger.info(
            "Refreshed case_kinds on %d of %d dossiers.", len(changed), len(wanted)
        )

    def _backfill_titles_and_stages(self, dossier_nodes: dict[str, Node]) -> None:
        """Persist title, stages and opening date on each dossier from what it links to.

        A dossier with no title of its own takes the first voorstel-van-wet or
        MvT title it links to, recording the provenance in ``title_source``.
        ``stages_present`` is every recognised stage with at least one signal,
        in chronological order, and ``current_stage`` is the last of them
        (``afgehandeld`` once ``semantic tk-dossier-outcomes`` closed it).
        ``opened_on`` is the date of its first document or activity.
        """
        nodes = _unique(dossier_nodes)
        if not nodes:
            return

        signals = self._dossier_signals(
            [f"{COLLECTION_DOSSIERS}/{node.key}" for node in nodes]
        )
        titles = stages = 0
        for node in nodes:
            row = signals.get(f"{COLLECTION_DOSSIERS}/{node.key}") or {}
            titles += self._apply_title(node, row.get("docs") or [])
            stages += self._apply_stages(node, row)

        self._upsert_nodes(nodes)
        logger.info(
            "Backfilled a title on %d dossiers and stages on %d.", titles, stages
        )

    def _dossier_signals(self, dossier_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Documents, activities and decisions per dossier, in chunked queries."""
        rows: dict[str, dict[str, Any]] = {}
        for chunk in chunked(dossier_ids, _BACKFILL_CHUNK):
            for row in normalize_queries.dossier_signals(self.store, chunk):
                rows[row["dossier_id"]] = row
            logger.info(
                "Collected signals for %d of %d dossiers.", len(rows), len(dossier_ids)
            )
        return rows

    @staticmethod
    def _apply_title(node: Node, docs: list[dict[str, Any]]) -> int:
        title, title_source = select_title(node.props, docs)
        if title_source != "document":
            return 0
        node.props["title"] = title
        node.props["title_source"] = "document"
        node.props["display_name"] = dossier_display_name(
            node.props.get("number") or node.key or "",
            node.props.get("suffix"),
            title or "",
        )
        return 1

    @staticmethod
    def _apply_stages(node: Node, row: dict[str, Any]) -> int:
        docs = row.get("docs") or []
        activities = row.get("activities") or []
        decisions = row.get("decisions") or []
        # Refreshed in the database by _refresh_case_kinds, not on this node.
        case_kinds = list(row.get("case_kinds") or [])
        # Whether it is closed is the answer of ``semantic tk-dossier-outcomes``, as stored.
        closed = bool(row.get("closed"))

        track_kind = classify_track_kind(
            case_kinds,
            title=node.props.get("title"),
            document_kinds=[doc.get("kind") or "" for doc in docs],
        )
        current_stage, stages_present = dossier_stages(
            track_kind, docs, activities, decisions, case_kinds, closed=closed
        )
        dated = [d["date"] for d in docs + activities if d.get("date")]
        opened_on = min(dated) if dated else row.get("opened_on")

        unchanged = (
            list(node.props.get("stages_present") or []) == stages_present
            and node.props.get("current_stage") == current_stage
            and node.props.get("track_kind") == track_kind
        )
        node.props["stages_present"] = stages_present
        node.props["current_stage"] = current_stage
        node.props["track_kind"] = track_kind
        node.props["opened_on"] = opened_on
        return 0 if unchanged else 1


def _unique(nodes: dict[str, Node]) -> list[Node]:
    """The distinct nodes of a dict that indexes each of them under two keys."""
    seen: set[int] = set()
    out: list[Node] = []
    for node in nodes.values():
        if id(node) not in seen:
            seen.add(id(node))
            out.append(node)
    return out
