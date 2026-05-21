"""Commissie, leden, fracties, and related query helpers."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    RELATION_DEEL_VAN_DOSSIER,
    RELATION_INTRODUCEERT,
    RELATION_PART_OF_INSTRUMENT,
    RELATION_TREKT_IN,
    RELATION_WIJZIGT,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.db import ArangoStore


def get_all_commissies_with_leden(store: ArangoStore) -> list[dict[str, Any]]:
    """Return every commissie with its leden inlined — one round trip.

    Backs ``/api/commissies?with_leden=true`` which the parliamentary
    layer-load uses to draw a halo of MPs around each commissie. Replaces
    the legacy N+1 (one fetch per commissie × ~130 commissies) with a
    single bulk aggregation. The DOCUMENT() per-edge lookup is avoided by
    fetching all LID_VAN edges into a map first, then joining with the
    commissies and leden collections.
    """
    aql = f"""
    LET today = DATE_FORMAT(DATE_NOW(), "%yyyy-%mm-%dd")
    LET commissie_ids = (FOR c IN commissies RETURN c._id)
    LET lid_edges = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == 'LID_VAN' AND e._to IN commissie_ids
            FILTER NOT HAS(e.meta, "geldig_tot") OR e.meta.geldig_tot == null
                OR e.meta.geldig_tot >= today
            RETURN {{ from: e._from, to: e._to }}
    )
    LET lid_ids = UNIQUE(lid_edges[*].from)
    LET lid_doc_map = MERGE(
        FOR id IN lid_ids
            LET d = DOCUMENT(id)
            FILTER d != null
            RETURN {{ [d._id]: d }}
    )
    LET leden_by_commissie = (
        FOR e IN lid_edges
            COLLECT commissie_id = e.to INTO group = e.from
            RETURN {{
                commissie_id: commissie_id,
                lid_ids: UNIQUE(group)
            }}
    )
    LET leden_map = MERGE(
        FOR row IN leden_by_commissie
            RETURN {{
                [row.commissie_id]: (
                    FOR id IN row.lid_ids
                        LET d = lid_doc_map[id]
                        FILTER d != null
                        SORT d.props.naam ASC
                        RETURN d
                )
            }}
    )
    FOR commissie IN commissies
        LET naam = commissie.props.naam
        FILTER naam != null AND naam != ""
        FILTER NOT REGEX_TEST(
            naam,
            "^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$",
            true
        )
        SORT commissie.props.naam ASC
        RETURN MERGE(commissie, {{
            leden: leden_map[commissie._id] != null ? leden_map[commissie._id] : []
        }})
    """
    return list(store.query(aql))


def get_commissie_detail(
    store: ArangoStore, slug: str, *, current_only: bool = True
) -> dict[str, Any] | None:
    """Return commissie with leden (via LID_VAN edges) and recent dossiers (via BEHANDELD_DOOR).

    Accepts either ``props.slug`` or ``_key`` so the FE can use whichever
    identifier the list endpoint surfaces.

    When ``current_only=True`` (default), only LID_VAN edges without a
    ``geldig_tot`` (or with a future ``geldig_tot``) are returned — i.e. MPs
    who are currently assigned to this commissie.  Set to False to include
    all historical members.
    """
    current_filter = (
        "FILTER NOT HAS(e.meta, 'geldig_tot') OR e.meta.geldig_tot == null"
        " OR e.meta.geldig_tot >= @today"
        if current_only
        else ""
    )
    aql = f"""
    FOR commissie IN commissies
        FILTER commissie.props.slug == @slug
            OR LOWER(commissie._key) == @slug
        LIMIT 1

        LET leden = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == commissie._id AND e.relation == 'LID_VAN'
                {current_filter}
                LET lid = DOCUMENT(e._from)
                FILTER lid != null
                SORT lid.props.naam ASC
                RETURN MERGE(lid, {{
                    geldig_van: e.meta.geldig_van,
                    geldig_tot: e.meta.geldig_tot
                }})
        )

        LET dossiers = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == commissie._id AND e.relation == 'BEHANDELD_DOOR'
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._from == e._from AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                    FILTER STARTS_WITH(e2._to, "kamerstukdossiers/")
                    LET dossier = DOCUMENT(e2._to)
                    FILTER dossier != null
                    RETURN DISTINCT dossier
            LIMIT 100
        )

        RETURN MERGE(commissie, {{ leden: leden, dossiers: dossiers }})
    """
    bind: dict[str, Any] = {"slug": slug.lower()}
    if current_only:
        bind["today"] = dt.date.today().isoformat()
    for doc in store.query(aql, bind):
        return doc
    return None


def get_all_leden(
    store: ArangoStore,
    *,
    partij: str | None = None,
    actief: bool | None = None,
    q: str | None = None,
    include_all: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List parliamentary members.

    By default restricted to leden who have an actual fractie membership
    (the 800 ever-MPs); pass ``include_all=True`` to include ministers /
    non-MP persons that the TK Persoon endpoint also exposes.

    Optional filters:
      * ``partij`` — match against partij OR any fractielidmaatschappen
        afkorting/naam (case-insensitive substring).
      * ``actief`` — only currently-active leden.
      * ``q``     — case-insensitive substring on naam.
    """
    filters: list[str] = []
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "actief": actief}

    if not include_all:
        filters.append("LENGTH(doc.props.fractielidmaatschappen) > 0")
    if partij:
        filters.append(
            "(LOWER(doc.props.partij) == @partij_lc"
            " OR LENGTH(FOR m IN (doc.props.fractielidmaatschappen OR [])"
            "    FILTER LOWER(m.afkorting) == @partij_lc"
            "        OR LOWER(m.naam) == @partij_lc"
            "        OR @partij_lc IN (FOR a IN (m.aliases OR []) RETURN LOWER(a))"
            "    LIMIT 1 RETURN 1) > 0)"
        )
        bind["partij_lc"] = partij.strip().lower()
    if q:
        filters.append("CONTAINS(LOWER(doc.props.naam), @q)")
        bind["q"] = q.strip().lower()

    where = ("FILTER " + " AND ".join(filters)) if filters else ""
    # actief is derived from fractielidmaatschappen (open tot_en_met) rather
    # than the stored props.actief which is always true in practice.
    aql = f"""
    FOR doc IN leden
        {where}
        LET _actief = LENGTH(
            FOR m IN (doc.props.fractielidmaatschappen OR [])
                FILTER m.tot_en_met == null
                LIMIT 1 RETURN 1
        ) > 0
        FILTER @actief == null OR _actief == @actief
        SORT doc.props.naam ASC
        LIMIT @offset, @limit
        RETURN doc
    """
    return list(store.query(aql, bind))


