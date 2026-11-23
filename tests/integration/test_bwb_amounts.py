"""The numbers of an article through its toestanden: the real ``normalize bwb``,
``normalize bwb-history`` and ``semantic bwb-amounts``, and the route ``/amounts``.

Two toestanden of one law: in the second, an amount of article 7 changed (a new version)
and the editors added the amount in force from later that year (a redaction). The old
amount keeps its row and holds until the new version begins; a day picks the value of that
day.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
)
from lawgraph.db import GraphStore
from tests.asserts import assert_status
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0001840"
_PHRASE = "Niemand heeft voorafgaand verlof nodig"
OLD = (
    (FIXTURES / "bwb_grondwet_toestand.xml")
    .read_text()
    .replace(
        _PHRASE,
        "Een vergunning kost € 3.068 en wordt binnen zes weken verleend; " + _PHRASE,
    )
)
NEW = OLD.replace(
    'versie-id="25689252" id="C36647081" label-id="2940564" inwerking="2018-12-21"',
    'versie-id="99999999" id="C36647081" label-id="2940564" inwerking="2025-01-01"',
).replace(
    "€ 3.068",
    '€ 3.115<redactie type="extra">per 1 juli 2025: € 3.200</redactie>',
)


def _seed(store: GraphStore) -> None:
    toestanden = [
        (RAW_KIND_BWB_TOESTAND, LAW, NEW, "2025-01-01", None),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2018-12-21",
            OLD,
            "2018-12-21",
            "2024-12-31",
        ),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2025-01-01",
            NEW,
            "2025-01-01",
            "9999-12-31",
        ),
    ]
    write_toestanden(
        store,
        [
            (
                kind,
                external_id,
                xml,
                {
                    "bwb_id": LAW,
                    "state_url": f"https://repo/{LAW}/{start}.xml",
                    "start_date": start,
                    "end_date": end,
                },
            )
            for kind, external_id, xml, start, end in toestanden
        ],
    )


pytestmark = pytest.mark.xdist_group("bwb_amounts")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _seed(store)
        cli("normalize", "bwb")
        cli("normalize", "bwb-history")
        cli("semantic", "bwb-amounts")
        cli("semantic", "bwb-amounts")  # a second run changes nothing
        yield store


def _rows(store: GraphStore) -> list[tuple[Any, ...]]:
    return [
        (
            r["valid_from"],
            r["kind"],
            float(r["value"]),
            r["unit"],
            r["source"],
            r["from"],
        )
        for r in store.query(
            """
            SELECT v.valid_from, a.kind, a.value, a.unit, a.source, a.valid_from AS from
            FROM lg_amounts a JOIN article_versions v ON v.id = a.version_id
            WHERE v.article_number = '7'
            ORDER BY v.valid_from, a.span_start
            """
        )
    ]


def test_a_new_toestand_with_another_amount_is_a_row_of_its_own(
    store: GraphStore,
) -> None:
    assert _rows(store) == [
        ("2018-12-21", "bedrag", 3068.0, "EUR", "text", None),
        ("2018-12-21", "termijn", 6.0, "week", "text", None),
        ("2025-01-01", "bedrag", 3115.0, "EUR", "text", None),
        ("2025-01-01", "bedrag", 3200.0, "EUR", "redaction", "2025-07-01"),
        ("2025-01-01", "termijn", 6.0, "week", "text", None),
    ]


def _held(amount: dict[str, Any]) -> dict[str, Any]:
    """The step of the version read."""
    (step,) = [s for s in amount["history"] if s["selected"]]
    return step


def test_the_route_gives_each_value_with_its_days(api: Api) -> None:
    body = api.get_json(f"/api/articles/{LAW}/7/amounts")
    assert (
        body["version_key"] is not None,
        body["valid_from"],
        body["valid_until"],
    ) == (
        True,
        "2025-01-01",
        None,
    )
    amount, redacted, term = body["amounts"]
    assert (
        amount["text"],
        _held(amount)["value"],
        amount["part"],
        amount["source"],
    ) == (
        "€ 3.115",
        3115.0,
        "lid-1",
        "text",
    )
    assert [
        (s["valid_from"], s["valid_until"], s["value"]) for s in amount["history"]
    ] == [
        ("2018-12-21", "2025-01-01", 3068.0),
        ("2025-01-01", None, 3115.0),
    ]
    assert (
        _held(redacted)["value"],
        redacted["source"],
        _held(redacted)["valid_from"],
    ) == (
        3200.0,
        "redaction",
        "2025-07-01",
    )
    assert len(redacted["history"]) == 1  # the old version had no redaction
    assert (term["kind"], _held(term)["value"], term["unit"], len(term["history"])) == (
        "termijn",
        6.0,
        "week",
        2,
    )


def test_a_day_picks_the_version_in_force_on_it(api: Api) -> None:
    body = api.get_json(f"/api/articles/{LAW}/7/amounts", date="2020-06-01")
    assert (body["valid_from"], body["valid_until"]) == ("2018-12-21", "2025-01-01")
    assert [(a["text"], _held(a)["valid_until"]) for a in body["amounts"]] == [
        ("€ 3.068", "2025-01-01"),
        ("zes weken", "2025-01-01"),
    ]
    before = api.get_json(f"/api/articles/{LAW}/7/amounts", date="1900-01-01")
    assert (before["version_key"], before["amounts"]) == (None, [])
    assert_status(api.get(f"/api/articles/{LAW}/9999/amounts"), 404)
