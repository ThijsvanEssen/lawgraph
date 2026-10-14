"""A module logs through ``get_logger(__name__)`` (``core/logging.py``), the one way."""

from __future__ import annotations

from tests.paths import SRC
from tests.source_scan import python_files


def test_a_module_gets_its_logger_through_get_logger() -> None:
    home = SRC / "core" / "logging.py"
    offenders = [
        str(path.relative_to(SRC))
        for path in python_files()
        if path != home and "logging.getLogger(__name__)" in path.read_text()
    ]
    assert offenders == []
