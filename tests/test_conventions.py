"""Conventions the whole code base keeps, checked by reading the source.

1. Relation names are written once, in ``config.constants``. Everywhere else
   they are referenced through a ``RELATION_*`` constant — including inside
   AQL, which is built with f-strings from those constants.
2. Identifiers are English. Dutch belongs to the sources: the modules that
   read a source's own field names are listed in ``SOURCE_FACING``.
3. Stored property names are English. What a node carries is ours to name, so
   no props field may be spelled in Dutch.
4. AQL is written in ``db/`` only. Pipelines, commands and the API call a
   function of ``db/queries/`` and do not touch the driver handle.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from lawgraph.core.relations import RELATION_NAMES

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "lawgraph"

# The two modules that are allowed to spell a relation name out.
RELATION_NAME_HOMES = {
    SRC / "config" / "constants.py",
    SRC / "core" / "relations.py",
}

# Modules that mirror a source's own vocabulary: the Dutch field names of the
# Tweede Kamer API and of the BWB and KOOP XML. Their
# identifiers may carry the source's spelling.
SOURCE_FACING = (
    SRC / "clients",
    SRC / "pipelines" / "retrieve",
)

# ``RAW_KIND_*`` values name a source's own record kinds (``tk-zaak``,
# ``tk-stemming``), so their constants keep the source's spelling.
SOURCE_KIND_PREFIX = "RAW_KIND_"

# Dutch stems that must not appear in an identifier of an owned module. Each
# has an English counterpart in the vocabulary: Annex, Committee, Faction,
# Decision, Commitment, Activity, Case, Document.
DUTCH_STEMS = (
    "bijlage",
    "commissie",
    "fractie",
    "stemming",
    "toezegging",
    "activiteit",
    "zaak",
    "publicatie",
)


def _python_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


def _owned_files() -> list[pathlib.Path]:
    skipped = SOURCE_FACING
    return [
        path
        for path in _python_files()
        if not any(path == entry or entry in path.parents for entry in skipped)
    ]


# ── 1. relation names live in the constants ──────────────────────────────────


def _quoted_relation_names(source: str) -> set[str]:
    """Relation names that appear as a quoted string anywhere in *source*.

    Covers plain string literals and the relation names baked into an AQL
    string, which is why the scan is textual rather than AST-based: a name
    interpolated from a constant (``f"... '{RELATION_PART_OF}' ..."``) never
    appears literally, while a hand-written ``'PART_OF'`` does.
    """
    found: set[str] = set()
    for name in RELATION_NAMES:
        # A quote, then the bare name, then a quote — no surrounding word
        # characters, so ``PART_OF`` does not match inside ``PART_OF_X``.
        if re.search(rf"""['"]{name}['"]""", source):
            found.add(name)
    return found


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_relation_names_are_only_written_in_the_constants(path: pathlib.Path) -> None:
    if path in RELATION_NAME_HOMES:
        return
    written = _quoted_relation_names(path.read_text())
    assert not written, (
        f"{path.relative_to(SRC)} spells out {sorted(written)}; use the "
        f"RELATION_* constant (in AQL: an f-string from the constant)."
    )


def test_the_scan_would_catch_a_literal() -> None:
    """The guard above is only worth having if it actually matches."""
    assert _quoted_relation_names("FILTER e.relation == 'PART_OF'") == {"PART_OF"}
    assert _quoted_relation_names('relation="REFERS_TO"') == {"REFERS_TO"}
    assert _quoted_relation_names("relation == '{RELATION_PART_OF}'") == set()
    assert _quoted_relation_names("PART_OF_SOMETHING_ELSE") == set()


# ── 2. identifiers are English ───────────────────────────────────────────────


