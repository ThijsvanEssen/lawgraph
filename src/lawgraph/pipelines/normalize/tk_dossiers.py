"""Normalize the parliamentary records of the Tweede Kamer into the graph.

The pipeline is the order in which the nodes must exist:

  1. committees, members, factions, dossiers  — no dependencies
  2. activities, decisions, commitments, documents
  3. edges, which need both endpoints stored

Node building lives next door, one module per part of the model:
``tk_members`` (committees, members, factions), ``tk_votes`` (decisions and
the votes on them) and ``tk_cases`` (activities, commitments, documents and
what they are about). The dossier itself — its title, its kind and phases, when it
opened — is what this module keeps; whether and how it ended is ``semantic tk-dossier-outcomes``.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_BESLUIT,
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
    dossier_display_name,
    opened_on,
    phase_props,
    select_title,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.progress import Progress
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize import _tk_members as tk_members
from lawgraph.pipelines.normalize import _tk_votes as tk_votes
from lawgraph.pipelines.normalize._tk_deleted import Deleted
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, RawRecords

logger = get_logger(__name__)

EDGE_SOURCE = "tk-dossiers"

RAW_KINDS = [
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_BESLUIT,
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
            # A deleted row names no decision; the VOTED edge it made does, so the rows and
            # the Besluit of that decision are read again too.
            since_iso = iso_timestamp(since)
            deleted = list(
                raw_queries.deleted_records_since(
                    self.store, RAW_KIND_TK_STEMMING, since_iso
                )
            )
            voted_on = [
                row["decision_id"]
                for row in normalize_tk.decisions_of_vote_records(
                    self.store, [str(self._payload_json(r).get("Id")) for r in deleted]
                )
                if row["decision_id"]
            ]
            raw[RAW_KIND_TK_STEMMING] = self._rows_of_decisions_voted_since(
                since_iso, voted_on, deleted
            )
            raw[RAW_KIND_TK_BESLUIT] = self._besluiten(
                raw[RAW_KIND_TK_BESLUIT], voted_on
            )
        return raw

    def _rows_of_decisions_voted_since(
        self,
        since_iso: str | None,
        voted_on: list[str],
        deleted: list[dict[str, Any]],
    ) -> Iterator[dict[str, Any]]:
        """Every Stemming row of the decisions that have a row in the window or that a
        *deleted* row of the window was on (*voted_on*), and those deleted rows.

        A decision is its rows together (the tally, who voted): one corrected vote must
        not turn it into a decision of one.
        """
        decisions = sorted(
            set(raw_queries.decisions_voted_since(self.store, since_iso))
            | set(voted_on)
        )
        progress = Progress(f"{RAW_KIND_TK_STEMMING} records")
        yield from progress.track(
            raw_queries.vote_rows_of_decisions(self.store, decisions)
            if decisions
            else ()
        )
        yield from deleted

    def _besluiten(
        self, window: Iterable[dict[str, Any]], voted_on: list[str]
    ) -> Iterator[dict[str, Any]]:
        """The Besluit records of the window, and those of the decisions *voted_on*: a
        Besluit whose votes were all deleted stays a decision."""
        yield from window
        if voted_on:
            yield from self.store.with_payloads(
                raw_queries.tk_records_of(self.store, RAW_KIND_TK_BESLUIT, voted_on)
            )

    def normalize_nodes(
        self,
        raw: dict[str, Iterable[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        store = self.store
        votes = tk_votes.read_votes(raw[RAW_KIND_TK_STEMMING])
        self._add_bill_decisions(votes, raw[RAW_KIND_TK_BESLUIT])
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
                store, raw[RAW_KIND_TK_FRACTIE], vote_labels, self._every_seat()
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
        tk_votes.remove_deleted_votes(store, votes, normalized["decisions"])
        self._refresh_case_kinds(normalized["activities"])
        return normalized

    def _add_bill_decisions(
        self, votes: tk_votes.Votes, raw_records: Iterable[dict[str, Any]]
    ) -> None:
        """Add the Besluiten on bills, also those without votes (a hamerstuk). An
        incremental run first reads the stored vote rows of those its window holds no
        rows of, so a Besluit that changed does not lose its votes."""
        payloads = [
            payload
            for raw in raw_records
            if not votes.struck(payload := self._payload_json(raw))
        ]
        if self._incremental:
            unseen = [
                decision_id
                for payload in payloads
                if (decision_id := str(payload.get("Id") or ""))
                and decision_id not in votes.by_decision
            ]
            if unseen:
                tk_votes.merge_votes(
                    votes,
                    tk_votes.read_votes(
                        raw_queries.vote_rows_of_decisions(self.store, unseen)
                    ),
                )
        added = tk_votes.add_decisions(votes, payloads)
        votes.drop_struck()  # a Besluit record the Kamer deleted, and its decision
        logger.info("Added %d decisions on bills without votes.", added)

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
        tk_members.name_nameless_members(
            store, normalized["members"], normalized["votes"], normalized["documents"]
        )

        # Once the edges exist, each dossier's documents can be walked to
        # derive its title and phases, so reads stay O(1).
        self._backfill_titles_and_phases(normalized["dossiers"])

    def _every_seat(self) -> RawRecords:
        """Every FractieZetelPersoon record, also on a run over a window: the seats date a
        faction (1,236 records)."""
        return RawRecords(
            self,
            source=SOURCE_TK,
            kinds=[RAW_KIND_TK_FRACTIEZETELPERSOON],
            since=None,
            batch_size=1000,
        )

    def _stored_faction_aliases(self) -> set[str]:
        return set(normalize_tk.faction_aliases(self.store))

    def _stored(self, collection: str, node_type: NodeType) -> dict[str, Node]:
        """The stored nodes of *collection* by TK ``Id``, with the props the edges read."""
        rows = normalize_tk.nodes_by_external_id(
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
        """Kamerstukdossier nodes, keyed by TK ``Id`` *and* by dossier number; the node of a
        dossier the Kamer deleted is removed."""
        nodes: dict[str, Node] = {}
        deleted = Deleted(COLLECTION_DOSSIERS, key=None)  # keyed by the dossier number
        for raw in raw_records:
            payload = self._payload_json(raw)
            if deleted(payload):
                continue
            parsed = tk_records.dossier(payload)
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
        removed = deleted.remove(self.store)
        logger.info(
            "Normalized %d dossiers; removed %d the Kamer deleted.",
            len(unique),
            removed,
        )
        self._refresh_same_number_counts({str(node.props["number"]) for node in unique})
        return nodes

    def _refresh_same_number_counts(self, numbers: set[str]) -> None:
        """Write on every dossier of these *numbers* how many other dossiers share it.

        This pipeline is the one writer of dossiers, so a new chapter of a budget reaches the
        count of all its siblings here, also in an incremental run.
        """
        rows = [
            row
            for chunk in chunked(sorted(numbers), 5000)
            for row in normalize_tk.dossiers_of_numbers(self.store, chunk)
        ]
        per_number = Counter(row["number"] for row in rows)
        changed = [
            {
                "_key": row["key"],
                "type": NodeType.DOSSIER.value,
                "labels": [],
                "props": {"same_number_count": per_number[row["number"]] - 1},
            }
            for row in rows
            if row.get("same_number_count") != per_number[row["number"]] - 1
        ]
        if changed:
            self.store.bulk_insert_or_update_nodes(COLLECTION_DOSSIERS, changed)
        logger.info("Refreshed the same-number count on %d dossiers.", len(changed))

    def _refresh_case_kinds(self, activity_nodes: dict[str, Node]) -> None:
        """Roll the ``Zaak.Soort`` values reachable per dossier onto the dossier.

        That list feeds the kind of the dossier in the backfill, which is the only
        writer of ``kind``, ``phases`` and ``current_phase``; writing them here too
        would blank the previous answer for the span between the two steps.
        """
        wanted: dict[str, set[str]] = {}
        for node in activity_nodes.values():
            by_dossier = node.props.get("case_kinds_by_dossier") or {}
            for number, kinds in by_dossier.items():
                wanted.setdefault(make_node_key(number), set()).update(kinds)
        sorted_kinds = {key: sorted(kinds) for key, kinds in wanted.items()}

        stored: dict[str, Any] = {}
        for keys in chunked(sorted_kinds, 5000):
            for row in normalize_tk.dossier_case_kinds(self.store, keys):
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

    def _backfill_titles_and_phases(self, dossier_nodes: dict[str, Node]) -> None:
        """Persist title, kind, phases and opening date on each dossier from what it links
        to.

        A dossier with no title of its own takes the first voorstel-van-wet or
        MvT title it links to, recording the provenance in ``title_source``.
        ``kind``, ``kind_basis``, ``phases`` and ``current_phase`` are those of
        :func:`~lawgraph.core.dossier_stages.phase_props`. ``opened_on`` is the date of
        nr. 1 of its own numbering, else of its Koninklijke boodschap, else of its first
        document or activity (``opened_on_basis`` says which).
        """
        nodes = _unique(dossier_nodes)
        if not nodes:
            return

        signals = self._dossier_signals(
            [f"{COLLECTION_DOSSIERS}/{node.key}" for node in nodes]
        )
        titles = phases = 0
        for node in nodes:
            row = signals.get(f"{COLLECTION_DOSSIERS}/{node.key}") or {}
            titles += self._apply_title(node, row.get("docs") or [])
            phases += self._apply_phases(node, row)

        self._upsert_nodes(nodes)
        logger.info(
            "Backfilled a title on %d dossiers and phases on %d.", titles, phases
        )

    def _dossier_signals(self, dossier_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Documents, activities and decisions per dossier, in chunked queries."""
        rows: dict[str, dict[str, Any]] = {}
        for chunk in chunked(dossier_ids, _BACKFILL_CHUNK):
            for row in normalize_tk.dossier_signals(self.store, chunk):
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
    def _apply_phases(node: Node, row: dict[str, Any]) -> int:
        docs = row.get("docs") or []
        activities = row.get("activities") or []
        props = phase_props(
            list(row.get("case_kinds") or []),
            docs,
            activities,
            row.get("decisions") or [],
        )
        day, basis = opened_on(
            node.props.get("number"), node.props.get("suffix"), docs, activities
        )
        props["opened_on"] = day or row.get("opened_on")
        props["opened_on_basis"] = basis if day else row.get("opened_on_basis")

        unchanged = all(node.props.get(name) == value for name, value in props.items())
        node.props.update(props)
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
