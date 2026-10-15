"""``docs/pipelines.md`` shows the wordings of ``tk-amendment-articles`` as the code has them."""

from __future__ import annotations

from lawgraph.pipelines.semantic import tk_amendment_articles
from tests.paths import ROOT


def test_the_docs_show_the_wordings() -> None:
    docs = (ROOT / "docs" / "pipelines.md").read_text()
    assert (
        tk_amendment_articles.block_of(docs) == tk_amendment_articles.render_table()
    ), (
        "docs/pipelines.md is out of date: "
        "python -m lawgraph.pipelines.semantic.tk_amendment_articles"
    )
