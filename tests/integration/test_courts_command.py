"""``retrieve rechtspraak-instanties`` stores the value list, and ``lawgraph courts`` builds
the court table from what it stored: the same table as the one in the repository."""

from __future__ import annotations

import json
from pathlib import Path

from lawgraph.commands import courts
from lawgraph.core.courts import DATA
from lawgraph.db import ArangoStore
from lawgraph.pipelines.retrieve.rechtspraak_instanties import (
    RechtspraakInstantiesRetrievePipeline,
)

LIST = (
    Path(__file__).resolve().parents[1] / "fixtures" / "rechtspraak_instanties.xml"
).read_text()


class _Client:
    def instanties(self) -> tuple[str, str]:
        return "https://data.rechtspraak.nl/Waardelijst/Instanties", LIST


def test_the_stored_list_builds_the_table_of_the_repository(
    database: str, tmp_path: Path
) -> None:
    store = ArangoStore()
    result = RechtspraakInstantiesRetrievePipeline(store, client=_Client()).run()  # type: ignore[arg-type]
    assert not result.errors, result.errors

    assert not courts.main(["check"]).errors

    out = tmp_path / "courts.json"
    assert not courts.main(["build", "--output", str(out)]).errors
    built = json.loads(out.read_text(encoding="utf-8"))
    assert built["courts"] == json.loads(DATA.read_text(encoding="utf-8"))["courts"]
    assert built["sources"]["rechtspraak"]["url"].endswith("/Waardelijst/Instanties")


def test_a_court_the_list_changed_fails_the_check(database: str) -> None:
    changed = LIST.replace(
        "<Naam>Hoge Raad</Naam>", "<Naam>Hoge Raad der Nederlanden</Naam>"
    )

    class Changed(_Client):
        def instanties(self) -> tuple[str, str]:
            return "u", changed

    RechtspraakInstantiesRetrievePipeline(ArangoStore(), client=Changed()).run()  # type: ignore[arg-type]
    assert courts.main(["check"]).errors
