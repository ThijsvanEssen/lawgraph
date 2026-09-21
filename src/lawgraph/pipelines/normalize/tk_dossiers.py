"""Normalize the parliamentary records of the Tweede Kamer into the graph.

The pipeline is the order in which the nodes must exist:

  1. committees, members, factions, dossiers  — no dependencies
  2. activities, decisions, commitments, documents
  3. edges, which need both endpoints stored

Node building lives next door, one module per part of the model:
``tk_members`` (committees, members, factions), ``tk_votes`` (decisions and
the votes on them) and ``tk_cases`` (activities, commitments, documents and
what they are about). The dossier itself — its title, its stage, its outcome —
is what this module keeps.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_RAW_SOURCES,
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
    accumulate_stage_signals,
    classify_track_kind,
    dossier_display_name,
    pick_current_stage,
    select_title,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.progress import Progress
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.normalize import tk_cases, tk_members, tk_votes
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
        bind_vars = {"source": SOURCE_TK, "kind": RAW_KIND_TK_STEMMING}
        touched = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.fetched_at >= @since
            FILTER r.payload_json.Besluit_Id != null
            RETURN DISTINCT r.payload_json.Besluit_Id
        """
        decisions = list(
            self.store.query(touched, {**bind_vars, "since": iso_timestamp(since)})
        )
        rows = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            FILTER r.payload_json.Besluit_Id IN @decisions
            RETURN r
        """
        progress = Progress(f"{RAW_KIND_TK_STEMMING} records")
        yield from progress.track(
            self.store.query(rows, {**bind_vars, "decisions": decisions})
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
        aql = f"""
        FOR faction IN {COLLECTION_FACTIONS}
            FOR alias IN faction.props.aliases || []
                RETURN DISTINCT alias
        """
        return set(self.store.query(aql))

    def _stored(self, collection: str, node_type: NodeType) -> dict[str, Node]:
        """The stored nodes of *collection* by TK ``Id``, with the props the edges read."""
        aql = f"""
        FOR d IN {collection}
            FILTER d.props.external_id != null
            RETURN {{
                key: d._key,
                id: d.props.external_id,
                props: KEEP(d.props, @names)
            }}
        """
        return {
            row["id"]: Node(
                collection=collection,
                type=node_type,
                key=row["key"],
                props=row["props"],
                _skip_validation=True,
            )
            for row in self.store.query(aql, {"names": list(tk_cases.LINK_PROPS)})
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
            kinds = node.props.get("case_kinds") or []
            for number in node.props.get("dossier_numbers") or []:
                wanted.setdefault(make_node_key(str(number)), set()).update(kinds)
        sorted_kinds = {key: sorted(kinds) for key, kinds in wanted.items()}

        stored: dict[str, Any] = {}
        lookup = f"""
        FOR dossier IN {COLLECTION_DOSSIERS}
            FILTER dossier._key IN @keys
            RETURN {{key: dossier._key, case_kinds: dossier.props.case_kinds}}
        """
        for keys in chunked(sorted_kinds, 5000):
            for row in self.store.query(lookup, {"keys": keys}):
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
        """Persist title, stages and outcome on each dossier from what it links to.

        A dossier with no title of its own takes the first voorstel-van-wet or
        MvT title it links to, recording the provenance in ``title_source``.
        ``stages_present`` is every recognised stage with at least one signal,
        in chronological order, and ``current_stage`` is the last of them.
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
        """Documents, activities and decisions per dossier, in chunked queries.

        Every subquery returns the few fields that are used: a list of whole documents (their
        text, their payload) is built in the memory of the server before it is projected.
        """
        signal = """{
                            id: doc._id,
                            kind: doc.props.kind,
                            date: doc.props.date,
                            title: (doc.props.title != null ? doc.props.title
                                    : doc.props.display_name)
                        }"""
        aql = f"""
        FOR dossier_id IN @dossier_ids
            LET direct = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == @part_of
                    FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
                    LET doc = DOCUMENT(e._from)
                    FILTER doc != null
                    RETURN {signal}
            )
            LET via_case = (
                FOR e1 IN {COLLECTION_EDGES}
                    FILTER e1._to == dossier_id AND e1.relation == @part_of
                    FILTER STARTS_WITH(e1._from, '{COLLECTION_CASES}/')
                    FOR e2 IN {COLLECTION_EDGES}
                        FILTER e2._to == e1._from AND e2.relation == @part_of
                        FILTER STARTS_WITH(e2._from, '{COLLECTION_DOCUMENTS}/')
                        LET doc = DOCUMENT(e2._from)
                        FILTER doc != null
                        RETURN {signal}
            )
            LET subjects = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == @about
                    LET node = DOCUMENT(e._from)
                    FILTER node != null
                    RETURN {{
                        id: node._id,
                        kind: node.props.kind,
                        date: node.props.date,
                        passed: node.props.passed
                    }}
            )
            RETURN {{
                dossier_id: dossier_id,
                docs: (
                    FOR doc IN UNIQUE(APPEND(direct, via_case))
                        RETURN UNSET(doc, "id")
                ),
                activities: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_ACTIVITIES}/')
                        RETURN {{kind: node.kind, date: node.date}}
                ),
                decisions: (
                    FOR node IN subjects
                        FILTER STARTS_WITH(node.id, '{COLLECTION_DECISIONS}/')
                        RETURN {{date: node.date, passed: node.passed}}
                )
            }}
        """
        rows: dict[str, dict[str, Any]] = {}
        bind = {"part_of": RELATION_PART_OF, "about": RELATION_ABOUT}
        for chunk in chunked(dossier_ids, _BACKFILL_CHUNK):
            for row in self.store.query(aql, {**bind, "dossier_ids": chunk}):
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
        case_kinds = list(node.props.get("case_kinds") or [])
        closed = bool(node.props.get("closed") or node.props.get("closed_on"))

        signals = accumulate_stage_signals(docs, activities, decisions, case_kinds)
        current_stage, stages_present = pick_current_stage(signals, closed=closed)
        if current_stage is None:
            current_stage = (
                "onbekend"
                if docs or activities
                else node.props.get("current_stage") or "onbekend"
            )
        track_kind = classify_track_kind(case_kinds, title=node.props.get("title"))

        if closed and not node.props.get("outcome"):
            outcome = dossier_outcome(docs, decisions)
            if outcome:
                node.props["outcome"] = outcome

        unchanged = (
            list(node.props.get("stages_present") or []) == stages_present
            and node.props.get("current_stage") == current_stage
            and node.props.get("track_kind") == track_kind
        )
        node.props["stages_present"] = stages_present
        node.props["current_stage"] = current_stage
        node.props["track_kind"] = track_kind
        return 0 if unchanged else 1


def dossier_outcome(
    docs: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> str | None:
    """How a closed dossier ended: aangenomen, verworpen or ingetrokken."""
    for doc in docs:
        kind = (doc.get("kind") or "").lower()
        if "intrekking" in kind or "ingetrokken" in kind:
            return "ingetrokken"
    for decision in decisions:
        passed = decision.get("passed")
        if passed is True:
            return "aangenomen"
        if passed is False:
            return "verworpen"
    return None


def _unique(nodes: dict[str, Node]) -> list[Node]:
    """The distinct nodes of a dict that indexes each of them under two keys."""
    seen: set[int] = set()
    out: list[Node] = []
    for node in nodes.values():
        if id(node) not in seen:
            seen.add(id(node))
            out.append(node)
    return out
