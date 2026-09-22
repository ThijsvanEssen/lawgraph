"""The relation vocabulary: one place that says what every edge type means.

Rules (enforced by ``tests/test_relation_catalogue.py``):

* names are English ``UPPER_SNAKE`` verbs that read as ``SOURCE VERB TARGET``;
* the target type never appears in the name (``REFERS_TO``, not
  ``REFERS_TO_ARTICLE``) — the node the edge points at says what it is;
* an edge type states which collections it may connect, so a writer that
  produces an edge in the wrong direction is caught by a test.

``RELATIONS`` is the whole vocabulary; ``config.constants`` has one
``RELATION_*`` constant per entry.

The tables in ``docs/data-model.md`` between the ``relations:begin`` and
``relations:end`` markers are generated from this module::

    python -m lawgraph.core.relations
"""

from __future__ import annotations

from dataclasses import dataclass

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)

# Concept (English name used in docs and the API) -> collection that stores it.
CONCEPTS: dict[str, str] = {
    "Instrument": COLLECTION_INSTRUMENTS,
    "InstrumentVersion": COLLECTION_INSTRUMENT_VERSIONS,
    "Article": COLLECTION_ARTICLES,
    "ArticleVersion": COLLECTION_ARTICLE_VERSIONS,
    "Annex": COLLECTION_ANNEXES,
    "Judgment": COLLECTION_JUDGMENTS,
    "Dossier": COLLECTION_DOSSIERS,
    "Case": COLLECTION_CASES,
    "Document": COLLECTION_DOCUMENTS,
    "Activity": COLLECTION_ACTIVITIES,
    "Decision": COLLECTION_DECISIONS,
    "Commitment": COLLECTION_COMMITMENTS,
    "Member": COLLECTION_MEMBERS,
    "Faction": COLLECTION_FACTIONS,
    "Committee": COLLECTION_COMMITTEES,
}
_CONCEPT_OF = {collection: concept for concept, collection in CONCEPTS.items()}


@dataclass(frozen=True)
class RelationSpec:
    name: str
    sources: tuple[str, ...]  # collections an edge may start in
    targets: tuple[str, ...]  # collections an edge may end in
    description: str


_I = COLLECTION_INSTRUMENTS
_IV = COLLECTION_INSTRUMENT_VERSIONS
_A = COLLECTION_ARTICLES
_AV = COLLECTION_ARTICLE_VERSIONS
_ANNEX = COLLECTION_ANNEXES
_J = COLLECTION_JUDGMENTS
_DOSSIER = COLLECTION_DOSSIERS
_CASE = COLLECTION_CASES
_DOC = COLLECTION_DOCUMENTS
_ACT = COLLECTION_ACTIVITIES
_DEC = COLLECTION_DECISIONS
_COMMIT = COLLECTION_COMMITMENTS
_MEMBER = COLLECTION_MEMBERS
_FACTION = COLLECTION_FACTIONS
_COMMITTEE = COLLECTION_COMMITTEES

