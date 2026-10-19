"""GET /render/{path} — the HTML of a page of Concordans, for every path that is no file
and no ``/api`` (Caddy rewrites it here):

- a readable address of a source (``/wetten/BWBR0005289/artikel/6:162``): the shell of the
  front end with the title, description, canonical address, structured data and content
  of the source (``api/seo``), so a crawler reads it without JavaScript, and its node in
  ``<meta name="focus">`` (``<collection>/<key>``), so the app opens it without a lookup;
- the same address in another spelling (``/uitspraken/ecli:nl:…``), or
  ``/explore?focus=<collection>/<key>``: a 301 to the readable address;
- a page of the app (``spa-routes.json`` of the front end): the shell with its title; the
  start page (``/``) with its content too (``pages/home``), read of nothing;
- anything else, and an address of a source the graph does not have: 404, the shell with
  "Niet gevonden" and ``noindex``;
- a law of the Staatsblad, or an article of it, that the BWB holds now: a 301 to the law
  in the BWB, or to its article of the same number;
- a judgment the Rechtspraak withdrew: 410 with its page (court, date, when it was
  withdrawn, what refers to it) and ``noindex``. Gone, not "not found": the source took
  it away for good, and a search engine drops a page that is gone at once, one that is
  not found only after asking again.

Light reads only, within ``RENDER_BUDGET``; a page whose reads take longer is the shell
with its title alone. Cacheable: an ETag of the API, the shell and the data version.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import unquote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import is_node_id
from lawgraph.api.seo import shell
from lawgraph.api.seo.pages.base import DESCRIPTION_MAX, Page, cut
from lawgraph.api.seo.pages.home import home_page
from lawgraph.api.seo.pages.judgments import withdrawn_page
from lawgraph.api.seo.pages.titles import title_and_description
from lawgraph.api.seo.sources import SOURCE_PAGES
from lawgraph.core.models import parse_node_id
from lawgraph.core.readable_paths import STB_LAW, Pad, pad_href, parse_path, path_of
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import lookup, seo
from lawgraph.db.request_context import read_budget

router = APIRouter()

# The seconds the reads of one page may take: past them the page is the shell with its
# title (Caddy gives up on the API after 2 s and serves the static shell).
RENDER_BUDGET = 1.0
# A page and a "not found" name the chunks of the current front end, gone after its next
# deploy: a cache asks again every time (a 304 on the ETag). A redirect names none.
CACHE_PAGE = "no-cache"
CACHE_REDIRECT = "public, max-age=86400"

NOT_FOUND = Page(
    title="Niet gevonden",
    description="Deze pagina of bron staat niet in Concordans.",
    path="",
    index=False,
)


def _query(request: Request, drop: str = "") -> str:
    """The query of the request (the state of a view: ``?lezen=1``), without *drop*."""
    rest = [(k, v) for k, v in request.query_params.multi_items() if k != drop]
    return f"?{urlencode(rest, safe='/,:')}" if rest else ""


def _redirect(location: str) -> Response:
    return RedirectResponse(
        location, status_code=301, headers={"Cache-Control": CACHE_REDIRECT}
    )


def _html(
    request: Request, page: Page, status: int, cache: str, stamp: str | None
) -> Response:
    """*page* in the shell, or 304 when the client has it."""
    etag = (
        f'W/"render-{request.app.version}-{shell.stamp()}-{stamp}"' if stamp else None
    )
    headers = {"Cache-Control": cache}
    if etag:
        headers["ETag"] = etag
        if etag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers=headers)
    return HTMLResponse(shell.render(page), status_code=status, headers=headers)


def _app_page(path: str) -> Page | None:
    """The page of the app at *path*, with its own title: none when the front end lists
    its pages (``spa-routes.json``) without it. Without that list every path is one, as
    before (the SPA says what it is not)."""
    if not shell.shell().routes:
        return Page(title="", description="", path="")
    route = shell.route_of(path)
    if route is None:
        return None
    if path == "/":
        return home_page(
            str(route.get("title") or "Concordans"),
            str(route.get("description") or ""),
            shell.indexed(route),
        )
    return Page(
        title=str(route.get("title") or "Concordans"),
        description=str(route.get("description") or ""),
        path=path,
        whole_title=True,
        index=shell.indexed(route),
    )


def _source_page(store: GraphStore, pad: Pad, node_id: str) -> Page:
    """The page of a source: its content where its kind has one (``SOURCE_PAGES``), else
    its name as the API gives it; with its node (``focus``)."""
    source = SOURCE_PAGES.get(pad.soort)
    row = source.read(store, node_id) if source is not None else None
    if source is not None and row is not None:
        page = source.build(row)
        page.image = source.image
        page.focus = node_id
        return page
    props: dict[str, Any] = (lookup.answer(store, node_id) or {}).get("props") or {}
    name = str(props.get("display_name") or "")
    return Page(
        title=name,
        description=cut(name, DESCRIPTION_MAX),
        path=pad_href(pad),
        index=bool(name) and not props.get("stub"),
        focus=node_id,
    )


def _props_of(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """What the readable address of the node *node_id* is built from (``lookup.answer``);
    None for a node that is not there or no node at all."""
    if not is_node_id(node_id) or not store.has_node(*parse_node_id(node_id)):
        return None
    return (lookup.answer(store, node_id) or {}).get("props") or {}


def _in_the_bwb(store: GraphStore, pad: Pad) -> str | None:
    """Of the address of a law of the Staatsblad, or of an article of it, that the graph no
    longer has: the same law in the BWB, which holds it now (``normalize staatsblad-laws``
    lets it go then), and the article of the same number in it, or the law when it has
    none of that number."""
    if pad.soort not in ("wet", "artikel") or not STB_LAW.match(pad.a):
        return None
    bwb_id = seo.law_enacted_by(store, pad.a)
    if bwb_id is None:
        return None
    if pad.soort == "artikel" and lookup.find_article(store, bwb_id, pad.b):
        return pad_href(Pad("artikel", bwb_id, pad.b))
    return pad_href(Pad("wet", bwb_id))


def _same_person_path(store: GraphStore, member_id: str) -> str | None:
    """The readable address of the member a bare member is the same person as."""
    other = seo.same_person(store, member_id)
    props = _props_of(store, other) if other else None
    return path_of(other, props) if other and props is not None else None


# HEAD as GET (Caddy, crawlers and uptime checks ask it): the server leaves out the body.
@router.api_route(
    "/render/{path:path}", methods=["GET", "HEAD"], include_in_schema=False
)
def render_page(
    path: str,
    request: Request,
    store: Annotated[GraphStore, Depends(get_store)],
) -> Response:
    pathname = "/" + path
    if pathname == "/explore" and (focus := request.query_params.get("focus")):
        props = _props_of(store, focus)
        readable = path_of(focus, props) if props is not None else None
        if readable:
            return _redirect(readable + _query(request, drop="focus"))
    pad = parse_path(pathname)
    if pad is None:
        page = _app_page(pathname.rstrip("/") or "/")
        if page is None:
            return _html(request, NOT_FOUND, 404, CACHE_PAGE, None)
        return _html(request, page, 200, CACHE_PAGE, "app")
    canonical = pad_href(pad)
    if unquote(canonical) != unquote(pathname):
        return _redirect(canonical + _query(request))
    node_id: str | None = None
    with read_budget(
        RENDER_BUDGET, f"The render of {pathname} (its title alone)"
    ) as budget:
        node_id = seo.node_of(store, pad)
        if node_id is None:
            moved = _in_the_bwb(store, pad)
            if moved:
                return _redirect(moved + _query(request))
            return _html(request, NOT_FOUND, 404, CACHE_PAGE, None)
        withdrawn = (
            seo.withdrawn_judgment(store, node_id) if pad.soort == "uitspraak" else None
        )
        if withdrawn is not None:
            return _html(request, withdrawn_page(withdrawn), 410, CACHE_PAGE, None)
        if pad.soort == "lid" and (same := _same_person_path(store, node_id)):
            return _redirect(same + _query(request))
        source = _source_page(store, pad, node_id)
        stamp = version_cache.current_version(store)
    if budget.ran_out:
        return _html(
            request, _title_page(store, node_id, canonical), 200, "no-store", None
        )
    return _html(request, source, 200, CACHE_PAGE, stamp)


# How long a page whose reads ran past ``RENDER_BUDGET`` may read the props of its node for
# its title (seconds).
TITLE_BUDGET = 0.5


def _title_page(store: GraphStore, node_id: str | None, path: str) -> Page:
    """A page whose reads took too long: its title and description from the props of its
    node alone (``title_and_description``, as ``/api/nodes`` gives them) and its node,
    without its content; the shell alone when even that is not read in time. A crawler sees
    the title of the page, never "Concordans", and the next request may have it whole."""
    if node_id is None:
        return Page("", "", path)
    collection, key = parse_node_id(node_id)
    doc = None
    with read_budget(TITLE_BUDGET, f"The title of {path}") as budget:
        doc = store.get_document(collection, key)
    if budget.ran_out:
        return Page("", "", path, focus=node_id)
    if not isinstance(doc, dict):
        return Page("", "", path)
    title, description = title_and_description(node_id, doc.get("props") or {})
    return Page(title, description, path, focus=node_id)