def get_all_commissies(store: ArangoStore) -> list[dict[str, Any]]:
    """List committees with their active-dossier counts.

    Performance: ``active_dossier_count`` is precomputed by the
    ``backfill_list_stats`` migration and refreshed via the normalize
    pipeline. The legacy shape did a nested edge-scan + DOCUMENT lookup
    per commissie (~800 ms wall on this corpus). When the precomputed
    prop is missing on a legacy doc we fall back to a single two-stage
    aggregation that builds open-dossier and open-activity hash maps once
    and counts BEHANDELD_DOOR edges in a single pass — still much cheaper
    than the per-commissie shape.
    """
    # Fast path: every commissie carries props.active_dossier_count after
    # backfill. If the prop is missing on some rows we compute counts only for
    # the affected ids (not a full second scan).
    fast_rows = list(
        store.query(
            """
        FOR doc IN commissies
            LET naam = doc.props.naam
            FILTER naam != null AND naam != ""
            FILTER NOT REGEX_TEST(
                naam,
                "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                true
            )
            SORT doc.props.naam ASC
            RETURN MERGE(doc, {
                active_dossier_count: (
                    doc.props.active_dossier_count != null
                        ? doc.props.active_dossier_count : null
                )
            })
    """
        )
    )
    if all(r.get("active_dossier_count") is not None for r in fast_rows):
        return fast_rows

    # Legacy fallback: derive counts in one pass only for commissies that are
    # missing the precomputed value — avoids discarding all fast-path results.
    missing_ids = [r["_id"] for r in fast_rows if r.get("active_dossier_count") is None]
    if not missing_ids:
        return fast_rows

    aql = f"""
    LET open_dossier_map = MERGE(
        FOR d IN kamerstukdossiers
            FILTER d.props.afgedaan == false
            RETURN {{ [d._id]: true }}
    )
    LET open_activity_map = MERGE(
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            FILTER open_dossier_map[e._to] == true
            RETURN {{ [e._from]: true }}
    )
    LET counts = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == 'BEHANDELD_DOOR'
            FILTER e._to IN @missing_ids
            FILTER open_activity_map[e._from] == true
            COLLECT commissie = e._to WITH COUNT INTO cnt
            RETURN {{ id: commissie, count: cnt }}
    )
    RETURN MERGE(FOR x IN counts RETURN {{ [x.id]: x.count }})
    """
    count_map: dict[str, Any] = {}
    for row in store.query(aql, {"missing_ids": missing_ids}):
        if isinstance(row, dict):
            count_map.update(row)

    for r in fast_rows:
        if r.get("active_dossier_count") is None:
            r["active_dossier_count"] = count_map.get(r["_id"], 0)
    return fast_rows


