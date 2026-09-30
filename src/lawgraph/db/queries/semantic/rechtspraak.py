"""The reads and updates of the semantic phase for Rechtspraak and the ECHR: the judgments
a step scans, the lookups that link them (appeals, conclusions, referrals, series) and
the stubs left unreached."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
    SOURCE_ECHR,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.judgments import (
    CONCLUSION_ONLY_COURTS,
    DOCUMENT_TYPE_CONCLUSION,
    PROCEDURE_PRELIMINARY_RULING,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import slim


def judgment_paragraphs(
    store: Store, *, eclis: list[str] | None, batch_size: int
) -> Iterator[dict[str, Any]]:
    """``{ecli, paragraphs, unresolved_citations}`` (as a slim document) of every
    Rechtspraak judgment, only those of *eclis* when it is given."""
    bind: dict[str, Any] = {"source": SOURCE_RECHTSPRAAK}
    recent = ""
    if eclis is not None:
        bind["eclis"] = eclis
        recent = "FILTER j.props.ecli IN @eclis"
    aql = f"""
        FOR j IN {COLLECTION_JUDGMENTS}
            FILTER j.props.source == @source
            {recent}
            RETURN {slim("j", "ecli", "paragraphs", "unresolved_citations")}
        """
    return store.query(aql, bind, batch_size=batch_size)


def count_rechtspraak_judgments(store: Store) -> int | None:
    """How many Rechtspraak judgments the graph holds, from the index."""
    count_aql = f"""
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER j.props.source == @source
                COLLECT WITH COUNT INTO n
                RETURN n
            """
    count = next(iter(store.query(count_aql, {"source": SOURCE_RECHTSPRAAK})), None)
    return count if isinstance(count, int) else None


def judgment_ids_by_ecli(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id}`` of the judgments with these *eclis*."""
    aql = f"""
        FOR doc IN {COLLECTION_JUDGMENTS}
            FILTER doc.props.ecli IN @eclis
            RETURN {{ ecli: doc.props.ecli, id: doc._id }}
        """
    return store.query(aql, bind_vars={"eclis": eclis})


def judgments_with_related_eclis(store: Store) -> Iterator[dict[str, Any]]:
    """``{j_id, ecli, date, case_number, case_number_keys, procedure_type,
    related_eclis}`` of every judgment that names an earlier one."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.related_eclis != null
  FILTER LENGTH(j.props.related_eclis) > 0
  RETURN {{
    j_id: j._id,
    ecli: j.props.ecli,
    date: j.props.date_eff,
    case_number: j.props.case_number,
    case_number_keys: j.props.case_number_keys OR [],
    procedure_type: j.props.judgment_metadata.type,
    related_eclis: j.props.related_eclis,
  }}
"""
    return store.query(aql)


def judgment_instances(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id, date, case_number, case_number_keys, procedure, is_conclusion}`` of the
    judgments with these *eclis* (``core.appeals.Instance``)."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.ecli IN @eclis
  RETURN {{
    ecli: j.props.ecli,
    id: j._id,
    date: j.props.date_eff,
    case_number: j.props.case_number,
    case_number_keys: j.props.case_number_keys OR [],
    procedure: j.props.judgment_metadata.type,
    is_conclusion: j.props.judgment_metadata.document_type == @conclusion
      OR j.props.court_code IN @conclusion_courts
  }}
"""
    return store.query(
        aql,
        {
            "eclis": eclis,
            "conclusion": DOCUMENT_TYPE_CONCLUSION,
            "conclusion_courts": sorted(CONCLUSION_ONLY_COURTS),
        },
    )


def appeals_to_read(
    store: Store, *, procedure: str, paragraphs: int
) -> Iterator[dict[str, Any]]:
    """``{key, j_id, ecli, read, paragraphs, unresolved_appeal_targets}`` of the appeals
    whose metadata names no earlier instance (``read``: *procedure*, a regular expression,
    matches their ``judgment_metadata.type``), with their first *paragraphs* paragraphs;
    and of the judgments that carry unresolved appeal targets, so that those no longer
    read lose them."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.source == @source
  LET read = LENGTH(j.props.related_eclis) == 0
    AND REGEX_TEST(j.props.judgment_metadata.type || "", @procedure, true)
  FILTER read OR j.props.unresolved_appeal_targets != null
  RETURN {{
    key: j._key,
    j_id: j._id,
    ecli: j.props.ecli,
    read: read,
    paragraphs: read ? SLICE(j.props.paragraphs OR [], 0, @paragraphs)[* RETURN {{
      text: CURRENT.text
    }}] : [],
    unresolved_appeal_targets: j.props.unresolved_appeal_targets
  }}
