"""Identifiers are in American English, as the URLs (``/neighborhood``): ``neighbor``,
``normalize``."""

from __future__ import annotations

import io
import tokenize

from tests.paths import SRC

_BRITISH = ("neighbour", "normalise")


def test_no_identifier_is_spelled_the_british_way() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{token.start[0]} {token.string}"
        for path in sorted(SRC.rglob("*.py"))
        for token in tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
        if token.type == tokenize.NAME
        and any(word in token.string.lower() for word in _BRITISH)
    ]
    assert not offenders, offenders