def get_all_fracties(
    store: ArangoStore,
    *,
    actief: bool | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    """Return all known parliamentary fracties with member count."""
    bind_vars: dict[str, Any] = {}
    filters: list[str] = ["doc.props.naam != null AND doc.props.naam != ''"]
    if actief is not None:
        filters.append("doc.props.actief == @actief")
        bind_vars["actief"] = actief
    if q:
        filters.append(
            "CONTAINS(LOWER(doc.props.naam), @q) "
            "OR CONTAINS(LOWER(doc.props.afkorting != null ? doc.props.afkorting : ''), @q)"
        )
        bind_vars["q"] = q.strip().lower()
    filter_clause = "\n        ".join(f"FILTER {f}" for f in filters)
    # Pre-aggregate member counts in one pass instead of one sub-query per fractie.
    aql = f"""
    LET count_map = MERGE(
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == 'LID_VAN_FRACTIE'
            COLLECT frac = e._to WITH COUNT INTO cnt
            RETURN {{ [frac]: cnt }}
    )
    FOR doc IN fracties
        {filter_clause}
        SORT doc.props.actief DESC, doc.props.afkorting ASC, doc.props.naam ASC
        RETURN MERGE(doc, {{
            member_count: count_map[doc._id] != null ? count_map[doc._id] : 0
        }})
    """
    return list(store.query(aql, bind_vars))


def get_lid_votes(
    store: ArangoStore, lid_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Return a paginated, time-aware voting record for a parliamentary member.

    For each stemming, the member's party at *stemming.props.datum* is looked
    up against ``lid.props.fractielidmaatschappen`` (a list of
    {afkorting, naam, van, tot_en_met} intervals). If no membership covers
    that date the stemming is skipped — the member wasn't seated then.

    Returned records include ``partij_at_time`` and ``fractie_key`` so the
    front-end can colour-code historic votes by the party held at the time
    and visualise the moment of a switch.

    Falls back to ``lid.props.partij`` when no memberships are stored
    (snapshots predating the FractieZetelPersoon migration).
    """
    aql = """
    LET lid = DOCUMENT(@lid_id)
    LET memberships = lid != null AND lid.props.fractielidmaatschappen != null
        ? lid.props.fractielidmaatschappen : []
    LET fallback_partij = lid != null ? lid.props.partij : null
    FILTER LENGTH(memberships) > 0 OR (fallback_partij != null AND fallback_partij != "")

    FOR stemming IN stemmingen
        LET datum = stemming.props.datum
        FILTER datum != null

        LET m = LENGTH(memberships) > 0
            ? FIRST(
                FOR mm IN memberships
                    FILTER (mm.van == null OR mm.van <= datum)
                       AND (mm.tot_en_met == null OR mm.tot_en_met >= datum)
                    LIMIT 1 RETURN mm
            )
            : null
        // Prefer a short alias for display (e.g. 'NSC' rather than the
        // bogus full-name afkorting). Falls back to afkorting, then naam.
        LET short_alias = m != null AND m.aliases != null
            ? FIRST(
                FOR a IN m.aliases
                    FILTER a != null AND LENGTH(a) <= 8 AND a != m.naam
                    SORT LENGTH(a) ASC
                    LIMIT 1 RETURN a
            )
            : null
        LET partij_at_time = m != null
            ? (short_alias != null ? short_alias
              : (m.afkorting != null AND m.afkorting != m.naam
                  ? m.afkorting : m.naam))
            : fallback_partij
        FILTER partij_at_time != null AND partij_at_time != ""
        // TK uses inconsistent labels across endpoints (e.g. NSC vs.
        // 'Nieuw Sociaal Contract'). Match against any alias from the
        // membership, falling back to partij_at_time itself.
        LET match_labels = m != null AND m.aliases != null AND LENGTH(m.aliases) > 0
            ? m.aliases
            : [partij_at_time]

        LET voor_match = FIRST(
            FOR v IN (stemming.props.voor != null ? stemming.props.voor : [])
                FILTER v.partij IN match_labels
                RETURN v
        )
        LET tegen_match = FIRST(
            FOR v IN (stemming.props.tegen != null ? stemming.props.tegen : [])
                FILTER v.partij IN match_labels
                RETURN v
        )
        LET onthouding_match = FIRST(
            FOR v IN (stemming.props.onthouding != null ? stemming.props.onthouding : [])
                FILTER v.partij IN match_labels
                RETURN v
        )
        LET match = voor_match != null ? voor_match
                  : tegen_match != null ? tegen_match
                  : onthouding_match
        FILTER match != null

        LET soort = voor_match != null ? "Voor"
                  : tegen_match != null ? "Tegen"
                  : "Onthouden"

        SORT datum DESC
        LIMIT @limit
        RETURN {
            stemming_id:    stemming._id,
            stemming_key:   stemming._key,
            besluit_id:     stemming.props.besluit_id,
            datum:          datum,
            onderwerp:      stemming.props.onderwerp,
            aangenomen:     stemming.props.aangenomen,
            soort:          soort,
            aantal_zetels:  match.aantal_zetels,
            partij_at_time: partij_at_time,
            fractie_key:    m != null ? m.fractie_key : null
        }
    """
    return list(store.query(aql, {"lid_id": lid_id, "limit": limit}))


def get_actor_touched_instruments(
    store: ArangoStore, actor_id: str, *, limit: int = 10
) -> list[dict[str, Any]]:
    """Return the laws an actor (lid or fractie) most often touches.

    Walks actor -AUTEUR_VAN-> publication -(WIJZIGT|INTRODUCEERT|TREKT_IN)->
    instrument_article -PART_OF_INSTRUMENT-> instrument, groups by instrument,
    counts the distinct publications behind each entry.
    """
    # Collect by instr_id (string) rather than the full instrument document to
    # avoid materialising the complete doc in every group entry. DOCUMENT() is
    # called only on the post-LIMIT result set.
    aql = f"""
    LET actor = DOCUMENT(@actor_id)
    FILTER actor != null

    FOR e1 IN {COLLECTION_EDGES}
        FILTER e1._from == @actor_id AND e1.relation == 'AUTEUR_VAN'
        LET pub_id = e1._to
        FOR e2 IN {COLLECTION_EDGES}
            FILTER e2._from == pub_id
                AND e2.relation IN ['{RELATION_WIJZIGT}',
                                    '{RELATION_INTRODUCEERT}',
                                    '{RELATION_TREKT_IN}']
            LET article_id = e2._to
            FOR e3 IN {COLLECTION_EDGES}
                FILTER e3._from == article_id
                    AND e3.relation == '{RELATION_PART_OF_INSTRUMENT}'
                COLLECT instr_id = e3._to INTO pubs = pub_id
                LET pub_count = LENGTH(UNIQUE(pubs))
                SORT pub_count DESC
                LIMIT @limit
                LET instrument = DOCUMENT(instr_id)
                FILTER instrument != null
                RETURN {{
                    instrument_id: instr_id,
                    instrument_key: instrument._key,
                    display_name: instrument.props.display_name,
                    title: instrument.props.title,
                    short_title: instrument.props.short_title,
                    citation_title: instrument.props.citation_title,
                    bwb_id: instrument.props.bwb_id,
                    celex: instrument.props.celex,
                    count: pub_count
                }}
    """
    return list(store.query(aql, {"actor_id": actor_id, "limit": limit}))