"""
    return store.query(
        aql,
        {
            "source": SOURCE_RECHTSPRAAK,
            "procedure": procedure,
            "paragraphs": paragraphs,
        },
    )


def conclusion_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{ecli, court_code, date, case_number, is_conclusion, conclusion_eclis,
    case_number_keys}`` of every conclusion and of every judgment that names its
    conclusion."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.source == @source
  LET is_conclusion = j.props.judgment_metadata.document_type == @conclusion
    OR j.props.court_code IN @conclusion_courts
  FILTER is_conclusion OR LENGTH(j.props.conclusion_eclis) > 0
  RETURN {{
    ecli: j.props.ecli,
    court_code: j.props.court_code,
    date: j.props.date_eff,
    case_number: j.props.case_number,
    is_conclusion: is_conclusion,
    conclusion_eclis: j.props.conclusion_eclis OR [],
    case_number_keys: j.props.case_number_keys OR []
  }}
"""
    return store.query(
        aql,
        {
            "source": SOURCE_RECHTSPRAAK,
            "conclusion": DOCUMENT_TYPE_CONCLUSION,
            "conclusion_courts": sorted(CONCLUSION_ONLY_COURTS),
        },
    )


def judgments_by_case_keys(store: Store, keys: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, ecli, court_code, date, is_conclusion}`` of the judgments with one of these
    case number *keys* (``core.judgments.case_number_keys``), one row per key they carry."""
    aql = f"""
FOR key IN @keys
  FOR j IN {COLLECTION_JUDGMENTS}
    FILTER key IN j.props.case_number_keys[*]
    RETURN {{
      key: key,
      ecli: j.props.ecli,
      court_code: j.props.court_code,
      date: j.props.date_eff,
      is_conclusion: j.props.judgment_metadata.document_type == @conclusion
        OR j.props.court_code IN @conclusion_courts
    }}
"""
    return store.query(
        aql,
        {
            "keys": keys,
            "conclusion": DOCUMENT_TYPE_CONCLUSION,
            "conclusion_courts": sorted(CONCLUSION_ONLY_COURTS),
        },
    )


def decisions_on_dates(store: Store, dates: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, date, case_number}`` of the decisions (not conclusions) of these *dates*."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.date_eff IN @dates AND j.props.ecli != null
  FILTER j.props.judgment_metadata.document_type != @conclusion
    AND j.props.court_code NOT IN @conclusion_courts
  RETURN {{ecli: j.props.ecli, date: j.props.date_eff, case_number: j.props.case_number}}
"""
    return store.query(
        aql,
        {
            "dates": dates,
            "conclusion": DOCUMENT_TYPE_CONCLUSION,
            "conclusion_courts": sorted(CONCLUSION_ONLY_COURTS),
        },
    )


def court_decisions_between(
    store: Store, spans: list[dict[str, str]]
) -> Iterator[dict[str, Any]]:
    """``{court_code, ecli, date, case_number}`` of the decisions (not conclusions) of the
    court of each span (``{court_code, start, end}``) dated from its start to its end."""
    aql = f"""
FOR span IN @spans
  FOR j IN {COLLECTION_JUDGMENTS}
    FILTER j.props.court_code == span.court_code
    FILTER j.props.date_eff >= span.start AND j.props.date_eff <= span.end
    FILTER j.props.judgment_metadata.document_type != @conclusion
    RETURN DISTINCT {{
      court_code: j.props.court_code,
      ecli: j.props.ecli,
      date: j.props.date_eff,
      case_number: j.props.case_number
    }}
"""
    return store.query(aql, {"spans": spans, "conclusion": DOCUMENT_TYPE_CONCLUSION})


def preliminary_rulings(store: Store, *, paragraphs: int) -> Iterator[dict[str, Any]]:
    """``{ecli, related_eclis, paragraphs}`` of every preliminary ruling, with its first
    *paragraphs* paragraphs (where it says who asked its questions)."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.judgment_metadata.type == @procedure
  RETURN {{
    ecli: j.props.ecli,
    related_eclis: j.props.related_eclis OR [],
    paragraphs: SLICE(j.props.paragraphs OR [], 0, @paragraphs)
  }}
"""
    return store.query(
        aql, {"procedure": PROCEDURE_PRELIMINARY_RULING, "paragraphs": paragraphs}
    )


def generic_summaries(store: Store, *, min_dates: int) -> Iterator[str]:
    """The MD5 (``core.judgment_series.summary_fingerprint``) of every Rechtspraak summary
    written on at least *min_dates* distinct dates: templates, not summaries."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.source == @source AND j.props.summary != null
  COLLECT fingerprint = MD5(j.props.summary)
  AGGREGATE dates = COUNT_DISTINCT(j.props.date_eff)
  FILTER dates >= @min_dates
  RETURN fingerprint
"""
    return store.query(aql, {"source": SOURCE_RECHTSPRAAK, "min_dates": min_dates})


# The judgments of one court on one day, read through the index that `/api/stats/coverage`
# counts from (``db/schema.py``): every field of its prefix is fixed.
_COURT_DAY_FILTER = """
  FILTER j.props.stub == false AND j.props.source == @source
"""


