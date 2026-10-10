"""The server HTML of Concordans on a real PostgreSQL (``GET /render/{path}``): per kind of
source its title, description, canonical address, structured data and content in the
shell of the front end; a 301 to the readable address; a real 404; the pages of the app;
an ETag a client can ask again with."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.seo import shell
from lawgraph.config import settings
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import seo

SHELL = """<!doctype html>
<html lang="nl">
	<head>
		<meta charset="utf-8" />
		<meta
			name="description"
			content="Concordans: wetten, uitspraken en Kamerstukken."
		/>
		<meta property="og:site_name" content="Concordans" />
		<meta property="og:type" content="website" />
		<script type="module">import("/_app/immutable/entry/start.js")</script>
	</head>
	<body data-sveltekit-preload-data="hover">
		<div style="display: contents"></div>
	</body>
</html>
"""
# As on the server, read before a test patches it: a cold article page is as fast as the
# static shell (~0.1 s) and waits no longer than this for its judgments.
CITED_BUDGET = seo.CITED_BUDGET
SORT = 1.0  # a sort of the judgments that takes longer than any page may wait

ROUTES = [
    {"path": "/", "title": "Concordans", "description": "Wetten en Kamerstukken."},
    {"path": "/actueel", "title": "Actueel, Concordans", "description": "Het nieuws."},
    {"path": "/explore", "title": "Verkenner, Concordans", "description": "De graaf."},
    # a reader's own maps, kept in the browser: nothing of its own to find
    {"path": "/gemarkeerd", "title": "Gemarkeerd, Concordans", "index": False},
]


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": ["TK"], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **meta: Any) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "meta": meta,
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0005289", "instrument", bwb_id="BWBR0005289",
                  citation_title="Burgerlijk Wetboek Boek 6", short_title="BW 6",
                  date_in_force="1992-01-01", kind="wet"),
            _node("bwbr0001854", "instrument", bwb_id="BWBR0001854",
                  citation_title="Wetboek van Strafrecht", short_title="Sr",
                  date_in_force="1886-09-01", kind="wet"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr0005289_162", "article", bwb_id="BWBR0005289",
                  article_number="162", heading="Onrechtmatige daad", position=162,
                  text="1. Hij die jegens een ander een onrechtmatige daad pleegt, welke "
                  "hem kan worden toegerekend, is verplicht de schade te vergoeden.\n"
                  "2. Als onrechtmatige daad worden aangemerkt …"),
            _node("bwbr0005289_163", "article", bwb_id="BWBR0005289",
                  article_number="163", position=163, text="Geen verplichting …"),
            _node("bwbr0001854_287", "article", bwb_id="BWBR0001854",
                  article_number="287", heading="Doodslag", position=287,
                  text="Hij die opzettelijk een ander van het leven berooft, wordt, als "
                  "schuldig aan doodslag, gestraft …"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("ecli_nl_hr_2019_2006", "judgment", ecli="ECLI:NL:HR:2019:2006",
                  display_name="Hoge Raad 20-12-2019", names=["Urgenda"],
                  court="Hoge Raad", date="2019-12-20", date_eff="2019-12-20",
                  summary="Klimaatzaak. De Staat moet de uitstoot van broeikasgassen "
                  "verminderen.", text="De hele tekst van de uitspraak."),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36496", "dossier", label="36496", number="36496",
                  title="Regels over kunstmatige intelligentie (Wet AI-toezicht)",
                  current_phase="Tweede Kamer", last_activity="2026-09-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36496_71", "document", kind="Motie", date="2026-09-01",
                  dossier_number="36496", dossier_numbers=["36496"], sequence=71,
                  title="Regels over kunstmatige intelligentie",
                  subject="Motie van het lid Bolhuis over een AI-killswitch",
                  actors=[{"name": "Bolhuis", "faction": "GL-PvdA",
                           "role": "Eerste ondertekenaar", "capacity": "Lid"}],
                  text="De Kamer, gehoord de beraadslaging, …"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases", [_node("z_1", "case", external_id="Z-1")]
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                "s_1", "decision", date="2026-09-08", primary_case_id="Z-1", passed=True
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node("vvd", "faction", abbreviation="VVD"),
            _node("pvv", "faction", abbreviation="PVV"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("r1", "judgments/ecli_nl_hr_2019_2006", "articles/bwbr0005289_162",
                  "REFERS_TO"),
            _edge("p1", "documents/kst_36496_71", "cases/z_1", "PART_OF"),
            _edge("a1", "decisions/s_1", "cases/z_1", "ABOUT"),
            _edge("v1", "factions/vvd", "decisions/s_1", "VOTED", choice="Voor", seats=24),
            _edge("v2", "factions/pvv", "decisions/s_1", "VOTED", choice="Tegen", seats=37),
        ]
    )  # fmt: skip


@pytest.fixture()
def client(
    store: GraphStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    index = tmp_path / "index.html"
    index.write_text(SHELL)
    (tmp_path / "spa-routes.json").write_text(json.dumps(ROUTES))
    monkeypatch.setattr(settings, "SPA_INDEX", str(index))
    monkeypatch.setattr(settings, "SITE_URL", "https://concordans.nl")
    # a page waits for what it links to, however slow the runner: what a page holds is
    # tested here, how long it waits in test_an_article_page_reads_its_judgments_once_…
    monkeypatch.setattr(seo, "CITED_BUDGET", 5.0)
    version_cache.clear()
    shell.forget()
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)
        shell.forget()


def _get(client: TestClient, path: str, **headers: str) -> Any:
    return client.get(f"/render{path}", headers=headers, follow_redirects=False)


def _head(html: str) -> dict[str, Any]:
    """The title, description, canonical, robots and JSON-LD of a page, and its #seo."""

    def meta(name: str) -> str | None:
        m = re.search(rf'<meta (?:name|property)="{name}" content="([^"]*)"', html)
        return m[1] if m else None

    title = re.search(r"<title[^>]*>(.*?)</title>", html)
    canonical = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    data = re.search(
        r'<script type="application/ld\+json" data-seo>(.*?)</script>', html, re.S
    )
    main = re.search(r'<main id="seo">(.*?)</main>', html, re.S)
    return {
        "title": title[1] if title else None,
        "description": meta("description"),
        "canonical": canonical[1] if canonical else None,
        "robots": meta("robots"),
        "og_image": meta("og:image"),
        "data": json.loads(data[1]) if data else None,
        "main": main[1] if main else None,
        "descriptions": len(re.findall(r'<meta\s+name="description"', html)),
    }


