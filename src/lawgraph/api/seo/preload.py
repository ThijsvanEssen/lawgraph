"""The API answers the app of a page asks first, named in its HTML as
``<link rel="preload" as="fetch" crossorigin>``: the browser asks them beside the JavaScript
of the app instead of after it (on 4G the app asks its first call 2 to 5 s after the HTML).

The browser uses a preload only for a request of the same URL, character for character
(path, the parameters in their order, ``encodeURIComponent``), and the same mode: the app
fetches same-origin without credentials, so ``crossorigin`` (anonymous); without it the
browser asks twice. Each URL here is the one the explorer asks (``lawgraph-explorer``):

- an article (``bron/leesbaar.ts``, ``askArticleAhead``): ``getArticleDetail``,
  ``getArticleHistory``, ``lawArticleList``, ``getExplainedBy``, by its law and its number as
  the API has it (``apiNumber``: 162 for BW 6:162), then its light node (``getNodeFirst``);
- a law (``bron/first-node.ts``): ``getInstrumentDetail``, its light node and
  ``lawArticleList``;
- a judgment: ``getJudgmentDetail`` by the ECLI of its key (``keyEcli``) and its light node;
- a Kamerstuk (``focusUitPagina``): ``getDocument`` and its light node;
- the start page (``routes/(main)/+page.svelte``): its summary of Actueel, and with ``?q=``
  the three lanes of the search (``search/lanes.ts``, ``session.svelte.ts``: the fast one
  from two characters, the other two from three);
- Actueel without a filter (``routes/(main)/actueel``): the chamber's schedule, the open
  motions of censure (``open-motions.ts``), the first page of the feed and its counts, the
  cabinets and the factions.

The sizes come from ``data/first-pages.json`` where the explorer reads them from its copy.
``tests/data/preloads.json`` holds the requests the explorer made on these pages; a URL here
it did not make fails ``tests/test_seo_preload.py``.
"""

from __future__ import annotations

import datetime as dt
import inspect

from lawgraph.api.params import LONG_LIST_MAX
from lawgraph.api.routes.feed import get_feed_summary_route
from lawgraph.core.code_families import native_number
from lawgraph.core.ecli import ecli_of_key
from lawgraph.core.models import parse_node_id
from lawgraph.core.motion_kinds import MOTION_KINDS
from lawgraph.core.readable_paths import Pad, uri_component
from lawgraph.core.time import dutch_today
from lawgraph.db.queries.warm_nodes import FIRST_PAGES

# The kinds of each lane of the search, in its order (``LANES`` of ``search/lanes.ts``), and
# from how many characters of the query it is asked.
SEARCH_LANES: tuple[tuple[tuple[str, ...], int, str], ...] = (
    (
        (
            "instruments",
            "dossiers",
            "cabinets",
            "ministries",
            "members",
            "commitments",
            "factions",
            "committees",
            "decisions",
        ),
        2,
        "live",
    ),
    (("articles", "documents"), 3, "full"),
    (("judgments",), 3, "full"),
)
# The hits a lane asks (``LIMIT`` of ``session.svelte.ts``).
SEARCH_LIMIT = 6
# The summary as the start page asks it: the route's own margin and few
_SUMMARY_DEFAULTS = inspect.signature(get_feed_summary_route).parameters
CLOSE_VOTE = _SUMMARY_DEFAULTS["margin"].default
FEW_VOTES = _SUMMARY_DEFAULTS["few"].default
# How far back Actueel looks for an open motion of censure, and how many it asks.
MOTION_DAYS = 60
MOTION_LIMIT = 20


def _query(*params: tuple[str, object]) -> str:
    """The query as the explorer's client writes it: in this order, each value as
    ``encodeURIComponent``, a list as the parameter repeated."""
    parts = [
        f"{name}={uri_component(str(value))}"
        for name, given in params
        for value in (given if isinstance(given, tuple) else (given,))
    ]
    return "?" + "&".join(parts)


