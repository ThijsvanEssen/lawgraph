"""The server HTML of Concordans on a real PostgreSQL (``GET /render/{path}``): per kind of
source its title, description, canonical address, structured data and content in the
shell of the front end; a 301 to the readable address; a real 404; the pages of the app;
an ETag a client can ask again with."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.seo import shell
from lawgraph.config import settings
from lawgraph.db import GraphStore

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
ROUTES = [
    {"path": "/", "title": "Concordans", "description": "Wetten en Kamerstukken."},
    {"path": "/actueel", "title": "Actueel, Concordans", "description": "Het nieuws."},
    {"path": "/explore", "title": "Verkenner, Concordans", "description": "De graaf."},
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
    assert page["description"].endswith("Met 1 uitspraken en Kamerstukken.")
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
    # a node without a readable address stays the explorer
    explorer = _get(client, "/explore?focus=decisions/s_1")
    assert explorer.status_code == 200
    assert _head(explorer.text)["title"] == "Verkenner, Concordans"


@pytest.mark.parametrize(
    "path",
    ["/uitspraken/ECLI:NL:HR:1900:1", "/wetten/BWBR9999999", "/kamerstukken/36496/999",
     "/bestaat/niet", "/wetten/xyz"],
)  # fmt: skip
def test_what_is_not_there_is_not_found(client: TestClient, path: str) -> None:
    response = _get(client, path)
    assert response.status_code == 404
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
    assert first.headers["cache-control"].startswith("public, max-age=3600")
    again = _get(client, "/wetten/BWBR0005289", **{"If-None-Match": etag})
    assert again.status_code == 304


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
        ("decisions/s_1", "s_1", None),
    ):  # fmt: skip
        body = client.get(f"/api/nodes/{node}").json()
        assert (body["title"], body["path"]) == (title, path), node
        assert body["description"]


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
