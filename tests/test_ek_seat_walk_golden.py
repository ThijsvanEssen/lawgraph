"""What the walk of the Eerste Kamer's seats gives, pinned for every term of the fixtures:
the pages of ``/personele_mutaties``, a faction's own history, the factions known per term,
the seats of its first day and each stretch with its events and mismatches.

``tests/fixtures/eerstekamer/ek_seat_walk_golden.json`` holds the expected output. A change in
it is a change in the seats: check every line of the diff before writing the file anew with
``python tests/test_ek_seat_walk_golden.py``.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from lawgraph.core import ek_composition as composition
from lawgraph.core import ek_mutations, ek_pages, ek_seat_walk
from lawgraph.core.kiesraad import parse_ek_result
from tests.paths import FIXTURES, fixture_text

GOLDEN = FIXTURES / "eerstekamer" / "ek_seat_walk_golden.json"

# Each term of the fixtures: its Kiesraad result, its first day and the day it ends.
TERMS = [
    ("2003-2007", "EK20030526", "2003-06-10", "2007-06-11"),
    ("2007-2011", "EK20070529", "2007-06-12", "2011-06-06"),
    ("2011-2015", "EK20110523", "2011-06-07", "2015-06-08"),
    ("2015-2019", "EK20150526", "2015-06-09", "2019-06-10"),
    ("2019-2023", "EK20190527", "2019-06-11", "2023-06-12"),
    ("2023-2027", "EK20230530", "2023-06-13", "2026-10-10"),
]


def _page(name: str) -> str:
    return fixture_text(name, sub="eerstekamer")


def _articles() -> list[tuple[str, ek_pages.Article]]:
    old = json.loads(fixture_text("articles_2003_2023.json", sub="eerstekamer"))
    current = json.loads(fixture_text("articles_2023.json", sub="eerstekamer"))
    return [
        (
            a.get("term", "2023-2027"),
            ek_pages.Article(a["headline"], a["date"], a["text"], a["persons"]),
        )
        for a in [*old, *current]
    ]


def _plain(value: Any) -> Any:
    """A value as JSON: dataclasses as dicts, sets sorted, tuples as lists."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _term(term: str, code: str, start: str, end: str) -> dict[str, Any]:
    articles = [a for t, a in _articles() if t == term]
    lineage = ek_mutations.faction_history(
        _page("fractie_progressief_nederland_pro.html")
    )
    changes = [c for a in articles for c in ek_mutations.read(a).changes] + lineage
    spelled = [n for a in articles for n in ek_mutations.spelled_out(a.text)]
    today = composition.factions(_page("fracties_2026.html"))
    known = {
        f.abbreviation or f.name: ek_seat_walk.aliases(f.abbreviation or f.name, f.path)
        for f in today
    }
    result = parse_ek_result(fixture_text(f"{code}.html", sub="kiesraad"))
    assert result is not None
    factions = ek_seat_walk.known_factions(known, result.seats, changes, spelled)
    seats, unmatched = ek_seat_walk.start_seats(result.seats, factions)
    walked = ek_seat_walk.walk(
        start, seats, ek_seat_walk.canonical(changes, factions), end
    )
    return {
        "spelled": spelled,
        "factions": factions,
        "start_seats": seats,
        "unmatched": unmatched,
        "stretches": walked.stretches,
        "mismatches": walked.mismatches,
        "checked": walked.checked,
    }


def _outputs() -> dict[str, Any]:
    return _plain(
        {
            "term_pages": {
                name: ek_pages.term_page(_page(name))
                for name in ("personele_mutaties_2019.html", "personele_mutaties_2023.html")
            },
            "article": ek_pages.article(
                _page("nieuws_20260402_senator_van_gasteren_uit_bbb.html"),
                "2026-04-02",
                "Senator Van Gasteren uit BBB-fractie",
            ),
            "faction_history": ek_mutations.faction_history(
                _page("fractie_progressief_nederland_pro.html")
            ),
            "terms": {term: _term(term, *rest) for term, *rest in TERMS},
        }
    )  # fmt: skip


def test_the_walk_of_every_term_stays_the_same() -> None:
    expected = json.loads(GOLDEN.read_text("utf-8"))
    actual = _outputs()
    for part in expected:
        assert actual[part] == expected[part], part
    assert actual.keys() == expected.keys()


if __name__ == "__main__":
    GOLDEN.write_text(
        json.dumps(_outputs(), ensure_ascii=False, indent=0, sort_keys=True) + "\n",
        "utf-8",
    )
