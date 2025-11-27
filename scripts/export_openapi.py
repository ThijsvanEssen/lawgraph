from __future__ import annotations

import json
from pathlib import Path

from lawgraph.api.app import app


def export_openapi(path: Path | str = "openapi.json") -> None:
    """Schrijf de OpenAPI-definitie naar schijf voor documentatie of clients."""
    destination = Path(path)
    payload = app.openapi()
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    export_openapi()