def _node(node_id: str) -> str:
    collection, key = parse_node_id(node_id)
    return f"/api/nodes/{collection}/{uri_component(key.lower())}{_query(('limit', 1))}"


def _law_articles(law: str) -> str:
    return f"/api/instruments/{uri_component(law)}/articles" + _query(
        ("text_preview_chars", 1), ("limit", LONG_LIST_MAX)
    )


def article_address(pad: Pad) -> tuple[str, str]:
    """The law and number by which the app asks the article at *pad*
    (``askArticleAhead``): the law in upper case, the number as the API has it (``162``
    for BW 6:162)."""
    law = pad.a.upper()
    return law, native_number(law, pad.b)


def source_preloads(pad: Pad, node_id: str) -> list[str]:
    """What the app asks first of the source *node_id* at the address *pad*."""
    _, key = parse_node_id(node_id)
    if pad.soort == "artikel":
        law, number = article_address(pad)
        article = f"/api/articles/{uri_component(law)}/{uri_component(number)}"
        return [
            article,
            f"{article}/history",
            _law_articles(law),
            f"{article}/explained-by{_query(('limit', 50))}",
            _node(node_id),
        ]
    if pad.soort == "wet":
        return [
            f"/api/instruments/{uri_component(pad.a)}",
            _node(node_id),
            _law_articles(pad.a),
        ]
    if pad.soort == "uitspraak":
        ecli = ecli_of_key(key)
        detail = [f"/api/judgments/{uri_component(ecli)}"] if ecli else []
        return [*detail, _node(node_id)]
    if pad.soort == "kamerstuk":
        return [f"/api/documents/{uri_component(key)}", _node(node_id)]
    return []


def app_preloads(path: str, query: list[tuple[str, str]]) -> list[str]:
    """What the app asks first on its page *path* under *query* (the parameters of the
    request): the start page, with or without a search, and Actueel without a filter."""
    today = dutch_today()
    if path == "/":
        return _home(today) + _search(query)
    if path == "/actueel" and not query:
        return _actueel(today)
    return []


def _home(today: dt.date) -> list[str]:
    summary = FIRST_PAGES["home_summary"]
    return [
        "/api/feed/summary"
        + _query(
            ("until", today.isoformat()),
            ("days", summary["days"]),
            ("margin", CLOSE_VOTE),
            ("few", FEW_VOTES),
            ("limit", summary["limit"]),
        )
    ]


def _search(query: list[tuple[str, str]]) -> list[str]:
    """The lanes of the search the start page asks of ``?q=`` alone (trimmed, as the field
    has it); none under another parameter, whose scope the app reads."""
    if [name for name, _ in query] != ["q"]:
        return []
    term = query[0][1].strip()
    asked = []
    for n, (kinds, min_chars, mode) in enumerate(SEARCH_LANES):
        if len(term) < min_chars:
            continue
        # the first lane also says what the query cites
        resolve = (("resolve", "true"),) if n == 0 else ()
        asked.append(
            "/api/search"
            + _query(
                ("q", term),
                ("types", kinds),
                ("limit", SEARCH_LIMIT),
                *resolve,
                ("mode", mode),
            )
        )
    return asked


def _actueel(today: dt.date) -> list[str]:
    summary = FIRST_PAGES["actueel_summary"]
    since = today - dt.timedelta(days=MOTION_DAYS)
    return [
        "/api/feed/summary"
        + _query(("days", summary["days"]), ("limit", summary["limit"])),
        "/api/documents"
        + _query(
            ("motion_kind", ",".join(MOTION_KINDS)),
            ("from", since.isoformat()),
            ("facets", "false"),
            ("limit", MOTION_LIMIT),
        ),
        "/api/feed"
        + _query(("limit", FIRST_PAGES["lists"]["feed"]), ("facets", "false")),
        "/api/feed" + _query(("limit", 1), ("facets", "true")),
        "/api/cabinets",
        "/api/factions",
    ]
