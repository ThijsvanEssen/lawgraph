"""Conventions the whole code base keeps, checked by reading the source.

1. Relation names are written once, in ``config.constants``. Everywhere else
   they are referenced through a ``RELATION_*`` constant — including inside
   AQL, which is built with f-strings from those constants.
2. Identifiers are English. Dutch belongs to the sources: the modules that
   read a source's own field names are listed in ``SOURCE_FACING``.
3. Stored property names are English. What a node carries is ours to name, so
   no props field may be spelled in Dutch.
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
# `semantic tk` scans every text prop of a paper and its API payload: it needs the document.
_READS_WHOLE_DOCUMENTS = {"tk.py"}


def test_a_semantic_pipeline_does_not_have_whole_documents_sent_over() -> None:
    """A judgment is its XML, its text and its paragraphs; a loader asks for what it reads.

    ``slim(var, *fields)`` and ``JUDGMENT_TEXT`` in ``pipelines/semantic/base.py`` project
    the props in the query.
    """
    offenders = [
        f"{path.name}:{number}"
        for path in sorted((SRC / "pipelines" / "semantic").glob("*.py"))
        if path.name not in _READS_WHOLE_DOCUMENTS
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _WHOLE_DOCUMENT.search(line)
    ]
    assert not offenders, offenders


# ── every pipeline reports its progress ──────────────────────────────────────


def test_every_pipeline_reports_progress() -> None:
    """One implementation (core/progress.py): a live line in a terminal, a line a minute in a
    log file, a summary at the end. A pipeline reaches it through the reader of its phase."""
    pipelines = SRC / "pipelines"
    ways = {
        # the one retrieve loop, through ``fetch`` or called by name; tk-content updates
        "retrieve": ("def fetch(", "_store_all(", "Progress("),
        "normalize": ("_iter_raw_sources(", "RawRecords("),  # the tracked raw readers
        "semantic": ("self._track(", "self._judgment_texts("),
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


def test_every_edge_phase_of_normalize_names_the_edges_it_writes() -> None:
    """A writer with a name reports how far it is; without one the edge phase of a
    normalize step (hundreds of thousands of edges) is minutes of silence."""
    normalize = SRC / "pipelines" / "normalize"
    unnamed = [
        f"{path.name}:{number}"
        for path in sorted(normalize.glob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "EdgeWriter(" in line and "what=" not in line
    ]
    assert not unnamed
