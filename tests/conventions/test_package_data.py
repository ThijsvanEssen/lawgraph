"""The package data (``src/lawgraph/data``) is found through
``config.constants.DATA_DIR``, and a curated list is read through ``core.curated.LISTS``.
"""

from __future__ import annotations

import re

from tests.paths import SRC
from tests.source_scan import python_files


def test_package_data_is_found_through_data_dir() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in python_files()
        if path != SRC / "config" / "constants.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r'/\s*"data"', line)
    ]
    assert not offenders, f"build the path from DATA_DIR: {offenders}"


def test_curated_files_are_read_through_their_list() -> None:
    """A curated file has one reader: its ``CuratedList`` in ``core.curated.LISTS``."""
    curated = SRC / "data" / "curated"
    names = [p.name for p in curated.glob("*.json")]
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in python_files()
        if path != SRC / "core" / "curated.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if '"curated"' in line and any(f'"{name}"' in line for name in names)
    ]
    assert names
    assert not offenders
