"""The source of a reader's address as the front end paints it first, before its app has
come (its ``lib/first-paint``, V4): the fields of the API's answers that paint reads, so it
sets the page as the app sets it and the app takes it over without a line moving.

Of an article (``article_paint``): its text and what the head of its reader shows above the
text, each as the route that the app asks gives it: of ``/api/articles/{law}/{number}`` the
article with its validity, its law, its completeness and its formulas of delegation; of
``/history`` its versions (a light read: without their parts); of ``/explained-by`` its
explanations; of the dossier that made its text, the memorie van toelichting the reader
names when none of those does; the law as the band "Behoort bij" names it; its place in its
law; whether an article stands before and after it. An article whose head the paint cannot
set as the app does (a recodified one, one whose references are still pending) is not
painted first.

Light reads only, within ``PAINT_BUDGET`` (``routes/render.py``): past it the page has no
first paint, as before.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.api.routes.instruments import (
    get_instrument,
    get_instrument_basis_route,
    list_articles,
    list_articles_at,
)
from lawgraph.api.routes.judgments import get_judgment_detail
from lawgraph.api.routes.nodes import get_node_graph
from lawgraph.api.schemas.articles import (
    ArticleExplanationDTO,
    ArticleSummaryDTO,
    listed_versions,
)
from lawgraph.api.schemas.common import InstrumentSummaryDTO
from lawgraph.api.schemas.completeness import COMPLETENESS_ADAPTER, completeness_dto
from lawgraph.api.schemas.dossiers import DossierDocumentDTO
from lawgraph.api.schemas.nodes import NodeGraphResponse
from lawgraph.api.validity import article_validity_dto
from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_ADVISES_ON,
    RELATION_APPEAL_OF,
    RELATION_LEGISLATED_IN,
)
from lawgraph.core.delegations import delegation_clauses
from lawgraph.core.ecli import ecli_of_key
from lawgraph.core.names import text_of
from lawgraph.core.staatsblad_laws import is_law
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import seo
from lawgraph.db.queries.articles import (
    get_article_explanations,
    get_article_versions_light,
)
from lawgraph.db.queries.dossiers import (
    get_dossier_by_number,
    get_dossier_documents,
    load_dossier_names,
)
from lawgraph.db.queries.nodes import NeighborFilter
from lawgraph.db.queries.unlinked_references import (
    law_reference_counts,
    reference_counts,
)

# The seconds the reads of a first paint may take: past them the page goes without it.
PAINT_BUDGET = 0.4

# The parts of a completeness whose line names how many the reader shows (``shown``): while
# one is pending the paint does not know that number, and paints nothing.
_COUNTED = ("references", "definitions")

# The paper of a dossier the reader names as the memorie van toelichting of a text.
_MVT = re.compile(r"memorie van toelichting", re.IGNORECASE)

# The most papers of a dossier the reader looks through for its memorie (``getDossierDocuments``).
_DOSSIER_DOCUMENTS = 100

# Of the article in the API's answer, what the paint reads.
_ARTICLE: dict[str, Any] = {
    "id": True,
    "key": True,
    "bwb_id": True,
    "official_id": True,
    "article_number": True,
    "label": True,
    "heading": True,
    "display_name": True,
    "repealed": True,
    "validity": True,
    "official_url": True,
    "text": True,
    "parts": {"__all__": {"id", "kind", "number", "start", "end"}},
    "tables": True,
    "headings": True,
    "footnote_marks": True,
    "footnotes": True,
}
_INSTRUMENT = {"key", "bwb_id", "celex", "display_name", "signed_on", "official_url"}
_VERSION = {
    "key",
    "valid_from",
    "valid_until",
    "current",
    "change",
    "text_changed",
    "changes",
    "amended_by",
}
_EXPLANATION: dict[str, Any] = {
    "target": True,
    "scope": True,
    "article_version_key": True,
    "section_anchor": True,
    "document": {"key", "title", "kind", "dossier_number"},
}
_LAW_PROPS = ("kind", "citation_title", "title", "bwb_id", "celex", "abbreviation")


def law_id_of(props: dict[str, Any]) -> str:
    """The law an article is part of as the reader names it (``lawIdOf`` of the front
    end): its BWB id, else its CELEX number, else its law of the Staatsblad."""
    official = text_of(props.get("official_id"))
    return (
        text_of(props.get("bwb_id"))
        or text_of(props.get("celex"))
        or (official.upper() if official else "")
    )


def article_paint(store: GraphStore, row: dict[str, Any]) -> dict[str, Any] | None:
    """The article of *row* (``db.queries.seo.article``) as its first paint reads it; None
    for one without text, or whose head the paint does not set as the app does."""
    props = row["props"] or {}
    law_id, number = law_id_of(props), text_of(props.get("article_number"))
    if not text_of(props.get("text")) or not law_id or not number:
        return None
    if seo.transposed(store, row["id"]):
        return None
    article = {"id": row["id"], "key": row["key"], "props": props}
    instrument = seo.article_law_node(store, row["id"])
    law = (instrument or {}).get("props") or {}
    counts = law_reference_counts if is_law(law) else reference_counts
    found = completeness_dto(props, law, counts(store, row["id"]))
    completeness = (
        COMPLETENESS_ADAPTER.dump_python(found, mode="json") if found else None
    )
    if completeness and any(
        (completeness.get(part) or {}).get("state") == "pending" for part in _COUNTED
    ):
        return None
    history = get_article_versions_light(store, article, law_id, number)
    versions = listed_versions(history.versions, history.dossier_titles)
    page = get_article_explanations(store, law_id, number, limit=100, offset=0)
    names = load_dossier_names(store) if page["items"] else {}
    summary = ArticleSummaryDTO.from_document(
        article, article_validity_dto(store, article, instrument, [])
    )
    return {
        "kind": "article",
        "article": {
            **summary.model_dump(mode="json", include=_ARTICLE),
            "law_id": law_id,
        },
        "instrument": (
            InstrumentSummaryDTO.from_document(instrument).model_dump(
                mode="json", include=_INSTRUMENT
            )
            if instrument is not None
            else None
        ),
        "completeness": completeness,
        "versions": [v.model_dump(mode="json", include=_VERSION) for v in versions],
        "explained": [
            ArticleExplanationDTO.from_row(item, names).model_dump(
                mode="json", include=_EXPLANATION
            )
            for item in page["items"]
        ],
        "mvt": _wording_mvt(store, versions),
        # the formulas of delegation in the text: each one control of the reader, whose
        # words break as one
        "delegations": [
            {"start": clause.start, "end": clause.end}
            for clause in delegation_clauses(props.get("text"), props.get("parts"))
        ],
        "law": _law_neighbor(instrument),
        "node": {
            name: props.get(name)
            for name in (
                "article_number",
                "breadcrumb",
                "instrument_citation_title",
                "valid_from",
                "stub",
            )
        },
        "steps": _steps(seo.listed_around(store, props)),
    }


def _wording_mvt(store: GraphStore, versions: list[Any]) -> dict[str, Any] | None:
    """The memorie van toelichting the reader names when no explanation of the article
    does: the first of that kind among the papers of the dossier of the law that made the
    text in force (``ArticleReader``); None without one."""
    if not versions or not (versions[-1].current or versions[-1].valid_until is None):
        return None
    first = next(v for v in reversed(versions) if v.text_changed)
    dossiers = (first.amended_by.dossiers if first.amended_by else None) or []
    if not dossiers or dossiers[0].exists is False or not dossiers[0].number:
        return None
    dossier = get_dossier_by_number(store, dossiers[0].number)
    if dossier is None:
        return None
    documents = get_dossier_documents(
        store, dossier["id"], limit=_DOSSIER_DOCUMENTS, offset=0
    )
    for document in documents.get("items") or []:
        dto = DossierDocumentDTO.from_row(document, None)
        if _MVT.search(dto.kind or ""):
            return dto.model_dump(mode="json", include={"key", "title", "kind"})
    return None


def _steps(around: tuple[bool, bool] | None) -> dict[str, bool]:
    """Whether the reader steps to an article before and after this one (Vorig, Volgend),
    and whether the list of its law holds it (``listed``): only then does the reader know
    its place in its law."""
    before, after = around or (False, False)
    return {"listed": around is not None, "prev": before, "next": after}


def _law_neighbor(instrument: dict[str, Any] | None) -> dict[str, Any] | None:
    """The law of the article as the band "Behoort bij" reads it of the light node."""
    if instrument is None:
        return None
    props = instrument.get("props") or {}
    return {
        "collection": "instruments",
        "key": instrument["key"],
        "display_name": props.get("display_name"),
        "props": {name: props[name] for name in _LAW_PROPS if props.get(name)},
    }


# The characters of a judgment's text the paint sets: its first paragraphs, more than a
# screen of them; the app adds the rest under them.
_JUDGMENT_TEXT = 6000

# What the props of a judgment hold of its text, which its paragraphs give.
_JUDGMENT_BULK = ("paragraphs", "text", "footnotes", "sections")

# The relations the band "Behoort bij" of a judgment names: its procesgang and its conclusie.
_BAND = NeighborFilter(relations=(RELATION_APPEAL_OF, RELATION_ADVISES_ON))
_EARLIER = NeighborFilter(relations=(RELATION_APPEAL_OF,), direction="outbound")

# How many instances before its eerdere aanleg the band names (``eerdereAanleg``).
_CHAIN = 3

# The props of its light node the band reads (``procesgang-chain``).
_BAND_PROPS = ("outcome", "unresolved_appeal_targets", "translation_of")


def judgment_paint(store: GraphStore, row: dict[str, Any]) -> dict[str, Any] | None:
    """The judgment of *row* as its first paint reads it: its answer of
    ``/api/judgments/{ecli}`` with its first paragraphs (those of ``_JUDGMENT_TEXT``
    characters) without their citations, and its light node for the band as
    ``/api/nodes/judgments/{key}?limit=1`` gives it, of its procesgang and conclusie, with
    the instances before its eerdere aanleg. None for one withdrawn, a translation, one with
    connected cases (their sentences come later), one without text, or one whose parties
    were not read (the reader reads them from its whole text)."""
    ecli = ecli_of_key(row["key"])
    if not ecli:
        return None
    detail = get_judgment_detail(ecli, store)
    judgment = detail.judgment
    if (
        judgment.withdrawn
        or judgment.translation_of
        or detail.related_to
        or not judgment.paragraphs
        # its parties read from its whole text, which the paint has not
        or judgment.parties is None
    ):
        return None
    kept, size = [], 0
    for paragraph in judgment.paragraphs:
        if size >= _JUDGMENT_TEXT:
            break
        kept.append(paragraph.model_copy(update={"citations": []}))
        size += len(paragraph.text or "")
    ids = {p.paragraph_id for p in kept}
    notes = [
        note.model_copy(update={"citations": []})
        for note in judgment.footnotes
        if note.paragraph_id in ids
    ]
    # its props without its text, which its paragraphs hold
    light_props = {
        name: value
        for name, value in (judgment.props or {}).items()
        if name not in _JUDGMENT_BULK
    }
    shown = judgment.model_copy(
        update={"paragraphs": kept, "footnotes": notes, "props": light_props}
    )
    return {
        "kind": "judgment",
        "judgment": shown.model_dump(mode="json"),
        "whole": len(kept) == len(judgment.paragraphs),
        # the numbers of all its paragraphs, for the margin they stand in to be as wide as
        # the reader's
        "numbers": sorted({p.number for p in judgment.paragraphs if p.number}),
        "same_as": [s.model_dump(mode="json") for s in detail.same_as],
        "conclusions": [c.model_dump(mode="json") for c in detail.conclusions],
        "completeness": (
            COMPLETENESS_ADAPTER.dump_python(detail.completeness, mode="json")
            if detail.completeness
            else None
        ),
        "light": _band_light(store, row["key"]),
        "chain": _chain(store, row["key"]),
    }


def _band_light(store: GraphStore, key: str) -> dict[str, Any]:
    """The light node of the judgment *key* as its band reads it: the buckets of its
    procesgang and conclusie, and the props it names its outcome by."""
    graph = _graph(store, key, _BAND)
    props = graph.node.props or {}
    return {
        "node": {
            "props": {name: props[name] for name in _BAND_PROPS if props.get(name)}
        },
        **graph.model_dump(mode="json", include={"neighbors": {"buckets"}}),
    }


def _graph(store: GraphStore, key: str, filters: NeighborFilter) -> NodeGraphResponse:
    """The light node of the judgment *key* (``limit=1``) of the edges *filters* lets
    through, as ``/api/nodes`` gives it."""
    return get_node_graph(
        COLLECTION_JUDGMENTS,
        key,
        store,
        filters,
        limit=1,
        offset=0,
        sort="key",
        props="full",
        edge_meta="light",
    )


def _light(store: GraphStore, key: str, filters: NeighborFilter) -> dict[str, Any]:
    """The light node of the judgment *key* (``limit=1``) of the edges *filters* lets
    through: its buckets as ``/api/nodes`` gives them."""
    return _graph(store, key, filters).model_dump(
        mode="json", include={"neighbors": {"buckets"}}
    )


def _chain(store: GraphStore, key: str) -> list[dict[str, Any]]:
    """The instances before the eerdere aanleg of the judgment *key*, the nearest first:
    each the first of its own ``APPEAL_OF`` (outbound), up to ``_CHAIN`` steps past the
    eerdere aanleg, as the band asks them."""
    found: list[dict[str, Any]] = []
    step = _first_earlier(store, key)
    for _ in range(_CHAIN):
        if step is None:
            break
        step = _first_earlier(store, step["key"])
        if step is not None:
            found.append(step)
    return found


def _first_earlier(store: GraphStore, key: str) -> dict[str, Any] | None:
    """The first eerdere aanleg of the judgment *key*, as its light node names it."""
    buckets = _light(store, key, _EARLIER)["neighbors"]["buckets"]
    items = buckets[0]["items"] if buckets else []
    return items[0] if items else None


# The articles of a law the paint sets, with their text: more than a screen of them; the app
# adds the rest of its page under them.
_LAW_ARTICLES = 12

# The preview of an article in the list, as the reader asks it (``PREVIEW_CHARS``).
_LAW_PREVIEW = 600

# The relation the band "Behoort bij" of a law names: the bill that made it.
_LAW_BAND = NeighborFilter(relations=(RELATION_LEGISLATED_IN,), direction="outbound")


def law_paint(store: GraphStore, row: dict[str, Any]) -> dict[str, Any] | None:
    """The law of the BWB of *row* as its first paint reads it: its answer of
    ``/api/instruments/{bwb_id}``, the first articles of its list with their text of today
    (``/articles`` and ``/articles/at/{today}``, as the reader asks its first page), and the
    laws its Gelet op names (``/basis``), and its light node of the bill that made it (its
    band). None for an act of
    the EU or a law of the Staatsblad (the reader asks their texts article by article)."""
    bwb_id = text_of((row.get("props") or {}).get("bwb_id"))
    if not bwb_id:
        return None
    detail = get_instrument(bwb_id, store)
    listed = list_articles(
        bwb_id,
        store,
        text_preview_chars=_LAW_PREVIEW,
        limit=_LAW_ARTICLES,
        offset=0,
        division=None,
    )
    texts = list_articles_at(
        bwb_id,
        dutch_today(),
        store,
        text_preview_chars=0,
        include_text=True,
        limit=_LAW_ARTICLES,
        offset=0,
        division=None,
        include=None,
    )
    # the reader names them under the head of a regulation that is no wet (its kind decides)
    basis = get_instrument_basis_route(bwb_id, store).model_dump(mode="json")["items"]
    today = [
        item.model_dump(
            mode="json",
            include={
                "article_number",
                "text",
                "parts",
                "tables",
                "headings",
                "footnote_marks",
                "footnotes",
            },
        )
        for item in texts.items
    ]
    with_text = {t["article_number"] for t in today if t.get("text")}
    return {
        "kind": "law",
        "bwb_id": bwb_id,
        "instrument": detail.model_dump(mode="json"),
        "total": listed.total,
        # its annexes counted: the contents beside the text list them
        "annexes": len(listed.annexes),
        # an article's preview only where its text of today is not there
        "articles": [
            {
                **item.model_dump(mode="json", exclude={"text_preview"}),
                "text_preview": (
                    None if item.article_number in with_text else item.text_preview
                ),
            }
            for item in listed.items
        ],
        "texts": today,
        "basis": basis,
        "light": get_node_graph(
            COLLECTION_INSTRUMENTS,
            row["key"],
            store,
            _LAW_BAND,
            limit=1,
            offset=0,
            sort="key",
            props="full",
            edge_meta="light",
        ).model_dump(mode="json", include={"neighbors": {"buckets"}}),
    }
