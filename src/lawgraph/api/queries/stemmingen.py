"""Stemmingen browser query helpers."""

from __future__ import annotations

from typing import Any

from lawgraph.config.settings import COLLECTION_EDGES, RELATION_PART_OF_PROCEDURE
from lawgraph.db import ArangoStore


def get_stemmingen(
    store: ArangoStore,
    *,
    aangenomen: bool | None = None,
    partij: str | None = None,
    chamber: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a paginated list of stemmingen, newest first.

    Optional filters: aangenomen (bool), partij (party name match in voor/tegen/onthouding).
    """
    bind_vars: dict[str, Any] = {"limit": limit, "offset": offset}
    aangenomen_filter = ""
    if aangenomen is not None:
        aangenomen_filter = "FILTER doc.props.aangenomen == @aangenomen"
        bind_vars["aangenomen"] = aangenomen

    chamber_filter = ""
    if chamber is not None:
        # TK stemmingen carry labels=["TK"]; EK carry labels=["EK"].
        # props.chamber is only set on EK, so filter by label to cover both.
        chamber_filter = "FILTER @chamber IN doc.labels"
        bind_vars["chamber"] = chamber.upper()

    partij_filter = ""
    if partij:
        bind_vars["partij"] = partij.strip().lower()
        partij_filter = """
        FILTER LENGTH(
            FOR p IN APPEND(
                doc.props.voor != null ? doc.props.voor : [],
                APPEND(
                    doc.props.tegen != null ? doc.props.tegen : [],
                    doc.props.onthouding != null ? doc.props.onthouding : []
                )
            )
            FILTER CONTAINS(LOWER(p.partij), @partij)
            LIMIT 1
            RETURN 1
        ) > 0"""

    aql = f"""
    LET total = LENGTH(
        FOR doc IN stemmingen
            {aangenomen_filter}
            {chamber_filter}
            {partij_filter}
            RETURN 1
    )
    LET items = (
        FOR doc IN stemmingen
            {aangenomen_filter}
            {chamber_filter}
            {partij_filter}
            SORT doc.props.datum DESC
            LIMIT @offset, @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                datum: doc.props.datum,
                onderwerp: doc.props.onderwerp,
                dossier_nummers: doc.props.dossier_nummers,
                aangenomen: doc.props.aangenomen,
                chamber: doc.props.chamber,
                voor_count: LENGTH(doc.props.voor != null ? doc.props.voor : []),
                tegen_count: LENGTH(doc.props.tegen != null ? doc.props.tegen : []),
                onthouding_count: LENGTH(doc.props.onthouding != null ? doc.props.onthouding : [])
            }}
    )
    RETURN {{ total: total, items: items }}
    """  # noqa: E501
    rows = list(store.query(aql, bind_vars))
    if not rows:
        return {"total": 0, "items": []}
    return rows[0]


def get_stemming_detail(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """Return a single stemming with full voor/tegen/onthouding breakdown."""
    aql = """
    LET doc = DOCUMENT(CONCAT('stemmingen/', @key))
    FILTER doc != null
    RETURN {
        id: doc._id,
        key: doc._key,
        datum: doc.props.datum,
        onderwerp: doc.props.onderwerp,
        dossier_nummers: doc.props.dossier_nummers,
        aangenomen: doc.props.aangenomen,
        chamber: doc.props.chamber,
        besluit_id: doc.props.besluit_id,
        voor: doc.props.voor,
        tegen: doc.props.tegen,
        onthouding: doc.props.onthouding
    }
    """
    for row in store.query(aql, {"key": key}):
        return row
    return None


def get_stemming_publication(
    store: ArangoStore, stemming_key: str
) -> dict[str, Any] | None:
    """Resolve the publication a stemming decided on.

    Resolution priority:
      1. Direct neighbour: any publication linked from the stemming via an edge
         (covers stemming → publication where such an edge exists).
      2. Via primary_zaak: stemming.props.primary_zaak.nummer → procedure with
         matching kamerstuknummer → publication via PART_OF_PROCEDURE.
      3. Fallback: any zaak in stemming.props.zaken → procedure → publication.

    Returns the raw publication document (same shape as ``publications.get``),
    or ``None`` when no candidate can be resolved.
    """
    aql = f"""
    LET stemming = DOCUMENT(@stemming_id)
    FILTER stemming != null

    // Step 1: direct neighbour
    LET direct_pub = FIRST(
        FOR v, e IN 1..1 ANY stemming._id {COLLECTION_EDGES}
            FILTER PARSE_IDENTIFIER(v._id).collection == "publications"
            LIMIT 1 RETURN v
    )

    // Step 2 + 3: collect zaak nummers (primary first, others next)
    LET primary_nummer = stemming.props.primary_zaak != null
        ? stemming.props.primary_zaak.nummer
        : null
    LET other_nummers = stemming.props.zaken != null
        ? (FOR z IN stemming.props.zaken
            FILTER z.nummer != null AND z.nummer != primary_nummer
            RETURN z.nummer)
        : []
    LET candidate_nummers = primary_nummer != null
        ? APPEND([primary_nummer], other_nummers)
        : other_nummers

    // First try: publication.props.raw.Zaak[].Nummer matches a candidate.
    // Publications store the full Zaak payload from the TK Document expand,
    // so this avoids the GUID/Nummer mismatch with procedures.
    LET zaak_pub = FIRST(
        FOR nummer IN candidate_nummers
            FOR pub IN publications
                FILTER pub.props.raw != null
                   AND pub.props.raw.Zaak != null
                   AND LENGTH(
                       FOR z IN pub.props.raw.Zaak
                           FILTER z.Nummer == nummer
                           LIMIT 1 RETURN 1
                   ) > 0
                LIMIT 1 RETURN pub
    )

    // Fallback: PART_OF_PROCEDURE walk through procedures keyed by
    // kamerstuknummer (works when procedures collection has been normalized
    // with kamerstuknummer set).
    LET proc_pub = zaak_pub != null ? null : FIRST(
        FOR nummer IN candidate_nummers
            FOR proc IN procedures
                FILTER proc.props.kamerstuknummer == nummer
                FOR pub, pe IN 1..1 INBOUND proc._id {COLLECTION_EDGES}
                    FILTER pe.relation == "{RELATION_PART_OF_PROCEDURE}"
                    LIMIT 1 RETURN pub
    )

    RETURN direct_pub != null ? direct_pub
        : (zaak_pub != null ? zaak_pub : proc_pub)
    """
    rows = list(store.query(aql, {"stemming_id": f"stemmingen/{stemming_key}"}))
    return rows[0] if rows and rows[0] is not None else None