def test_an_article_has_its_title_text_and_the_judgments_that_cite_it(
    client: TestClient,
) -> None:
    response = _get(client, "/wetten/BWBR0005289/artikel/6:162")
    assert response.status_code == 200
    page = _head(response.text)
    assert page["title"] == "Artikel 6:162 BW: onrechtmatige daad, Concordans"
    assert page["description"].startswith("1. Hij die jegens een ander")
    # the text alone, the same before and after its judgments are kept (no count)
    assert "uitspraken" not in page["description"]
    assert page["canonical"] == "https://concordans.nl/wetten/BWBR0005289/artikel/6:162"
    assert page["og_image"] == "https://concordans.nl/og/artikel.png"
    assert page["descriptions"] == 1  # the one of the shell replaced
    assert page["robots"] is None
    assert "Hij die jegens een ander" in page["main"]
    assert 'href="/uitspraken/ECLI:NL:HR:2019:2006"' in page["main"]
    assert 'href="/wetten/BWBR0005289"' in page["main"]
    graph = page["data"]["@graph"]
    assert graph[0]["@type"] == "Legislation"
    assert graph[0]["isPartOf"]["legislationIdentifier"] == "BWBR0005289"
    assert [i["name"] for i in graph[1]["itemListElement"]] == [
        "Concordans",
        "Burgerlijk Wetboek Boek 6 (BW 6)",
        "Artikel 6:162 BW: onrechtmatige daad",
    ]
    # the shell's own head and body stay: the app starts over it
    assert 'import("/_app/immutable/entry/start.js")' in response.text
    assert response.text.index('<main id="seo">') < response.text.index(
        '<div style="display: contents">'
    )


def test_an_article_of_a_law_without_books(client: TestClient) -> None:
    response = _get(client, "/wetten/BWBR0001854/artikel/287")
    assert response.status_code == 200
    page = _head(response.text)
    assert page["title"].startswith("Artikel 287 Sr")
    assert page["description"].startswith("Hij die opzettelijk een ander")
    assert page["canonical"] == "https://concordans.nl/wetten/BWBR0001854/artikel/287"
    assert "Hij die opzettelijk een ander" in page["main"]


