"""What the HTML of a page preloads of the API: only URLs its app asks, character for
character (``tests/data/preloads.json``, the requests the explorer made on concordans.nl)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.api.seo import preload, shell
from lawgraph.api.seo.pages.base import Page
from lawgraph.config import settings
from lawgraph.core.readable_paths import parse_path
from tests.paths import TESTS

RECORDED: dict[str, Any] = json.loads(
    (TESTS / "data" / "preloads.json").read_text("utf-8")
)


def _preloads(case: dict[str, Any]) -> list[str]:
    query = [(name, value) for name, value in case.get("query", [])]
    if "focus" not in case:
        return preload.app_preloads(case["path"], query)
    pad = parse_path(case["path"])
    assert pad is not None
    return preload.source_preloads(pad, case["focus"])


@pytest.mark.parametrize(
    "case", RECORDED["cases"], ids=[c["path"] for c in RECORDED["cases"]]
)
def test_a_page_preloads_only_what_its_app_asks(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date.fromisoformat(RECORDED["day"])
    monkeypatch.setattr(preload, "dutch_today", lambda: day)
    preloads = _preloads(case)
    assert preloads
    assert len(set(preloads)) == len(preloads)
    assert [url for url in preloads if url not in case["asked"]] == []


def test_the_search_is_preloaded_of_its_query_alone() -> None:
    lanes = preload.app_preloads("/", [("q", " huur ")])[1:]
    assert [url.split("&")[0] for url in lanes] == ["/api/search?q=huur"] * 3
    # one character asks nothing; two the fast lane alone
    assert preload.app_preloads("/", [("q", "h")])[1:] == []
    assert len(preload.app_preloads("/", [("q", "hu")])[1:]) == 1
    # under another parameter the scope is the app's to read
    assert preload.app_preloads("/", [("q", "huur"), ("soort", "wetten")])[1:] == []


def test_actueel_under_a_filter_and_other_pages_preload_nothing() -> None:
    assert preload.app_preloads("/actueel", [("soort", "stemming")]) == []
    assert preload.app_preloads("/over", []) == []


def test_the_head_preloads_each_url_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``crossorigin`` (anonymous): the app fetches same-origin without credentials, and a
    preload of another credentials mode is not used."""
    monkeypatch.setattr(settings, "SPA_INDEX", str(tmp_path / "none.html"))
    shell.forget()
    page = Page("Art. 1", "", "/x", preload=["/api/feed?limit=1&facets=true"])
    html = shell.render(page)
    assert (
        '<link rel="preload" as="fetch" crossorigin '
        'href="/api/feed?limit=1&amp;facets=true" />'
    ) in html
    assert html.index('rel="preload"') < html.index("<title")
