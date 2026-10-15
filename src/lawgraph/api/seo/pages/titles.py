"""The title and the description of each kind of source from its props, as its page has
them: the title from ``core.names``, which the API gives too."""

from __future__ import annotations

from typing import Any

from lawgraph.api.seo.pages.base import DESCRIPTION_MAX, cut
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.models import parse_node_id
from lawgraph.core.names import text_of, title_of

# What describes a node of a collection besides its title: the prop, else its title.
_DESCRIBED_BY = {
    "articles": "text",
    "annexes": "description",
    "judgments": "summary",
    "dossiers": "title",
    "commitments": "text",
}


def title_and_description(
    node_id: str,
    props: dict[str, Any],
    law: dict[str, Any] | None = None,
    note: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """The title (``core.names.title_of``) and the description of a node from its own props
    alone, as its page has them: what the SPA shows when it opens a node in the app. *law*:
    of an article or an annex, its law as its page reads it (``seo.law_of``); *note*: of a
    publication, its nota van toelichting (``seo.note_of``)."""
    title = title_of(node_id, props, law, note)
    collection = parse_node_id(node_id)[0]
    if collection == "instruments":
        since = long_date(props.get("date_in_force"))
        return title, cut(
            f"{title}, geldend sinds {since}" if since else title, DESCRIPTION_MAX
        )
    described = text_of(props.get(_DESCRIBED_BY.get(collection, "")))
    return title, cut(described or title, DESCRIPTION_MAX)
