"""The closed vocabularies of the graph and the API: each written once, its values pinned.

A ``Literal`` of two or more words is declared in one place; ``core`` (or
``config.constants``) holds what the graph stores, the API imports it, and the runtime
tuple is ``get_args`` of it. The values the API answers are pinned in
``tests/api/openapi_enums.json``.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
from typing import Any, get_args

import pytest

from lawgraph.config import constants
from lawgraph.core import (
    cabinet_phases,
    cabinet_posts,
    coalition,
    echr_findings,
    eerstekamer_votes,
    judgment_outcome,
    models,
    post_ministries,
    publications,
    tk_records,
    votes,
)
from lawgraph.core import documents as core_documents
from lawgraph.core import feed as core_feed
from lawgraph.core import judgments as core_judgments
from lawgraph.core.provenance import BASIS_FORMAL
from lawgraph.core.relations import RELATIONS
from tests.paths import SRC

PINNED: list[tuple[str, Any, tuple[str, ...]]] = [
    ("chambers by label", core_documents.CHAMBER_PRECEDENCE, ("EK", "TK")),
    ("chambers", constants.CHAMBERS, ("TK", "EK")),
    (
        "feed kinds",
        core_feed.FEED_KINDS,
        (
            "toezegging",
            "Voorstel van wet",
            "Nota van wijziging",
            "Amendement",
            "Motie",
            "stemming",
            "publicatie",
            "inwerkingtreding",
            "Brief regering",
            "uitspraak",
        ),
    ),
    (
        "person roles",
        get_args(core_feed.PersonRole),
        ("indiener", "medeindiener", "bewindspersoon"),
    ),
    (
        "feed coalition",
        get_args(core_feed.FeedCoalition),
        ("together", "split", "wissel", "decisive"),
    ),
    (
        "coalition patterns",
        (coalition.PATTERN_TOGETHER, coalition.PATTERN_SPLIT, coalition.PATTERN_WISSEL),
        ("together", "split", "wissel"),
    ),
    (
        "decision kinds",
        core_judgments.DECISION_KINDS,
        (
            "arrest",
            "vonnis",
            "beschikking",
            "uitspraak",
            "beslissing",
            "conclusie",
            "prejudiciële beslissing",
        ),
    ),
    (
        "phase kinds",
        get_args(cabinet_phases.PhaseKind),
        ("formatie", "in_functie", "demissionair", "dubbel_demissionair", "missionair"),
    ),
    (
        "judgment outcomes",
        (
            judgment_outcome.REJECTED,
            judgment_outcome.QUASHED,
            judgment_outcome.PARTLY_QUASHED,
            judgment_outcome.QUASHED_REFERRED,
            judgment_outcome.AFFIRMED,
            judgment_outcome.CONFIRMED,
            judgment_outcome.WELL_FOUNDED,
            judgment_outcome.UNFOUNDED,
            judgment_outcome.INADMISSIBLE,
            judgment_outcome.DISMISSED,
            judgment_outcome.GRANTED,
            echr_findings.VIOLATION,
            echr_findings.NO_VIOLATION,
        ),
        (
            "verworpen",
            "vernietigd",
            "gedeeltelijk vernietigd",
            "vernietigd en verwezen",
            "bekrachtigd",
            "bevestigd",
            "gegrond",
            "ongegrond",
            "niet-ontvankelijk",
            "afgewezen",
            "toegewezen",
            "schending",
            "geen schending",
        ),
    ),
    (
        "conclusion outcomes",
        (
            judgment_outcome.TO_REJECT,
            judgment_outcome.TO_QUASH,
            judgment_outcome.TO_QUASH_REFER,
            judgment_outcome.TO_INADMISSIBLE,
            judgment_outcome.TO_WELL_FOUNDED,
            judgment_outcome.TO_UNFOUNDED,
            judgment_outcome.TO_ANSWER,
        ),
        (
            "verwerping",
            "vernietiging",
            "vernietiging en verwijzing",
            "niet-ontvankelijkverklaring",
            "gegrondverklaring",
            "ongegrondverklaring",
            "beantwoording",
        ),
    ),
    (
        "ministry sources",
        (post_ministries.SOURCE_PAGE, *post_ministries.SOURCES),
        ("page", "tk_signatures", "tk_commitments", "staatscourant"),
    ),
    (
        "ministry missing",
        (post_ministries.MISSING_NO_SOURCE, post_ministries.MISSING_AMBIGUOUS),
        ("no_source", "ambiguous"),
    ),
    (
        "acting reasons",
        (cabinet_posts.ACTING_SOURCE, cabinet_posts.ACTING_HELD_OTHER_SEAT),
        ("source", "held_other_seat"),
    ),
    (
        "EK vote labels",
        (
            eerstekamer_votes.LABEL_FOR,
            eerstekamer_votes.LABEL_AGAINST,
            eerstekamer_votes.LABEL_NOTED,
        ),
        ("voor", "tegen", "aantekening gevraagd"),
    ),
    (
        "signing capacities",
        (
            tk_records.CAPACITY_MEMBER,
            tk_records.CAPACITY_GOVERNMENT,
            tk_records.CAPACITY_OTHER,
        ),
        ("kamerlid", "bewindspersoon", "overig"),
    ),
    (
        "paper outcomes",
        votes.OUTCOMES,
        (
            "aangenomen",
            "verworpen",
            "ingetrokken",
            "aangehouden",
            "vervallen",
            "vervangen",
        ),
    ),
    (
        "committee kinds",
        get_args(tk_records.CommitteeKind),
        ("vast", "algemeen", "tijdelijk", "enquete", "delegatie", "overig"),
    ),
    (
        "vote choices",
        (votes.VOTE_FOR, votes.VOTE_AGAINST, votes.VOTE_NOTED),
        ("Voor", "Tegen", "Aantekening gevraagd"),
    ),
    (
        "vote kinds",
        (tk_records.VOTE_KIND_MEMBER, tk_records.VOTE_KIND_FACTION),
        ("member", "faction"),
    ),
    ("directions", models.DIRECTIONS, ("outbound", "inbound")),
    ("publication series", publications.SERIES, ("stb", "stcrt", "trb")),
    (
        "edge statuses",
        (constants.EDGE_STATUS_CANONIEK, constants.EDGE_STATUS_VOORGESTELD),
        ("canoniek", "voorgesteld"),
    ),
    (
        "implements bases",
        (constants.IMPLEMENTS_BASIS_NIM, constants.IMPLEMENTS_BASIS_CONSIDERANS),
        ("national_implementing_measure", "considerans"),
    ),
    (
        "echr findings",
        (echr_findings.VIOLATION, echr_findings.NO_VIOLATION),
        ("schending", "geen schending"),
    ),
]


@pytest.mark.parametrize(
    ("name", "values", "pinned"), PINNED, ids=[p[0] for p in PINNED]
)
def test_a_vocabulary_keeps_its_values(name: str, values: Any, pinned: Any) -> None:
    assert tuple(values) == tuple(pinned)


# ── each vocabulary written once ─────────────────────────────────────────────


def _literals(source: str) -> list[tuple[int, frozenset[str]]]:
    """The words of each ``Literal[...]`` of two or more words *source* spells out: the
    quoted ones (a ``Literal`` built from another lists only its own)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Literal"
        ):
            parts = (
                node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            )
            words = [
                part.value
                for part in parts
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ]
            if len(words) >= 2:
                found.append((node.lineno, frozenset(words)))
    return found


