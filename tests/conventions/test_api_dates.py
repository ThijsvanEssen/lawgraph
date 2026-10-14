"""A route reads a day as ``dt.date`` and hands it to a query with ``api.params.iso_day``,
so no route writes the ISO day of a parameter itself."""

from __future__ import annotations

import re

from tests.conventions._scan import SRC

ROUTES = SRC / "api" / "routes"
# a day parameter (``date_from``, ``since``, ``due_before``, …) written out by hand
_OWN_ISO_DAY = re.compile(
    r"\b\w*(?:from|to|since|until|before|date)\.isoformat\(\) if \w+ else None"
)


def test_a_route_writes_a_day_with_iso_day() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{n}"
        for path in sorted(ROUTES.glob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if _OWN_ISO_DAY.search(line) or re.match(r"def _day\(", line)
    ]
    assert not offenders, f"use api.params.iso_day: {offenders}"
