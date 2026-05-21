"""Normalize pipeline: turn raw parliamentary dossier records into graph nodes and edges.

Processing order matters:
  1. Commissies  — no dependencies
  2. Personen    — no dependencies
  3. Dossiers    — no dependencies
  4. Activiteiten — depend on Commissie nodes
  5. Stemmingen  — grouped by Besluit_Id (expanded Besluit record)
  6. Toezeggingen — depend on Activiteit nodes

Edges written:
  - Zaak → Kamerstukdossier          (DEEL_VAN_DOSSIER, strict)
  - Publication → Kamerstukdossier   (DEEL_VAN_DOSSIER, via dossier_nummer prop)
  - Activiteit → Kamerstukdossier    (DEEL_VAN_DOSSIER)
  - Activiteit → Commissie           (BEHANDELD_DOOR)
  - Toezegging → Activiteit          (GEDAAN_IN)
  - Lid → Commissie                  (LID_VAN, from CommissieZetel)
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.api.queries import (
    DOSSIER_STAGES,
    classify_doc_soort,
    classify_traject_kind,
    classify_zaak_soort,
)
from lawgraph.config.constants import (
    COLLECTION_ACTIVITEITEN,
    COLLECTION_COMMISSIES,
    COLLECTION_FRACTIES,
    COLLECTION_KAMERSTUKDOSSIERS,
    COLLECTION_LEDEN,
    COLLECTION_PUBLICATIONS,
    COLLECTION_STEMMINGEN,
    COLLECTION_TOEZEGGINGEN,
    EDGE_STATUS_CANONIEK,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RELATION_AUTEUR_VAN,
    RELATION_BEHANDELD_DOOR,
    RELATION_DEEL_VAN_DOSSIER,
    RELATION_GEDAAN_IN,
    RELATION_LID_VAN,
    RELATION_LID_VAN_FRACTIE,
    RELATION_STEMT,
    SOURCE_TK,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)

_TOEZEGGING_STATUS_MAP = {
    "Openstaand": "open",
    "Afgedaan": "gedaan",
    "Niet nagekomen": "vervallen",
    "Nagekomen": "gedaan",
}


def _compute_dossier_outcome(
    docs: list[dict[str, Any]],
    stemmingen: list[dict[str, Any]],
) -> str | None:
    """Derive the legislative outcome for a closed dossier.

    Returns:
        'aangenomen' | 'verworpen' | 'ingetrokken' | None (if undetermined)
    """
    # Check for explicit intrekking in the documents
    for doc in docs:
        soort = (doc.get("soort") or "").lower()
        if "intrekking" in soort or "ingetrokken" in soort:
            return "ingetrokken"

    if not stemmingen:
        return None

    # Find the most decisive stemming — prefer votes that have an explicit
    # aangenomen value over those without.
    for stemming in stemmingen:
        aangenomen = stemming.get("aangenomen")
        if aangenomen is True:
            return "aangenomen"
        if aangenomen is False:
            return "verworpen"

    return None


class TkDossiersNormalizePipeline(NormalizePipeline):
    """Normalize raw TK parliamentary dossier entities into graph nodes and edges."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        kinds = [
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
        rows = self._query_raw_sources(source=SOURCE_TK, kinds=kinds, since=since)
        grouped = self._group_by_kind(rows, kinds=kinds)
        for kind in kinds:
            logger.info(
                "Loaded %d raw records for kind=%s",
                len(grouped.get(kind, [])),
                kind,
            )
        return grouped

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        commissie_nodes = self._normalize_commissies(raw.get(RAW_KIND_TK_COMMISSIE, []))
        lid_nodes = self._normalize_personen(raw.get(RAW_KIND_TK_PERSOON, []))
        dossier_nodes = self._normalize_dossiers(raw.get(RAW_KIND_TK_DOSSIER, []))
        activiteit_nodes = self._normalize_activiteiten(
            raw.get(RAW_KIND_TK_ACTIVITEIT, [])
        )
        stemming_nodes = self._normalize_stemmingen(raw.get(RAW_KIND_TK_STEMMING, []))
        # Canonical Fractie list comes from the Fractie endpoint. We fall back
        # to deriving fracties from ActorFractie strings in stemmingen when no
        # Fractie raws are loaded yet (older snapshots), so backwards-compat
        # is preserved during the migration.
        fractie_raws = raw.get(RAW_KIND_TK_FRACTIE, [])
        # Stash stemmingen raws so _normalize_fracties can derive aliases from
        # ActorFractie strings (TK abbrev. inconsistency: e.g. NSC).
        self._raw_stemmingen_cache = raw.get(RAW_KIND_TK_STEMMING, [])
        if fractie_raws:
            fractie_nodes = self._normalize_fracties(fractie_raws)
        else:
            fractie_nodes = self._normalize_fracties_from_stemmingen(
                raw.get(RAW_KIND_TK_STEMMING, [])
            )
        toezegging_nodes = self._normalize_toezeggingen(
            raw.get(RAW_KIND_TK_TOEZEGGING, [])
        )
        document_nodes = self._normalize_documents(raw.get(RAW_KIND_TK_DOCUMENT, []))

        # Enrich dossier huidige_fase using Zaak.Soort from activiteiten raw data.
        # This must run after both dossier_nodes and activiteit_nodes are built.
        self._enrich_dossier_fasen(raw.get(RAW_KIND_TK_ACTIVITEIT, []))

        return {
            "commissie_nodes": commissie_nodes,
            "lid_nodes": lid_nodes,
            "dossier_nodes": dossier_nodes,
            "activiteit_nodes": activiteit_nodes,
            "stemming_nodes": stemming_nodes,
            "fractie_nodes": fractie_nodes,
            "toezegging_nodes": toezegging_nodes,
            "document_nodes": document_nodes,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        edges = 0

        # Link Zaak (procedures) → Kamerstukdossier
        edges += self._link_zaken_to_dossiers(raw.get(RAW_KIND_TK_DOSSIER, []))

        # Link TK Documents (current batch) → Kamerstukdossier
        edges += self._link_documents_to_dossiers(normalized["document_nodes"])

        # Link BWO Publications already in the DB → Kamerstukdossier via dossier_nummer
        # (TK documents are handled above; this covers the smaller set of BWO pubs)
        edges += self._link_publications_to_dossiers()

        # Link Activiteit → Kamerstukdossier + Activiteit → Commissie
        edges += self._link_activiteiten(
            raw.get(RAW_KIND_TK_ACTIVITEIT, []),
            normalized["activiteit_nodes"],
        )

        # Link Stemming → Activiteit/Zaak
        edges += self._link_stemmingen(
            raw.get(RAW_KIND_TK_STEMMING, []),
            normalized["stemming_nodes"],
        )

        # Link Toezegging → Activiteit
        edges += self._link_toezeggingen(
            raw.get(RAW_KIND_TK_TOEZEGGING, []),
            normalized["toezegging_nodes"],
        )

        # Link Lid → Commissie via CommissieZetel
        edges += self._link_leden_to_commissies(
            raw.get(RAW_KIND_TK_COMMISSIE, []),
            normalized["lid_nodes"],
        )
        # Prefer date-bounded membership edges from FractieZetelPersoon.
        # When that raw kind is unavailable, fall back to the legacy
        # Fractielabel-based linker so existing snapshots keep working.
        fzp_raws = raw.get(RAW_KIND_TK_FRACTIEZETELPERSOON, [])
        if fzp_raws:
            edges += self._normalize_fractie_memberships(
                fzp_raws,
                normalized["lid_nodes"],
                normalized["fractie_nodes"],
            )
        else:
            edges += self._link_leden_to_fracties(
                normalized["lid_nodes"],
                normalized["fractie_nodes"],
            )

        # Link Lid/Fractie → Document (AUTEUR_VAN) for every indiener / co-signer.
        edges += self._link_documents_to_indieners(
            normalized["document_nodes"],
            normalized["fractie_nodes"],
        )

        # Link Fractie → Stemming (STEMT, with meta.stem)
        edges += self._link_fracties_to_stemmingen(
            normalized["stemming_nodes"],
            normalized["fractie_nodes"],
        )

        logger.info("TkDossiersNormalizePipeline: wrote %d edges total.", edges)

        # Once edges exist, walk each dossier's documents and persist the
        # derived titel + stages on the dossier node so reads are O(1) and
        # the frontend can trust the values without a runtime fallback.
        self._backfill_dossier_titel_and_stages(normalized.get("dossier_nodes") or {})

        return edges

    # ── Commissies ─────────────────────────────────────────────────────────────

    def _normalize_commissies(
        self, raw_records: list[dict[str, Any]]
    ) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            if not external_id:
                continue

            naam = payload.get("NaamNL") or payload.get("Naam") or external_id
            afkorting = payload.get("Afkorting") or ""
            slug = make_node_key(afkorting or naam)

            props: dict[str, Any] = {
                "external_id": external_id,
                "naam": naam,
                "afkorting": afkorting,
                "slug": slug,
                "display_name": naam,
            }
            key = make_node_key(external_id)
            node = Node(
                collection=COLLECTION_COMMISSIES,
                type=NodeType.COMMISSIE,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted

        logger.info("Normalized %d commissies.", len(nodes))
        return nodes

    # ── Personen (leden) ───────────────────────────────────────────────────────

    def _normalize_personen(self, raw_records: list[dict[str, Any]]) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            if not external_id:
                continue

            naam = (
                f"{payload.get('Voornamen') or ''} {payload.get('Tussenvoegsel') or ''} "
                f"{payload.get('Achternaam') or ''}"
            ).strip()
            naam = " ".join(naam.split())  # collapse whitespace

            # Fractielabel is a current-snapshot field — only populated for
            # currently-seated MPs. We seed `partij` from it but the canonical
            # value is overwritten by _normalize_fractie_memberships once the
            # FractieZetelPersoon timeline is processed.
            fractie = str(payload.get("Fractielabel") or "").strip() or None

            props: dict[str, Any] = {
                "external_id": external_id,
                "naam": naam,
                "partij": fractie,
                "actief": not bool(payload.get("Verwijderd")),
                "display_name": f"{naam} ({fractie})" if fractie else naam,
            }
            key = make_node_key(external_id)
            node = Node(
                collection=COLLECTION_LEDEN,
                type=NodeType.LID,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted

        logger.info("Normalized %d leden.", len(nodes))
        return nodes

    # ── Kamerstukdossiers ──────────────────────────────────────────────────────

    def _normalize_dossiers(self, raw_records: list[dict[str, Any]]) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            nummer = payload.get("Nummer")
            if not external_id or nummer is None:
                continue

            nummer_str = str(nummer)
            toevoeging = payload.get("Toevoeging") or ""
            # Leave titel None when the source has neither Titel nor Citeertitel
            # so the read-time / backfill enrichment can supply it from a
            # voorstel-van-wet document instead of looking superficially valid.
            titel = payload.get("Titel") or payload.get("Citeertitel") or None
            titel_source = "dossier" if titel else None
            afgedaan = bool(payload.get("Afgedaan"))
            gesloten_op = _iso_date(payload.get("DatumGesloten"))
            geopend_op = _iso_date(payload.get("DatumRegistratie"))

            display_name = f"Kamerstukdossier {nummer_str}"
            if toevoeging:
                display_name += f"-{toevoeging}"
            if titel:
                display_name += f": {titel}"

            # Only set huidige_fase/stages_present/traject_kind for closed
            # dossiers (where 'afgehandeld' is unambiguous). For active ones,
            # omit those keys so the AQL MERGE preserves whatever the previous
            # backfill wrote — preventing every pipeline run from wiping the
            # classifier output for the entire window between _normalize_dossiers
            # and _backfill_dossier_titel_and_stages.
            props: dict[str, Any] = {
                "external_id": external_id,
                "nummer": int(nummer),
                "kamerstuknummer": nummer_str,
                "toevoeging": toevoeging,
                "titel": titel,
                "titel_source": titel_source,
                "afgedaan": afgedaan,
                "geopend_op": geopend_op,
                "gesloten_op": gesloten_op,
                "display_name": display_name,
            }
            if afgedaan or gesloten_op:
                props["huidige_fase"] = "afgehandeld"

            # Natural key: nummer (+ toevoeging if present)
            key_parts = [nummer_str]
            if toevoeging:
                key_parts.append(toevoeging)
            key = make_node_key(*key_parts)

            node = Node(
                collection=COLLECTION_KAMERSTUKDOSSIERS,
                type=NodeType.DOSSIER,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted
            # Index by nummer (+ toevoeging) to avoid collisions between dossiers
            # with the same nummer but different toevoeging (e.g. "I" vs "II").
            dict_key = f"{nummer_str}-{toevoeging}" if toevoeging else nummer_str
            nodes[dict_key] = inserted

        logger.info("Normalized %d kamerstukdossiers.", len(nodes) // 2 or len(nodes))
        return nodes

    # ── Dossier fase enrichment ────────────────────────────────────────────────

    _WETGEVING_SOORTEN = frozenset(["Wetgeving", "Initiatiefwetgeving"])

    def _enrich_dossier_fasen(self, activiteit_raws: list[dict[str, Any]]) -> None:
        """Persist the Zaak.Soort roll-up onto each dossier.

        Collects every distinct ``Zaak.Soort`` value reachable through the
        dossier's activiteiten and writes them to ``props.zaak_soorten``.
        That list feeds both ``classify_traject_kind`` (kind-of-dossier) and
        ``classify_zaak_soort`` (stage signals) in the later backfill —
        which is now the sole writer of ``huidige_fase``, ``traject_kind``,
        and ``stages_present``. We deliberately do not touch those fields
        here; doing so would briefly clobber the previous backfill's output
        between this step and the new one.
        """
        # Collect: dossier_nummer → set of Zaak.Soort values
        dossier_soorten: dict[str, set[str]] = {}
        for raw in activiteit_raws:
            payload = self._payload_json(raw)
            for agendapunt in payload.get("Agendapunt") or []:
                if not isinstance(agendapunt, dict):
                    continue
                for zaak in agendapunt.get("Zaak") or []:
                    if not isinstance(zaak, dict):
                        continue
                    zaak_soort = zaak.get("Soort") or ""
                    for dossier in zaak.get("Kamerstukdossier") or []:
                        if not isinstance(dossier, dict):
                            continue
                        nummer = dossier.get("Nummer")
                        if nummer:
                            dossier_soorten.setdefault(str(nummer), set()).add(
                                zaak_soort
                            )

        updated = 0
        for nummer, soorten in dossier_soorten.items():
            dossier_key = make_node_key(nummer)
            dossier_node = self.store.get_node(
                COLLECTION_KAMERSTUKDOSSIERS, dossier_key
            )
            if not dossier_node:
                continue

            new_soorten = sorted(soorten)
            if dossier_node.props.get("zaak_soorten") != new_soorten:
                dossier_node.props["zaak_soorten"] = new_soorten
                self.store.insert_or_update(dossier_node)
                updated += 1

        logger.info(
            "Refreshed zaak_soorten on %d dossiers (from %d dossier→zaak mappings).",
            updated,
            len(dossier_soorten),
        )

    # ── Dossier titel + stage backfill ─────────────────────────────────────────

    @staticmethod
    def _derive_titel_for_dossier(
        props: dict[str, Any], docs: list[dict[str, Any]]
    ) -> tuple[str | None, str | None]:
        """Return (picked_titel, display_name) derived from linked documents.

        Priority: wetsvoorstel title → MvT title → any document with a title.
        Returns (None, None) when no title can be found or one is already set.
        """
        if props.get("titel"):
            return None, None
        wets: str | None = None
        mvt: str | None = None
        any_titel: str | None = None
        for d in docs:
            titel = d.get("titel")
            if not titel:
                continue
            if any_titel is None:
                any_titel = titel
            soort = classify_doc_soort(d.get("soort"))
            if soort == "wetsvoorstel" and wets is None:
                wets = titel
            elif soort == "mvt" and mvt is None:
                mvt = titel
            if wets and mvt:
                break
        picked = wets or mvt or any_titel
        if not picked:
            return None, None
        nummer = props.get("kamerstuknummer") or props.get("key") or ""
        toevoeging = props.get("toevoeging") or ""
        display_name = f"Kamerstukdossier {nummer}"
        if toevoeging:
            display_name += f"-{toevoeging}"
        display_name += f": {picked}"
        return picked, display_name

    @staticmethod
    def _derive_stage_signals(
        docs: list[dict[str, Any]],
        activiteiten: list[dict[str, Any]],
        zaak_soorten: list[str],
        stemmingen: list[dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, str], bool]:
        """Accumulate stage_first, stage_last, and any_signal from all evidence.

        Returns (stage_first, stage_last, any_signal).
        """
        stage_first: dict[str, str] = {}
        stage_last: dict[str, str] = {}
        any_signal = False

        def _record(stage: str | None, datum: str | None) -> None:
            if stage is None:
                return
            d = datum or ""
            if stage not in stage_first or (d and d < stage_first[stage]):
                stage_first[stage] = d
            if stage not in stage_last or (d and d > stage_last[stage]):
                stage_last[stage] = d

        for doc in docs:
            stage = classify_doc_soort(doc.get("soort"))
            if stage is not None:
                any_signal = True
            _record(stage, doc.get("datum"))

        for act in activiteiten:
            stage = classify_doc_soort(act.get("soort")) or classify_zaak_soort(
                act.get("soort")
            )
            if stage is not None:
                any_signal = True
            _record(stage, act.get("datum"))

        for soort in zaak_soorten:
            stage = classify_zaak_soort(soort)
            if stage is not None and stage not in stage_first:
                any_signal = True
                stage_first[stage] = ""
                stage_last[stage] = ""

        if stemmingen:
            any_signal = True
            datums = [s.get("datum") for s in stemmingen if s.get("datum")]
            _record("stemming", min(datums) if datums else None)
            if datums:
                stage_last["stemming"] = max(datums)

        return stage_first, stage_last, any_signal

    def _backfill_dossier_titel_and_stages(
        self, dossier_nodes: dict[str, Node]
    ) -> None:
        """Persist titel (when missing) + stage signals onto each dossier.

        Walks the publications linked to each dossier (directly via
        DEEL_VAN_DOSSIER, or via a procedure) and:

        - copies the first voorstel-van-wet / MvT title onto ``props.titel``
          when no source title was present, and records the provenance in
          ``props.titel_source``;
        - sets ``props.stages_present`` to every recognised stage with at
          least one matching document, in chronological order;
        - replaces ``props.huidige_fase`` with the latest recognised stage,
          falling back to ``'onbekend'`` for dossiers that have documents but
          none classify, and ``'afgehandeld'`` for closed dossiers.
        """
        # Deduplicate (the dossier dict is double-indexed by external_id and
        # by nummer/nummer-toevoeging).
        seen: set[str] = set()
        unique_nodes: list[Node] = []
        for node in dossier_nodes.values():
            if node.props.get("external_id") in seen:
                continue
            seen.add(str(node.props.get("external_id") or node.key or ""))
            unique_nodes.append(node)

        if not unique_nodes:
            return

        dossier_ids = [
            f"{COLLECTION_KAMERSTUKDOSSIERS}/{node.key}" for node in unique_nodes
        ]

        aql = f"""
        FOR dossier_id IN @dossier_ids
            LET direct = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    FILTER SPLIT(e._from, '/')[0] == 'publications'
                    LET pub = DOCUMENT(e._from)
                    FILTER pub != null
                    RETURN pub
            )
            LET via_procedure = (
                FOR e1 IN {COLLECTION_EDGES}
                    FILTER e1._to == dossier_id AND e1.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    FILTER SPLIT(e1._from, '/')[0] == 'procedures'
                    FOR e2 IN {COLLECTION_EDGES}
                        FILTER e2._to == e1._from AND e2.relation == 'PART_OF_PROCEDURE'
                        FILTER SPLIT(e2._from, '/')[0] == 'publications'
                        LET pub = DOCUMENT(e2._from)
                        FILTER pub != null
                        RETURN pub
            )
            LET pubs = UNIQUE(APPEND(direct, via_procedure))
            LET activiteiten = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    FILTER SPLIT(e._from, '/')[0] == 'activiteiten'
                    LET a = DOCUMENT(e._from)
                    FILTER a != null
                    RETURN {{soort: a.props.soort, datum: a.props.datum}}
            )
            LET stemmingen = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    FILTER SPLIT(e._from, '/')[0] == 'stemmingen'
                    LET s = DOCUMENT(e._from)
                    FILTER s != null
                    RETURN {{datum: s.props.datum, aangenomen: s.props.aangenomen}}
            )
            RETURN {{
                dossier_id: dossier_id,
                docs: (
                    FOR p IN pubs
                        RETURN {{
                            soort: p.props.soort,
                            datum: p.props.datum,
                            titel: (p.props.titel != null ? p.props.titel :
                                    p.props.title != null ? p.props.title :
                                    p.props.display_name)
                        }}
                ),
                activiteiten: activiteiten,
                stemmingen: stemmingen
            }}
        """
        # Chunk to keep each AQL query under the cursor TTL — the join over
        # publications/procedures/activiteiten/stemmingen is expensive enough
        # that one query for all 7000+ dossiers can outrun the cursor lifetime.
        rows_by_id: dict[str, dict[str, Any]] = {}
        chunk_size = 500
        for i in range(0, len(dossier_ids), chunk_size):
            chunk = dossier_ids[i : i + chunk_size]
            for row in self.store.query(aql, {"dossier_ids": chunk}):
                rows_by_id[row["dossier_id"]] = row
            logger.info(
                "Backfill query: fetched signals for %d/%d dossiers.",
                len(rows_by_id),
                len(dossier_ids),
            )

        updated_titel = 0
        updated_stages = 0
        for node in unique_nodes:
            did = f"{COLLECTION_KAMERSTUKDOSSIERS}/{node.key}"
            row = rows_by_id.get(did) or {}
            docs = row.get("docs") or []
            activiteiten = row.get("activiteiten") or []
            stemmingen = row.get("stemmingen") or []
            zaak_soorten = list(node.props.get("zaak_soorten") or [])

            # ── Titel ─────────────────────────────────────────────────────
            picked, display_name = self._derive_titel_for_dossier(node.props, docs)
            if picked:
                node.props["titel"] = picked
                node.props["titel_source"] = "document"
                node.props["display_name"] = display_name
                updated_titel += 1

            # ── Stages ────────────────────────────────────────────────────
            # Combine signals from documents (richest), activiteiten and the
            # dossier-level zaak_soorten roll-up (coarser, but available even
            # when no documents are linked), and stemmingen (presence implies
            # the 'stemming' stage).
            stage_first, stage_last, any_signal = self._derive_stage_signals(
                docs, activiteiten, zaak_soorten, stemmingen
            )

            stages_present = sorted(
                stage_first.keys(),
                key=lambda st: (stage_first[st] or "", DOSSIER_STAGES.index(st)),
            )

            afgedaan = bool(node.props.get("afgedaan")) or bool(
                node.props.get("gesloten_op")
            )
            if afgedaan:
                huidige_fase = "afgehandeld"
                if "afgehandeld" not in stages_present:
                    stages_present = [*stages_present, "afgehandeld"]
            elif any_signal:
                huidige_fase = max(
                    stage_last.keys(),
                    key=lambda st: (stage_last[st] or "", DOSSIER_STAGES.index(st)),
                )
            elif docs or activiteiten:
                huidige_fase = "onbekend"
            else:
                huidige_fase = node.props.get("huidige_fase") or "onbekend"

            traject_kind = classify_traject_kind(
                zaak_soorten, titel=node.props.get("titel")
            )

            old_stages = node.props.get("stages_present") or []
            old_fase = node.props.get("huidige_fase")
            old_kind = node.props.get("traject_kind")
            if (
                list(old_stages) != stages_present
                or old_fase != huidige_fase
                or old_kind != traject_kind
            ):
                node.props["stages_present"] = stages_present
                node.props["huidige_fase"] = huidige_fase
                node.props["traject_kind"] = traject_kind
                updated_stages += 1

            # ── Outcome ───────────────────────────────────────────────────
            # Only compute outcome for closed dossiers.
            if afgedaan and not node.props.get("outcome"):
                outcome = _compute_dossier_outcome(docs, stemmingen)
                if outcome:
                    node.props["outcome"] = outcome

            self.store.insert_or_update(node)

        logger.info(
            "Backfilled titel on %d dossiers and stages on %d dossiers.",
            updated_titel,
            updated_stages,
        )

    # ── Activiteiten ───────────────────────────────────────────────────────────

    def _normalize_activiteiten(
        self, raw_records: list[dict[str, Any]]
    ) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            if not external_id:
                continue

            datum = _iso_date(payload.get("Datum"))
            omschrijving = payload.get("Omschrijving") or ""
            soort = payload.get("Soort") or ""

            # Extract dossier nummers + Zaak soorten via
            # Agendapunt → Zaak → Kamerstukdossier chain
            _seen: set[str] = set()
            dossier_nummers: list[str] = []
            zaak_soorten: list[str] = (
                []
            )  # all Zaak.Soort values linked to this activity
            for agendapunt in payload.get("Agendapunt") or []:
                if not isinstance(agendapunt, dict):
                    continue
                for zaak in agendapunt.get("Zaak") or []:
                    if not isinstance(zaak, dict):
                        continue
                    zaak_soort = zaak.get("Soort") or ""
                    if zaak_soort and zaak_soort not in zaak_soorten:
                        zaak_soorten.append(zaak_soort)
                    for dossier in zaak.get("Kamerstukdossier") or []:
                        if not isinstance(dossier, dict):
                            continue
                        nummer = dossier.get("Nummer")
                        if nummer:
                            n = str(nummer)
                            if n not in _seen:
                                _seen.add(n)
                                dossier_nummers.append(n)

            commissie_id: str | None = None
            if payload.get("Voortouwcommissie_Id"):
                commissie_id = str(payload["Voortouwcommissie_Id"])

            display_name = f"{datum or '?'} — {omschrijving or soort}"
            # Direct link to this vergadering on tweedekamer.nl
            tk_url = (
                f"https://www.tweedekamer.nl/vergaderingen/details?id={external_id}"
            )
            props: dict[str, Any] = {
                "external_id": external_id,
                "datum": datum,
                "agenda_titel": omschrijving,
                "soort": soort,
                "commissie_id": commissie_id,
                "dossier_nummers": dossier_nummers,
                "zaak_soorten": zaak_soorten,
                "tk_url": tk_url,
                "display_name": display_name,
                "nummer": str(payload.get("Nummer") or ""),
            }

            key = make_node_key(external_id)
            node = Node(
                collection=COLLECTION_ACTIVITEITEN,
                type=NodeType.ACTIVITEIT,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted

        logger.info("Normalized %d activiteiten.", len(nodes))
        return nodes

    # ── Stemmingen ─────────────────────────────────────────────────────────────

    def _normalize_stemmingen(  # noqa: C901
        self, raw_records: list[dict[str, Any]]
    ) -> dict[str, Node]:
        """Group individual Stemming rows by Besluit_Id, one node per motion.

        The TK API returns one Stemming record per fractie per Besluit. We
        aggregate them into a single Stemming node per Besluit with
        voor/tegen/onthouding breakdowns.
        Fields: ActorFractie (party name), Soort (Voor/Tegen/Onthouden),
        FractieGrootte (seats). Besluit expand: BesluitSoort, BesluitTekst.
        """
        by_besluit: dict[str, list[dict[str, Any]]] = {}
        besluit_payloads: dict[str, dict[str, Any]] = {}

        for raw in raw_records:
            payload = self._payload_json(raw)
            besluit_id = str(payload.get("Besluit_Id") or "")
            if not besluit_id:
                continue
            by_besluit.setdefault(besluit_id, []).append(payload)
            if "Besluit" in payload and isinstance(payload["Besluit"], dict):
                besluit_payloads[besluit_id] = payload["Besluit"]

        nodes: dict[str, Node] = {}
        for besluit_id, votes in by_besluit.items():
            besluit = besluit_payloads.get(besluit_id, {})
            datum = _iso_date(votes[0].get("GewijzigdOp"))
            agendapunt_id = str(besluit.get("Agendapunt_Id") or "")

            # Build a descriptive onderwerp from the Agendapunt → Zaak chain.
            # BesluitTekst is typically just "Aangenomen." / "Verworpen." — not useful.
            # We prefer Agendapunt.Onderwerp (the agenda item description) or
            # the first Zaak.Titel linked to this besluit.
            agendapunt_obj = besluit.get("Agendapunt") or {}
            if isinstance(agendapunt_obj, list):
                agendapunt_obj = agendapunt_obj[0] if agendapunt_obj else {}
            agendapunt_onderwerp = agendapunt_obj.get("Onderwerp") or ""
            vergadering_soort = agendapunt_obj.get("Vergadering_Soort") or ""

            zaak_list = agendapunt_obj.get("Zaak") or []
            _zaak_titels = [z.get("Titel") or "" for z in zaak_list if z.get("Titel")]

            # Dossier nummers reachable via Besluit → Agendapunt → Zaak → Kamerstukdossier
            _seen_dossier: set[str] = set()
            dossier_nummers: list[str] = []
            # Zaken (motions/amendments) on this agendapunt — surfaced so the
            # frontend can show *what* each stemming is about, not just a
            # generic block title. Each entry carries the per-Zaak metadata
            # needed to resolve the underlying Kamerstuk.
            zaken: list[dict[str, Any]] = []
            for zaak in zaak_list:
                if not isinstance(zaak, dict):
                    continue
                zaak_dossiers = []
                for dossier in zaak.get("Kamerstukdossier") or []:
                    if not isinstance(dossier, dict):
                        continue
                    n = str(dossier.get("Nummer") or "")
                    if not n:
                        continue
                    zaak_dossiers.append(n)
                    if n not in _seen_dossier:
                        _seen_dossier.add(n)
                        dossier_nummers.append(n)
                zaken.append(
                    {
                        "nummer": zaak.get("Nummer"),
                        "soort": zaak.get("Soort"),
                        "titel": zaak.get("Titel"),
                        "onderwerp": zaak.get("Onderwerp"),
                        "volgnummer": zaak.get("Volgnummer"),
                        "vergaderjaar": zaak.get("Vergaderjaar"),
                        "dossier_nummers": zaak_dossiers,
                    }
                )

            # AgendapuntZaakBesluitVolgorde is the 1-based index of the
            # specific Zaak this Besluit decided on. When present and in
            # range, treat that Zaak as the primary subject of the stemming.
            volgorde_raw = besluit.get("AgendapuntZaakBesluitVolgorde")
            besluit_volgorde: int | None = None
            try:
                if volgorde_raw is not None:
                    besluit_volgorde = int(volgorde_raw)
            except (TypeError, ValueError):
                besluit_volgorde = None

            primary_zaak: dict[str, Any] | None = None
            if besluit_volgorde is not None and 1 <= besluit_volgorde <= len(zaken):
                primary_zaak = zaken[besluit_volgorde - 1]

            besluit_tekst = besluit.get("BesluitTekst") or ""

            # Compose a human-readable onderwerp.
            #
            # Priority:
            #   1. primary_zaak.onderwerp — the per-motie/amendement subject
            #      ("openbaar maken wachtlijsten woningcorporaties"). This
            #      distinguishes the 18 moties on a single agendapunt.
            #   2. agendapunt_onderwerp — the cluster headline ("Moties
            #      ingediend bij de Wet versterking regie volkshuisvesting").
            #      Honest about being shared across siblings.
            #   3. besluit_tekst, then a synthetic fallback.
            #
            # We deliberately do NOT fall back to primary_zaak.titel or
            # zaak_titels[0]: on a motie those carry the parent dossier's
            # umbrella title and inflict the "18 identical rows" bug.
            primary_onderwerp = (primary_zaak or {}).get("onderwerp") or None
            if primary_onderwerp:
                onderwerp = primary_onderwerp
            elif agendapunt_onderwerp:
                onderwerp = agendapunt_onderwerp
            else:
                onderwerp = besluit_tekst or f"Besluit {besluit_id[:8]}"

            besluit_soort = (
                besluit.get("BesluitSoort") or besluit.get("StemmingsSoort") or ""
            ).lower()

            voor: list[dict[str, Any]] = []
            tegen: list[dict[str, Any]] = []
            onthouding: list[dict[str, Any]] = []

            for vote in votes:
                soort = (vote.get("Soort") or "").lower()
                partij_entry = {
                    "partij": vote.get("ActorFractie") or "",
                    "aantal_zetels": vote.get("FractieGrootte") or 0,
                }
                if "voor" in soort:
                    voor.append(partij_entry)
                elif "tegen" in soort:
                    tegen.append(partij_entry)
                else:
                    onthouding.append(partij_entry)

            if "aangenomen" in besluit_soort:
                aangenomen = True
            elif "verworpen" in besluit_soort:
                aangenomen = False
            else:
                zetels_voor = sum(v["aantal_zetels"] for v in voor)
                zetels_tegen = sum(v["aantal_zetels"] for v in tegen)
                aangenomen = zetels_voor > zetels_tegen

            # Compose a display name that distinguishes stemmingen on the
            # same agendapunt: prefer the primary zaak's nummer + soort, then
            # a "(N/M)" hint when only the volgorde is known. The outcome
            # (aangenomen/verworpen) is intentionally NOT included — the FE
            # renders that as a badge, so repeating it in the title is noise.
            if primary_zaak and primary_zaak.get("nummer"):
                primary_soort = primary_zaak.get("soort") or "Stemming"
                primary_label = primary_zaak.get("nummer")
                head = f"{primary_soort} {primary_label}"
            elif besluit_volgorde is not None and zaken:
                head = f"Stemming {besluit_volgorde}/{len(zaken)}"
            else:
                head = "Stemming"
            # Carry the full onderwerp through to display_name; FE can
            # truncate per layout. The 120-char cut was causing motie subjects
            # to be sliced mid-sentence.
            display_name = f"{head} — {onderwerp}" if onderwerp else head

            props: dict[str, Any] = {
                "besluit_id": besluit_id,
                "agendapunt_id": agendapunt_id,
                "datum": datum,
                "onderwerp": onderwerp,
                "agendapunt_onderwerp": agendapunt_onderwerp,
                "besluit_tekst": besluit_tekst,
                "besluit_volgorde": besluit_volgorde,
                "vergadering_soort": vergadering_soort,
                "dossier_nummers": dossier_nummers,
                "zaken": zaken,
                "primary_zaak": primary_zaak,
                "voor": voor,
                "tegen": tegen,
                "onthouding": onthouding,
                "aangenomen": aangenomen,
                "display_name": display_name,
            }

            key = make_node_key("stemming", besluit_id)
            node = Node(
                collection=COLLECTION_STEMMINGEN,
                type=NodeType.STEMMING,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[besluit_id] = inserted

        logger.info(
            "Normalized %d stemmingen (from %d raw votes).",
            len(nodes),
            len(raw_records),
        )
        return nodes

    # ── Fracties ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_fractie_aliases(
        afkorting: str,
        naam_nl: str,
        label: str,
        stemming_labels: set[str],
    ) -> set[str]:
        """Derive the full alias set for a fractie.

        Includes the afkorting and NaamNL directly, plus any auto-acronym
        validated against known stemming labels, plus any stemming label that
        key-sanitises to the same canonical key as ``label``.
        """
        aliases: set[str] = set()
        if afkorting:
            aliases.add(afkorting)
        if naam_nl:
            aliases.add(naam_nl)
        # Auto-acronym: NaamNL='Nieuw Sociaal Contract' → 'NSC'. Only accept
        # the acronym if a stemming actually uses it (proves cross-endpoint
        # identity); otherwise keep the alias set tight.
        if naam_nl:
            acro = "".join(
                w[0] for w in naam_nl.split() if w and w[0].isalpha()
            ).upper()
            if len(acro) >= 2 and acro in stemming_labels:
                aliases.add(acro)
        # Accept any stemming label that key-sanitises to the same key
        # (covers casing/whitespace variants).
        target_key = make_node_key(label)
        for sl in stemming_labels:
            if make_node_key(sl) == target_key:
                aliases.add(sl)
        return aliases

    def _normalize_fracties(
        self, fractie_raws: list[dict[str, Any]]
    ) -> dict[str, Node]:
        """Build canonical Fractie nodes from the TK Fractie endpoint.

        TK is inconsistent about abbreviations: ``Fractie.Afkorting`` is
        sometimes the full party name (e.g. NSC has Afkorting='Nieuw Sociaal
        Contract'), while ``Stemming.ActorFractie`` uses the real short form
        ('NSC'). We derive an alias set per fractie so cross-endpoint matches
        work in get_lid_votes.
        """
        # Collect ActorFractie strings from stemmingen so we can map them to
        # canonical fracties as aliases.
        stemming_labels: set[str] = set()
        for raw in getattr(self, "_raw_stemmingen_cache", []) or []:
            payload = self._payload_json(raw)
            label = (payload.get("ActorFractie") or "").strip()
            if label:
                stemming_labels.add(label)

        nodes: dict[str, Node] = {}
        by_label: dict[str, Node] = {}

        # TK recycles afkortingen — e.g. 50PLUS dissolves in 2021, reforms in
        # 2025 with a fresh Fractie record but the same Afkorting. Both raws
        # collapse to the same node key. Dedupe so the currently-active record
        # (or, failing that, the most recently updated) wins.
        def _raw_sort_key(raw: dict[str, Any]) -> tuple[int, str]:
            p = self._payload_json(raw)
            still_active = p.get("DatumInactief") is None
            return (1 if still_active else 0, str(p.get("GewijzigdOp") or ""))

        deduped_by_key: dict[str, dict[str, Any]] = {}
        for raw in fractie_raws:
            payload = self._payload_json(raw)
            afk = (payload.get("Afkorting") or "").strip()
            naam = (payload.get("NaamNL") or "").strip()
            label = afk or naam
            if not label:
                continue
            key = make_node_key(label)
            existing = deduped_by_key.get(key)
            if existing is None or _raw_sort_key(raw) > _raw_sort_key(existing):
                deduped_by_key[key] = raw

        for raw in deduped_by_key.values():
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            if not external_id:
                continue
            afkorting = (payload.get("Afkorting") or "").strip()
            naam_nl = (payload.get("NaamNL") or "").strip()
            label = afkorting or naam_nl
            if not label:
                continue

            aliases = self._build_fractie_aliases(
                afkorting, naam_nl, label, stemming_labels
            )

            props: dict[str, Any] = {
                "external_id": external_id,
                "naam": naam_nl or afkorting,
                "afkorting": afkorting or None,
                "aliases": sorted(aliases),
                "datum_actief": _iso_date(payload.get("DatumActief")),
                "datum_inactief": _iso_date(payload.get("DatumInactief")),
                "aantal_zetels": payload.get("AantalZetels"),
                "actief": payload.get("DatumInactief") is None,
                "display_name": afkorting or naam_nl,
            }
            key = make_node_key(label)
            node = Node(
                collection=COLLECTION_FRACTIES,
                type=NodeType.FRACTIE,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted
            for alias in aliases:
                by_label[alias] = inserted

        # Make the label-indexed view available to other linkers (stemmingen,
        # AUTEUR_VAN) that match by ActorFractie text.
        self._fractie_by_label = by_label
        logger.info("Normalized %d fracties (canonical).", len(nodes))
        return nodes

    def _normalize_fracties_from_stemmingen(
        self, stemming_raws: list[dict[str, Any]]
    ) -> dict[str, Node]:
        """Legacy fallback: derive Fractie nodes from ActorFractie strings on
        Stemming rows. Used only when no RAW_KIND_TK_FRACTIE rows are loaded
        (e.g. snapshots predating the FZP migration). Returned dict is keyed
        by ActorFractie label so existing matchers keep working.
        """
        names: set[str] = set()
        for raw in stemming_raws:
            payload = self._payload_json(raw)
            naam = str(payload.get("ActorFractie") or "").strip()
            if naam:
                names.add(naam)

        nodes: dict[str, Node] = {}
        for naam in sorted(names):
            key = make_node_key(naam)
            node = Node(
                collection=COLLECTION_FRACTIES,
                type=NodeType.FRACTIE,
                key=key,
                labels=["TK"],
                props={
                    "naam": naam,
                    "display_name": naam,
                },
            )
            inserted = self.store.insert_or_update(node)
            nodes[naam] = inserted

        self._fractie_by_label = dict(nodes)
        logger.info("Normalized %d fracties (legacy from stemmingen).", len(nodes))
        return nodes

    # ── Toezeggingen ───────────────────────────────────────────────────────────

    def _normalize_toezeggingen(
        self, raw_records: list[dict[str, Any]]
    ) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            if not external_id:
                continue

            tekst = (
                payload.get("TekstAlgemeen")
                or payload.get("TekstBrief")
                or payload.get("Tekst")
                or ""
            )
            minister_naam = (
                payload.get("MinisterNaam")
                or payload.get("NaamMinistrieAfkorting")
                or ""
            )
            minister_functie = payload.get("MinisterTitel") or ""
            gedaan_op = _iso_date(
                payload.get("DatumRegistratie") or payload.get("Datum")
            )
            verwacht = _iso_date(payload.get("VerwachteAfhandeling"))
            raw_status = payload.get("Status") or "Openstaand"
            status = _TOEZEGGING_STATUS_MAP.get(raw_status, "unknown")
            if status == "unknown":
                logger.warning(
                    "Unknown toezegging status %r, defaulting to 'unknown'", raw_status
                )
            activiteit_nummer = str(payload.get("ActiviteitNummer") or "")
            dossier_id = str(payload.get("KamerstukdossierId") or "")

            display_name = (tekst[:80] + "…") if len(tekst) > 80 else tekst

            props: dict[str, Any] = {
                "external_id": external_id,
                "tekst": tekst,
                "minister_naam": minister_naam,
                "minister_functie": minister_functie,
                "gedaan_op": gedaan_op,
                "verwachte_afhandeling": verwacht,
                "status": status,
                "activiteit_nummer": activiteit_nummer,
                "dossier_id": dossier_id,
                "display_name": display_name,
            }

            key = make_node_key(external_id)
            node = Node(
                collection=COLLECTION_TOEZEGGINGEN,
                type=NodeType.TOEZEGGING,
                key=key,
                labels=["TK"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted

        logger.info("Normalized %d toezeggingen.", len(nodes))
        return nodes

    # ── TK Documents (Kamerstukken) ────────────────────────────────────────────

    def _normalize_documents(
        self, raw_records: list[dict[str, Any]]
    ) -> dict[str, "Node"]:
        """Normalize TK Document records into publications nodes.

        The TK Document entity does NOT carry a direct dossier number; it links
        to dossiers via Zaak → Kamerstukdossier (expanded during retrieve).
        Key fields on Document:
          Soort       — Motie, Amendement, Brief van de minister, etc.
          Titel       — full descriptive title
          Volgnummer  — document sequence number within the dossier (e.g. 7)
          Datum       — date of the document
          Vergaderjaar — parliamentary year

        One document may link to multiple dossiers through multiple Zaken.
        All dossier nummers are stored in ``dossier_nummers`` (list); the first
        one is also stored in ``dossier_nummer`` for backwards-compatible edge
        building via ``_link_publications_to_dossiers``.

        Nodes land in the ``publications`` collection so they are automatically
        picked up by dossier-detail count and timeline queries.
        """
        nodes: dict[str, "Node"] = {}
        skipped = 0
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            if not external_id:
                skipped += 1
                continue

            soort = payload.get("Soort") or ""
            titel = payload.get("Titel") or payload.get("Onderwerp") or soort
            volgnummer = payload.get("Volgnummer")  # int or None; -1 = not a Kamerstuk
            datum = _iso_date(payload.get("Datum") or payload.get("DatumRegistratie"))
            vergaderjaar = payload.get("Vergaderjaar") or ""

            # Collect dossier nummers via Zaak → Kamerstukdossier chain, plus
            # the zaak nummers themselves so the timeline endpoint can join a
            # stemming's primary_zaak.nummer back to the document without
            # walking the full raw payload.
            _seen_d: set[str] = set()
            _seen_z: set[str] = set()
            dossier_nummers: list[str] = []
            zaak_nummers: list[str] = []
            for zaak in payload.get("Zaak") or []:
                zn = str(zaak.get("Nummer") or "")
                if zn and zn not in _seen_z:
                    _seen_z.add(zn)
                    zaak_nummers.append(zn)
                for ksd in zaak.get("Kamerstukdossier") or []:
                    n = str(ksd.get("Nummer") or "")
                    if n and n not in _seen_d:
                        _seen_d.add(n)
                        dossier_nummers.append(n)

            primary_dossier = dossier_nummers[0] if dossier_nummers else None

            # Indieners / co-signers (from DocumentActor expand). Persisted on
            # the publication so the frontend can render them without a join.
            actors: list[dict[str, Any]] = []
            for actor in payload.get("DocumentActor") or []:
                persoon_id = str(actor.get("Persoon_Id") or "") or None
                rol = actor.get("Relatie") or ""
                naam = actor.get("ActorNaam") or ""
                fractie = actor.get("ActorFractie") or ""
                if not (persoon_id or naam):
                    continue
                actors.append(
                    {
                        "persoon_id": persoon_id,
                        "fractie_id": str(actor.get("Fractie_Id") or "") or None,
                        "naam": naam,
                        "fractie": fractie,
                        "rol": rol,
                    }
                )

            # Build display_name: "Kamerstuk 29684, nr. 7 — Motie: Titel"
            if primary_dossier and volgnummer is not None and volgnummer > 0:
                display_name = f"Kamerstuk {primary_dossier}, nr. {volgnummer}"
            elif primary_dossier:
                display_name = f"Kamerstuk {primary_dossier}"
            else:
                display_name = soort or "Document"
            if soort:
                display_name += f" — {soort}"
            if titel and titel != soort:
                display_name += f": {titel[:120]}"

            # TK website link for this document
            tk_url = f"https://www.tweedekamer.nl/kamerstukken/detail?id={external_id}"

            props: dict[str, Any] = {
                "external_id": external_id,
                # dossier_nummer (singular) for backwards-compat with
                # _link_publications_to_dossiers — use primary only
                "dossier_nummer": primary_dossier,
                "dossier_nummers": dossier_nummers,
                "zaak_nummers": zaak_nummers,
                "volgnummer": (
                    volgnummer if (volgnummer is not None and volgnummer > 0) else None
                ),
                "soort": soort,
                "titel": titel,
                "datum": datum,
                "vergaderjaar": vergaderjaar,
                "tk_url": tk_url,
                "display_name": display_name,
                "source": SOURCE_TK,
                "actors": actors,
            }

            # Key by external UUID — guaranteed unique, avoids collisions with
            # BWO publications which use different identifiers.
            key = make_node_key(external_id)
            node = Node(
                collection=COLLECTION_PUBLICATIONS,
                type=NodeType.PUBLICATION,
                key=key,
                labels=["TK", "Kamerstuk"],
                props=props,
            )
            inserted = self.store.insert_or_update(node)
            nodes[external_id] = inserted

        logger.info("Normalized %d TK documents (%d skipped).", len(nodes), skipped)
        return nodes

    # ── Edge builders ──────────────────────────────────────────────────────────

    def _link_documents_to_dossiers(self, document_nodes: dict[str, "Node"]) -> int:
        """Create DEEL_VAN_DOSSIER edges from TK Document nodes to Kamerstukdossier nodes.

        Each document may link to multiple dossiers (stored in ``dossier_nummers``).
        Duplicate edge attempts are silently caught and skipped.
        """
        edges = 0
        for _ext_id, doc_node in document_nodes.items():
            if not doc_node.id:
                continue
            # Use dossier_nummers (list); fall back to singular dossier_nummer
            nummers: list[str] = doc_node.props.get("dossier_nummers") or []
            if not nummers:
                singular = str(doc_node.props.get("dossier_nummer") or "")
                if singular:
                    nummers = [singular]
            for nummer in nummers:
                dossier_key = make_node_key(str(nummer))
                dossier_node = self.store.get_node(
                    COLLECTION_KAMERSTUKDOSSIERS, dossier_key
                )
                if not dossier_node or not dossier_node.id:
                    continue
                try:
                    self.store.create_edge(
                        from_id=doc_node.id,
                        to_id=dossier_node.id,
                        relation=RELATION_DEEL_VAN_DOSSIER,
                        source="tk-dossiers",
                        status=EDGE_STATUS_CANONIEK,
                    )
                    edges += 1
                except Exception as exc:
                    logger.error("Document→dossier edge failed: %s", exc)

        logger.info("Linked %d TK documents to dossiers.", edges)
        return edges

    def _link_documents_to_indieners(
        self,
        document_nodes: dict[str, "Node"],
        fractie_nodes: dict[str, "Node"],
    ) -> int:
        """Create AUTEUR_VAN edges from each indiener → publication.

        Two kinds of source nodes:
          * lid (Persoon_Id present on the actor)
          * fractie (ActorFractie label present, matched to fractie node by name)

        Source data is ``props.actors`` populated during _normalize_documents
        from the TK DocumentActor expansion. Edges carry ``meta.rol`` so the
        frontend can distinguish indieners from co-signers / addressees.
        Per-document fractie edges are de-duplicated so a 5-MP-from-VVD
        amendement only writes one VVD edge.
        """
        edges = 0
        for _ext_id, doc_node in document_nodes.items():
            if not doc_node.id:
                continue
            seen_fracties: set[str] = set()
            for actor in doc_node.props.get("actors") or []:
                rol = actor.get("rol") or ""
                persoon_id = actor.get("persoon_id")
                if persoon_id:
                    lid_key = make_node_key(str(persoon_id))
                    if self.store.get_node(COLLECTION_LEDEN, lid_key) is not None:
                        try:
                            self.store.create_edge(
                                from_id=f"{COLLECTION_LEDEN}/{lid_key}",
                                to_id=doc_node.id,
                                relation=RELATION_AUTEUR_VAN,
                                source="tk-dossiers",
                                status=EDGE_STATUS_CANONIEK,
                                meta={"rol": rol},
                            )
                            edges += 1
                        except Exception as exc:
                            logger.error("Lid→document edge failed: %s", exc)

                fractie_naam = (actor.get("fractie") or "").strip()
                if not fractie_naam or fractie_naam in seen_fracties:
                    continue
                # fractie_nodes is keyed by Fractie GUID under the canonical
                # path; resolve via the label index populated by _normalize_fracties.
                fractie_node = getattr(self, "_fractie_by_label", {}).get(
                    fractie_naam
                ) or fractie_nodes.get(fractie_naam)
                if fractie_node is None or not fractie_node.id:
                    # Fall back to a key lookup — covers fracties that only
                    # appear on documents but not in stemmingen of this batch.
                    fractie_key = make_node_key(fractie_naam)
                    if self.store.get_node(COLLECTION_FRACTIES, fractie_key) is None:
                        continue
                    fractie_id = f"{COLLECTION_FRACTIES}/{fractie_key}"
                else:
                    fractie_id = fractie_node.id
                seen_fracties.add(fractie_naam)
                try:
                    self.store.create_edge(
                        from_id=fractie_id,
                        to_id=doc_node.id,
                        relation=RELATION_AUTEUR_VAN,
                        source="tk-dossiers",
                        status=EDGE_STATUS_CANONIEK,
                        meta={"rol": rol},
                    )
                    edges += 1
                except Exception as exc:
                    logger.error("Fractie→document edge failed: %s", exc)

        logger.info("Linked %d AUTEUR_VAN edges (lid + fractie → document).", edges)
        return edges

    def _link_fracties_to_stemmingen(
        self,
        stemming_nodes: dict[str, "Node"],
        fractie_nodes: dict[str, "Node"],
    ) -> int:
        """Create STEMT edges from each fractie → stemming with meta.stem.

        Uses the voor/tegen/onthouding lists already aggregated on the
        stemming node. Per-lid voting is intentionally NOT materialised:
        the TK API only exposes votes per fractie, and lid-level votes are
        derived from partij at read time (see get_lid_votes).
        """
        edges = 0
        for _besluit_id, stemming_node in stemming_nodes.items():
            if not stemming_node.id:
                continue
            buckets = (
                ("Voor", stemming_node.props.get("voor") or []),
                ("Tegen", stemming_node.props.get("tegen") or []),
                ("Onthouden", stemming_node.props.get("onthouding") or []),
            )
            for stem_label, entries in buckets:
                for entry in entries:
                    partij = (entry.get("partij") or "").strip()
                    if not partij:
                        continue
                    fractie_node = getattr(self, "_fractie_by_label", {}).get(
                        partij
                    ) or fractie_nodes.get(partij)
                    if fractie_node is not None and fractie_node.id:
                        fractie_id = fractie_node.id
                    else:
                        fractie_key = make_node_key(partij)
                        if (
                            self.store.get_node(COLLECTION_FRACTIES, fractie_key)
                            is None
                        ):
                            continue
                        fractie_id = f"{COLLECTION_FRACTIES}/{fractie_key}"
                    try:
                        self.store.create_edge(
                            from_id=fractie_id,
                            to_id=stemming_node.id,
                            relation=RELATION_STEMT,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                            meta={
                                "stem": stem_label,
                                "aantal_zetels": entry.get("aantal_zetels") or 0,
                            },
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Fractie→stemming edge failed: %s", exc)

        logger.info("Linked %d fracties to stemmingen (STEMT).", edges)
        return edges

    def _link_zaken_to_dossiers(self, dossier_raws: list[dict[str, Any]]) -> int:
        """Create DEEL_VAN_DOSSIER edges from Zaak (procedures) to Kamerstukdossier.

        We read all procedures that have a `kamerstuknummer` prop and link them
        to the matching dossier node.
        """
        # Build a lookup: kamerstuknummer → dossier node id
        dossier_lookup: dict[str, str] = {}
        for raw in dossier_raws:
            payload = self._payload_json(raw)
            nummer = payload.get("Nummer")
            if nummer is None:
                continue
            nummer_str = str(nummer)
            toevoeging = payload.get("Toevoeging") or ""
            key_parts = [nummer_str]
            if toevoeging:
                key_parts.append(toevoeging)
            dossier_key = make_node_key(*key_parts)
            dossier_lookup[nummer_str] = f"{COLLECTION_KAMERSTUKDOSSIERS}/{dossier_key}"

        # Query all procedures that have a kamerstuknummer
        aql = """
        FOR doc IN procedures
            FILTER doc.props.kamerstuknummer != null
            RETURN { _id: doc._id, kamerstuknummer: doc.props.kamerstuknummer }
        """
        edges = 0
        for row in self.store.query(aql):
            nummer = str(row.get("kamerstuknummer") or "")
            dossier_id = dossier_lookup.get(nummer)
            if not dossier_id:
                continue
            try:
                self.store.create_edge(
                    from_id=row["_id"],
                    to_id=dossier_id,
                    relation=RELATION_DEEL_VAN_DOSSIER,
                    source="tk-dossiers",
                    status=EDGE_STATUS_CANONIEK,
                )
                edges += 1
            except Exception as exc:
                logger.error(
                    "Failed to link zaak %s → dossier %s: %s",
                    row["_id"],
                    dossier_id,
                    exc,
                )

        logger.info("Linked %d zaken to dossiers.", edges)
        return edges

    def _link_publications_to_dossiers(self) -> int:
        """Create DEEL_VAN_DOSSIER edges from existing publications that have dossier_nummer."""
        aql = """
        FOR doc IN publications
            FILTER doc.props.dossier_nummer != null
            LIMIT 50000
            RETURN { _id: doc._id, dossier_nummer: doc.props.dossier_nummer }
        """
        edges = 0
        for row in self.store.query(aql):
            nummer = str(row.get("dossier_nummer") or "")
            if not nummer:
                continue
            dossier_key = make_node_key(nummer)
            dossier_id = f"{COLLECTION_KAMERSTUKDOSSIERS}/{dossier_key}"
            # Only create edge if dossier node exists
            dossier_node = self.store.get_node(
                COLLECTION_KAMERSTUKDOSSIERS, dossier_key
            )
            if dossier_node is None:
                continue
            try:
                self.store.create_edge(
                    from_id=row["_id"],
                    to_id=dossier_id,
                    relation=RELATION_DEEL_VAN_DOSSIER,
                    source="tk-dossiers",
                    status=EDGE_STATUS_CANONIEK,
                )
                edges += 1
            except Exception as exc:
                logger.error(
                    "Failed to link publication %s → dossier %s: %s",
                    row["_id"],
                    dossier_id,
                    exc,
                )

        logger.info("Linked %d publications to dossiers.", edges)
        return edges

    def _link_activiteiten(
        self,
        raw_records: list[dict[str, Any]],
        activiteit_nodes: dict[str, Node],
    ) -> int:
        edges = 0
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = str(payload.get("Id") or "")
            activiteit_node = activiteit_nodes.get(external_id)
            if not activiteit_node or not activiteit_node.id:
                continue

            # → Kamerstukdossier(s)
            for nummer in activiteit_node.props.get("dossier_nummers") or []:
                dossier_key = make_node_key(str(nummer))
                dossier_node = self.store.get_node(
                    COLLECTION_KAMERSTUKDOSSIERS, dossier_key
                )
                if dossier_node and dossier_node.id:
                    try:
                        self.store.create_edge(
                            from_id=activiteit_node.id,
                            to_id=dossier_node.id,
                            relation=RELATION_DEEL_VAN_DOSSIER,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Activiteit→dossier edge failed: %s", exc)

            # → Commissie
            commissie_id = activiteit_node.props.get("commissie_id")
            if commissie_id:
                commissie_key = make_node_key(commissie_id)
                commissie_node = self.store.get_node(
                    COLLECTION_COMMISSIES, commissie_key
                )
                if commissie_node and commissie_node.id:
                    try:
                        self.store.create_edge(
                            from_id=activiteit_node.id,
                            to_id=commissie_node.id,
                            relation=RELATION_BEHANDELD_DOOR,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Activiteit→commissie edge failed: %s", exc)

        logger.info("Built %d activiteit edges.", edges)
        return edges

    def _link_stemmingen(
        self,
        raw_records: list[dict[str, Any]],
        stemming_nodes: dict[str, Node],
    ) -> int:
        """Create DEEL_VAN_DOSSIER edges from Stemming nodes to Kamerstukdossier nodes."""
        edges = 0
        for _besluit_id, stemming_node in stemming_nodes.items():
            if not stemming_node.id:
                continue

            for nummer in stemming_node.props.get("dossier_nummers") or []:
                dossier_key = make_node_key(str(nummer))
                dossier_node = self.store.get_node(
                    COLLECTION_KAMERSTUKDOSSIERS, dossier_key
                )
                if dossier_node and dossier_node.id:
                    try:
                        self.store.create_edge(
                            from_id=stemming_node.id,
                            to_id=dossier_node.id,
                            relation=RELATION_DEEL_VAN_DOSSIER,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Stemming→dossier edge failed: %s", exc)

        logger.info("Built %d stemming edges.", edges)
        return edges

    def _link_toezeggingen(
        self,
        raw_records: list[dict[str, Any]],
        toezegging_nodes: dict[str, Node],
    ) -> int:
        edges = 0

        # Bulk-fetch all activiteit IDs needed by this batch of toezeggingen in
        # one query instead of one query per toezegging.
        activiteit_nummers = {
            node.props.get("activiteit_nummer")
            for node in toezegging_nodes.values()
            if node.props.get("activiteit_nummer")
        }
        activiteit_id_by_nummer: dict[str, str] = {}
        if activiteit_nummers:
            aql = """
FOR act IN activiteiten
  FILTER act.props.nummer IN @nummers
  RETURN {nummer: act.props.nummer, id: act._id}
"""
            for row in self.store.query(aql, {"nummers": list(activiteit_nummers)}):
                activiteit_id_by_nummer[row["nummer"]] = row["id"]

        for _external_id, toezegging_node in toezegging_nodes.items():
            if not toezegging_node.id:
                continue

            activiteit_nummer = toezegging_node.props.get("activiteit_nummer") or ""
            if activiteit_nummer:
                act_id = activiteit_id_by_nummer.get(activiteit_nummer)
                if act_id:
                    try:
                        self.store.create_edge(
                            from_id=toezegging_node.id,
                            to_id=act_id,
                            relation=RELATION_GEDAAN_IN,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Toezegging→activiteit edge failed: %s", exc)

            # → Kamerstukdossier (via KamerstukdossierId stored as dossier_id)
            dossier_ext_id = toezegging_node.props.get("dossier_id")
            if dossier_ext_id:
                dossier_node = self._find_dossier_by_external_id(dossier_ext_id)
                if dossier_node and dossier_node.id:
                    try:
                        self.store.create_edge(
                            from_id=toezegging_node.id,
                            to_id=dossier_node.id,
                            relation=RELATION_DEEL_VAN_DOSSIER,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Toezegging→dossier edge failed: %s", exc)

        logger.info("Built %d toezegging edges.", edges)
        return edges

    def _link_leden_to_commissies(
        self,
        commissie_raws: list[dict[str, Any]],
        lid_nodes: dict[str, Node],
    ) -> int:
        edges = 0
        for raw in commissie_raws:
            payload = self._payload_json(raw)
            commissie_id = str(payload.get("Id") or "")
            commissie_key = make_node_key(commissie_id)
            commissie_node = self.store.get_node(COLLECTION_COMMISSIES, commissie_key)
            if not commissie_node or not commissie_node.id:
                continue

            # Collect all membership periods per persoon before writing edges.
            # Van/TotEnMet live on CommissieZetelVastPersoon, not CommissieZetel.
            # One persoon may have multiple periods (different parliamentary terms);
            # the edge key is deterministic per (lid, commissie) so we pick the
            # most representative period: open-ended (TotEnMet=null) wins over
            # historical; among ties, the latest start date wins.
            periods_by_persoon: dict[str, list[tuple[str | None, str | None]]] = {}
            for zetel in payload.get("CommissieZetel") or []:
                for vaste in zetel.get("CommissieZetelVastPersoon") or []:
                    persoon_id = str(vaste.get("Persoon_Id") or "")
                    if not persoon_id:
                        continue
                    geldig_van = _iso_date(vaste.get("Van"))
                    geldig_tot = _iso_date(vaste.get("TotEnMet"))
                    periods_by_persoon.setdefault(persoon_id, []).append(
                        (geldig_van, geldig_tot)
                    )

            for persoon_id, periods in periods_by_persoon.items():
                lid_key = make_node_key(persoon_id)
                lid_node = self.store.get_node(COLLECTION_LEDEN, lid_key)
                if not lid_node or not lid_node.id:
                    continue
                open_periods = [(van, tot) for van, tot in periods if tot is None]
                if open_periods:
                    best_van = max(
                        (van for van, _ in open_periods if van), default=None
                    )
                    best_tot: str | None = None
                else:
                    best_van, best_tot = max(periods, key=lambda p: p[1] or "")
                zetel_meta: dict[str, Any] = {}
                if best_van:
                    zetel_meta["geldig_van"] = best_van
                if best_tot:
                    zetel_meta["geldig_tot"] = best_tot
                try:
                    self.store.create_edge(
                        from_id=lid_node.id,
                        to_id=commissie_node.id,
                        relation=RELATION_LID_VAN,
                        source="tk-dossiers",
                        status=EDGE_STATUS_CANONIEK,
                        meta=zetel_meta if zetel_meta else None,
                    )
                    edges += 1
                except Exception as exc:
                    logger.error("Lid→commissie edge failed: %s", exc)

        logger.info("Built %d lid→commissie edges.", edges)
        return edges

    def _link_leden_to_fracties(
        self,
        lid_nodes: dict[str, Node],
        fractie_nodes: dict[str, Node],
    ) -> int:
        """Create LID_VAN_FRACTIE edges from Lid → Fractie using props.partij.

        A Lid's partij is the Fractielabel from the TK API (e.g. "VVD", "D66").
        We look up the matching Fractie node by name; if none exists, we skip.
        """
        edges = 0
        for _external_id, lid_node in lid_nodes.items():
            if not lid_node.id:
                continue
            partij = str(lid_node.props.get("partij") or "").strip()
            if not partij or partij == "onafhankelijk":
                continue
            fractie_node = fractie_nodes.get(partij)
            if not fractie_node or not fractie_node.id:
                continue
            try:
                self.store.create_edge(
                    from_id=lid_node.id,
                    to_id=fractie_node.id,
                    relation=RELATION_LID_VAN_FRACTIE,
                    source="tk-dossiers",
                    status=EDGE_STATUS_CANONIEK,
                )
                edges += 1
            except Exception as exc:
                logger.error("Lid→fractie edge failed: %s", exc)

        logger.info("Built %d lid→fractie edges.", edges)
        return edges

    def _normalize_fractie_memberships(
        self,
        fzp_raws: list[dict[str, Any]],
        lid_nodes: dict[str, Node],
        fractie_nodes: dict[str, Node],
    ) -> int:
        """Build LID_VAN_FRACTIE edges (with [van, tot_en_met] meta) from
        FractieZetelPersoon. Also denormalises ``fractielidmaatschappen`` onto
        each Lid node so the profile timeline renders without an extra join,
        and refreshes ``partij`` / ``display_name`` to reflect the most-recent
        membership rather than the (unreliable) Fractielabel snapshot.

        Note on edges: the deterministic edge key is SHA-1(from, relation, to),
        so a person who left and rejoined a party collapses to a single edge
        carrying the *latest* period in meta. The full timeline is preserved
        on the Lid node's ``fractielidmaatschappen`` list.
        """
        edges = 0
        by_lid: dict[str, list[dict[str, Any]]] = {}

        for raw in fzp_raws:
            payload = self._payload_json(raw)
            persoon_id = str(payload.get("Persoon_Id") or "")
            if not persoon_id:
                continue
            zetel = payload.get("FractieZetel") or {}
            if isinstance(zetel, list):
                zetel = zetel[0] if zetel else {}
            fractie_id_ext = str(zetel.get("Fractie_Id") or "")
            if not fractie_id_ext:
                continue

            lid_node = lid_nodes.get(persoon_id)
            fractie_node = fractie_nodes.get(fractie_id_ext)
            if (
                lid_node is None
                or not lid_node.id
                or fractie_node is None
                or not fractie_node.id
            ):
                continue

            van = _iso_date(payload.get("Van"))
            tot = _iso_date(payload.get("TotEnMet"))
            functie = payload.get("Functie") or None

            try:
                self.store.create_edge(
                    from_id=lid_node.id,
                    to_id=fractie_node.id,
                    relation=RELATION_LID_VAN_FRACTIE,
                    source="tk-dossiers",
                    status=EDGE_STATUS_CANONIEK,
                    meta={"van": van, "tot_en_met": tot, "functie": functie},
                )
                edges += 1
            except Exception as exc:
                logger.error("Lid→fractie edge failed: %s", exc)

            by_lid.setdefault(persoon_id, []).append(
                {
                    "fractie_id": fractie_node.id,
                    "fractie_key": fractie_node.key,
                    "naam": fractie_node.props.get("naam"),
                    "afkorting": fractie_node.props.get("afkorting"),
                    "aliases": fractie_node.props.get("aliases") or [],
                    "van": van,
                    "tot_en_met": tot,
                    "functie": functie,
                }
            )

        # Denormalise sorted memberships onto the Lid node + refresh partij.
        for persoon_id, mships in by_lid.items():
            lid_node = lid_nodes.get(persoon_id)
            if not lid_node:
                continue
            mships.sort(key=lambda m: (m["van"] or "", m["tot_en_met"] or "9999-12-31"))
            lid_node.props["fractielidmaatschappen"] = mships
            current = next(
                (m for m in reversed(mships) if not m["tot_en_met"]),
                mships[-1] if mships else None,
            )
            if current:
                partij = current["afkorting"] or current["naam"]
                lid_node.props["partij"] = partij
                naam = lid_node.props.get("naam") or ""
                lid_node.props["display_name"] = (
                    f"{naam} ({partij})" if naam and partij else (naam or partij or "")
                )
            self.store.insert_or_update(lid_node)

        logger.info(
            "Built %d lid→fractie edges (date-bounded, %d leden with timeline).",
            edges,
            len(by_lid),
        )
        return edges

    def _find_dossier_by_external_id(self, external_id: str) -> Node | None:
        """Look up a dossier node by its TK GUID stored in props.external_id."""
        aql = """
        FOR doc IN kamerstukdossiers
            FILTER doc.props.external_id == @eid
            LIMIT 1
            RETURN doc
        """
        for doc in self.store.query(aql, bind_vars={"eid": external_id}):
            return Node.from_document(COLLECTION_KAMERSTUKDOSSIERS, doc)
        return None
