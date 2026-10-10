"""GET /render/{path} — the HTML of a page of Concordans, for every path that is no file
and no ``/api`` (Caddy rewrites it here):

- a readable address of a source (``/wetten/BWBR0005289/artikel/6:162``): the shell of the
  front end with the title, description, canonical address, structured data and content
  of the source (``api/seo``), so a crawler reads it without JavaScript;
- the same address in another spelling (``/uitspraken/ecli:nl:…``), or
  ``/explore?focus=<collection>/<key>``: a 301 to the readable address;
- a page of the app (``spa-routes.json`` of the front end): the shell with its title;
- anything else, and an address of a source the graph does not have: 404, the shell with
  "Niet gevonden" and ``noindex``.

Light reads only, within ``RENDER_BUDGET``; a page whose reads take longer is the shell
with its title alone. Cacheable: an ETag of the API, the shell and the data version.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import unquote, urlencode

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from lawgraph.api.dependencies import get_store
from lawgraph.api.seo import shell
from lawgraph.api.seo.pages import PAGES, Page, cut
from lawgraph.core.logging import get_logger
from lawgraph.core.readable_paths import Pad, pad_href, parse_path, path_of
from lawgraph.db import GraphStore
from lawgraph.db.queries import lookup, seo
from lawgraph.db.schema import NODE_COLLECTIONS
from lawgraph.db.store import (
    ReadTimedOut,
    RequestCancelled,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)

logger = get_logger(__name__)
router = APIRouter()

# The seconds the reads of one page may take: past them the page is the shell with its
# title (Caddy gives up on the API after 2 s and serves the static shell).
RENDER_BUDGET = 1.0
# A page and a "not found" name the chunks of the current front end, gone after its next
# deploy: a cache asks again every time (a 304 on the ETag). A redirect names none.
CACHE_PAGE = "no-cache"
CACHE_REDIRECT = "public, max-age=86400"

# The image of a page when it is shared, per kind (``static/og`` of the front end).
IMAGES = {
    "wet": "/og/wet.png",
    "artikel": "/og/artikel.png",
    "uitspraak": "/og/uitspraak.png",
    "kamerstuk": "/og/kamerstuk.png",
    "dossier": "/og/dossier.png",
}
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
    return Page(
        title=str(route.get("title") or "Concordans"),
        description=str(route.get("description") or ""),
        path=path,
        whole_title=True,
        index=shell.indexed(route),
    )


def _source_page(store: GraphStore, pad: Pad, node_id: str) -> Page:
    """The page of a source: its content where its kind has one (``PAGES``), else its
    name as the API gives it."""
    build = PAGES.get(pad.soort)
    if build is not None:
        row = seo.READS[pad.soort](store, node_id)
        if row is not None:
            page = build(row)
            page.image = IMAGES.get(pad.soort, page.image)
            return page
    props: dict[str, Any] = lookup.answer(store, node_id).get("props") or {}
    name = str(props.get("display_name") or "")
    return Page(
        title=name,
        description=cut(name, 155),
        path=pad_href(pad),
        index=bool(name) and not props.get("stub"),
    )


def _props_of(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """What the readable address of the node *node_id* is built from (``lookup.answer``);
    None for a node that is not there or no node at all."""
    collection, _, key = node_id.partition("/")
    if collection not in NODE_COLLECTIONS or not key:
        return None
    if not store.has_node(collection, key):
        return None
    return lookup.answer(store, node_id).get("props") or {}


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
    left = read_time_left()
    token = set_read_deadline(
        RENDER_BUDGET if left is None else min(RENDER_BUDGET, left)
    )
    try:
        node_id = seo.node_of(store, pad)
        if node_id is None:
            return _html(request, NOT_FOUND, 404, CACHE_PAGE, None)
        page = _source_page(store, pad, node_id)
        stamp = store.data_version()
    except RequestCancelled:
        raise
    except ReadTimedOut:
        logger.warning(
            "Render of %s past %.1f s: the shell alone.", pathname, RENDER_BUDGET
        )
        return _html(request, Page("", "", canonical), 200, "no-store", None)
    except psycopg.OperationalError:
        # the database is gone: Caddy serves the static shell on a 503
        return Response(status_code=503, headers={"Retry-After": "30"})
    finally:
        reset_read_deadline(token)
    return _html(request, page, 200, CACHE_PAGE, stamp)
