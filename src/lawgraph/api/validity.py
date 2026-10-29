"""The ``validity`` of an instrument and of an article as the routes give it: its state today
(``core.validity``), the day the data of its source stands on, the laws that take its
place."""

from __future__ import annotations

from collections import Counter
from typing import Any

from lawgraph.api.schemas.validity import SuccessorLawDTO, ValidityDTO
from lawgraph.core.time import dutch_today
from lawgraph.core.validity import ValidityState, article_validity, instrument_validity
from lawgraph.db import GraphStore
from lawgraph.db.queries.validity import article_end, source_as_of, successor_laws


def instrument_validity_dto(
    store: GraphStore, doc: dict[str, Any]
) -> ValidityDTO | None:
    """The ``validity`` of the instrument *doc* (a whole node)."""
    props = doc.get("props") or {}
    validity = instrument_validity(props, dutch_today().isoformat())
    if validity is None:
        return None
    successors = [SuccessorLawDTO.from_row(r) for r in successor_laws(store, doc["id"])]
    return ValidityDTO.build(
        validity, source_as_of(store, props.get("source")), successors
    )


def article_validity_dto(
    store: GraphStore,
    article: dict[str, Any],
    law: dict[str, Any] | None,
    successors: list[dict[str, Any]],
) -> ValidityDTO | None:
    """The ``validity`` of the article *article* of the law *law* (whole nodes), whose own
    ``successors`` are *successors* (``{edge, target, instrument}`` rows)."""
    return ended_article_validity_dto(
        store, article, law, successors, article_end(store, article["id"])
    )


def ended_article_validity_dto(
    store: GraphStore,
    article: dict[str, Any],
    law: dict[str, Any] | None,
    successors: list[dict[str, Any]],
    ended: str | None,
) -> ValidityDTO | None:
    """``article_validity_dto`` of an article whose newest version ends on *ended* (its
    ``valid_until``, ``db.queries.validity.article_end``), read with it."""
    today = dutch_today().isoformat()
    props = article.get("props") or {}
    law_props = (law or {}).get("props") or {}
    validity = article_validity(
        instrument_validity(law_props, today) if law else None,
        ended,
        bool(props.get("repealed")),
        today,
    )
    if validity is None:
        return None
    return ValidityDTO.build(
        validity,
        source_as_of(store, law_props.get("source")),
        _successor_laws(store, validity.state, law, successors),
    )


def _successor_laws(
    store: GraphStore,
    state: ValidityState,
    law: dict[str, Any] | None,
    successors: list[dict[str, Any]],
) -> list[SuccessorLawDTO]:
    """The laws of the article's own *successors*, the one most of them stand in first;
    else, of an expired article, those of its *law*."""
    laws = {
        row["instrument"]["id"]: row["instrument"]
        for row in successors
        if row.get("instrument")
    }
    if laws:
        counted = Counter(
            row["instrument"]["id"] for row in successors if row.get("instrument")
        )
        return [
            SuccessorLawDTO.from_row({**laws[law_id], "articles": count})
            for law_id, count in sorted(
                counted.items(), key=lambda item: (-item[1], laws[item[0]]["key"])
            )
        ]
    if state is ValidityState.EXPIRED and law is not None:
        return [SuccessorLawDTO.from_row(r) for r in successor_laws(store, law["id"])]
    return []