RELATIONS: tuple[RelationSpec, ...] = (
    # ── structure ────────────────────────────────────────────────────────────
    RelationSpec(
        "PART_OF",
        (_A, _ANNEX, _DOC, _CASE),
        (_I, _CASE, _DOSSIER),
        "Containment. Article/Annex → Instrument; Document → Case or Dossier; "
        "Case → Dossier.",
    ),
    RelationSpec(
        "VERSION_OF",
        (_IV, _AV),
        (_I, _A),
        "A dated version of an instrument or article. An article keeps one "
        "identity across versions (BWB `stam-id`); each version has valid_from / "
        "valid_until.",
    ),
    # ── legislation ──────────────────────────────────────────────────────────
    RelationSpec(
        "AMENDS",
        (_I, _DOC),
        (_I, _A),
        "An instrument changes existing text (effective date and version in `meta`). "
        "A bill (Document) proposing the change carries status `voorgesteld`.",
    ),
    RelationSpec(
        "INTRODUCES",
        (_I, _DOC),
        (_I, _A),
        "An instrument adds a new article or instrument; a bill proposing it is `voorgesteld`.",
    ),
    RelationSpec(
        "REPEALS",
        (_I, _DOC),
        (_I, _A),
        "An instrument withdraws an article or instrument; a bill proposing it is `voorgesteld`.",
    ),
    RelationSpec(
        "BASED_ON",
        (_I,),
        (_A,),
        "The legal basis (delegation basis) an instrument is issued under: "
        "'Gelet op artikel …' in the preamble.",
    ),
    RelationSpec(
        "IMPLEMENTS",
        (_I,),
        (_I,),
        "A national instrument transposes an EU directive.",
    ),
    RelationSpec(
        "LEGISLATED_IN",
        (_I,),
        (_DOSSIER,),
        "The parliamentary dossier in which an instrument was legislated "
        "(BWB `dossierref`).",
    ),
    # ── references and explanation ───────────────────────────────────────────
    RelationSpec(
        "REFERS_TO",
        (_A, _DOC, _J),
        (_A, _I, _J),
        "A text refers to an article, instrument or judgment. The source node says "
        "who refers; article → article edges also carry a `semantic_type`.",
    ),
    RelationSpec(
        "EXPLAINS",
        (_DOC,),
        (_AV, _A, _I),
        "A document (MvT, NvT) explains the article version or instrument it "
        "introduced or changed; an MvT edge carries `meta.section_anchor` when one "
        "of its sections is about that article.",
    ),
    RelationSpec(
        "APPEAL_OF",
        (_J,),
        (_J,),
        "An appeal or cassation judgment → the judgment it appeals.",
    ),
    RelationSpec(
        "SCOPED_BY",
        (_A,),
        (_ANNEX,),
        "An article whose scope is defined by an annex.",
    ),
    # ── parliament ───────────────────────────────────────────────────────────
    RelationSpec(
        "ABOUT",
        (_ACT, _DEC, _COMMIT),
        (_CASE, _DOSSIER),
        "The subject of an activity, decision or commitment: Activity/Decision → "
        "Case; Commitment → Dossier.",
    ),
    RelationSpec(
        "LED_BY",
        (_ACT,),
        (_COMMITTEE,),
        "The lead committee (`voortouwcommissie`) of an activity; absent for plenary.",
    ),
    RelationSpec(
        "MADE_IN",
        (_COMMIT,),
        (_ACT,),
        "The activity in which a commitment (toezegging) was made.",
    ),
    RelationSpec(
        "MEMBER_OF",
        (_MEMBER,),
        (_COMMITTEE, _FACTION),
        "Membership of a committee or faction, with from/to dates and role.",
    ),
    RelationSpec(
        "AUTHORED",
        (_MEMBER,),
        (_DOC, _CASE),
        "A person signed or submitted a document or case; `role` says how "
        "(first signatory, co-signatory, minister, …).",
    ),
    RelationSpec(
        "VOTED",
        (_MEMBER, _FACTION),
        (_DEC,),
        "A vote on a decision: per member for roll-call votes, per faction "
        "otherwise (`choice`, `seats`).",
    ),
)

RELATION_NAMES: frozenset[str] = frozenset(r.name for r in RELATIONS)
BY_NAME: dict[str, RelationSpec] = {r.name: r for r in RELATIONS}


def concept(collection: str) -> str:
    """Concept name for a collection (``procedures`` → ``Case``)."""
    return _CONCEPT_OF.get(collection, collection)


BLOCK_BEGIN = "<!-- relations:begin (generated: python -m lawgraph.core.relations) -->"
BLOCK_END = "<!-- relations:end -->"


def render_tables() -> str:
    """Markdown tables of the node types and the relations (no headings)."""
    lines = [
        "| Node type | Collection |",
        "|-----------|-----------|",
    ]
    lines += [f"| {c} | `{col}` |" for c, col in CONCEPTS.items()]
    lines += [
        "",
        "| Relation | From | To | Meaning |",
        "|----------|------|----|---------|",
    ]
    for r in RELATIONS:
        src = " / ".join(concept(c) for c in r.sources)
        tgt = " / ".join(concept(c) for c in r.targets)
        lines.append(f"| `{r.name}` | {src} | {tgt} | {r.description} |")
    return "\n".join(lines) + "\n"


def replace_block(document: str) -> str:
    """Return *document* with the generated block between the markers refreshed."""
    head, _, rest = document.partition(BLOCK_BEGIN)
    _, _, tail = rest.partition(BLOCK_END)
    return f"{head}{BLOCK_BEGIN}\n\n{render_tables()}\n{BLOCK_END}{tail}"


def block_of(document: str) -> str:
    """The generated block currently in *document* (markers excluded)."""
    _, _, rest = document.partition(BLOCK_BEGIN)
    body, _, _ = rest.partition(BLOCK_END)
    return body.strip() + "\n"


if __name__ == "__main__":
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "docs" / "data-model.md"
    path.write_text(replace_block(path.read_text()))