def _declared(source: str) -> list[str]:
    """The names *source* declares as a ``Literal`` at module level: ``X = Literal[...]``."""
    return [
        node.targets[0].id
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Subscript)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "Literal"
    ]


def _module(path: pathlib.Path) -> str:
    return ".".join(("lawgraph", *path.relative_to(SRC).with_suffix("").parts))


def _written() -> dict[frozenset[str], list[str]]:
    """Where each set of words is spelled out as a ``Literal``: ``module:line``."""
    written: dict[frozenset[str], list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        for line, words in _literals(path.read_text()):
            written.setdefault(words, []).append(f"{path.relative_to(SRC)}:{line}")
    return written


def test_a_vocabulary_is_spelled_out_once() -> None:
    twice = {
        ", ".join(sorted(words)): where
        for words, where in _written().items()
        if len(where) > 1
    }
    assert twice == {}, "declare it once and import it"


def test_a_vocabulary_built_from_another_is_not_spelled_out_again() -> None:
    """``PersonRole`` is ``SubmitterRole`` and ``bewindspersoon``: a ``Literal`` that lists
    all three words copies it."""
    written = _written()
    copies = {}
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text()
        names = _declared(source)
        if not names:
            continue
        module = importlib.import_module(_module(path))
        here = str(path.relative_to(SRC))
        for name in names:
            words = frozenset(get_args(getattr(module, name)))
            own = {f"{here}:{line}" for line, w in _literals(source) if w == words}
            others = [where for where in written.get(words, []) if where not in own]
            if others:
                copies[f"{_module(path)}.{name}"] = others
    assert copies == {}, "import the Literal instead"


def test_the_scan_reads_the_words_of_a_literal() -> None:
    source = (
        'A = Literal["x", "y"]\n'
        'B = Literal[A, "z"]\n'
        'def f(c: Literal["one"]) -> None: ...\n'
    )
    assert _literals(source) == [(1, frozenset({"x", "y"}))]
    assert _declared(source) == ["A", "B"]


# ── the words of the Kamer named once ────────────────────────────────────────

# The chambers and the kinds of paper, as ``config.constants`` and ``core.tk_records`` name
# them; the queries and the pipelines use those names (in SQL through an f-string).
KAMER_WORDS = (
    constants.CHAMBER_TK,
    constants.CHAMBER_EK,
    tk_records.KIND_MOTION,
    tk_records.KIND_AMENDMENT,
    tk_records.KIND_BILL,
    tk_records.KIND_GOVERNMENT_LETTER,
    tk_records.FIRST_SIGNATORY,
)
NAMED_ONCE = ("db", "pipelines")


def _quoted(source: str) -> set[str]:
    """The words of ``KAMER_WORDS`` *source* spells out between quotes."""
    return {
        word
        for word in KAMER_WORDS
        if re.search(rf"""['"]{re.escape(word)}['"]""", source)
    }


@pytest.mark.parametrize(
    "path",
    [path for part in NAMED_ONCE for path in sorted((SRC / part).rglob("*.py"))],
    ids=lambda path: str(path.relative_to(SRC)),
)
def test_queries_and_pipelines_name_the_words_of_the_kamer(path: pathlib.Path) -> None:
    assert _quoted(path.read_text()) == set()


def test_the_scan_finds_a_quoted_word() -> None:
    assert _quoted("WHERE lg_str(d.props -> 'kind') = 'Motie'") == {"Motie"}
    assert _quoted('labels=["EK"]') == {"EK"}
    assert _quoted("WHERE kind = '{KIND_MOTION}' -- TK documents") == set()


def test_the_relations_name_the_basis_of_a_formal_relation() -> None:
    assert any(f"`{BASIS_FORMAL}`" in spec.description for spec in RELATIONS)
