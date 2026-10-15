"""The website of the Eerste Kamer is addressed through ``core.official_urls.ek_url`` and
``ek_path``; the EK modules name the chamber with ``CHAMBER_EK``.
"""

from __future__ import annotations

import re

from tests.paths import SRC
from tests.source_scan import python_files


def test_the_eerste_kamer_site_is_addressed_in_one_place() -> None:
    homes = {SRC / "config" / "sources.py", SRC / "core" / "official_urls.py"}
    offenders = [
        str(path.relative_to(SRC))
        for path in python_files()
        if path not in homes
        and re.search(r"\bEERSTEKAMER_SITE\.base_url\b", path.read_text())
    ]
    assert not offenders, f"use ek_url / ek_path: {offenders}"


def test_the_ek_modules_name_their_chamber_by_constant() -> None:
    modules = [
        *(SRC / "pipelines" / "normalize").glob("eerstekamer*.py"),
        SRC / "pipelines" / "semantic" / "eerstekamer.py",
    ]
    offenders = [
        f"{path.relative_to(SRC)}: {literal}"
        for path in modules
        for literal in ('"EK"', '"EersteKamer"')
        if literal in path.read_text()
    ]
    assert modules
    assert not offenders, "use CHAMBER_EK / LABEL_EERSTE_KAMER"


def test_an_eerstekamer_pipeline_reads_its_page_with_an_ek_module() -> None:
    core = SRC / "core"
    assert not list(core.glob("eerstekamer*.py")), (
        "a core module of the EK is ek_<part>"
    )
    read = []
    for path in sorted((SRC / "pipelines" / "normalize").glob("eerstekamer_*.py")):
        part = path.stem.removeprefix("eerstekamer_")
        if (core / f"ek_{part}.py").exists():
            pattern = rf"lawgraph\.core(\.ek_{part}\b| import [^\n]*\bek_{part}\b)"
            assert re.search(pattern, path.read_text()), path.name
            read.append(part)
    assert len(read) >= 7, read
