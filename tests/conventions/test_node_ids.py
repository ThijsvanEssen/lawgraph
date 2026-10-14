"""A node id is built and split by the helpers of ``core.models`` (``node_id``,
``article_id``, ``Node.skeleton``; ``parse_node_id``, ``key_of``), never by hand."""

from __future__ import annotations

import re

from tests.conventions._scan import SRC, _python_files

MODELS = SRC / "core" / "models.py"

# An id written by hand: ``f"{COLLECTION_X}/{key}"``, ``f"judgments/{key}"``.
_BUILT_BY_HAND = re.compile(
    r'f"\{COLLECTION_[A-Z_]+\}/\{|f"(?:judgments|articles|article_versions|instruments|'
    r"instrument_versions|dossiers|decisions|documents|members|cases|activities|"
    r"commitments|committees|factions|cabinets|annexes)/\{"
)
# An id split by hand: ``node_id.split("/", 1)[1]``, ``row["id"].partition("/")[2]``.
_SPLIT_BY_HAND = re.compile(
    r'(?:_id|\bid\b|\["id"\]|\["other"\]|\bpaper|target_id|\bt)\s*\.\s*'
    r'(?:split\("/"(?:, ?1)?\)|partition\("/"\))'
)


def _lines_matching(pattern: re.Pattern[str]) -> list[str]:
    return [
        f"{path.relative_to(SRC)}:{number}: {line.strip()}"
        for path in _python_files()
        if path != MODELS
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]


def test_no_node_id_built_by_hand() -> None:
    assert _lines_matching(_BUILT_BY_HAND) == []


def test_no_node_id_split_by_hand() -> None:
    assert _lines_matching(_SPLIT_BY_HAND) == []
