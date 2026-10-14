"""A vote choice and the outcome of a decision are named from ``core/votes.py``, never
spelled out."""

from __future__ import annotations

import re

from tests.conventions._scan import SRC, _python_files

_SPELLED_OUT = re.compile(
    r"""["'](?:aangenomen|verworpen|ingetrokken|aangehouden|vervangen|Voor|Tegen|"""
    r"""Aantekening gevraagd|Stemmen - [a-z ]+)["']"""
)
# Their own vocabularies: a judgment is also ``verworpen`` (``core/judgment_outcome.py``).
_HOMES = {SRC / "core" / "votes.py", SRC / "core" / "judgment_outcome.py"}
# A Literal cannot name a constant: the one outcome a pending amendment can have.
_LITERAL = 'outcome: Literal["aangenomen"] | None = Field('


def test_no_vote_word_spelled_out() -> None:
    found = [
        f"{path.relative_to(SRC)}:{number}: {line.strip()}"
        for path in _python_files()
        if path not in _HOMES
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _SPELLED_OUT.search(line) and "``" not in line and _LITERAL not in line
    ]
    assert found == []