def judgment_court_days(
    store: Store, *, eclis: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{court_code, date, tier, courts}`` of every day on which a court gave two or more
    Rechtspraak judgments, or, with *eclis*, of the days of those judgments."""
    bind: dict[str, Any] = {"source": SOURCE_RECHTSPRAAK}
    of_eclis = ""
    if eclis is not None:
        bind["eclis"] = eclis
        of_eclis = "FILTER j.props.ecli IN @eclis"
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  {_COURT_DAY_FILTER}
  {of_eclis}
  FILTER j.props.court_code != null AND j.props.date_eff != null
  COLLECT court_code = j.props.court_code, date = j.props.date_eff
  AGGREGATE tier = MAX(j.props.tier), courts = UNIQUE(j.props.court),
            count = COUNT(1)
  FILTER @eclis_given OR count > 1
  RETURN {{court_code, date, tier, courts}}
"""
    bind["eclis_given"] = eclis is not None
    return store.query(aql, bind)


def judgments_in_series(store: Store) -> Iterator[str]:
    """The ECLIs of the judgments that carry a ``series_id``."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.series_id != null
  RETURN j.props.ecli
"""
    return store.query(aql)


def replaced_judgments(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, key, ecli, replaced_by, same_as}`` of the judgments a later publication
    replaces (``props.replaced_by``) and of those ``SAME_AS`` another now; each through
    its sparse index."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.replaced_by != null OR j.props.same_as != null
  RETURN {{
    id: j._id,
    key: j._key,
    ecli: j.props.ecli,
    replaced_by: j.props.replaced_by,
    same_as: j.props.same_as
  }}
"""
    return store.query(aql)


def loaded_judgment_ids(store: Store, eclis: list[str]) -> Iterator[dict[str, Any]]:
    """``{ecli, id}`` of the judgments with these *eclis* that are loaded (no stub)."""
    aql = f"""
FOR doc IN {COLLECTION_JUDGMENTS}
  FILTER doc.props.ecli IN @eclis AND doc.props.stub != true
  RETURN {{ ecli: doc.props.ecli, id: doc._id }}
"""
    return store.query(aql, {"eclis": eclis})


def judgments_of_court_day(
    store: Store,
    *,
    court_code: str,
    date: str,
    tier: str | None,
    courts: list[str | None],
    batch_size: int,
) -> Iterator[dict[str, Any]]:
    """``{key, ecli, text, summary, document_type, case_number_keys, series_id,
    series_size}`` of the Rechtspraak judgments of one court on one day."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  {_COURT_DAY_FILTER}
  FILTER j.props.tier == @tier AND j.props.court_code == @court_code
  FILTER j.props.court IN @courts AND j.props.date_eff == @date
  RETURN {{
    key: j._key,
    ecli: j.props.ecli,
    text: j.props.text,
    summary: j.props.summary,
    document_type: j.props.judgment_metadata.document_type,
    case_number_keys: j.props.case_number_keys OR [],
    series_id: j.props.series_id,
    series_size: j.props.series_size
  }}
"""
    bind = {
        "source": SOURCE_RECHTSPRAAK,
        "court_code": court_code,
        "date": date,
        "tier": tier,
        "courts": courts,
    }
    return store.query(aql, bind, batch_size=batch_size)


def echr_judgments(store: Store) -> Iterator[dict[str, Any]]:
    """``{j_id, j_key, articles, conclusion}`` of the ECHR judgments that cite an article
    or have a conclusion."""
    aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.source == @source
  FILTER j.props.articles != null OR j.props.conclusion != null
  RETURN {{
    j_id: j._id,
    j_key: j._key,
    articles: j.props.articles,
    conclusion: j.props.conclusion
  }}
"""
    return store.query(aql, {"source": SOURCE_ECHR})


def procedural_neighbours(
    store: Store, ids: list[str], relations: list[str], *, chunk: int = 5000
) -> Iterator[list[str]]:
    """``[id, other]`` for every edge of *relations* between a node of *ids* and another,
    either way."""
    aql = f"""
    FOR id IN @ids
        FOR e IN {COLLECTION_EDGES}
            FILTER (e._from == id OR e._to == id) AND e.relation IN @relations
            RETURN [id, e._from == id ? e._to : e._from]
    """
    for start in range(0, len(ids), chunk):
        yield from store.query(
            aql, {"ids": ids[start : start + chunk], "relations": relations}
        )


def remove_unreached_judgment_stubs(store: Store) -> int:
    """Remove the stub judgments no edge reaches or leaves any more: a stub stands in for a
    judgment something links, and one nothing links is left from an earlier run. How many
    went."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.stub == true
        FILTER LENGTH(FOR e IN {COLLECTION_EDGES} FILTER e._to == j._id LIMIT 1 RETURN 1) == 0
        FILTER LENGTH(FOR e IN {COLLECTION_EDGES} FILTER e._from == j._id LIMIT 1 RETURN 1) == 0
        REMOVE j IN {COLLECTION_JUDGMENTS}
        RETURN 1
    """
    return sum(store.query(aql))
