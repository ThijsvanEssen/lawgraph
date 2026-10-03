"""The requests of the parity harness: every route of the API, with values from the data.

The catalogue is made once, from the API that records the goldens, and saved with them, so
the other API is asked exactly the same. It reads the routes and their parameters from
``openapi.json``, harvests values (keys, ECLIs, BWB ids, dossier numbers, facet values) from
the list routes, and asks per route:

* the route with each sampled path value and its defaults;
* each query parameter on its own, with each enum value, both booleans, a few numbers and
  dates, and values from the facets or the pools;
* paging edges (first, second, last and past-the-end page);
* a not-found path value;
* a search corpus of about 200 questions and a resolve corpus;
* the feed from its first page to the end of its cursor chain (added while recording).

It is deterministic: the same data gives the same catalogue.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests

PER_POOL = 20  # values per path parameter
VARIANT_SAMPLES = 3  # path values on which each query variant is asked
DATES = ["2000-01-01", "2021-03-17", "2026-01-01", "2026-09-15"]
MISSING = "parity-does-not-exist"
_NODE_ID = re.compile(r"^[a-z_]+/[^/\s]+$")


@dataclass(frozen=True)
class Request:
    path: str
    query: tuple[tuple[str, str], ...] = ()
    tag: str = ""

    @property
    def url(self) -> str:
        return f"{self.path}?{urlencode(self.query)}" if self.query else self.path

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "query": [list(p) for p in self.query],
            "tag": self.tag,
        }

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> Request:
        return cls(row["path"], tuple(tuple(p) for p in row["query"]), row["tag"])


@dataclass
class Route:
    path: str
    path_params: list[str]
    query_params: dict[str, dict[str, Any]]  # name -> resolved schema


@dataclass
class Pools:
    """Values harvested from the API, per pool name, in the order first seen."""

    values: dict[str, dict[str, None]] = field(default_factory=dict)

    def add(self, pool: str, value: Any) -> None:
        if isinstance(value, str | int) and not isinstance(value, bool) and value != "":
            self.values.setdefault(pool, {})[str(value)] = None

    def sample(self, pool: str, n: int = PER_POOL) -> list[str]:
        """*n* values spread over the pool: the same pool gives the same sample."""
        found = sorted(self.values.get(pool, {}))
        if len(found) <= n:
            return found
        return sorted(random.Random(pool).sample(found, n))


# ── routes ───────────────────────────────────────────────────────────────────


def routes(openapi: dict[str, Any]) -> list[Route]:
    schemas = openapi.get("components", {}).get("schemas", {})
    found = []
    for path, methods in sorted(openapi["paths"].items()):
        op = methods.get("get")
        if op is None or not path.startswith("/api/"):
            continue
        params = op.get("parameters", [])
        found.append(
            Route(
                path,
                [p["name"] for p in params if p["in"] == "path"],
                {
                    p["name"]: _resolve(p.get("schema", {}), schemas)
                    for p in params
                    if p["in"] == "query"
                },
            )
        )
    return found


def _resolve(schema: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """The schema with ``$ref`` and ``anyOf [x, null]`` taken away."""
    if "$ref" in schema:
        return _resolve(schemas[schema["$ref"].rsplit("/", 1)[-1]], schemas)
    options = [s for s in schema.get("anyOf", []) if s.get("type") != "null"]
    if options:
        return {**_resolve(options[0], schemas), "default": schema.get("default")}
    if schema.get("type") == "array" and "items" in schema:
        return {**schema, "items": _resolve(schema["items"], schemas)}
    return schema


# ── harvesting ───────────────────────────────────────────────────────────────

# Lists to harvest from: route -> query. Large pages, so the pools have enough to sample.
HARVEST = {
    "/api/instruments": {},
    "/api/judgments": {},
    "/api/dossiers": {"status": "all"},
    "/api/committees": {},
    "/api/members": {"include_all": "true"},
    "/api/factions": {},
    "/api/factions?chamber=EK": {},
    "/api/cabinets": {},
    "/api/commitments": {},
    "/api/documents": {},
    "/api/decisions": {},
    "/api/ministries": {},
    "/api/relationships/search": {},
    "/api/relationships/types": {},
    "/api/feed": {},
}
HARVEST_ITEMS = 1000  # items read per list route, a page of its largest limit at a time
# Fields whose values go into a pool of the same name, wherever they occur.
FIELDS = {
    "bwb_id",
    "celex",
    "ecli",
    "slug",
    "court",
    "subjects",
    "abbreviation",
    "citation_title",
    "short_title",
    "full_name",
}
# Key of a list item -> pool, per list route.
ITEM_KEYS = {
    "/api/members": "member",
    "/api/factions": "faction",
    "/api/cabinets": "cabinet",
    "/api/commitments": "commitment",
    "/api/documents": "document",
    "/api/decisions": "decision",
    "/api/ministries": "ministry",
}


def harvest(get: Callable[[str], Any], found: list[Route]) -> Pools:
    pools = Pools()
    limits = {r.path: r.query_params.get("limit", {}) for r in found}
    for url, query in HARVEST.items():
        path = url.split("?")[0]
        for body in _pages(get, url, query, limits.get(path, {})):
            _harvest_list(url, body, pools)
    # Neighbours: the nodes no list route names (annexes, activities, cases).
    for key in pools.sample("key:instruments", 10) + pools.sample("dossier", 10):
        collection = (
            "dossiers" if key in pools.values.get("dossier", {}) else "instruments"
        )
        _walk(get(f"/api/nodes/{collection}/{key}?limit=100"), pools)
        if collection == "instruments":
            _walk(get(f"/api/nodes/instruments/{key}?node_types=annexes"), pools)
    for bwb_id in pools.sample("bwb_id", 8):
        for item in _items(get(f"/api/instruments/{bwb_id}/articles")):
            number = item.get("article_number") or item.get("number")
            if number:
                pools.add("article", f"{bwb_id}|{number}")
            _walk(item, pools)
    _harvest_passages(get, pools)
    return pools


def _harvest_passages(get: Callable[[str], Any], pools: Pools) -> None:
    """The papers that explain an article, as ``document|bwb_id|article``."""
    for article in pools.sample("article", 60):
        bwb_id, number = article.split("|", 1)
        url = f"/api/articles/{bwb_id}/{requests.utils.quote(number, safe='')}/explained-by"
        for item in _items(get(url)):
            document = item.get("document") or {}
            if document.get("key"):
                pools.add("passage", f"{document['key']}|{bwb_id}|{number}")


def _pages(
    get: Callable[[str], Any], url: str, query: dict[str, str], limit: dict[str, Any]
) -> Iterator[Any]:
    if not limit:
        yield get(f"{url}?{urlencode(query)}" if query else url)
        return
    size = int(limit.get("maximum") or limit.get("default") or 50)
    for offset in range(0, HARVEST_ITEMS, size):
        body = get(f"{url}?{urlencode({**query, 'limit': size, 'offset': offset})}")
        yield body
        if len(_items(body)) < size:
            return


def _harvest_list(url: str, body: Any, pools: Pools) -> None:
    _walk(body, pools)
    path = url.split("?")[0]
    for item in _items(body):
        if path in ITEM_KEYS and isinstance(item, dict):
            pools.add(ITEM_KEYS[path], item.get("key"))
        if url == "/api/factions?chamber=EK":
            pools.add("ek_faction", item.get("key"))
        if path == "/api/dossiers":
            pools.add("dossier", item.get("number"))
    if path == "/api/relationships/types" and isinstance(body, dict):
        for value in body.get("semantic_types", []):
            pools.add("semantic_type", value)


def _items(body: Any) -> list[Any]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "relationships", "articles"):
            if isinstance(body.get(key), list):
                return list(body[key])
    return []


def _walk(value: Any, pools: Pools) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "id" and isinstance(inner, str) and _NODE_ID.match(inner):
                collection, node_key = inner.split("/", 1)
                pools.add("node", inner)
                pools.add(f"key:{collection}", node_key)
            elif key in FIELDS:
                for one in inner if isinstance(inner, list) else [inner]:
                    pools.add(_pool_of(key, value), one)
            _walk(inner, pools)
    elif isinstance(value, list):
        for inner in value:
            _walk(inner, pools)


def _pool_of(field: str, owner: dict[str, Any]) -> str:
    """The pool of a value of *field* in *owner*: a member's ``slug`` (``rob-jetten``) is
    no committee's, whose slugs ``/api/committees/{slug}`` takes; nor is the slug of a
    concept of the registers of the instruments (``familierecht``, a facet item with a
    TOOI id and a count)."""
    owner_id = owner.get("id")
    if field != "slug" or not isinstance(owner_id, str):
        return field
    if owner_id.startswith("members/"):
        return "member_slug"
    if "/" not in owner_id and "count" in owner:
        return "register_slug"
    return field


# ── requests ─────────────────────────────────────────────────────────────────

# Path parameter -> pool, per route prefix where a name means different things.
PATH_POOLS = {
    ("/api/members/", "key"): "member",
    ("/api/factions/", "key"): "faction",
    ("/api/cabinets/", "key"): "cabinet",
    ("/api/commitments/", "key"): "commitment",
    ("/api/documents/", "key"): "document",
    ("/api/decisions/", "key"): "decision",
    ("/api/annexes/", "key"): "key:annexes",
    ("/api/dossiers/", "number"): "dossier",
    ("/api/committees/", "slug"): "slug",
    ("/api/judgments/", "ecli"): "ecli",
    ("/api/instruments/", "bwb_id"): "bwb_id",
    ("/api/instruments/", "identifier"): "identifier",
}
# Query parameter -> pool, when the facets of the route do not name its values.
QUERY_POOLS = {
    "court": "court",
    "subject": "subjects",
    "party": "abbreviation",
    "member": "member",
    "cabinet": "cabinet",
    "dossier": "dossier",
    "committee": "slug",
    "slug": "member_slug",  # ``/api/members?slug=``
    "legal_area": "register_slug",  # ``/api/instruments?legal_area=``
    "policy_domain": "register_slug",
    "ministry": "ministry",
    "type": "semantic_type",
    "exclude_type": "semantic_type",
    "law": "bwb_id",
    "faction": "faction",
}
DATE_PARAMS = {
    "from",
    "to",
    "since",
    "until",
    "opened_from",
    "opened_to",
    "due_before",
    "date",
}
NUMBERS = {
    "limit": ["1", "3"],
    "offset": ["1", "7"],
    "depth": ["1", "2", "4"],
    "cap": ["5", "50"],
}


def path_values(route: Route, pools: Pools) -> list[dict[str, str]]:
    """The path values to ask *route* with: sampled from the pools."""
    names = route.path_params
    if not names:
        return [{}]
    if names == ["bwb_id", "article_number"]:
        return [
            dict(zip(names, a.split("|", 1), strict=True))
            for a in pools.sample("article")
        ]
    if names == ["collection", "key"]:
        return [dict(zip(names, n.split("/", 1), strict=True)) for n in _nodes(pools)]
    if route.path == "/api/factions/{key}/votes":
        return [{"key": k} for k in pools.sample("ek_faction")]
    if route.path == "/api/documents/{key}/passages":
        return [{"key": p.split("|", 1)[0]} for p in pools.sample("passage")]
    if names == ["bwb_id", "at_date"]:
        return [
            {"bwb_id": b, "at_date": d}
            for b in pools.sample("bwb_id", 5)
            for d in DATES
        ]
    pool = next(
        (
            p
            for (prefix, name), p in PATH_POOLS.items()
            if route.path.startswith(prefix) and name == names[0]
        ),
        names[0],
    )
    if pool == "identifier":
        values = (
            pools.sample("bwb_id")
            + pools.sample("celex", 5)
            + pools.sample("key:instruments", 5)
        )
    else:
        values = pools.sample(pool)
    return [{names[0]: v} for v in dict.fromkeys(values)]


def _nodes(pools: Pools) -> list[str]:
    """A few nodes of every collection."""
    by_collection: dict[str, list[str]] = {}
    for node in sorted(pools.values.get("node", {})):
        by_collection.setdefault(node.split("/", 1)[0], []).append(node)
    chosen = []
    for collection, nodes in sorted(by_collection.items()):
        chosen += sorted(random.Random(collection).sample(nodes, min(4, len(nodes))))
    return chosen


def query_variants(
    route: Route, pools: Pools, facets: dict[str, list[str]]
) -> Iterator[tuple[tuple[str, str], ...]]:
    """Each query parameter on its own, with the values worth asking."""
    for name, schema in route.query_params.items():
        for value in _values(name, schema, pools, facets):
            yield ((name, value),)


def _values(
    name: str, schema: dict[str, Any], pools: Pools, facets: dict[str, list[str]]
) -> list[str]:
    kind = schema.get("type")
    if "enum" in schema:
        return [str(v) for v in schema["enum"]][:12]
    if kind == "array":
        return [str(v) for v in schema.get("items", {}).get("enum", [])]
    if kind == "boolean":
        return ["true", "false"]
    if kind == "integer":
        return NUMBERS.get(name, ["1", "3"])
    if name in DATE_PARAMS:
        return DATES
    if facets.get(
        name
    ):  # a facet without ``value``s (a tree by id and slug) names none
        return facets[name][:6]
    if name in QUERY_POOLS:
        return pools.sample(QUERY_POOLS[name], 4)
    return []


def facet_values(body: Any) -> dict[str, list[str]]:
    facets = body.get("facets") if isinstance(body, dict) else None
    if not isinstance(facets, dict):
        return {}
    return {
        name: [str(f["value"]) for f in rows if isinstance(f, dict) and f.get("value")]
        for name, rows in facets.items()
        if isinstance(rows, list)
    }


def paging(route: Route, total: int | None) -> Iterator[tuple[tuple[str, str], ...]]:
    if "offset" not in route.query_params or not total:
        return
    for limit, offset in [(5, 0), (5, 5), (5, max(total - 1, 0)), (5, total + 10)]:
        yield (("limit", str(limit)), ("offset", str(offset)))


def _required(
    route: Route, values: dict[str, str], pools: Pools
) -> tuple[tuple[str, str], ...]:
    """The query parameters a route cannot do without: the article of a paper's passages."""
    if route.path != "/api/documents/{key}/passages":
        return ()
    for passage in pools.sample("passage"):
        key, bwb_id, number = passage.split("|", 2)
        if key == values["key"]:
            return (("bwb_id", bwb_id), ("article", number))
    return ()


