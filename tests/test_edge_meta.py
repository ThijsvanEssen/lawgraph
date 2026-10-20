"""The models of ``meta`` per relation (``RelationSpec.meta`` in ``core/relations.py``):
documented, holding what writers write outside ``make_edge_doc``, and the check the
recorder of the test run (``tests/edge_meta_recorder.py``) holds every edge made to."""

from __future__ import annotations

import re
from typing import get_args

from pydantic import BaseModel

from lawgraph.config.constants import (
    RELATION_ABOUT,
    RELATION_EXPLAINS,
    RELATION_REFERS_TO,
    RELATION_VOTED,
)
from lawgraph.core.relations import BY_NAME, RELATIONS
from tests.edge_meta_recorder import meta_problems
from tests.paths import SRC


def _models(model: type[BaseModel]) -> list[type[BaseModel]]:
    """*model* and the models of its fields, of a list or not, all the way down."""
    found = [model]
    for field in model.model_fields.values():
        for inner in (field.annotation, *get_args(field.annotation)):
            for each in (inner, *get_args(inner)):
                if isinstance(each, type) and issubclass(each, BaseModel):
                    found += _models(each)
    return found


def test_every_key_of_a_model_says_what_it_holds() -> None:
    models = {m for r in RELATIONS if r.meta is not None for m in _models(r.meta)}
    bare = sorted(
        f"{model.__name__}.{name}"
        for model in models
        for name, field in model.model_fields.items()
        if not field.description
    )
    assert len(models) > len([r for r in RELATIONS if r.meta is not None])
    assert not bare, bare


def test_the_classification_writes_keys_of_refers_to() -> None:
    # the one writer of meta outside make_edge_doc: an UPDATE of the REFERS_TO of the BWB
    sql = (SRC / "db" / "queries" / "semantic" / "bwb.py").read_text()
    update = sql[sql.index("_CLASSIFICATIONS_SQL") :]
    keys = set(re.findall(r"'(\w+)', u\.value", update.split("'meta', lg_update")[1]))
    model = BY_NAME[RELATION_REFERS_TO].meta
    assert isinstance(model, type) and issubclass(model, BaseModel)
    assert keys and keys <= set(model.model_fields)


def test_a_key_the_model_lacks_and_a_value_of_another_type_are_found() -> None:
    assert meta_problems(RELATION_VOTED, {"choice": "Voor", "seats": "15"}) == [
        "seats: int_type"
    ]
    assert meta_problems(RELATION_VOTED, {"choice": "Voor", "colour": "red"}) == [
        "unknown key colour"
    ]
    assert meta_problems(RELATION_ABOUT, {"basis": "subject"}) == ["unknown key basis"]
    assert meta_problems(
        RELATION_REFERS_TO, {"mentions": [{"paragraph_id": "p1", "page": 3}]}
    ) == [
        "mentions[].confidence: missing",
        "mentions[].end: missing",
        "mentions[].raw_match: missing",
        "mentions[].snippet: missing",
        "mentions[].start: missing",
        "unknown key mentions[].page",
    ]


def test_the_meta_of_two_writers_of_one_edge_fits() -> None:
    mention = {
        "paragraph_id": "p1",
        "start": 0,
        "end": 9,
        "raw_match": "C-123/20",
        "snippet": "zie C-123/20",
        "confidence": 0.9,
    }
    # judgment-citation-linker and eurlex-cjeu on one citation between judgments
    merged = {
        "cited_ecli": "ECLI:EU:C:2021:1",
        "paragraphs": ["3.1"],
        "mentions": [mention],
        "mention_count": 1,
    }
    assert meta_problems(RELATION_REFERS_TO, merged) == []
    section = {
        "section_anchor": "s1",
        "heading": "Artikel I, onderdeel A",
        "char_start": 10,
        "char_end": 90,
        "match_type": "heading_target",
        "changed": True,
        "confidence": 0.95,
        "explanation": "De kop noemt het artikel.",
    }
    best = {k: v for k, v in section.items() if k != "confidence"}
    assert meta_problems(RELATION_EXPLAINS, {**best, "sections": [section]}) == []
