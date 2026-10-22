"""The ``citation_*`` meta of a page: what Zotero and Google Scholar read from the HTML
of a judgment, a law, an article and a paper."""

from __future__ import annotations

import re

from lawgraph.api.seo import shell
from lawgraph.api.seo.pages.base import Page
from lawgraph.api.seo.pages.judgments import judgment_page

ROW = {
    "id": "judgments/ecli_nl_hr_2019_2006",
    "light": {
        "ecli": "ECLI:NL:HR:2019:2006",
        "date": "2019-12-20",
        "court": "Hoge Raad",
        "title": "Urgenda",
    },
    "summary": "Klimaatzaak.",
}


def _meta(html: str) -> dict[str, str]:
    return dict(re.findall(r'<meta name="([^"]+)" content="([^"]*)" data-seo />', html))


def test_a_judgment_has_the_meta_of_a_reference() -> None:
    page = judgment_page(ROW)
    assert page.citation["DC.identifier"] == "ECLI:NL:HR:2019:2006"
    assert page.citation["citation_date"] == "2019/12/20"
    assert page.citation["citation_publisher"] == "Hoge Raad"
    meta = _meta(shell._head(page, "https://concordans.nl"))
    assert meta["citation_title"] == page.title
    assert meta["citation_public_url"] == "https://concordans.nl" + page.path


def test_a_page_without_citation_has_none() -> None:
    head = shell._head(Page(title="Start", description="x", path="/"), "https://x.nl")
    assert "citation_" not in head


def test_a_value_is_escaped() -> None:
    page = Page(
        title="t",
        description="d",
        path="/p",
        citation={"citation_title": 'Wet "x" & <y>'},
    )
    assert 'content="Wet &quot;x&quot; &amp; &lt;y&gt;"' in shell._head(
        page, "https://x.nl"
    )
