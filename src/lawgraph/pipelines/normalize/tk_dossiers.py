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

from lawgraph.config.settings import (
    COLLECTION_ACTIVITEITEN,
    COLLECTION_COMMISSIES,
    COLLECTION_KAMERSTUKDOSSIERS,
    COLLECTION_LEDEN,
    COLLECTION_STEMMINGEN,
    COLLECTION_TOEZEGGINGEN,
    EDGE_STATUS_CANONIEK,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RELATION_BEHANDELD_DOOR,
    RELATION_DEEL_VAN_DOSSIER,
    RELATION_GEDAAN_IN,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)

_TOEZEGGING_STATUS_MAP = {
    "Openstaand": "open",
    "Afgedaan": "gedaan",
    "Niet nagekomen": "vervallen",
    "Nagekomen": "gedaan",
}


def _iso_date(value: Any) -> str | None:
    """Extract a YYYY-MM-DD string from an OData datetime value."""
    if value is None:
        return None
    s = str(value)
    if "T" in s:
        return s.split("T")[0]
    return s[:10] if len(s) >= 10 else s


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

    def normalize_nodes(self, raw: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        commissie_nodes = self._normalize_commissies(raw.get(RAW_KIND_TK_COMMISSIE, []))
        lid_nodes = self._normalize_personen(raw.get(RAW_KIND_TK_PERSOON, []))
        dossier_nodes = self._normalize_dossiers(raw.get(RAW_KIND_TK_DOSSIER, []))
        activiteit_nodes = self._normalize_activiteiten(
            raw.get(RAW_KIND_TK_ACTIVITEIT, [])
        )
        stemming_nodes = self._normalize_stemmingen(raw.get(RAW_KIND_TK_STEMMING, []))
        toezegging_nodes = self._normalize_toezeggingen(
            raw.get(RAW_KIND_TK_TOEZEGGING, [])
        )

        return {
            "commissie_nodes": commissie_nodes,
            "lid_nodes": lid_nodes,
            "dossier_nodes": dossier_nodes,
            "activiteit_nodes": activiteit_nodes,
            "stemming_nodes": stemming_nodes,
            "toezegging_nodes": toezegging_nodes,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        edges = 0

        # Link Zaak (procedures) → Kamerstukdossier
        edges += self._link_zaken_to_dossiers(raw.get(RAW_KIND_TK_DOSSIER, []))

        # Link existing Publications → Kamerstukdossier via dossier_nummer prop
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

        logger.info("TkDossiersNormalizePipeline: wrote %d edges total.", edges)
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

            fractie = str(payload.get("Fractielabel") or "")

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
            titel = payload.get("Titel") or payload.get("Citeertitel") or nummer_str
            afgedaan = bool(payload.get("Afgedaan"))
            gesloten_op = _iso_date(payload.get("DatumGesloten"))
            geopend_op = _iso_date(payload.get("DatumRegistratie"))

            # huidige_fase: derive from afgedaan + gesloten_op
            if afgedaan or gesloten_op:
                huidige_fase = "afgehandeld"
            else:
                huidige_fase = (
                    "wetsvoorstel"  # default; enriched by semantic pipeline later
                )

            display_name = f"Kamerstukdossier {nummer_str}"
            if toevoeging:
                display_name += f"-{toevoeging}"
            if titel:
                display_name += f": {titel}"

            props: dict[str, Any] = {
                "external_id": external_id,
                "nummer": int(nummer),
                "kamerstuknummer": nummer_str,
                "toevoeging": toevoeging,
                "titel": titel,
                "afgedaan": afgedaan,
                "huidige_fase": huidige_fase,
                "geopend_op": geopend_op,
                "gesloten_op": gesloten_op,
                "display_name": display_name,
            }

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
            nodes[nummer_str] = inserted  # also index by nummer for link resolution

        logger.info("Normalized %d kamerstukdossiers.", len(nodes) // 2 or len(nodes))
        return nodes

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

            # Agendapunt expand has no Dossier sub-property; dossier links resolved later
            dossier_nummers: list[str] = []

            commissie_id: str | None = None
            if payload.get("Voortouwcommissie_Id"):
                commissie_id = str(payload["Voortouwcommissie_Id"])

            display_name = f"{datum or '?'} — {omschrijving or soort}"
            props: dict[str, Any] = {
                "external_id": external_id,
                "datum": datum,
                "agenda_titel": omschrijving,
                "soort": soort,
                "commissie_id": commissie_id,
                "dossier_nummers": dossier_nummers,
                "display_name": display_name,
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

    def _normalize_stemmingen(
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
            onderwerp = besluit.get("BesluitTekst") or f"Besluit {besluit_id[:8]}"
            datum = _iso_date(votes[0].get("GewijzigdOp"))
            agendapunt_id = str(besluit.get("Agendapunt_Id") or "")

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

            props: dict[str, Any] = {
                "besluit_id": besluit_id,
                "agendapunt_id": agendapunt_id,
                "datum": datum,
                "onderwerp": onderwerp,
                "voor": voor,
                "tegen": tegen,
                "onthouding": onthouding,
                "aangenomen": aangenomen,
                "display_name": f"Stemming: {onderwerp[:80]}",
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
            status = _TOEZEGGING_STATUS_MAP.get(raw_status, "open")
            activiteit_id = str(payload.get("ActiviteitId") or "")
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
                "activiteit_id": activiteit_id,
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

    # ── Edge builders ──────────────────────────────────────────────────────────

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
        edges = 0
        for _besluit_id, stemming_node in stemming_nodes.items():
            if not stemming_node.id:
                continue

            # Stemming links to Activiteit via Agendapunt_Id when we have it; skipped
            # for now as Activiteit nodes are keyed by external_id (Activiteit.Id),
            # not Agendapunt.Id — no reliable join available without extra lookups.

            pass

        logger.info("Built %d stemming edges.", edges)
        return edges

    def _link_toezeggingen(
        self,
        raw_records: list[dict[str, Any]],
        toezegging_nodes: dict[str, Node],
    ) -> int:
        edges = 0
        for _external_id, toezegging_node in toezegging_nodes.items():
            if not toezegging_node.id:
                continue

            activiteit_id = toezegging_node.props.get("activiteit_id")
            if activiteit_id:
                activiteit_key = make_node_key(activiteit_id)
                activiteit_node = self.store.get_node(
                    COLLECTION_ACTIVITEITEN, activiteit_key
                )
                if activiteit_node and activiteit_node.id:
                    try:
                        self.store.create_edge(
                            from_id=toezegging_node.id,
                            to_id=activiteit_node.id,
                            relation=RELATION_GEDAAN_IN,
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Toezegging→activiteit edge failed: %s", exc)

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

            for zetel in payload.get("CommissieZetel") or []:
                for vaste in zetel.get("CommissieZetelVastPersoon") or []:
                    persoon_id = str(vaste.get("Persoon_Id") or "")
                    if not persoon_id:
                        continue
                    lid_key = make_node_key(persoon_id)
                    lid_node = self.store.get_node(COLLECTION_LEDEN, lid_key)
                    if not lid_node or not lid_node.id:
                        continue
                    try:
                        self.store.create_edge(
                            from_id=lid_node.id,
                            to_id=commissie_node.id,
                            relation="LID_VAN",
                            source="tk-dossiers",
                            status=EDGE_STATUS_CANONIEK,
                        )
                        edges += 1
                    except Exception as exc:
                        logger.error("Lid→commissie edge failed: %s", exc)

        logger.info("Built %d lid→commissie edges.", edges)
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
