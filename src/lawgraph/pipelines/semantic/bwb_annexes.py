"""``semantic bwb-annexes``: an article that names an annex is scoped by it.

SCOPED_BY from an article to the annex its text refers to, with the detected scope type
(fixed or discretionary). An article refers to an annex in two ways:

* by its label: "vermeld in bijlage I", "de bijlage";
* by its name, in the same regulation: "de bij deze wet behorende Bevoegdheidsregeling
  bestuursrechtspraak" names bijlage 2 of the Awb, whose title is that name followed by the
  articles it belongs to in parentheses (``annex_name``). The articles of that annex itself
  are left out.

The annex nodes themselves, and their PART_OF edge to the regulation, are made by
``normalize bwb`` from the toestand it parses; a reference by label to an annex that is not
there gets a stub, so the graph stays connected.
"""

from __future__ import annotations

from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    RELATION_SCOPED_BY,
    SOURCE_BWB,
)
from lawgraph.core.annex_xml import ANNEX_EDGE_SOURCE, annex_node_key
from lawgraph.core.batching import chunked
from lawgraph.core.bwb_xml import annex_article_number
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic._annex_detect import (
    AnnexReferenceHit,
    annex_name,
    detect_annex_name,
    detect_annex_references,
)
from lawgraph.pipelines.semantic.base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = ANNEX_EDGE_SOURCE

_NAMES_PER_QUERY = 200


class BWBAnnexesSemanticPipeline(SemanticPipelineBase):
    """Link the articles that name an annex to it (SCOPED_BY)."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None)
        self._link_labels(edges, result, self._annex_keys())
        self._link_names(edges)
        edges.flush_into(result)
        return result

    def _annex_keys(self) -> set[str]:
        """The annexes ``normalize bwb`` made of the toestanden (and earlier stubs)."""
        return set(semantic_bwb.annex_keys(self.store))

    def _link_labels(
        self, edges: EdgeWriter, result: PipelineResult, known_keys: set[str]
    ) -> None:
        """The articles that name an annex by its label ("bijlage 2")."""
        articles = self._load_articles_mentioning_annex()
        for doc in self._track(articles, "articles"):
            article = Node.from_document(COLLECTION_ARTICLES, doc)
            text = article.props.get("text") or ""
            bwb_id = str(article.props.get("bwb_id") or "")
            if not text or not bwb_id:
                result.skipped += 1
                continue
            for hit in detect_annex_references(text):
                annex = self._ensure_annex(bwb_id, hit.label, known_keys)
                if annex is not None:
                    self._add_edge(
                        edges, article, annex, hit, 0.9 if hit.label else 0.7
                    )

    def _link_names(self, edges: EdgeWriter) -> None:
        """The articles of a regulation that name one of its annexes by its title."""
        names: list[dict[str, Any]] = []
        # annex key -> how the numbers of its own articles start ("bijlage 2 artikel ")
        own_prefix: dict[str, str | None] = {}
        for row in semantic_bwb.titled_annexes(self.store):
            name = annex_name(row.get("title"))
            if name is None:
                continue
            names.append({"key": row["key"], "bwb_id": row["bwb_id"], "name": name})
            label = row.get("label")
            own_prefix[row["key"]] = annex_article_number(label, "") if label else None
        by_key = {n["key"]: n["name"] for n in names}
        for chunk in chunked(names, _NAMES_PER_QUERY):
            for row in semantic_bwb.articles_naming_annexes(self.store, chunk):
                article = Node.from_document(COLLECTION_ARTICLES, row["article"])
                number = str(article.props.get("article_number") or "")
                prefix = own_prefix[row["annex"]]
                if prefix and number.startswith(prefix):
                    continue  # an article of the annex itself
                hit = detect_annex_name(
                    article.props.get("text") or "", by_key[row["annex"]]
                )
                if hit is not None:
                    self._add_edge(edges, article, self._annex(row["annex"]), hit, 0.9)

    def _add_edge(
        self,
        edges: EdgeWriter,
        article: Node,
        annex: Node,
        hit: AnnexReferenceHit,
        confidence: float,
    ) -> None:
        edge = self._make_edge_doc(
            from_node=article,
            to_node=annex,
            relation=RELATION_SCOPED_BY,
            source=SEMANTIC_SOURCE,
            confidence=confidence,
            meta={
                "start": hit.start,
                "end": hit.end,
                "text": hit.text,
                "scope_type": hit.scope_type,
            },
        )
        if edge:
            edges.add_doc(edge)

    def _load_articles_mentioning_annex(self) -> Iterable[dict[str, Any]]:
        return semantic_bwb.articles_mentioning_annex(self.store)

    @staticmethod
    def _annex(key: str) -> Node:
        return Node(
            collection=COLLECTION_ANNEXES,
            type=NodeType.ANNEX,
            key=key,
            props={},
            _skip_validation=True,
        )

    def _ensure_annex(
        self, bwb_id: str, label: str | None, known_keys: set[str]
    ) -> Node | None:
        """Return the annex node for (bwb_id, label), creating a stub if needed."""
        key = annex_node_key(bwb_id, label)
        if key in known_keys:
            return self._annex(key)
        node = self.store.ensure_stub_node(
            COLLECTION_ANNEXES,
            key,
            NodeType.ANNEX,
            {
                "bwb_id": bwb_id,
                "label": label,
                "display_name": f"Annex {label}".strip() if label else "Annex",
                "source": SOURCE_BWB,
            },
        )
        if node is not None:
            known_keys.add(key)
        return node