def test_an_article_whose_judgments_take_too_long_is_its_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Of a much cited article (6:162 BW on prod) the citing judgments take long: the page
    is the article without them, not the shell."""
    monkeypatch.setattr(seo, "CITED_BUDGET", 0.0)
    response = _get(client, "/wetten/BWBR0005289/artikel/6:162")
    assert response.status_code == 200
    assert response.headers["cache-control"] != "no-store"
    page = _head(response.text)
    assert page["title"] == "Artikel 6:162 BW: onrechtmatige daad, Concordans"
    assert page["description"].startswith("1. Hij die jegens een ander")
    assert "Hij die jegens een ander" in page["main"]
    assert 'href="/wetten/BWBR0005289"' in page["main"]
    assert "/uitspraken/" not in page["main"]


def test_an_article_page_reads_its_judgments_once_per_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The judgments citing an article are sorted once per version of the edges and the
    judgments (about half a second for 6:162 on prod), in the background, and a later
    page reads them kept: a page that cannot wait for them is the article, the next one
    has them."""
    version_cache.clear()
    sorted_ = []
    compute = seo._cited

    def slow(store: GraphStore, node_id: str) -> Any:
        sorted_.append(node_id)
        time.sleep(SORT)
        return compute(store, node_id)

    monkeypatch.setattr(seo, "_cited", slow)
    assert CITED_BUDGET <= 0.05
    monkeypatch.setattr(seo, "CITED_BUDGET", CITED_BUDGET)
    started = time.monotonic()
    first = _head(_get(client, "/wetten/BWBR0005289/artikel/6:162").text)
    # not kept yet: the article alone, without waiting for the sort
    assert time.monotonic() - started < SORT / 2
    assert "/uitspraken/" not in first["main"]
    assert "Hij die jegens een ander" in first["main"]
    for _ in range(100):  # computed on in the background
        if _kept():
            break
        time.sleep(0.05)
    for _ in range(3):
        started = time.monotonic()
        page = _head(_get(client, "/wetten/BWBR0005289/artikel/6:162").text)
        assert time.monotonic() - started < SORT / 2  # read kept, not sorted again
        assert 'href="/uitspraken/ECLI:NL:HR:2019:2006"' in page["main"]
    assert sorted_ == ["articles/bwbr0005289_162"]


def _kept() -> bool:
    return any("seo article cited" in str(key) for key in version_cache._values)


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/wetten/BWBR0005289/artikel/6:162", 200),
        ("/uitspraken/ecli:nl:hr:2019:2006", 301),
        ("/bestaat/niet", 404),
        ("/actueel", 200),
    ],
)
def test_head_is_answered_as_get(client: TestClient, path: str, status: int) -> None:
    """Caddy, crawlers and uptime checks ask HEAD."""
    got = _get(client, path)
    head = client.head(f"/render{path}", follow_redirects=False)
    assert (head.status_code, got.status_code) == (status, status)
    assert head.headers.get("location") == got.headers.get("location")
    assert head.headers["cache-control"] == got.headers["cache-control"]
    assert head.content == b""


def test_a_law_lists_its_articles(client: TestClient) -> None:
    page = _head(_get(client, "/wetten/BWBR0005289").text)
    assert page["title"] == "Burgerlijk Wetboek Boek 6 (BW 6), Concordans"
    assert "geldend sinds 01-01-1992" in page["description"]
    assert 'href="/wetten/BWBR0005289/artikel/6:162"' in page["main"]
    assert 'href="/wetten/BWBR0005289/artikel/6:163"' in page["main"]
    assert page["data"]["@graph"][0]["legislationIdentifier"] == "BWBR0005289"


def test_a_judgment_has_its_summary_not_its_text(client: TestClient) -> None:
    response = _get(client, "/uitspraken/ECLI:NL:HR:2019:2006")
    page = _head(response.text)
    assert (
        page["title"]
        == "ECLI:NL:HR:2019:2006, Hoge Raad 20-12-2019 (Urgenda), Concordans"
    )
    assert page["description"].startswith("Klimaatzaak.")
    assert "De hele tekst" not in response.text
    assert 'href="/wetten/BWBR0005289/artikel/6:162"' in page["main"]
    assert "rechtspraak.nl" in page["main"]
    assert page["data"]["@graph"][0]["author"]["name"] == "Hoge Raad"


def test_a_motion_has_its_submitter_and_the_vote(client: TestClient) -> None:
    page = _head(_get(client, "/kamerstukken/36496/71").text)
    assert page["title"].startswith("Motie Bolhuis over een AI-killswitch (36496-71)")
    assert "aangenomen" in page["title"]
    assert "Ingediend door Bolhuis" in page["description"]
    assert "voor: VVD" in page["description"]
    assert "Voor: VVD" in page["main"] and "Tegen: PVV" in page["main"]
    assert 'href="/dossiers/36496"' in page["main"]
    assert "De Kamer, gehoord" not in page["main"]  # the text is not read


def test_a_dossier_lists_its_papers(client: TestClient) -> None:
    page = _head(_get(client, "/dossiers/36496").text)
    assert (
        page["title"]
        == "36496 Wet AI-toezicht: dossier, moties en stemmingen, Concordans"
    )
    assert "1 stukken" in page["description"]
    assert 'href="/kamerstukken/36496/71"' in page["main"]