def fill(path: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        path = path.replace(f"{{{name}}}", requests.utils.quote(value, safe=""))
    return path


def build(openapi: dict[str, Any], get: Callable[[str], Any]) -> list[Request]:
    found_routes = routes(openapi)
    pools = harvest(get, found_routes)
    found: list[Request] = []
    for route in found_routes:
        if route.path in ("/api/search", "/api/resolve"):
            continue
        found += _route_requests(route, pools, get)
    found += search_requests(pools)
    return list(dict.fromkeys(found))


def _route_requests(
    route: Route, pools: Pools, get: Callable[[str], Any]
) -> list[Request]:
    found = []
    samples = path_values(route, pools)
    for n, values in enumerate(samples):
        path = fill(route.path, values)
        found.append(Request(path, _required(route, values, pools), "base"))
        if n >= VARIANT_SAMPLES:
            continue
        body = get(path)
        facets = facet_values(body)
        total = body.get("total") if isinstance(body, dict) else None
        found += [
            Request(path, q, "param") for q in query_variants(route, pools, facets)
        ]
        found += [Request(path, q, "paging") for q in paging(route, total)]
    if route.path_params:
        missing = dict.fromkeys(route.path_params, MISSING)
        found.append(Request(fill(route.path, missing), tag="missing"))
    return found


# ── search and resolve ───────────────────────────────────────────────────────

FIXED_QUESTIONS = [
    "wet",
    "Awb",
    "art. 6:162 BW",
    "artikel 3:4 Awb",
    "6:162",
    "onrechtmatige daad",
    "Grondwet",
    "grondwet artikel 1",
    "Wetboek van Strafrecht",
    "strafvordering",
    "Burgerlijk Wetboek Boek 7",
    "bestuursrecht",
    "AVG",
    "Uitvoeringswet AVG",
    "privacy",
    "abortus",
    "stikstof",
    "asiel",
    "motie",
    "amendement",
    "Hoge Raad",
    "Raad van State",
    "ECLI:NL:HR:2020:1",
    "hr 2020",
    "kinderopvang",
    "omgevingswet",
    "belasting",
    "ministerie van Financiën",
    "D66",
    "VVD",
    "Jetten",
    "Schoof",
    "Wilders",
    "rutte",
    "kamerstuk 36799",
    "36799",
    "Wet openbare manifestaties",
    "demonstratie",
    "a",
    "de",
    "zz",
    "é",
    "Straße",
    "'s-Gravenhage",
    "art. 1",
    "artikel 1 lid 2 onder b",
    "1:2",
    "BWBR0001840",
    "bwbr0005537",
    "32016R0679",
    "celex 32016R0679",
    "EVRM",
    "artikel 8 EVRM",
]


def search_requests(pools: Pools) -> list[Request]:
    questions = list(FIXED_QUESTIONS)
    for pool, n in [
        ("bwb_id", 15),
        ("ecli", 15),
        ("dossier", 15),
        ("abbreviation", 10),
        ("subjects", 10),
        ("court", 5),
        ("slug", 5),
    ]:
        questions += pools.sample(pool, n)
    questions += [a.replace("|", " art. ") for a in pools.sample("article", 20)]
    questions += pools.sample("citation_title", 20) + pools.sample("short_title", 10)
    questions += pools.sample("full_name", 10) + _words(pools)
    questions = list(dict.fromkeys(questions))
    found = [Request("/api/search", (("q", q),), "search") for q in questions]
    found += [
        Request("/api/search", (("q", q), ("types", t)), "search")
        for q in questions[:10]
        for t in ("articles", "instruments", "judgments", "dossiers", "members")
    ]
    found += [
        Request("/api/search", (("q", q), ("limit", "5")), "search")
        for q in questions[:10]
    ]
    found += [Request("/api/resolve", (("q", q),), "resolve") for q in questions]
    return found


def _words(pools: Pools) -> list[str]:
    """Single words and prefixes of the titles: what a user types before the whole title."""
    titles = pools.values.get("citation_title", {})
    words = sorted(
        {w.strip(",.()").lower() for t in titles for w in t.split() if len(w) > 4}
    )
    chosen = random.Random("words").sample(words, min(30, len(words)))
    return chosen + [w[:4] for w in chosen[:10]]
