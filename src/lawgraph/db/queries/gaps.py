"""The graph reads of the retrieve phase: what the graph refers to and does not hold (the
work list of ``retrieve <source> --mode gaps`` and the report of ``lawgraph gaps``), and the
identifiers a retrieve command takes from the graph."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_EU_CELEX,
    RELATION_ANSWERS,
    SOURCE_BWB,
    SOURCE_EURLEX,
)
from lawgraph.core.judgments import PROCEDURE_PRELIMINARY_RULING
from lawgraph.db.counting import Store


def _truthy(value: str) -> str:
    """Whether the json *value* is truthy as ArangoDB's ``||`` takes it: not missing, null,
    false, 0 or "" (an empty array or object is truthy)."""
    return f"coalesce(({value})::jsonb NOT IN ('null', 'false', '0', '\"\"'), false)"


def _first_truthy(*values: str) -> str:
    """``a || b || c``: the first truthy one of the json *values*, else the last."""
    whens = " ".join(f"WHEN {_truthy(v)} THEN {v}" for v in values[:-1])
    return f"CASE {whens} ELSE {values[-1]} END"


def _given(value: str) -> str:
    """``x != null`` for the json *value*: present and not null."""
    return f"coalesce(json_typeof({value}), 'null') <> 'null'"


# ── laws ─────────────────────────────────────────────────────────────────────


def basis_bwb_ids(store: Store) -> Iterator[Any]:
    """BWB ids named as the basis of a loaded regulation, the most named first."""
    return store.query(
        f"""
        SELECT upper(b.v ->> 'bwb_id') AS bwb_id
        FROM instruments i
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(i.props -> 'basis') = 'array' THEN i.props -> 'basis' END
        ) AS b(v)
        WHERE lg_str(i.props -> 'source') = %(source)s AND {_given("b.v -> 'bwb_id'")}
        GROUP BY 1
        ORDER BY count(*) DESC NULLS LAST, bwb_id NULLS FIRST
        """,
        {"source": SOURCE_BWB},
    )


def loaded_bwb_ids(store: Store) -> Iterator[Any]:
    """The BWB ids (upper case) of the regulations that are loaded, not stubs."""
    return store.query(
        """
        SELECT upper(bwb_id) FROM instruments
        WHERE bwb_id IS NOT NULL AND stub IS NOT TRUE
        ORDER BY key
        """
    )


def stub_article_counts(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, count}`` of the stub articles per law, the most referred to first."""
    return store.query(
        """
        SELECT bwb_id, count(*)::int AS count FROM articles
        WHERE stub IS TRUE AND bwb_id IS NOT NULL
        GROUP BY bwb_id
        ORDER BY count DESC NULLS LAST, bwb_id NULLS FIRST
        """
    )


