"""``ops/usage-counts.py``: the counts it gives, and that only counts leave it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from lawgraph.core.notation import NotationParser
from lawgraph.db.queries.search.parser import load_notation_parser
from tests.paths import ROOT


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "usage_counts", ROOT / "ops" / "usage-counts.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


usage = _load()
NETWORK = "203.0.113.0"


def _line(day: str, method: str, path: str, status: int) -> str:
    return (
        f"{day} 09:22:00,316 [INFO] api.middleware: [abcd1234] {NETWORK} {method} {path}"
        f" → {status} 12b (1.0ms) cache=hit db=0.0ms worker=7\n"
    )


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/render/", ("pagina", "start")),
        ("/render/explore", ("pagina", "explore")),
        ("/render/wetten/BWBR0005289", ("pagina", "wetten")),
        ("/render/wetten/BWBR0005289/artikel/6:162", ("pagina", "wetten/artikel")),
        ("/render/leden/rob-jetten", ("pagina", "leden")),
        ("/render/wp-admin/x", ("pagina", "overig")),
        ("/api/search", ("api", "search")),
        ("/api/nodes/factions/vvd/neighborhood", ("api", "nodes/neighborhood")),
        ("/api/nodes/factions/vvd", ("api", "nodes")),
        ("/api/geheim", ("api", "overig")),
        ("/api", ("api", "overig")),
        ("/.env", ("overig", "overig")),
    ],
)
def test_route_kind(path: str, kind: tuple[str, str]) -> None:
    assert usage.route_kind(path) == kind


def test_the_requests_are_counted_and_only_counts_leave(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = [
        _line("2026-11-04", "GET", "/render/leden/geheime-naam", 200),
        _line("2026-11-05", "HEAD", "/render/leden/geheime-naam", 200),
        _line("2026-11-05", "GET", "/render/wp-geheim", 404),
        _line("2026-11-05", "GET", "/api/search", 200),
        "2026-11-05 09:22:00,316 [INFO] api.warm: Warm-up done\n",
        "something → else\n",
    ]
    routes, days, unread = usage.count_requests(lines)
    assert routes["pagina", "leden", "alle"] == 2
    assert routes["pagina", "leden", "HEAD"] == 1
    assert routes["pagina", "overig", "4xx"] == 1
    assert days["2026-11-05", "pagina"] == 2
    assert days["2026-11-05", "api"] == 1
    assert unread == 1

    usage.print_requests(routes, days, unread)
    out = capsys.readouterr().out
    assert "periode: 2026-11-04 tot en met 2026-11-05" in out
    assert NETWORK not in out
    assert "geheim" not in out


def test_the_terms_are_split_and_only_counts_leave(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = NotationParser({"SR": "BWBR0001854"}, {"wetboek van strafrecht": ["X"]})
    (tmp_path / "search-2026-11-05.json").write_text(
        json.dumps(
            {
                "ecli:nl:hr:2019:2006": 3,
                "art. 310 sr": 2,
                "wetboek van strafrecht": 4,
                "rechtszaak geheimenaam": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "search-2026-10.json").write_text(
        json.dumps({"ontslag": 7}), encoding="utf-8"
    )
    (tmp_path / ".lock").write_text("", encoding="utf-8")

    periods = usage.count_terms(parser, tmp_path)
    assert [p[0] for p in periods] == ["2026-10", "2026-11-05"]
    day = periods[1][2]
    assert (day["citatie"], day["citatie termen"]) == (5, 2)
    assert day["wetnaam"] == 4
    assert day["vrije tekst"] == 1
    assert periods[0][2]["vrije tekst"] == 7

    usage.print_terms(periods)
    out = capsys.readouterr().out
    assert "geheimenaam" not in out
    assert "ontslag" not in out
    assert "strafrecht" not in out


def test_the_parser_loads_on_a_store_that_only_reads() -> None:
    """The store of the script is enough for ``load_notation_parser``."""

    class Connection:
        def execute(self, statement: str, params: Any = None) -> Any:
            assert params is None
            return self

        def fetchall(self) -> list[dict[str, Any]]:
            return []

    parser = load_notation_parser(usage._ReadOnlyStore(Connection()))
    assert parser.parse("ontslag") is None