def test_another_spelling_and_the_explorer_redirect_to_the_readable_address(
    client: TestClient,
) -> None:
    lower = _get(client, "/uitspraken/ecli:nl:hr:2019:2006?lezen=1")
    assert lower.status_code == 301
    assert lower.headers["location"] == "/uitspraken/ECLI:NL:HR:2019:2006?lezen=1"
    focus = _get(client, "/explore?focus=articles/bwbr0005289_162&lezen=1")
    assert focus.status_code == 301
    assert focus.headers["location"] == "/wetten/BWBR0005289/artikel/6:162?lezen=1"
    # a decision by its key; a node without a readable address stays the explorer
    vote = _get(client, "/explore?focus=decisions/s_1")
    assert (vote.status_code, vote.headers["location"]) == (301, "/stemmingen/s_1")
    explorer = _get(client, "/explore?focus=activities/a1")
    assert explorer.status_code == 200
    assert _head(explorer.text)["title"] == "Verkenner, Concordans"


@pytest.mark.parametrize(
    "path",
    ["/uitspraken/ECLI:NL:HR:1900:1", "/wetten/BWBR9999999", "/kamerstukken/36496/999",
     "/stemmingen/s_999",
     "/bestaat/niet", "/wetten/xyz"],
)  # fmt: skip
def test_what_is_not_there_is_not_found(client: TestClient, path: str) -> None:
    response = _get(client, path)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-cache"
    page = _head(response.text)
    assert page["title"] == "Niet gevonden, Concordans"
    assert page["robots"] == "noindex"
    assert page["main"] is None


def test_a_page_of_the_app_has_its_own_title(client: TestClient) -> None:
    for path, title in (("/", "Concordans"), ("/actueel", "Actueel, Concordans")):
        response = _get(client, path)
        assert response.status_code == 200
        assert _head(response.text)["title"] == title


def test_a_page_is_asked_again_with_its_etag(client: TestClient) -> None:
    first = _get(client, "/wetten/BWBR0005289")
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"
    again = _get(client, "/wetten/BWBR0005289", **{"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "no-cache"


def test_without_the_list_of_pages_every_other_path_is_the_shell(
    client: TestClient, tmp_path: Path
) -> None:
    """Before the front end lists its pages, no path is turned away: the SPA says it."""
    (tmp_path / "spa-routes.json").unlink()
    shell.forget()
    response = _get(client, "/bestaat/niet")
    assert response.status_code == 200
    assert _head(response.text)["main"] is None


def test_a_node_in_the_app_has_the_title_and_address_of_its_page(
    client: TestClient,
) -> None:
    """``title``, ``description`` and ``path`` of ``/api/nodes``: the SPA shows the same
    title when it opens a node, from the same templates."""
    for node, title, path in (
        ("articles/bwbr0005289_162", "Artikel 6:162 BW: onrechtmatige daad",
         "/wetten/BWBR0005289/artikel/6:162"),
        ("judgments/ecli_nl_hr_2019_2006",
         "ECLI:NL:HR:2019:2006, Hoge Raad 20-12-2019 (Urgenda)",
         "/uitspraken/ECLI:NL:HR:2019:2006"),
        ("dossiers/36496", "36496 Wet AI-toezicht: dossier, moties en stemmingen",
         "/dossiers/36496"),
        ("decisions/s_1", "Stemming, 08-09-2026: aangenomen", "/stemmingen/s_1"),
    ):  # fmt: skip
        body = client.get(f"/api/nodes/{node}").json()
        assert (body["title"], body["path"]) == (title, path), node
        assert body["description"]


def test_a_decision_has_its_page(client: TestClient) -> None:
    response = _get(client, "/stemmingen/s_1")
    assert response.status_code == 200
    assert _head(response.text)["canonical"] == "https://concordans.nl/stemmingen/s_1"


@pytest.mark.parametrize(
    "focus", ["decisions/nothing", "activities/a1", "geen/collectie", "zonder-slash"]
)
def test_the_explorer_of_a_node_that_is_not_there_is_the_explorer(
    client: TestClient, focus: str
) -> None:
    """No 500: a focus on a node the graph lacks, or on no node at all, is the page of the
    explorer, which says so itself."""
    response = _get(client, f"/explore?focus={focus}")
    assert response.status_code == 200
    assert _head(response.text)["title"] == "Verkenner, Concordans"


def test_a_dossier_with_a_suffix_by_its_label(
    client: TestClient, store: GraphStore
) -> None:
    """The key of a dossier is its label made a key (36600_viii): the page, its address
    and the redirect from the explorer go by the label."""
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("36600_viii", "dossier", label="36600-VIII", number="36600",
               suffix="VIII", title="Begroting Onderwijs")],
    )  # fmt: skip
    page = _head(_get(client, "/dossiers/36600-VIII").text)
    assert page["canonical"] == "https://concordans.nl/dossiers/36600-VIII"
    focus = _get(client, "/explore?focus=dossiers/36600_viii")
    assert focus.headers["location"] == "/dossiers/36600-VIII"
    node = client.get("/api/nodes/dossiers/36600_viii").json()
    assert node["path"] == "/dossiers/36600-VIII"