def _identifiers(tree: ast.AST) -> set[str]:
    """Every name this module defines: functions, classes, arguments, targets."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    return names


@pytest.mark.parametrize("path", _owned_files(), ids=lambda p: p.name)
def test_identifiers_have_no_dutch_stems(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text())
    offenders = {
        name
        for name in _identifiers(tree)
        if not name.startswith(SOURCE_KIND_PREFIX)
        for stem in DUTCH_STEMS
        if stem in name.lower()
    }
    assert not offenders, (
        f"{path.relative_to(SRC)} defines {sorted(offenders)}; the graph and "
        f"the API use the English vocabulary."
    )


def test_module_names_have_no_dutch_stems() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in _owned_files()
        for stem in DUTCH_STEMS
        if stem in path.stem.lower()
    ]
    assert not offenders, offenders


# ── 3. stored property names are English ─────────────────────────────────────

PROPS_MODULE = SRC / "core" / "props.py"

# Dutch words that must not be a token of a stored property name. Matching is
# per snake_case token, so ``title`` does not trip on ``titel`` and ``number``
# does not trip on ``nummer``.
DUTCH_PROP_TOKENS = frozenset(
    {
        *DUTCH_STEMS,
        "aangenomen",
        "actief",
        "afgedaan",
        "afkorting",
        "agendapunt",
        "besluit",
        "datum",
        "fase",
        "gedaan",
        "geopend",
        "gesloten",
        "kamerstuk",
        "kamerstuknummer",
        "lid",
        "naam",
        "nummer",
        "onderwerp",
        "partij",
        "persoon",
        "soort",
        "tekst",
        "titel",
        "toestand",
        "toevoeging",
        "traject",
        "verdrag",
        "verdragsnummer",
        "vergaderjaar",
        "vergadering",
        "volgnummer",
        "wet",
        "zetels",
    }
)


def _props_fields() -> list[tuple[str, str]]:
    """``(class name, field name)`` for every annotated field in props.py."""
    tree = ast.parse(PROPS_MODULE.read_text())
    return [
        (node.name, stmt.target.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]


def _dutch_tokens(field: str) -> set[str]:
    return DUTCH_PROP_TOKENS & set(field.lower().split("_"))


def test_the_props_scan_finds_the_schemas() -> None:
    """The guard below is only worth having if it reads real fields."""
    fields = _props_fields()
    assert ("DossierProps", "current_stage") in fields
    assert len(fields) > 100


def test_the_props_scan_tells_dutch_from_english() -> None:
    """Whole-token matching, so the English word next to it stays clean."""
    assert _dutch_tokens("titel_source") == {"titel"}
    assert _dutch_tokens("dossier_nummer") == {"nummer"}
    assert _dutch_tokens("title_source") == set()
    assert _dutch_tokens("dossier_number") == set()
    assert _dutch_tokens("date") == set()


def test_props_field_names_are_english() -> None:
    offenders = sorted(
        f"{class_name}.{field}"
        for class_name, field in _props_fields()
        if _dutch_tokens(field)
    )
    assert not offenders, (
        f"{sorted(offenders)} are stored under a Dutch name; a property name "
        f"is ours to choose, so it is English."
    )


# ── joins on a sparse index ──────────────────────────────────────────────────

_SPARSE_JOIN = re.compile(r"\.props\.(bwb_id|celex|ecli) == (?!@|null\b)[A-Za-z_]")


def test_a_join_on_a_sparse_index_excludes_null() -> None:
    """``i.props.bwb_id == pub.props.bwb_id`` alone is a full scan per outer row.

    The indexes on ``props.bwb_id``, ``props.celex`` and ``props.ecli`` are sparse. Compared
    with a value that is not a bind parameter, ArangoDB only uses one when the query also says
    ``!= null`` (explain: cost 587M against 410K for the Staatscourant join).
    """
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _SPARSE_JOIN.search(line) and "!= null" not in line
    ]
    assert not offenders, offenders


# ── semantic pipelines read the props they use ───────────────────────────────

_WHOLE_DOCUMENT = re.compile(r"RETURN (doc|art|inst|j|pub)\b(?![._\[])")
_SEMANTIC_QUERIES = (
    SRC / "db" / "queries" / "semantic.py",
    SRC / "db" / "queries" / "graph_stats.py",
)
# `semantic tk` scans every text prop of a paper and its API payload: it needs the document.
_READS_WHOLE_DOCUMENTS = {"tk_documents"}


def _exempt_lines(tree: ast.AST) -> set[int]:
    return {
        number
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in _READS_WHOLE_DOCUMENTS
        for number in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    }


def test_a_semantic_pipeline_does_not_have_whole_documents_sent_over() -> None:
    """A judgment is its XML, its text and its paragraphs; a loader asks for what it reads.

    ``slim(var, *fields)`` in ``db/queries/semantic.py`` projects the props in the query.
    """
    offenders = []
    for path in _SEMANTIC_QUERIES:
        text = path.read_text()
        exempt = _exempt_lines(ast.parse(text))
        offenders += [
            f"{path.name}:{number}"
            for number, line in enumerate(text.splitlines(), 1)
            if number not in exempt and _WHOLE_DOCUMENT.search(line)
        ]
    assert not offenders, offenders


# ── AQL lives in db/ ─────────────────────────────────────────────────────────

DB = SRC / "db"

# A whole query (``FOR x IN`` and a clause of its body), a search, or a filter clause built
# apart to be put into one. Keywords are upper case, as the code writes AQL; prose ("for
# every record in the list") is not.
_AQL = re.compile(
    r"\bFOR\s+\w+(\s*,\s*\w+)*\s+IN\b[\s\S]*\b"
    r"(RETURN|FILTER|COLLECT|SORT|LIMIT|UPDATE|UPSERT|REPLACE|REMOVE|INSERT)\b"
    r"|\bSEARCH\s+ANALYZER\b"
    r"|\bFILTER\s+[\w.@\[\]]+\s*(==|!=|>=|<=|<|>|IN|LIKE)\s"
)

# Access to the database handle itself: what ``db/`` wraps.
_DRIVER_CALL = re.compile(
    r"\bstore\.query\(|\.aql\.execute\(|\bstore\.collection\(|\bstore\.db\."
)


def _string_texts(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, text)`` of every string literal; an f-string with ``{}`` for its fields."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                inside.update(id(sub) for sub in ast.walk(part))
    found = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{}"
                for part in node.values
            )
            found.append((node.lineno, text))
    return found


def _aql_in(source: str) -> list[int]:
    return [
        line for line, text in _string_texts(ast.parse(source)) if _AQL.search(text)
    ]


def test_the_aql_scan_tells_a_query_from_prose() -> None:
    """The guards below are only worth having if they match queries and nothing else."""
    assert _aql_in('A = f"FOR d IN {COLLECTION_X}\\n  FILTER d.x == @x\\n  RETURN d"')
    assert _aql_in('A = "FOR a IN annexes RETURN a._key"')
    assert _aql_in('A = "FILTER r.fetched_at >= @since"')
    assert _aql_in("A = \"FOR d IN view SEARCH ANALYZER(d.text == @q, 'text_nl')\"")
    assert not _aql_in('"""For every record in the list, return the key."""')
    assert not _aql_in('"""FOR a IN the list: nothing more."""')
    assert _DRIVER_CALL.search("rows = self.store.query(aql, bind)")
    assert _DRIVER_CALL.search("store.collection(COLLECTION_X).get(key)")
    assert not _DRIVER_CALL.search("raw_queries.iter_raw_records(self.store, source=s)")


@pytest.mark.parametrize(
    "path",
    [p for p in _python_files() if DB not in p.parents],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_aql_is_only_written_in_db(path: pathlib.Path) -> None:
    lines = _aql_in(path.read_text())
    assert not lines, (
        f"{path.relative_to(SRC)}:{lines} holds AQL; queries live in "
        f"db/queries/, the code outside db/ calls a function there."
    )


@pytest.mark.parametrize(
    "path",
    [
        p
        for top in ("pipelines", "commands", "api")
        for p in sorted((SRC / top).rglob("*.py"))
    ],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_pipelines_commands_and_api_do_not_use_the_driver(path: pathlib.Path) -> None:
    calls = [
        number
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _DRIVER_CALL.search(line)
    ]
    assert not calls, (
        f"{path.relative_to(SRC)}:{calls} queries the database itself; the queries and "
        f"collection access live in db/."
    )


# ── every pipeline reports its progress ──────────────────────────────────────


def test_every_pipeline_reports_progress() -> None:
    """One implementation (core/progress.py): a live line in a terminal, a line a minute in a
    log file, a summary at the end. A pipeline reaches it through the reader of its phase."""
    pipelines = SRC / "pipelines"
    ways = {
        # the one retrieve loop, through ``fetch`` or called by name; tk-content updates
        "retrieve": ("def fetch(", "_store_all(", "Progress("),
        "normalize": ("_iter_raw_sources(", "RawRecords("),  # the tracked raw readers
        "semantic": (
            "self._track(",
            "self._judgment_texts(",
            "self._judgment_paragraphs(",
        ),
    }
    silent = []
    for phase, calls in ways.items():
        for path in sorted((pipelines / phase).glob("*.py")):
            text = path.read_text()
            if "PipelineBase):" not in text or path.name == "base.py":
                continue  # helpers and detectors, not a pipeline
            if not any(call in text for call in calls) and "super().run(" not in text:
                silent.append(f"{phase}/{path.name}")
    assert "Progress(" in (pipelines / "semantic" / "graph_list_stats.py").read_text()
    assert not silent, f"no progress reported by: {silent}"


def test_semantic_pipelines_end_their_edges_through_the_edge_writer() -> None:
    """A list, a size check, a flush and two `+=` per pipeline: thirteen copies, of which
    one wrote its edges and forgot to count them. `EdgeWriter.flush_into` counts."""
    semantic = SRC / "pipelines" / "semantic"
    offenders = [
        f"{path.name}: {needle}"
        for path in sorted(semantic.glob("*.py"))
        for needle in ("edge_batch", "bulk_insert_or_update_edges(", "edges.created")
        if needle in path.read_text()
    ]
    assert not offenders
