"""Every closed vocabulary the API answers or reads, as ``/openapi.json`` lists it.

The values are pinned in ``openapi_enums.json``: a word that comes or goes is a change of
the contract (and of the explorer's generated types), so it changes that file too.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from lawgraph.api.app import app

PINNED = pathlib.Path(__file__).with_name("openapi_enums.json")


def enums(spec: dict[str, Any]) -> dict[str, list[Any]]:
    """Each ``enum`` (and each ``const``) of *spec*, by the path to it."""
    found: dict[str, list[Any]] = {}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "enum" in node:
                found[path] = list(node["enum"])
            if "const" in node:
                found[f"{path}#const"] = [node["const"]]
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for n, value in enumerate(node):
                walk(value, f"{path}/{n}")

    walk(spec, "")
    return found


def test_every_vocabulary_of_the_api_is_the_pinned_one() -> None:
    assert enums(app.openapi()) == json.loads(PINNED.read_text())