def instrument_titles(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, title}`` of every instrument with a BWB id: its best available title."""
    title = _first_truthy(
        "props -> 'citation_title'", "props -> 'title'", "props -> 'display_name'"
    )
    return store.query(
        f"""
        SELECT bwb_id, {title} AS title FROM instruments
        WHERE bwb_id IS NOT NULL
        ORDER BY key
        """
    )


# ── judgments, EU acts, treaties ─────────────────────────────────────────────


def stub_dutch_eclis(store: Store) -> Iterator[Any]:
    """ECLIs of the Dutch stub judgments, sorted."""
    return store.query(
        """
        SELECT ecli FROM judgments
        WHERE stub IS TRUE AND starts_with(ecli, 'ECLI:NL:')
        ORDER BY ecli NULLS FIRST
        """
    )


def unanswered_preliminary_rulings(
    store: Store, *, paragraphs: int
) -> Iterator[dict[str, Any]]:
    """``{ecli, paragraphs}`` of the preliminary rulings without an ANSWERS edge, with their
    first *paragraphs* paragraphs (where they say who asked their questions)."""
    first = """(
        SELECT coalesce(json_agg(p.v ORDER BY p.n), '[]'::json)
        FROM json_array_elements(
            CASE WHEN json_typeof(j.props -> 'paragraphs') = 'array'
                 THEN j.props -> 'paragraphs' END
        ) WITH ORDINALITY AS p(v, n)
        WHERE p.n <= %(paragraphs)s
    )"""
    return store.query(
        f"""
        SELECT j.ecli, {first} AS paragraphs
        FROM judgments j
        WHERE lg_str(j.props -> 'judgment_metadata' -> 'type') = %(procedure)s
          AND j.ecli IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM edges e WHERE e.from_id = j.id AND e.relation = %(answers)s
          )
        ORDER BY j.ecli NULLS FIRST
        """,
        {
            "procedure": PROCEDURE_PRELIMINARY_RULING,
            "answers": RELATION_ANSWERS,
            "paragraphs": paragraphs,
        },
    )


def unretrieved_celex_refs(store: Store) -> Iterator[Any]:
    """The EU acts BWB regulations name (``props.celex_refs``) or implement by their
    considerans (``props.implements_celex``) that were not retrieved, sorted."""
    return store.query(
        """
        SELECT DISTINCT c.named
        FROM instruments i
        CROSS JOIN LATERAL unnest(
            coalesce(lg_text_array(i.props -> 'celex_refs'), '{}')
            || coalesce(lg_text_array(i.props -> 'implements_celex'), '{}')
        ) AS c(named)
        WHERE NOT EXISTS (
            SELECT 1 FROM raw_sources r
            WHERE r.source = %(source)s AND r.kind = %(kind)s
              AND upper(r.external_id) = c.named
        )
        ORDER BY c.named NULLS FIRST
        """,
        {"source": SOURCE_EURLEX, "kind": RAW_KIND_EU_CELEX},
    )


def known_celex_ids(store: Store) -> Iterator[Any]:
    """The CELEX number of every instrument that has one."""
    return store.query(
        "SELECT celex FROM instruments WHERE celex IS NOT NULL ORDER BY key"
    )


def stub_echr_eclis(store: Store) -> Iterator[Any]:
    """ECLIs (or HUDOC app numbers) of the stub ECHR judgments, sorted."""
    return store.query(
        """
        SELECT ecli FROM judgments
        WHERE stub IS TRUE AND starts_with(ecli, 'ECLI:CE:ECHR:')
        ORDER BY ecli NULLS FIRST
        """
    )


def stub_treaty_ids(store: Store) -> Iterator[Any]:
    """External ids of the stub treaty instruments."""
    return store.query(
        """
        SELECT props -> 'external_id' FROM instruments
        WHERE stub IS TRUE
          AND kind IN ('verdrag', 'bilateraalverdrag', 'multilateraalverdrag')
        ORDER BY key
        """
    )


# ── Kamerstukken ─────────────────────────────────────────────────────────────


def papers_with_dossier(store: Store, kinds: list[str]) -> Iterator[dict[str, Any]]:
    """The Tweede Kamer papers whose kind contains one of *kinds* (lower case), with the
    dossier they are numbered in and their number there: ``{key, title, number, suffix,
    sequence, date}``."""
    title = _first_truthy("props -> 'title'", "props -> 'display_name'", "to_json(key)")
    return store.query(
        f"""
        SELECT key,
               {title} AS title,
               props -> 'dossier_number' AS number,
               props -> 'dossier_suffix' AS suffix,
               props -> 'sequence' AS sequence,
               props -> 'date' AS date
        FROM documents
        WHERE 'TK' = ANY(labels)
          AND {_given("props -> 'dossier_number'")} AND {_given("props -> 'sequence'")}
          AND EXISTS (
            SELECT 1 FROM unnest(%(kinds)s::text[]) AS w
            WHERE strpos(lower(coalesce(kind, '')), w) > 0
          )
        ORDER BY key
        """,
        {"kinds": kinds},
    )


def existing_raw_keys(
    store: Store, keys: list[str], *, retry_after_iso: str | None = None
) -> Iterator[Any]:
    """Which of the raw record *keys* exist; with *retry_after_iso* only those whose
    ``retry_after`` lies after it (a missing document not to be asked for again yet)."""
    retry = (
        "AND lg_str(doc -> 'meta' -> 'retry_after') > %(now)s"
        if retry_after_iso
        else ""
    )
    bind: dict[str, Any] = {"keys": keys}
    if retry_after_iso:
        bind["now"] = retry_after_iso
    return store.query(
        f"""
        SELECT key FROM raw_sources
        WHERE key = ANY(%(keys)s::text[]) {retry}
        ORDER BY key
        """,
        bind,
    )


def dossiers_named_by_publications(store: Store) -> list[str]:
    """The dossier numbers that an amending or commencing publication names (on an article
    version, or on the publication or regulation itself) and that no dossier has."""
    rows = store.query(
        """
        WITH named AS (
            SELECT unnest(
                coalesce(lg_text_array(
                    v.props -> 'origin_publication' -> 'dossiers'), '{}')
                || coalesce(lg_text_array(
                    v.props -> 'commencement_publication' -> 'dossiers'), '{}')
            ) AS number
            FROM article_versions v
            UNION
            SELECT unnest(lg_text_array(i.props -> 'dossier_numbers'))
            FROM instruments i
        )
        SELECT number FROM named
        WHERE number ~ '^[0-9]+$'
          AND NOT EXISTS (SELECT 1 FROM dossiers d WHERE d.number = named.number)
        ORDER BY number NULLS FIRST
        """
    )
    return list(rows)


def dossiers_with_numbers(store: Store, numbers: list[str]) -> set[str]:
    """Those of *numbers* that a dossier has."""
    rows = store.query(
        """
        SELECT n FROM unnest(%(numbers)s::text[]) AS n
        WHERE EXISTS (SELECT 1 FROM dossiers d WHERE d.number = n)
        """,
        {"numbers": numbers},
    )
    return set(rows)


def dossiers_named_by_papers(store: Store) -> list[str]:
    """The dossier labels (``36996``, ``31700-VI``) that a Tweede Kamer paper or case is part
    of and that no dossier has."""
    rows = store.query(
        """
        WITH named AS (
            SELECT unnest(dossier_numbers) AS label
            FROM documents WHERE 'TK' = ANY(labels)
            UNION
            SELECT unnest(lg_text_array(props -> 'dossier_numbers')) FROM cases
        )
        SELECT label FROM named
        WHERE NOT EXISTS (SELECT 1 FROM dossiers d WHERE d.label = named.label)
        ORDER BY label NULLS FIRST
        """
    )
    return list(rows)


def dossiers_missing_papers(store: Store) -> list[str]:
    """The numbers of the dossiers that lack a paper below the highest number the graph has
    of them: nr. 48 of the Wmcz 2018 without nr. 1 to 47. Each paper counts in the dossier
    it is numbered in, a chapter of a budget (``36600-XV``) on its own."""
    rows = store.query(
        """
        SELECT DISTINCT number FROM (
            SELECT dossier_number AS number
            FROM documents
            WHERE 'TK' = ANY(labels)
              AND dossier_number IS NOT NULL
              AND lg_num(props -> 'sequence') IS NOT NULL
            GROUP BY dossier_number, props ->> 'dossier_suffix'
            HAVING count(DISTINCT lg_num(props -> 'sequence'))
                   < max(lg_num(props -> 'sequence'))
        ) incomplete
        ORDER BY number NULLS FIRST
        """
    )
    return list(rows)


def holds_label(store: Store, collection: str, label: str) -> bool:
    """Whether *collection* holds a node with *label* (``documents``, ``TK``): whether the
    normalize pipeline that writes them has run."""
    return bool(
        next(
            store.query(
                f"SELECT EXISTS (SELECT 1 FROM {collection} "
                "WHERE labels @> ARRAY[%(label)s]::text[])",
                {"label": label},
            )
        )
    )
