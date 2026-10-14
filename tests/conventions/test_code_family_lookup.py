"""Whether a name is a code with books (``BW``) is asked of ``core.code_families``."""

from __future__ import annotations

import re

from tests.conventions._scan import SRC, _python_files


def test_a_code_family_is_asked_of_code_families() -> None:
    """``CODE_FAMILIES`` is keyed in the spelling the WTI gives; a lookup by an upper-cased
    name misses a family such as ``WvK``. ``is_code_family`` ignores case."""
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in _python_files()
        if path != SRC / "core" / "code_families.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"\bin CODE_FAMILIES(?![.\w])|CODE_FAMILIES\.get\(", line)
    ]
    assert not offenders
