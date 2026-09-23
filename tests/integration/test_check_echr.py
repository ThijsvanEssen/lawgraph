"""`lawgraph check` counts ECHR judgments, not HUDOC items, run for real on the small test server.

HUDOC holds a judgment once per language, each an item of its own (``001-...``) with the same
ECLI; ``normalize echr`` makes one node of them. ``lawgraph_small`` had 100 records of 30
judgments, and the check took the 30 nodes for a normalize that was behind.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lawgraph.commands.check import check
from lawgraph.config.constants import RAW_KIND_ECHR_JUDGMENT, SOURCE_ECHR
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

LANGUAGES = ("ENG", "FRE", "DUT", "GER", "UKR")


def _item(number: int, language: str) -> dict[str, Any]:
    return {
        "itemid": f"001-{number}{LANGUAGES.index(language)}",
        "ecli": f"ECLI:CE:ECHR:2026:0908JUD00{number:05d}23",
        "appno": f"{number}/23",
        "docname": f"CASE OF A.A. v. THE NETHERLANDS ({number})",
        "languageisocode": language,
        "kpdate": "2026-09-08T00:00:00",
        "respondent": "NLD",
        "importance": "3",
        "article": "8;8-1",
        "doctype": "HFJUD",
    }


def _items() -> list[dict[str, Any]]:
    """Ten judgments, the first four in all five languages and the rest in English: 26 items."""
    return [
        _item(number, language)
        for number in range(10)
        for language in (LANGUAGES if number < 4 else LANGUAGES[:1])
    ]


def _store_items(store: ArangoStore, items: list[dict[str, Any]]) -> None:
    with RawSourceWriter(store) as writer:
        for item in items:
            writer.add(
                raw_source_doc(
                    source=SOURCE_ECHR,
                    kind=RAW_KIND_ECHR_JUDGMENT,
                    external_id=item["itemid"],
                    payload_json=item,
                )
            )


def _echr_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith(f"{SOURCE_ECHR}:")]


def test_a_judgment_in_several_languages_is_one_node_to_the_check(
    database: str, cli: Callable[..., Any]
) -> None:
    store = ArangoStore()
    _store_items(store, _items())
    cli("normalize", "echr")

    report = check(store, edges=False)

    assert not _echr_lines(report.problems)
    assert "nodes of echr in judgments: 10" in report.notes


def test_a_normalize_that_is_behind_is_still_reported(
    database: str, cli: Callable[..., Any]
) -> None:
    store = ArangoStore()
    _store_items(store, _items())
    cli("normalize", "echr")
    # Six English-only judgments came in after the normalize.
    _store_items(store, [_item(number, "ENG") for number in range(10, 16)])

    (line,) = _echr_lines(check(store, edges=False).problems)
    assert line.startswith(
        "echr: 32 echr-judgment-json records, 16 distinct, and 10 nodes"
    )
    assert "normalize echr" in line
