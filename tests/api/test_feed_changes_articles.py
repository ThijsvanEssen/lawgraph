"""The feed says per dossier whether it changes an article, so a front end asks
``changed-articles`` only of those that do."""

from __future__ import annotations

import pytest

from lawgraph.api.routes import feed
from lawgraph.api.schemas.feed import FeedDossierCountDTO, FeedDossierDTO


def test_each_dossier_is_marked_by_one_read(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[list[str]] = []

    def changing(store, ids):
        asked.append(sorted(ids))
        return {"dossiers/36586"}

    monkeypatch.setattr(feed, "dossiers_changing_articles", changing)
    yes = FeedDossierDTO(key="36586", number="36586")
    no = FeedDossierCountDTO(kind="Motie", number="31765", key="31765", count=2)
    unknown = FeedDossierCountDTO(kind="Motie", number="1", count=1)

    feed.mark_changes(None, [yes, no, unknown])  # type: ignore[arg-type]

    assert (yes.changes_articles, no.changes_articles) == (True, False)
    assert unknown.changes_articles is None  # no key: not looked up
    assert asked == [["dossiers/31765", "dossiers/36586"]]
