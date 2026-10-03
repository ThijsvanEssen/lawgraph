"""The TOOI thesauri of the BWB (legal areas, government themes): found by version and stored
next to the ministries list, from the real lists."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from lawgraph.clients.tooi import (
    LEGAL_AREAS_LIST,
    THEMES_LIST,
    TooiClient,
    latest_version,
)
from lawgraph.config.constants import (
    RAW_KIND_TOOI_MINISTRIES,
    RAW_KIND_TOOI_THESAURUS,
    TOOI_BWB_LEGAL_AREAS,
    TOOI_BWB_THEMES,
)
from lawgraph.pipelines.retrieve.tooi import TooiRetrievePipeline
from tests.fakes import RawSourcesFake

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LEGAL_AREAS = json.loads((FIXTURES / "tooi_bwb_rechtsgebieden.json").read_text())
THEMES = json.loads((FIXTURES / "tooi_bwb_themas.json").read_text())
MINISTRIES = json.loads((FIXTURES / "tooi_ministeries.json").read_text())


def _page(name: str, *versions: int) -> str:
    return "".join(
        f'<a href="expression?lijst_uri=https%3A%2F%2Fidentifier.overheid.nl%2Ftooi%2Fset'
        f'%2F{name}%2F{v}">{v}</a>'
        for v in versions
    )


def test_the_latest_version_of_each_list() -> None:
    assert latest_version(_page(TOOI_BWB_LEGAL_AREAS, 1, 2), LEGAL_AREAS_LIST) == 2
    # the page of one list says nothing of another
    assert latest_version(_page(TOOI_BWB_LEGAL_AREAS, 1, 2), THEMES_LIST) is None


class _Response:
    def __init__(self, text: str = "", body: Any = None) -> None:
        self.text, self.body = text, body

    def json(self) -> Any:
        return self.body


def _client(answers: dict[str, _Response]) -> TooiClient:
    client = TooiClient.__new__(TooiClient)
    client._build_url = lambda path: path  # type: ignore[method-assign]

    def fake_get(url: str, **_kw: Any) -> _Response:
        return answers[url]

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def _answers() -> dict[str, _Response]:
    return {
        "tooi/set/rwc_ministeries_compleet": _Response(
            _page("rwc_ministeries_compleet", 6)
        ),
        "tooi/set/rwc_ministeries_compleet/6": _Response(body=MINISTRIES),
        LEGAL_AREAS_LIST: _Response(_page(TOOI_BWB_LEGAL_AREAS, 1, 2)),
        f"{LEGAL_AREAS_LIST}/2": _Response(body=LEGAL_AREAS),
        THEMES_LIST: _Response(_page(TOOI_BWB_THEMES, 2)),
        f"{THEMES_LIST}/2": _Response(body=THEMES),
    }


def test_a_thesaurus_is_its_latest_version() -> None:
    url, items = _client(_answers()).thesaurus(LEGAL_AREAS_LIST)
    assert url == f"{LEGAL_AREAS_LIST}/2" and items == LEGAL_AREAS


def test_a_list_without_concepts_raises() -> None:
    answers = {**_answers(), f"{THEMES_LIST}/2": _Response(body=MINISTRIES)}
    with pytest.raises(RuntimeError, match="no concept"):
        _client(answers).thesaurus(THEMES_LIST)


def test_the_retrieve_stores_the_ministries_and_both_thesauri() -> None:
    pipeline = TooiRetrievePipeline(RawSourcesFake(), client=_client(_answers()))  # type: ignore[arg-type]
    records = pipeline.fetch()

    assert [(r.kind, r.external_id) for r in records] == [
        (RAW_KIND_TOOI_MINISTRIES, "rwc_ministeries_compleet"),
        (RAW_KIND_TOOI_THESAURUS, TOOI_BWB_LEGAL_AREAS),
        (RAW_KIND_TOOI_THESAURUS, TOOI_BWB_THEMES),
    ]
    assert records[2].payload_json == {"items": THEMES}
    assert records[1].meta["url"] == f"{LEGAL_AREAS_LIST}/2"
