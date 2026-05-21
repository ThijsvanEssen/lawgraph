"""Dossier classification + dossier query helpers."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from lawgraph.config.constants import (
    EDGE_STATUS_VOORGESTELD,
    RELATION_DEEL_VAN_DOSSIER,
    RELATION_EXPLAINS_ARTICLE,
    RELATION_INTRODUCEERT,
    RELATION_MENTIONS_ARTICLE,
    RELATION_PART_OF_PROCEDURE,
    RELATION_REFERS_TO_ARTICLE,
    RELATION_TREKT_IN,
    RELATION_WIJZIGT,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.db import ArangoStore

# ── Dossier stage classification ──────────────────────────────────────────────

DOSSIER_STAGES: tuple[str, ...] = (
    "wetsvoorstel",
    "mvt",
    "advies_rvs",
    "nota",
    "verslag",
    "amendementen",
    "stemming",
    "afgehandeld",
)


def classify_doc_soort(soort: str | None) -> str | None:
    """Map a document.soort string to one of the canonical dossier stages.

    Mirrors the frontend classifier (see brief). Returns None when no rule
    fires; callers decide whether to bucket those as 'onbekend'.
    """
    if not soort:
        return None
    s = soort.lower()
    if "voorstel van wet" in s or s.startswith("wetsvoorstel"):
        return "wetsvoorstel"
    if "memorie van toelichting" in s or re.search(r"\bmvt\b", s):
        return "mvt"
    if "advies" in s and ("raad van state" in s or re.search(r"\brvs\b", s)):
        return "advies_rvs"
    if "nota" in s:
        return "nota"
    if "verslag" in s:
        return "verslag"
    if "amendement" in s or "motie" in s:
        return "amendementen"
    if "stemming" in s or "besluit" in s:
        return "stemming"
    return None


def classify_zaak_soort(soort: str | None) -> str | None:
    """Map a Zaak.Soort value (from activiteiten) to a dossier stage.

    Coarser than ``classify_doc_soort`` but available even for older
    dossiers that have no documents linked. Examples of inputs:
    'Wetgeving', 'Initiatiefwetgeving', 'Motie', 'Amendement',
    'Brief regering', 'Schriftelijke vragen', 'Nota n.a.v. het verslag'.
    """
    if not soort:
        return None
    s = soort.lower()
    if "wetgeving" in s or "voorstel van wet" in s:
        return "wetsvoorstel"
    if "memorie van toelichting" in s:
        return "mvt"
    if "advies" in s and ("raad van state" in s or re.search(r"\brvs\b", s)):
        return "advies_rvs"
    if "nota" in s and "verslag" in s:
        return "nota"
    if "verslag" in s:
        return "verslag"
    if "amendement" in s or "motie" in s:
        return "amendementen"
    return None


DOSSIER_TRAJECT_KINDS: tuple[str, ...] = (
    "wetsvoorstel",
    "initiatiefwetsvoorstel",
    "begroting",
    "motie",
    "overig",
)


def classify_traject_kind(
    zaak_soorten: list[str] | None,
    *,
    titel: str | None = None,
) -> str | None:
    """Pick the canonical *kind* of a dossier (its legislative path).

    This answers "what kind of dossier is this?" — separate from
    ``huidige_fase`` (the latest stage). A dossier whose Zaak chain contains
    'Initiatiefwetgeving' is an initiatiefwetsvoorstel for its entire life,
    regardless of whether the current stage is 'verslag' or 'stemming'.

    Returns ``None`` only when no signal at all is available.
    """
    soorten = [s.lower() for s in (zaak_soorten or []) if s]
    if any("initiatiefwetgeving" in s for s in soorten):
        return "initiatiefwetsvoorstel"
    if any("wetgeving" in s for s in soorten):
        return "wetsvoorstel"
    if titel:
        t = titel.lower()
        if (
            t.startswith("voorstel van wet van het lid")
            or "initiatiefwetsvoorstel" in t
        ):
            return "initiatiefwetsvoorstel"
        if t.startswith("voorstel van wet") or t.startswith("wetsvoorstel"):
            return "wetsvoorstel"
        if "begroting" in t or "begrotingsstaat" in t:
            return "begroting"
    if any("motie" in s for s in soorten) and not any(
        "wetgeving" in s for s in soorten
    ):
        return "motie"
    if soorten:
        return "overig"
    return None


@dataclass
class DossierEnrichment:
    """Read-time augmentation of a dossier summary derived from linked documents."""

    titel: str | None = None
    titel_source: str | None = None  # 'dossier' | 'document' | None
    huidige_fase: str | None = None  # latest recognised stage, 'afgehandeld', or None
    stages_present: list[str] = field(default_factory=list)
    traject_kind: str | None = (
        None  # canonical kind: wetsvoorstel / initiatief / begroting / motie / overig
    )
    geopend_op: str | None = None  # earliest dated doc/activiteit, best-effort proxy


def enrich_dossier_docs(
    store: ArangoStore, dossiers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill missing titel / stage props on dossier docs from linked documents.

    This is the read-time fallback for records that haven't yet been
    re-ingested. The ingest pipeline persists the same fields into the
    dossier props; here we only fill gaps so previously-ingested data still
    surfaces sensible values.

    Fast path: when every dossier already carries the four fields this
    function can fill (``titel``, ``stages_present``, ``huidige_fase`` not
    in the legacy ``overig`` sentinel, ``traject_kind``), we skip the
    expensive ``_enrich_dossiers`` query entirely. That call walks
    DEEL_VAN_DOSSIER + PART_OF_PROCEDURE for every dossier and DOCUMENT()s
    each linked publication/activity/vote — ~900 ms for an 80-row batch.
    The ingest pipeline writes these props on every dossier it touches,
    so the slow path only fires for legacy or stub docs.
    """
    needs_enrich = False
    for doc in dossiers:
        props = doc.get("props") or {}
        if (
            not props.get("titel")
            or not props.get("stages_present")
            or props.get("huidige_fase") in (None, "overig", "onbekend")
            or not props.get("traject_kind")
        ):
            needs_enrich = True
            break
    if not needs_enrich:
        # Still set titel_source for ingested rows that lack it — cheap.
        for doc in dossiers:
            props = doc.setdefault("props", {})
            if not props.get("titel_source") and props.get("titel"):
                props["titel_source"] = "dossier"
        return dossiers

    enrichments = _enrich_dossiers(store, dossiers)
    for doc in dossiers:
        props = doc.setdefault("props", {})
        enrichment = enrichments.get(doc["_id"])
        if enrichment is None:
            continue
        if not props.get("titel") and enrichment.titel:
            props["titel"] = enrichment.titel
            props["titel_source"] = enrichment.titel_source
        elif not props.get("titel_source") and props.get("titel"):
            props["titel_source"] = "dossier"
        if not props.get("stages_present"):
            props["stages_present"] = enrichment.stages_present
        # Fill huidige_fase only when persisted is missing or the legacy
        # 'overig' sentinel. We deliberately do NOT overwrite the legacy
        # 'wetsvoorstel' value here, even though the new vocabulary would
        # reassign it to a later stage: until the persisted backfill runs,
        # 'wetsvoorstel' is the only signal the frontend has that this is a
        # wet-traject, and dropping it leaves users with empty buckets. The
        # ingest pipeline writes the authoritative latest-stage value, plus
        # traject_kind to carry the wet-traject signal independently.
        if props.get("huidige_fase") in (None, "overig"):
            if enrichment.huidige_fase is not None:
                props["huidige_fase"] = enrichment.huidige_fase
        if not props.get("traject_kind") and enrichment.traject_kind:
            props["traject_kind"] = enrichment.traject_kind
        if not props.get("geopend_op") and enrichment.geopend_op:
            props["geopend_op"] = enrichment.geopend_op
    return dossiers


