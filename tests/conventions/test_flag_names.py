"""One name per option across the commands: ``--limit`` for at most N, ``--output`` for
where a command writes."""

from __future__ import annotations

import re

from tests.paths import SRC

_OTHER_NAMES = re.compile(r"""["'](--max-records|--out)["']""")


def test_no_command_has_another_name_for_limit_or_output() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{n}"
        for path in sorted(SRC.rglob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if _OTHER_NAMES.search(line)
    ]
    assert not offenders, f"use --limit or --output: {offenders}"
