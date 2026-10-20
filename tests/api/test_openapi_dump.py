"""``docs/openapi.json`` is the schema the API serves, as ``lawgraph openapi`` writes it
without a server: the front end generates its types from it. Only ``info.version`` may lag
(a release changes it, not the contract)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.paths import ROOT

DUMP = ROOT / "docs" / "openapi.json"


def _contract(spec: dict[str, Any]) -> dict[str, Any]:
    """*spec* without its version."""
    info = {key: value for key, value in spec["info"].items() if key != "version"}
    return spec | {"info": info}


def _differences(served: dict[str, Any], dumped: dict[str, Any]) -> list[str]:
    """The paths and schemas, and the other parts, that differ."""
    found = []
    for part in ("paths", "components"):
        inner = "schemas" if part == "components" else None
        left = served.get(part, {}).get(inner, {}) if inner else served.get(part, {})
        right = dumped.get(part, {}).get(inner, {}) if inner else dumped.get(part, {})
        found += [
            f"{part}: {name}"
            for name in sorted(set(left) | set(right))
            if left.get(name) != right.get(name)
        ]
    found += [
        key
        for key in sorted(set(served) | set(dumped))
        if key not in ("paths", "components") and served.get(key) != dumped.get(key)
    ]
    return found


def test_the_dumped_schema_is_the_one_the_api_serves(tmp_path: Path) -> None:
    """The command as one runs it: in a directory without ``.env`` and with no
    ``LAWGRAPH_`` variable set, so the schema states the defaults the API runs with. The
    code is that of this checkout (``src``), not a ``lawgraph`` installed elsewhere, which a
    relative ``PYTHONPATH`` would find from that directory."""
    env = {key: value for key, value in os.environ.items() if "LAWGRAPH_" not in key}
    env["PYTHONPATH"] = str(ROOT / "src")
    written = subprocess.run(
        [sys.executable, "-m", "lawgraph", "openapi"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    served = _contract(json.loads(written.stdout))
    dumped = _contract(json.loads(DUMP.read_text("utf-8")))
    assert _differences(served, dumped) == [], (
        "docs/openapi.json is out of date: lawgraph openapi > docs/openapi.json"
    )