def _select_titel(
    props: dict[str, Any], docs: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Return (titel, titel_source) for a dossier, falling back to linked docs."""
    raw_titel = props.get("titel")
    nummer = props.get("kamerstuknummer") or str(props.get("nummer") or "")
    # Treat placeholder titel == kamerstuknummer as missing.
    has_real_titel = bool(raw_titel) and raw_titel != nummer
    if has_real_titel:
        return raw_titel, "dossier"
    if not docs:
        return None, None
    # Prefer wetsvoorstel → mvt → any document with a title.
    for target_stage in ("wetsvoorstel", "mvt", None):
        for d in docs:
            if not d.get("titel"):
                continue
            if (
                target_stage is None
                or classify_doc_soort(d.get("soort")) == target_stage
            ):
                return d["titel"], "document"
    return None, None


def _accumulate_stages(
    docs: list[dict[str, Any]],
    activiteiten: list[dict[str, Any]],
    stemmingen: list[dict[str, Any]],
    zaak_soorten: list[str],
) -> tuple[dict[str, str], dict[str, str], bool]:
    """Build stage_first, stage_last dicts and any_signal flag from all signals."""
    stage_first: dict[str, str] = {}
    stage_last: dict[str, str] = {}
    any_signal = False

    def _record(stage: str | None, datum: str | None) -> None:
        nonlocal any_signal
        if stage is None:
            return
        any_signal = True
        d = datum or ""
        if stage not in stage_first or (d and d < stage_first[stage]):
            stage_first[stage] = d
        if stage not in stage_last or (d and d > stage_last[stage]):
            stage_last[stage] = d

    for doc in docs:
        _record(classify_doc_soort(doc.get("soort")), doc.get("datum"))

    for act in activiteiten:
        stage = classify_doc_soort(act.get("soort")) or classify_zaak_soort(
            act.get("soort")
        )
        _record(stage, act.get("datum"))

    # Dossier-level Zaak.Soort roll-up — presence-only, no datum.
    for soort in zaak_soorten:
        stage = classify_zaak_soort(soort)
        if stage is not None and stage not in stage_first:
            any_signal = True
            stage_first[stage] = ""
            stage_last[stage] = ""

    if stemmingen:
        datums = [s.get("datum") for s in stemmingen if s.get("datum")]
        _record("stemming", min(datums) if datums else None)
        if datums:
            stage_last["stemming"] = max(datums)

    return stage_first, stage_last, any_signal


def _pick_huidige_fase(
    stage_first: dict[str, str],
    stage_last: dict[str, str],
    any_signal: bool,
    afgedaan: bool,
) -> tuple[str | None, list[str]]:
    """Return (huidige_fase, stages_present) given the accumulated stage dicts."""
    stages_present = sorted(
        stage_first.keys(),
        key=lambda st: (stage_first[st] or "", DOSSIER_STAGES.index(st)),
    )
    if afgedaan:
        if "afgehandeld" not in stages_present:
            stages_present = [*stages_present, "afgehandeld"]
        return "afgehandeld", stages_present
    if any_signal:
        huidige_fase = max(
            stage_last.keys(),
            key=lambda st: (stage_last[st] or "", DOSSIER_STAGES.index(st)),
        )
        return huidige_fase, stages_present
    return None, stages_present


def _enrich_dossiers(
    store: ArangoStore, dossiers: list[dict[str, Any]]
) -> dict[str, DossierEnrichment]:
    """Compute titel fallback + stage signals for a batch of dossiers.

    Looks at every publication linked to the dossier (directly via
    DEEL_VAN_DOSSIER, or via a procedure) and classifies its `soort`. Stages
    that fire at least once become `stages_present` (chronologically by first
    appearance). `huidige_fase` is the chronologically latest stage; falls
    back to 'afgehandeld' when the dossier is afgedaan, or to None for empty dossiers.
    """
    if not dossiers:
        return {}

    dossier_ids = [d["_id"] for d in dossiers]

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
    rows = list(store.query(aql, {"dossier_ids": dossier_ids}))
    rows_by_id: dict[str, dict[str, Any]] = {row["dossier_id"]: row for row in rows}

    by_id: dict[str, DossierEnrichment] = {}
    for dossier in dossiers:
        did = dossier["_id"]
        props = dossier.get("props") or {}
        row = rows_by_id.get(did) or {}
        docs = row.get("docs") or []
        activiteiten = row.get("activiteiten") or []
        stemmingen = row.get("stemmingen") or []
        zaak_soorten = list(props.get("zaak_soorten") or [])

        titel, titel_source = _select_titel(props, docs)
        stage_first, stage_last, any_signal = _accumulate_stages(
            docs, activiteiten, stemmingen, zaak_soorten
        )
        afgedaan = bool(props.get("afgedaan")) or bool(props.get("gesloten_op"))
        huidige_fase, stages_present = _pick_huidige_fase(
            stage_first, stage_last, any_signal, afgedaan
        )
        traject_kind = classify_traject_kind(
            zaak_soorten, titel=titel or props.get("titel")
        )
        all_dated = [d.get("datum") for d in docs if d.get("datum")] + [
            a.get("datum") for a in activiteiten if a.get("datum")
        ]

        by_id[did] = DossierEnrichment(
            titel=titel,
            titel_source=titel_source,
            huidige_fase=huidige_fase,
            stages_present=stages_present,
            traject_kind=traject_kind,
            geopend_op=min(all_dated) if all_dated else None,
        )

    return by_id


def get_dossier_by_nummer(
    store: ArangoStore, kamerstuknummer: str
) -> dict[str, Any] | None:
    """Fetch a Kamerstukdossier by its kamerstuknummer (e.g. '36558')."""
    aql = """
    FOR doc IN kamerstukdossiers
        FILTER doc.props.kamerstuknummer == @nummer
        LIMIT 1
        RETURN doc
    """
    for doc in store.query(aql, {"nummer": kamerstuknummer}):
        return doc
    return None


_DICTUM_EXCERPT_CHARS = 280


def _enrich_stemming_entry(
    entry: dict[str, Any],
    dossier_pubs_by_zaak_nummer: dict[str, dict[str, Any]],
) -> None:
    """Inline publication body (dictum excerpt + indieners) onto a stemming
    timeline entry, when the underlying publication can be resolved.

    Resolution: ``stemming.body.primary_zaak.nummer`` keys into a per-dossier
    map of publications (built once by the timeline query). Mutates ``entry``
    in place; no-op when no publication is found.
    """
    body = entry.get("body") or {}
    primary_zaak = body.get("primary_zaak") or {}
    nummer = primary_zaak.get("nummer")
    if not nummer:
        return
    pub = dossier_pubs_by_zaak_nummer.get(str(nummer))
    if pub is None:
        return
    pub_props = pub.get("props") or {}
    text = pub_props.get("text") or ""
    dictum_excerpt: str | None = None
    if text:
        dictum_excerpt = " ".join(text.split())[:_DICTUM_EXCERPT_CHARS]
    actors = pub_props.get("actors") or []
    # TK's DocumentActor.Relatie uses 'Eerste ondertekenaar' / 'Mede
    # ondertekenaar' / 'Medeondertekenaar'. Normalise to a tighter
    # 'indiener' / 'mede-indiener' for the FE while keeping the raw rol.
    _ROL_MAP = {
        "eerste ondertekenaar": "indiener",
        "mede ondertekenaar": "mede-indiener",
        "medeondertekenaar": "mede-indiener",
        "indiener": "indiener",
    }
    indieners = []
    for a in actors:
        raw_rol = (a.get("rol") or "").strip().lower()
        normalised = _ROL_MAP.get(raw_rol)
        if not normalised:
            continue
        indieners.append(
            {
                "lid_key": (a.get("persoon_id") or None),
                "naam": a.get("naam"),
                "partij": a.get("fractie"),
                "rol": normalised,
                "rol_raw": a.get("rol") or "",
            }
        )
    body["publication"] = {
        "key": pub.get("_key"),
        "id": pub.get("_id"),
        "soort": pub_props.get("soort"),
        "titel": pub_props.get("titel") or pub_props.get("title"),
        "volgnummer": pub_props.get("volgnummer"),
        "vergaderjaar": pub_props.get("vergaderjaar"),
        "datum": pub_props.get("datum"),
        "tk_url": pub_props.get("tk_url"),
        "dictum_excerpt": dictum_excerpt,
        "indieners": indieners,
    }
    entry["body"] = body


def _build_dossier_pub_index(
    store: ArangoStore, dossier_id: str
) -> dict[str, dict[str, Any]]:
    """Map Zaak.Nummer → publication for every publication linked to a dossier.

    Walks DEEL_VAN_DOSSIER directly and also via PART_OF_PROCEDURE; reads each
    publication's ``props.raw.Zaak[].Nummer`` as the join key. One query, used
    by ``get_dossier_timeline`` to enrich stemming rows without N+1 lookups.
    """
    aql = f"""
    LET direct = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            FILTER STARTS_WITH(e._from, 'publications/')
            LET p = DOCUMENT(e._from)
            FILTER p != null
            RETURN p
    )
    LET via_proc = (
        FOR e1 IN {COLLECTION_EDGES}
            FILTER e1._to == @dossier_id AND e1.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            FILTER STARTS_WITH(e1._from, 'procedures/')
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._to == e1._from AND e2.relation == '{RELATION_PART_OF_PROCEDURE}'
                LET p = DOCUMENT(e2._from)
                FILTER p != null
                RETURN p
    )
    FOR pub IN UNIQUE(APPEND(direct, via_proc))
        // Two shapes coexist: _normalize_documents stores a flat
        // ``zaak_nummers`` array; the older _normalize_publications keeps
        // the full TK payload under ``props.raw.Zaak[].Nummer``.
        LET nummers = LENGTH(pub.props.zaak_nummers OR []) > 0
            ? pub.props.zaak_nummers
            : (pub.props.raw != null AND pub.props.raw.Zaak != null
                ? (FOR z IN pub.props.raw.Zaak
                    FILTER z.Nummer != null RETURN z.Nummer)
                : [])
        FOR nummer IN nummers
            RETURN {{ nummer: nummer, pub: pub }}
    """
    out: dict[str, dict[str, Any]] = {}
    for row in store.query(aql, {"dossier_id": dossier_id}):
        nummer = str(row.get("nummer") or "")
        if nummer and nummer not in out:
            out[nummer] = row["pub"]
    return out


def get_dossier_timeline(
    store: ArangoStore,
    dossier_id: str,
    *,
    order: Literal["desc", "asc"] = "desc",
    soort_filter: list[str] | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    """Return ordered timeline entries (pubs, activiteiten, stemmingen, toezeggingen) for a dossier.

    Each entry has shape: {datum, soort, titel, body, _cursor_key}. Stemming
    entries are additionally enriched with ``body.publication`` carrying the
    underlying motie/amendement's dictum excerpt and indieners — resolved via
    primary_zaak.nummer when the document is loaded.
    """
    sort_dir = "DESC" if order == "desc" else "ASC"

    soort_clause = ""
    bind_vars: dict[str, Any] = {"dossier_id": dossier_id, "limit": limit}
    if soort_filter:
        soort_clause = "FILTER LOWER(item.soort) IN @soort_filter"
        bind_vars["soort_filter"] = [s.lower() for s in soort_filter]

    cursor_clause = ""
    if cursor:
        op = "<" if order == "desc" else ">"
        cursor_clause = f"FILTER item.datum {op} @cursor"
        bind_vars["cursor"] = cursor

    # DEEL_VAN_DOSSIER edges consistently point FROM linked nodes TO the dossier,
    # so filtering only on _to avoids the OR that prevented index use.
    aql = f"""
    LET docs = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @dossier_id AND edge.relation == "{RELATION_DEEL_VAN_DOSSIER}"
            LET col = SPLIT(edge._from, '/')[0]
            FILTER col IN ['publications', 'activiteiten', 'stemmingen', 'toezeggingen']
            LET doc = DOCUMENT(edge._from)
            FILTER doc != null
            RETURN doc
    )
    FOR item IN docs
        LET soort = (item.props.soort != null ? item.props.soort :
                     item.type == 'activiteit' ? 'Activiteit' :
                     item.type == 'stemming' ? 'Stemming' :
                     item.type == 'toezegging' ? 'Toezegging' : 'Document')
        LET datum = (item.props.datum != null ? item.props.datum :
                     item.props.gedaan_op != null ? item.props.gedaan_op : null)
        FILTER datum != null
        {soort_clause}
        {cursor_clause}
        SORT datum {sort_dir}
        LIMIT @limit
        RETURN {{
            datum: datum,
            soort: soort,
            titel: item.props.display_name,
            tk_url: item.props.tk_url,
            body: item.props,
            node_id: item._id,
            node_type: item.type
        }}
    """
    rows = list(store.query(aql, bind_vars))

    # Enrich stemming entries with the underlying publication's dictum +
    # indieners. The pub index is built once per dossier; we only look it up
    # when there's at least one stemming row in the result.
    if any(r.get("node_type") == "stemming" for r in rows):
        pub_index = _build_dossier_pub_index(store, dossier_id)
        for entry in rows:
            if entry.get("node_type") == "stemming":
                _enrich_stemming_entry(entry, pub_index)

    return rows


def get_dossier_documents(
    store: ArangoStore,
    dossier_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return publications (Kamerstuk documents) linked to this dossier.

    Looks for publications connected via DEEL_VAN_DOSSIER edges, either directly
    or indirectly via the procedure chain (publication → procedure → dossier).
    Returns a paginated list sorted by datum descending.
    """
    aql = f"""
    LET direct = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            LET node = DOCUMENT(e._from)
            FILTER node != null AND SPLIT(e._from, '/')[0] == 'publications'
            RETURN node
    )
    LET via_procedure = (
        FOR e1 IN {COLLECTION_EDGES}
            FILTER e1._to == @dossier_id AND e1.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            FILTER SPLIT(e1._from, '/')[0] == 'procedures'
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._to == e1._from AND e2.relation == 'PART_OF_PROCEDURE'
                LET pub = DOCUMENT(e2._from)
                FILTER pub != null AND SPLIT(e2._from, '/')[0] == 'publications'
                RETURN pub
    )
    LET all_docs = UNIQUE(APPEND(direct, via_procedure))
    LET total = LENGTH(all_docs)
    LET items = (
        FOR doc IN all_docs
            SORT doc.props.datum DESC
            LIMIT @offset, @limit
            RETURN {{
                id: doc._id,
                key: doc._key,
                soort: doc.props.soort,
                titel: (doc.props.titel != null ? doc.props.titel :
                        doc.props.title != null ? doc.props.title :
                        doc.props.display_name),
                volgnummer: doc.props.volgnummer,
                dossier_nummer: doc.props.dossier_nummer,
                vergaderjaar: doc.props.vergaderjaar,
                datum: doc.props.datum,
                tk_url: doc.props.tk_url,
                display_name: doc.props.display_name
            }}
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(
        store.query(aql, {"dossier_id": dossier_id, "limit": limit, "offset": offset})
    )
    if not rows:
        return {"total": 0, "items": []}
    return rows[0]


def get_documents_for_dossiers(
    store: ArangoStore,
    dossier_ids: list[str],
    *,
    per_dossier_limit: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Bulk variant: top-N publications per dossier in one round trip.

    Replaces the N+1 of calling ``/api/dossiers/{key}/documents`` 25× from
    the parliamentary Lagen load. Returns a map keyed by dossier ``_id``.
    """
    if not dossier_ids:
        return {}
    aql = f"""
    FOR dossier_id IN @ids
        LET direct = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                FILTER STARTS_WITH(e._from, 'publications/')
                LET pub = DOCUMENT(e._from)
                FILTER pub != null
                RETURN pub
        )
        LET via_procedure = (
            FOR e1 IN {COLLECTION_EDGES}
                FILTER e1._to == dossier_id AND e1.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                FILTER STARTS_WITH(e1._from, 'procedures/')
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._to == e1._from AND e2.relation == 'PART_OF_PROCEDURE'
                    FILTER STARTS_WITH(e2._from, 'publications/')
                    LET pub = DOCUMENT(e2._from)
                    FILTER pub != null
                    RETURN pub
        )
        LET all_pubs = UNIQUE(APPEND(direct, via_procedure))
        LET items = (
            FOR doc IN all_pubs
                SORT doc.props.datum DESC
                LIMIT @per_dossier_limit
                RETURN {{
                    id: doc._id,
                    key: doc._key,
                    soort: doc.props.soort,
                    titel: (doc.props.titel != null ? doc.props.titel :
                            doc.props.title != null ? doc.props.title :
                            doc.props.display_name),
                    volgnummer: doc.props.volgnummer,
                    dossier_nummer: doc.props.dossier_nummer,
                    vergaderjaar: doc.props.vergaderjaar,
                    datum: doc.props.datum,
                    tk_url: doc.props.tk_url,
                    display_name: doc.props.display_name
                }}
        )
        RETURN {{ dossier_id: dossier_id, items: items }}
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for row in store.query(
        aql, {"ids": dossier_ids, "per_dossier_limit": per_dossier_limit}
    ):
        result[row["dossier_id"]] = row["items"]
    return result


_MUTATION_RELATIONS = frozenset(
    {
        RELATION_WIJZIGT,
        RELATION_INTRODUCEERT,
        RELATION_TREKT_IN,
        RELATION_REFERS_TO_ARTICLE,
        RELATION_MENTIONS_ARTICLE,
    }
)
_EXPLANATION_RELATIONS = frozenset({RELATION_EXPLAINS_ARTICLE})


def _classify_relation(relation: str | None) -> str:
    """Map an edge relation to a coarse kind: 'mutation' or 'explanation'.

    Mutation edges flag pending changes to article text (WIJZIGT/INTRODUCEERT/
    TREKT_IN) or strong references to articles in a wijzigingsvoorstel
    (REFERS_TO_ARTICLE/MENTIONS_ARTICLE). Explanation edges (EXPLAINS_ARTICLE)
    are MvT-style discussion of an article without proposing a change. The
    frontend renders these as separate overlays, so the discriminator must be
    preserved in the response.
    """
    if relation in _EXPLANATION_RELATIONS:
        return "explanation"
    return "mutation"


def get_dossier_mutations(store: ArangoStore, dossier_id: str) -> dict[str, Any]:
    """Return the pending-mutation + MvT-explanation subgraph for this dossier.

    Primary signal: edges from publications/procedures that are
    DEEL_VAN_DOSSIER this dossier, in either of two kinds:
      - ``mutation``    — VOORGESTELD status, or relation in
        WIJZIGT/INTRODUCEERT/TREKT_IN/REFERS_TO_ARTICLE/MENTIONS_ARTICLE
      - ``explanation`` — relation EXPLAINS_ARTICLE (MvT-style discussion)

    Fallback (when the primary returns nothing — e.g. no DEEL_VAN_DOSSIER
    links yet): same relations, scoped via publication ``dossier_nummer``
    instead of the edge graph.

    Each edge carries a ``kind`` discriminator so the frontend can render
    the two channels as separate overlays. Each node's ``kind`` is the
    strongest kind across its incident edges (``mutation`` wins over
    ``explanation``).
    """
    # DEEL_VAN_DOSSIER edges point FROM nodes TO the dossier — use only _to to
    # leverage the index. The second filter drops the OR on _from/_to: since
    # STARTS_WITH(e._to, "instrument_articles/") is required and dossier member
    # IDs are never instrument_articles, only e._from IN member_ids can fire.
    aql_primary = f"""
    LET member_ids = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._to == @dossier_id AND edge.relation == "{RELATION_DEEL_VAN_DOSSIER}"
            RETURN edge._from
    )
    FOR e IN {COLLECTION_EDGES}
        FILTER e._from IN member_ids
        FILTER e.status == "{EDGE_STATUS_VOORGESTELD}"
            OR e.relation IN [
                "{RELATION_WIJZIGT}",
                "{RELATION_INTRODUCEERT}",
                "{RELATION_TREKT_IN}",
                "{RELATION_REFERS_TO_ARTICLE}",
                "{RELATION_MENTIONS_ARTICLE}",
                "{RELATION_EXPLAINS_ARTICLE}"
            ]
        FILTER STARTS_WITH(e._to, "instrument_articles/")
        LET from_node = DOCUMENT(e._from)
        LET to_node = DOCUMENT(e._to)
        RETURN {{
            edge: e,
            from_node: from_node,
            to_node: to_node
        }}
    """
    rows = list(store.query(aql_primary, {"dossier_id": dossier_id}))
    nodes_by_id: dict[str, dict[str, Any]] = {}
    node_kinds: dict[str, str] = {}
    edges_out: list[dict[str, Any]] = []

    def _bump_kind(node_id: str | None, kind: str) -> None:
        if not node_id:
            return
        if node_kinds.get(node_id) != "mutation":
            node_kinds[node_id] = kind

    for row in rows:
        e = row.get("edge") or {}
        fn = row.get("from_node")
        tn = row.get("to_node")
        if fn:
            nodes_by_id[fn["_id"]] = fn
        if tn:
            nodes_by_id[tn["_id"]] = tn
        kind = _classify_relation(e.get("relation"))
        _bump_kind(e.get("_from"), kind)
        _bump_kind(e.get("_to"), kind)
        edges_out.append(
            {
                "from_id": e.get("_from"),
                "to_id": e.get("_to"),
                "relation": e.get("relation"),
                "status": e.get("status"),
                "meta": e.get("meta"),
                "kind": kind,
            }
        )

    if nodes_by_id:
        nodes_with_kind = [
            {**doc, "_kind": node_kinds.get(node_id, "mutation")}
            for node_id, doc in nodes_by_id.items()
        ]
        return {"nodes": nodes_with_kind, "edges": edges_out}

    # Fallback: derive kamerstuknummer from the dossier document and look up
    # articles mentioned by publications with a matching dossier_nummer.
    dossier_doc = cast(
        dict[str, Any] | None,
        store.db.collection("kamerstukdossiers").get(dossier_id.split("/", 1)[-1]),
    )
    if not dossier_doc:
        return {"nodes": [], "edges": []}

    nummer = str(dossier_doc.get("props", {}).get("nummer", ""))
    if not nummer:
        return {"nodes": [], "edges": []}

    aql_fallback = f"""
    FOR pub IN publications
        FILTER pub.props.dossier_nummer == @nummer
            OR @nummer IN (pub.props.dossier_nummers OR [])
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == pub._id
            FILTER e.relation IN [
                "{RELATION_REFERS_TO_ARTICLE}",
                "{RELATION_MENTIONS_ARTICLE}",
                "{RELATION_EXPLAINS_ARTICLE}",
                "{RELATION_WIJZIGT}",
                "{RELATION_INTRODUCEERT}",
                "{RELATION_TREKT_IN}"
            ]
            FILTER STARTS_WITH(e._to, "instrument_articles/")
            LET article = DOCUMENT(e._to)
            FILTER article != null
            RETURN DISTINCT {{
                article: article,
                pub_id: pub._id,
                edge_relation: e.relation,
                pub_soort: pub.props.soort
            }}
    """
    for row in store.query(aql_fallback, {"nummer": nummer}):
        article = row.get("article") or {}
        article_id = article.get("_id")
        if not article_id:
            continue
        nodes_by_id[article_id] = article
        kind = _classify_relation(row.get("edge_relation"))
        _bump_kind(article_id, kind)
        _bump_kind(row.get("pub_id"), kind)
        edges_out.append(
            {
                "from_id": row.get("pub_id"),
                "to_id": article_id,
                "relation": row.get("edge_relation"),
                "status": None,
                "meta": {"pub_soort": row.get("pub_soort")},
                "kind": kind,
            }
        )

    nodes_with_kind = [
        {**doc, "_kind": node_kinds.get(node_id, "mutation")}
        for node_id, doc in nodes_by_id.items()
    ]
    return {"nodes": nodes_with_kind, "edges": edges_out}


def get_open_dossiers(
    store: ArangoStore,
    *,
    commissie_slug: str | None = None,
    onderwerp: str | None = None,
    fase: str | None = None,
    has_stage: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return open (non-afgedaan) dossiers with optional filters, paginated.

    Returns ``{"total": int, "items": [...]}``.  ``total`` is the absolute
    count of matching dossiers, independent of ``limit``/``offset``.

    `has_stage` filters to dossiers whose `stages_present` contains every
    listed stage (intersection semantics).
    """
    filters = [
        "doc.props.afgedaan == false OR doc.props.afgedaan == null",
        "doc.props.gesloten_op == null",
    ]
    bind_vars: dict[str, Any] = {"limit": limit, "offset": offset}

    if fase:
        filters.append("doc.props.huidige_fase == @fase")
        bind_vars["fase"] = fase
    if onderwerp:
        filters.append("CONTAINS(LOWER(doc.props.titel), LOWER(@onderwerp))")
        bind_vars["onderwerp"] = onderwerp
    if has_stage:
        filters.append("@has_stage ALL IN (doc.props.stages_present OR [])")
        bind_vars["has_stage"] = has_stage

    filter_clause = "\n        ".join(f"FILTER {f}" for f in filters)

    # Commissie filter: pre-compute the set of dossier _ids linked to this
    # commissie ONCE (as a top-level LET), then use a cheap IN-set check per
    # dossier row. The previous nested traversal inside the FOR loop was
    # O(D × E_commissie × E_activiteit).
    commissie_pre = ""
    commissie_filter = ""
    if commissie_slug:
        bind_vars["commissie_slug"] = commissie_slug
        commissie_pre = f"""
    LET _commissie = FIRST(
        FOR c IN commissies FILTER c.props.slug == @commissie_slug LIMIT 1 RETURN c
    )
    LET _commissie_dossier_ids = _commissie != null ? UNIQUE(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == _commissie._id AND e.relation == 'BEHANDELD_DOOR'
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._from == e._from AND e2.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                FILTER STARTS_WITH(e2._to, 'kamerstukdossiers/')
                RETURN e2._to
    ) : []
        """
        commissie_filter = "FILTER doc._id IN _commissie_dossier_ids"

    aql = f"""
    {commissie_pre}
    LET total = LENGTH(
        FOR doc IN kamerstukdossiers
            {filter_clause}
            {commissie_filter}
            RETURN 1
    )
    LET items = (
        FOR doc IN kamerstukdossiers
            {filter_clause}
            {commissie_filter}
            SORT doc.props.geopend_op DESC
            LIMIT @offset, @limit
            RETURN doc
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(store.query(aql, bind_vars))
    return rows[0] if rows else {"total": 0, "items": []}


def get_recent_dossiers(
    store: ArangoStore, *, days: int = 30, limit: int = 50
) -> list[dict[str, Any]]:
    """Return dossiers that had activity in the last N days."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    aql = f"""
    LET recent = (
        FOR doc IN activiteiten
            FILTER doc.props.datum >= @cutoff
            FOR edge IN {COLLECTION_EDGES}
                FILTER edge._from == doc._id AND edge.relation == '{RELATION_DEEL_VAN_DOSSIER}'
                LET dossier = DOCUMENT(edge._to)
                FILTER dossier != null AND SPLIT(edge._to, '/')[0] == 'kamerstukdossiers'
                RETURN DISTINCT dossier
    )
    FOR d IN recent
        LIMIT @limit
        RETURN d
    """
    return list(store.query(aql, {"cutoff": cutoff, "limit": limit}))


def count_dossier_members(store: ArangoStore, dossier_id: str) -> dict[str, int]:
    """Return member counts for all 4 collections linked to a dossier."""
    aql = f"""
    LET colls = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id AND e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            RETURN SPLIT(e._from, '/')[0]
    )
    RETURN {{
        publications:  LENGTH(FOR c IN colls FILTER c == 'publications'  RETURN 1),
        activiteiten:  LENGTH(FOR c IN colls FILTER c == 'activiteiten'  RETURN 1),
        stemmingen:    LENGTH(FOR c IN colls FILTER c == 'stemmingen'    RETURN 1),
        toezeggingen:  LENGTH(FOR c IN colls FILTER c == 'toezeggingen'  RETURN 1)
    }}
    """
    rows = list(store.query(aql, {"dossier_id": dossier_id}))
    return rows[0] if rows else {}