def _seed_people(store: GraphStore) -> None:
    """A minister-president, a former member, someone the Kamer never seated, a faction
    of each chamber, a cabinet and a committee of each chamber."""
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node("m_jetten", "member", name="Rob Jetten", family_name="Jetten",
                  slug="rob-jetten", party="D66",
                  government_functions=[
                      {"function": "Minister voor Klimaat en Energie",
                       "cabinet": "kabinet-Rutte IV", "cabinet_key": "rutte_iv",
                       "from_date": "2022-01-10", "to_date": "2024-07-02"},
                      {"function": "Minister-president", "cabinet": "kabinet-Jetten",
                       "cabinet_key": "jetten", "from_date": "2026-02-23"},
                  ],
                  faction_memberships=[
                      {"faction_key": "d66", "name": "Democraten 66",
                       "abbreviation": "D66", "from_date": "2017-03-23",
                       "to_date": "2026-02-22"},
                  ]),
            _node("m_paternotte", "member", name="Jan Paternotte",
                  family_name="Paternotte", slug="jan-paternotte",
                  faction_memberships=[
                      {"faction_key": "d66", "name": "Democraten 66",
                       "abbreviation": "D66", "from_date": "2017-03-23"},
                  ]),
            _node("m_oud", "member", name="Alexander Pechtold", family_name="Pechtold",
                  slug="alexander-pechtold",
                  faction_memberships=[
                      {"faction_key": "d66", "name": "Democraten 66",
                       "abbreviation": "D66", "from_date": "2003-01-30",
                       "to_date": "2018-10-09"},
                  ]),
            _node("m_onbekend", "member", name="J. de Vries", slug="j-de-vries"),
            _node("m_ek", "member", name="Paul van Meenen", family_name="Meenen",
                  slug="paul-van-meenen",
                  ek={"faction": "ek_d66", "abbreviation": "D66",
                      "observed_from": "2023-06-13", "observed_until": None}),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node("d66", "faction", name="Democraten 66", abbreviation="D66",
                  seats=26, active_from="2006-11-30"),
            _node("ek_d66", "faction", name="D66-fractie", abbreviation="D66",
                  chamber="EK", seats=5,
                  url="https://www.eerstekamer.nl/fractie/d66",
                  board=[{"function": "Fractievoorzitter", "name": "P. van Meenen"}]),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node("jetten", "cabinet", name="kabinet-Jetten", from_date="2026-02-23",
                  previous="schoof", prime_minister="m_jetten",
                  parties=[{"short": "D66", "faction": "d66"}], factions=["d66"],
                  phases=[{"kind": "in_functie", "label": "in functie",
                           "from_date": "2026-02-23"}]),
            _node("schoof", "cabinet", name="kabinet-Schoof", from_date="2024-07-02",
                  to_date="2026-02-23"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "committees",
        [
            _node("szw", "committee",
                  name="Vaste commissie voor Sociale Zaken en Werkgelegenheid",
                  abbreviation="SZW", slug="szw", kind="Vaste commissie",
                  started_on="2010-06-17"),
            _node("ek_jenv", "committee", name="Justitie en Veiligheid",
                  title="Vaste commissie voor Justitie en Veiligheid",
                  abbreviation="J&V", slug="ek-jenv", chamber="EK",
                  url="https://www.eerstekamer.nl/commissies/jenv"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("f1", "members/m_paternotte", "factions/d66", "MEMBER_OF",
                  from_date="2017-03-23", role="Fractievoorzitter"),
            _edge("f2", "members/m_oud", "factions/d66", "MEMBER_OF",
                  from_date="2003-01-30", to_date="2018-10-09"),
            _edge("f3", "members/m_ek", "factions/ek_d66", "MEMBER_OF",
                  chamber="EK", observed_from="2023-06-13", observed_until=None),
            _edge("c1", "members/m_paternotte", "committees/szw", "MEMBER_OF",
                  from_date="2021-04-01", role="Voorzitter"),
            _edge("c2", "members/m_oud", "committees/szw", "MEMBER_OF",
                  from_date="2010-06-17", to_date="2018-10-09"),
            _edge("c3", "members/m_ek", "committees/ek_jenv", "MEMBER_OF",
                  chamber="EK", observed_from="2023-06-13", observed_until=None,
                  role="lid"),
            _edge("s1", "members/m_jetten", "cabinets/jetten", "SERVED_IN",
                  posts=[{"function": "Minister-president"},
                         {"function": "Minister van Algemene Zaken"}]),
            _edge("w1", "members/m_jetten", "documents/kst_36496_71", "AUTHORED",
                  role="Eerste ondertekenaar"),
        ]
    )  # fmt: skip


def test_a_member_has_their_post_and_their_papers(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    response = _get(client, "/leden/rob-jetten")
    assert response.status_code == 200
    page = _head(response.text)
    assert page["title"] == "Rob Jetten, Minister-president, Concordans"
    assert page["description"] == (
        "Rob Jetten (D66), Minister-president in kabinet-Jetten (2026–), Minister voor "
        "Klimaat en Energie in kabinet-Rutte IV (2022–2024)"
    )
    assert page["canonical"] == "https://concordans.nl/leden/rob-jetten"
    assert page["robots"] is None
    assert page["data"]["@graph"][0]["@type"] == "Person"
    assert page["data"]["@graph"][0]["jobTitle"] == "Minister-president"
    assert 'href="/kabinetten/jetten"' in page["main"]
    assert 'href="/kabinetten/rutte_iv"' in page["main"]
    assert 'href="/fracties/d66"' in page["main"]
    assert 'href="/kamerstukken/36496/71"' in page["main"]


@pytest.mark.parametrize(
    ("slug", "title"),
    [
        ("jan-paternotte", "Jan Paternotte, Tweede Kamerlid (D66)"),
        ("alexander-pechtold", "Alexander Pechtold, oud-Kamerlid"),
        ("paul-van-meenen", "Paul van Meenen, Eerste Kamerlid (D66)"),
        # no seat and no post: the name alone, nothing guessed
        ("j-de-vries", "J. de Vries"),
    ],
)
def test_what_a_member_is_comes_from_the_source(
    client: TestClient, store: GraphStore, slug: str, title: str
) -> None:
    _seed_people(store)
    assert _head(_get(client, f"/leden/{slug}").text)["title"] == f"{title}, Concordans"


def test_a_faction_lists_its_members_now(client: TestClient, store: GraphStore) -> None:
    _seed_people(store)
    page = _head(_get(client, "/fracties/d66").text)
    assert page["title"] == "D66, fractie in de Tweede Kamer, Concordans"
    # its name and its years: no seats, nothing that changes with a day of the data
    assert page["description"] == (
        "Democraten 66 (D66), fractie in de Tweede Kamer, actief sinds 30-11-2006"
    )
    assert 'href="/leden/jan-paternotte"' in page["main"]
    assert "Fractievoorzitter" in page["main"]
    assert "/leden/alexander-pechtold" not in page["main"]  # left in 2018
    assert page["data"]["@graph"][0]["parentOrganization"]["name"] == (
        "Tweede Kamer der Staten-Generaal"
    )
    ek = _head(_get(client, "/fracties/ek_d66").text)
    assert ek["title"] == "D66-fractie in de Eerste Kamer, Concordans"
    assert 'href="/leden/paul-van-meenen"' in ek["main"]
    assert "P. van Meenen" in ek["main"]  # its board
    assert 'href="https://www.eerstekamer.nl/fractie/d66"' in ek["main"]


def test_a_cabinet_has_its_bewindspersonen_and_parties(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    page = _head(_get(client, "/kabinetten/jetten").text)
    assert page["title"] == "Kabinet-Jetten (2026–), Concordans"
    assert page["description"] == (
        "Kabinet-Jetten, sinds 23-02-2026, D66, minister-president Rob Jetten"
    )
    assert 'href="/leden/rob-jetten"' in page["main"]
    assert "Minister-president; Minister van Algemene Zaken" in page["main"]
    assert 'href="/fracties/d66"' in page["main"]
    assert 'href="/kabinetten/schoof"' in page["main"]
    assert page["data"]["@graph"][0]["foundingDate"] == "2026-02-23"
    before = _head(_get(client, "/kabinetten/schoof").text)
    assert before["title"] == "Kabinet-Schoof (2024–2026), Concordans"


def test_a_committee_lists_its_members_with_their_role(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    page = _head(_get(client, "/commissies/szw").text)
    assert page["title"] == (
        "Vaste commissie voor Sociale Zaken en Werkgelegenheid (SZW), Concordans"
    )
    assert "Tweede Kamer" in page["description"]
    assert "actief sinds 17-06-2010" in page["description"]
    assert 'href="/leden/jan-paternotte"' in page["main"]
    assert "Voorzitter" in page["main"]
    assert "/leden/alexander-pechtold" not in page["main"]
    ek = _head(_get(client, "/commissies/ek-jenv").text)
    assert ek["title"].startswith(
        "Vaste commissie voor Justitie en Veiligheid (J&amp;V)"
    )
    assert 'href="/leden/paul-van-meenen"' in ek["main"]
    assert ek["data"]["@graph"][0]["parentOrganization"]["name"] == (
        "Eerste Kamer der Staten-Generaal"
    )


@pytest.mark.parametrize(
    "path", ["/leden/niemand", "/fracties/geen", "/kabinetten/geen", "/commissies/geen"]
)
def test_a_person_or_body_that_is_not_there_is_not_found(
    client: TestClient, store: GraphStore, path: str
) -> None:
    _seed_people(store)
    assert _get(client, path).status_code == 404


def test_the_app_titles_a_person_or_body_as_its_page(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    for node, title in (
        ("members/m_jetten", "Rob Jetten, Minister-president"),
        ("factions/d66", "D66, fractie in de Tweede Kamer"),
        ("cabinets/jetten", "Kabinet-Jetten (2026–)"),
        (
            "committees/szw",
            "Vaste commissie voor Sociale Zaken en Werkgelegenheid (SZW)",
        ),
    ):
        assert client.get(f"/api/nodes/{node}").json()["title"] == title, node


def _seed_publications(store: GraphStore) -> None:
    """A Staatsblad the BWB names with its nota van toelichting, one known only by its
    own source, a commitment with the letter that fulfils it, and a decision."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("stb_2025_263", "instrument", kind="publicatie",
               citation_title="Stb. 2025, 263", official_id="stb-2025-263",
               publication_kind="Stb", publication_year=2025, publication_number=263,
               date_signed="2025-08-20", date_published="2025-09-02",
               dossier_numbers=["36496"])],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("stb_stb_2025_263", "document", identifier="stb-2025-263",
                  kind="Nota van toelichting", year="2025", number="263",
                  title="Besluit tot wijziging van het Mediabesluit 2008",
                  text="Nota van toelichting. " * 500),
            _node("stb_stb_2024_7", "document", identifier="stb-2024-7",
                  kind="Nota van toelichting", year="2024", number="7",
                  title="Staatsblad 2024/7", text="…"),
            # normalized before the ``DC.title`` was read: the masthead as its title
            _node("stb_stb_2026_94", "document", identifier="stb-2026-94",
                  kind="Nota van toelichting", year="2026", number="94",
                  title="Staatsblad", text="…"),
            _node("kst_36496_80", "document", kind="Brief regering",
                  dossier_number="36496", sequence=80, date="2026-10-01",
                  subject="Nakoming van de toezegging over AI-toezicht"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "commitments",
        [_node("tz_1", "commitment", number="TZ202609-124",
               text="De minister stuurt voor de zomer een brief over AI-toezicht.",
               made_on="2026-09-10", minister_name="R. Jetten",
               minister_role="minister-president", ministry_name="Algemene Zaken",
               status="Openstaand", expected_resolution="0001-01-01",
               member_key="m_jetten", cabinet="jetten")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        # an article whose key does not start with its law's id: its law read from it
        [_node("sr_288_oud", "article", bwb_id="BWBR0001854", article_number="288")],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("am1", "instruments/stb_2025_263", "articles/bwbr0005289_162",
                  "AMENDS"),
            _edge("am2", "instruments/stb_2025_263", "articles/sr_288_oud", "REPEALS"),
            _edge("ab1", "commitments/tz_1", "dossiers/36496", "ABOUT"),
            _edge("an1", "documents/kst_36496_80", "commitments/tz_1", "ANSWERS"),
        ]
    )  # fmt: skip


def test_a_publication_has_its_title_and_what_it_changes(
    client: TestClient, store: GraphStore
) -> None:
    _seed_publications(store)
    response = _get(client, "/stb/2025/263")
    assert response.status_code == 200
    page = _head(response.text)
    assert page["title"] == (
        "Stb. 2025, 263: Besluit tot wijziging van het Mediabesluit 2008, Concordans"
    )
    assert "gepubliceerd 02-09-2025" in page["description"]
    assert "over Burgerlijk Wetboek Boek 6" in page["description"]
    assert page["robots"] is None
    assert 'href="/wetten/BWBR0005289"' in page["main"]
    assert "(wijzigt)" in page["main"]
    assert 'href="/wetten/BWBR0001854"' in page["main"]
    assert "(trekt in)" in page["main"]
    assert 'href="/dossiers/36496"' in page["main"]
    assert "zoek.officielebekendmakingen.nl/stb-2025-263" in page["main"]
    assert "Nota van toelichting. Nota" not in response.text  # its text is not read
    assert page["data"]["@graph"][0]["legislationIdentifier"] == "stb-2025-263"


def test_a_publication_without_a_title_or_a_change_is_not_indexed(
    client: TestClient, store: GraphStore
) -> None:
    _seed_publications(store)
    page = _head(_get(client, "/stb/2024/7").text)
    assert page["title"] == "Stb. 2024, 7, Concordans"
    assert page["canonical"] == "https://concordans.nl/stb/2024/7"
    assert page["robots"] == "noindex"


def test_the_name_of_the_series_is_no_title_of_its_own(
    client: TestClient, store: GraphStore
) -> None:
    _seed_publications(store)
    page = _head(_get(client, "/stb/2026/94").text)
    assert page["title"] == "Stb. 2026, 94, Concordans"
    assert page["robots"] == "noindex"


def test_a_commitment_has_its_text_minister_and_the_letter_that_fulfils_it(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    _seed_publications(store)
    page = _head(_get(client, "/toezeggingen/TZ202609-124").text)
    assert page["title"].startswith("Toezegging TZ202609-124: De minister stuurt")
    assert page["description"] == (
        "De minister stuurt voor de zomer een brief over AI-toezicht."
    )
    assert 'href="/leden/rob-jetten"' in page["main"]
    assert 'href="/kabinetten/jetten"' in page["main"]
    assert 'href="/dossiers/36496"' in page["main"]
    assert 'href="/kamerstukken/36496/80"' in page["main"]
    assert "Openstaand" in page["main"]
    assert "Verwachte afdoening" not in page["main"]  # 0001-01-01: none named
    assert page["data"]["@graph"][0]["identifier"] == "TZ202609-124"


def test_a_decision_links_its_motion_and_is_not_indexed(client: TestClient) -> None:
    response = _get(client, "/stemmingen/s_1")
    page = _head(response.text)
    assert page["title"] == "Stemming, 08-09-2026: aangenomen, Concordans"
    assert page["description"].endswith("voor: VVD; tegen: PVV")
    assert page["canonical"] == "https://concordans.nl/stemmingen/s_1"
    assert page["robots"] == "noindex"
    assert 'href="/kamerstukken/36496/71"' in page["main"]
    assert "Voor: VVD" in page["main"] and "Tegen: PVV" in page["main"]


def test_what_a_publication_changes_reads_no_article_keyed_by_its_law(
    store: GraphStore,
) -> None:
    """The law of an article keyed by it (``bwbr0005289_162``) comes from its key: a code
    amended in a hundred articles is not a hundred reads of them (Stb. 2026, 94: 0.13 s
    cold)."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("bwbr0005289", "instrument", bwb_id="BWBR0005289",
               citation_title="Burgerlijk Wetboek Boek 6"),
         _node("stb_2026_94", "instrument", kind="publicatie",
               official_id="stb-2026-94")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [_node(f"bwbr0005289_{n}", "article", bwb_id="BWBR0005289",
               article_number=str(n)) for n in range(1, 41)],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [_edge(f"c{n}", "instruments/stb_2026_94", f"articles/bwbr0005289_{n}",
               "AMENDS") for n in range(1, 41)]
    )  # fmt: skip
    seen: list[tuple[str, Any]] = []
    stream = store._stream

    def recorded(statement: Any, params: Any, *a: Any, **k: Any) -> Any:
        seen.append((statement, params))
        return stream(statement, params, *a, **k)

    store._stream = recorded  # type: ignore[method-assign]
    try:
        laws = seo._changed(store, ["instruments/stb_2026_94"])
    finally:
        store._stream = stream  # type: ignore[method-assign]
    assert [(law["name"], law["relations"]) for law in laws] == [
        ("Burgerlijk Wetboek Boek 6", ["AMENDS"])
    ]
    ((statement, params),) = seen
    with store.pool.connection() as conn:
        plan = conn.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON) " + str(statement), params
        ).fetchone()[0]
    ran: list[tuple[str, int]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("Relation Name") == "articles":
                ran.append((node["Node Type"], node.get("Actual Loops", 0)))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(plan)
    assert all(loops == 0 for _, loops in ran), ran


def test_a_page_of_the_app_may_keep_out_of_the_index(client: TestClient) -> None:
    """``"index": false`` in ``spa-routes.json``: the page with its title, ``noindex``."""
    own = _head(_get(client, "/gemarkeerd").text)
    assert own["title"] == "Gemarkeerd, Concordans"
    assert own["robots"] == "noindex"
    # the others as ever
    assert _head(_get(client, "/actueel").text)["robots"] is None
