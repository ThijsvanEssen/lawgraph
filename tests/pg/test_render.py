"""The server HTML of Concordans on a real PostgreSQL (``GET /render/{path}``): per kind of
source its title, description, canonical address, structured data and content in the
shell of the front end; a 301 to the readable address; a real 404; the pages of the app;
an ETag a client can ask again with."""

from __future__ import annotations

import html
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import render
from lawgraph.api.seo import article as seo_article
from lawgraph.api.seo import paint, shell
from lawgraph.api.seo.pages import home
from lawgraph.config import settings
from lawgraph.core.bwb_xml import article_key, article_props, parse_toestand
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import seo
from tests.asserts import assert_status
from tests.fakes import PATIENCE, until
from tests.paths import fixture_text
from tests.pg.plans import explain, plan_nodes, recorded

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

ROUTES = [
    {"path": "/", "title": "Concordans", "description": "Wetten en Kamerstukken."},
    {"path": "/actueel", "title": "Actueel, Concordans", "description": "Het nieuws."},
    {"path": "/explore", "title": "Verkenner, Concordans", "description": "De graaf."},
    # a reader's own bundels, kept in the browser: nothing of their own to find
    {"path": "/bundels", "title": "Bundels, Concordans", "index": False},
    # any one segment: a bundel by its id
    {"path": "/bundels/[id]", "title": "Bundel, Concordans", "index": False},
]


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": ["TK"], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **meta: Any) -> dict:
    return {
        "key": key,
        "from_id": source,
        "to_id": target,
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
                  instrument_citation_title="Burgerlijk Wetboek Boek 6",
                  text="1. Hij die jegens een ander een onrechtmatige daad pleegt, welke "
                  "hem kan worden toegerekend, is verplicht de schade te vergoeden.\n"
                  "2. Als onrechtmatige daad worden aangemerkt …"),
            _node("bwbr0005289_163", "article", bwb_id="BWBR0005289",
                  article_number="163", position=163, text="Geen verplichting …",
                  instrument_citation_title="Burgerlijk Wetboek Boek 6"),
            _node("bwbr0001854_287", "article", bwb_id="BWBR0001854",
                  article_number="287", heading="Doodslag", position=287,
                  instrument_citation_title="Wetboek van Strafrecht",
                  instrument_abbreviation="Sr",
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
            _edge("ref163", "articles/bwbr0005289_163", "articles/bwbr0005289_162",
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
    # a page waits for what it links to, and is read whole, however slow the runner (a
    # full run side by side): what a page holds is tested here, how long it waits in
    # test_an_article_page_reads_its_judgments_once_… and past the render budget in
    # test_a_page_whose_reads_take_too_long_keeps_its_title
    monkeypatch.setattr(seo, "CITED_BUDGET", 5.0)
    monkeypatch.setattr(seo_article, "EXTRA_BUDGET", 5.0)
    monkeypatch.setattr(render, "RENDER_BUDGET", 30.0)
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
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == "Art. 6:162 BW, Onrechtmatige daad, Concordans"
    assert page["description"].startswith("1. Hij die jegens een ander")
    # then what the page has besides, by count: the same before and after its judgments
    # are kept
    assert page["description"].endswith("… Met 1 uitspraak en 1 verwijzing.")
    assert len(page["description"]) <= 155
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
        "Boek 6 BW",
        "Art. 6:162 BW, Onrechtmatige daad",
    ]
    # the shell's own head and body stay: the app starts over it
    assert 'import("/_app/immutable/entry/start.js")' in response.text
    assert response.text.index('<main id="seo">') < response.text.index(
        '<div style="display: contents">'
    )


def test_an_article_of_a_law_without_books(client: TestClient) -> None:
    response = _get(client, "/wetten/BWBR0001854/artikel/287")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"].startswith("Art. 287 Sr")
    assert page["description"].startswith("Hij die opzettelijk een ander")
    assert page["canonical"] == "https://concordans.nl/wetten/BWBR0001854/artikel/287"
    assert "Hij die opzettelijk een ander" in page["main"]


def _history_and_chain(store: GraphStore) -> None:
    """Of 6:162 BW: the version the BWB holds first, a change of it whose dossier the data
    holds, one without its publication; two regulations based on it, the AMvB first, and
    one expired."""
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node("av_1", "article_version", bwb_id="BWBR0005289", article_number="162",
                  valid_from="1992-01-01", text="1. Oud.", effect="nieuwe-regeling",
                  origin_publication={"id": "stb-1991-600", "kind": "Staatsblad",
                                      "year": 1991, "number": "600",
                                      "dossiers": ["17541"]}),
            _node("av_2", "article_version", bwb_id="BWBR0005289", article_number="162",
                  valid_from="2020-07-01", text="1. Tussen.", effect="wijziging"),
            _node("av_3", "article_version", bwb_id="BWBR0005289", article_number="162",
                  valid_from="2026-01-01", current=True, text="1. Hij die …",
                  effect="wijziging",
                  origin_publication={"id": "stb-2025-263", "kind": "Staatsblad",
                                      "year": 2025, "number": "263",
                                      "dossiers": ["36496"]}),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0099001", "instrument", bwb_id="BWBR0099001", kind="ministeriele-regeling",
                  citation_title="Regeling schadevergoeding"),
            _node("bwbr0099002", "instrument", bwb_id="BWBR0099002", kind="AMvB",
                  citation_title="Besluit schadevergoeding"),
            _node("bwbr0099003", "instrument", bwb_id="BWBR0099003", kind="AMvB",
                  citation_title="Besluit van vroeger", date_expired="2000-01-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge(f"bo{n}", f"instruments/bwbr009900{n}", "articles/bwbr0005289_162",
                  "BASED_ON")
            for n in (1, 2, 3)
        ]
    )  # fmt: skip


def test_an_article_has_its_regulations_and_its_history(
    client: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uitgewerkt in: the AMvB first, ``CHAIN`` of them, the rest to the app; the expired
    one left out. Wetsgeschiedenis: newest first, each with its publication and dossier,
    the gaps said; both as JSON-LD of what changes it and is based on it."""
    _history_and_chain(store)
    monkeypatch.setattr(seo_article, "CHAIN", 1)
    page = _head(_get(client, "/wetten/BWBR0005289/artikel/6:162").text)
    main = page["main"]
    chain = main[main.index("<h2>Uitgewerkt in</h2>") :]
    assert chain.index("Besluit schadevergoeding") < chain.index("En 1 andere regeling")
    assert "Regeling schadevergoeding" not in main
    assert "Besluit van vroeger" not in main
    path = "/wetten/BWBR0005289/artikel/6:162"
    assert f'href="{path}?relatie=BASED_ON"' in chain
    history = main[main.index("<h2>Wetsgeschiedenis</h2>") :]
    lines = re.findall(r"<li>(.*?)</li>", history.split("</section>")[0])
    assert [re.sub(r"<[^>]+>", "", line) for line in lines] == [
        "1 januari 2026: gewijzigd bij Stb. 2025, 263, Kamerstukken 36496, Wet AI-toezicht",
        "1 juli 2020: gewijzigd, publicatie niet bekend",
        "1 januari 1992: vastgesteld bij Stb. 1991, 600, Kamerstukken 17541",
    ]
    assert 'href="/dossiers/36496"' in history
    assert "/dossiers/17541" not in history  # not in the data: its number alone
    assert "wetsgeschiedenis" in page["description"]
    reverse = page["data"]["@graph"][0]["@reverse"]
    assert [x["name"] for x in reverse["legislationChanges"]] == ["Stb. 2025, 263"]
    assert [x["name"] for x in reverse["isBasedOn"]] == ["Besluit schadevergoeding"]


def test_an_article_without_a_change_or_a_version(
    client: TestClient, store: GraphStore
) -> None:
    """One version: not changed since it; none: no block, no regulations: no block."""
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [_node("av_163", "article_version", bwb_id="BWBR0005289", article_number="163",
               valid_from="1992-01-01", current=True, text="Geen verplichting …")],
    )  # fmt: skip
    one = _head(_get(client, "/wetten/BWBR0005289/artikel/6:163").text)
    assert "<p>Sinds 1 januari 1992 niet gewijzigd.</p>" in one["main"]
    assert "Uitgewerkt in" not in one["main"]
    assert "@reverse" not in one["data"]["@graph"][0]
    none = _head(_get(client, "/wetten/BWBR0001854/artikel/287").text)
    assert "Wetsgeschiedenis" not in none["main"]


def test_an_article_whose_regulations_take_too_long_goes_without(
    client: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past ``EXTRA_BUDGET`` the page is the article without those blocks."""
    _history_and_chain(store)
    monkeypatch.setattr(seo_article, "EXTRA_BUDGET", 0.0)
    response = _get(client, "/wetten/BWBR0005289/artikel/6:162")
    assert_status(response, 200)
    main = _head(response.text)["main"]
    assert "Hij die jegens een ander" in main
    assert "Uitgewerkt in" not in main and "Wetsgeschiedenis" not in main


def test_an_article_whose_judgments_take_too_long_is_its_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Of a much cited article (6:162 BW on prod) the citing judgments take long: the page
    is the article without them, not the shell."""
    monkeypatch.setattr(seo, "CITED_BUDGET", 0.0)
    response = _get(client, "/wetten/BWBR0005289/artikel/6:162")
    assert_status(response, 200)
    assert response.headers["cache-control"] != "no-store"
    page = _head(response.text)
    assert page["title"] == "Art. 6:162 BW, Onrechtmatige daad, Concordans"
    assert page["description"].startswith("1. Hij die jegens een ander")
    assert page["description"].endswith("Met 1 uitspraak en 1 verwijzing.")
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
    release = threading.Event()

    def slow(store: GraphStore, node_id: str) -> Any:
        sorted_.append(node_id)
        release.wait(PATIENCE)  # a sort that takes longer than any page may wait
        return compute(store, node_id)

    monkeypatch.setattr(seo, "_cited", slow)
    assert CITED_BUDGET <= 0.05
    monkeypatch.setattr(seo, "CITED_BUDGET", CITED_BUDGET)
    try:
        first = _head(_get(client, "/wetten/BWBR0005289/artikel/6:162").text)
        # not kept yet: the article alone, without waiting for the sort
        assert not release.is_set()
    finally:
        release.set()
    assert "/uitspraken/" not in first["main"]
    assert "Hij die jegens een ander" in first["main"]
    assert until(_kept)  # computed on in the background
    for _ in range(3):
        page = _head(_get(client, "/wetten/BWBR0005289/artikel/6:162").text)
        assert 'href="/uitspraken/ECLI:NL:HR:2019:2006"' in page["main"]
    assert sorted_ == ["articles/bwbr0005289_162"]


def _kept() -> bool:
    return any("seo cited" in str(key) for key in version_cache._values)


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
    assert (head.status_code, got.status_code) == (status, status), (
        head.text,
        got.text,
    )
    assert head.headers.get("location") == got.headers.get("location")
    assert head.headers["cache-control"] == got.headers["cache-control"]
    assert head.content == b""


def test_a_law_lists_its_articles(client: TestClient) -> None:
    page = _head(_get(client, "/wetten/BWBR0005289").text)
    # the title of the API; the form lawyers search a book by, "BW 6", in the description
    assert page["title"] == "Boek 6 BW, Concordans"
    assert page["description"].startswith("Burgerlijk Wetboek Boek 6 (BW 6), ")
    assert "geldend sinds 1 januari 1992" in page["description"]
    assert 'href="/wetten/BWBR0005289/artikel/6:162"' in page["main"]
    assert 'href="/wetten/BWBR0005289/artikel/6:163"' in page["main"]
    assert page["data"]["@graph"][0]["legislationIdentifier"] == "BWBR0005289"


def test_the_one_article_of_a_regulation_has_its_page(
    client: TestClient, store: GraphStore
) -> None:
    # A regulation of one article, as normalize bwb writes it from its toestand.
    toestand = parse_toestand(fixture_text("bwb_enig_artikel_toestand.xml"))
    (article,) = toestand.articles
    bwb_id, title = "BWBR0007846", toestand.citation_title
    store.bulk_insert_or_update_nodes(
        "instruments", [_node("bwbr0007846", "instrument", bwb_id=bwb_id,
                              citation_title=title, kind="ministeriele-regeling")]
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [_node(article_key(bwb_id, article.number, article.stam_id) or "", "article",
               **article_props(article, bwb_id, title, 0))],
    )  # fmt: skip
    response = _get(client, "/wetten/BWBR0007846/artikel/enig-artikel")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == f"Enig artikel {title}, Concordans"
    assert page["canonical"] == (
        "https://concordans.nl/wetten/BWBR0007846/artikel/enig-artikel"
    )
    assert "Vanaf 1 januari 1996 bedraagt de vergoeding" in page["main"]
    # the label of the source, not the number the graph keys it by
    assert page["data"]["@graph"][0]["legislationIdentifier"] == (
        "BWBR0007846 Enig artikel"
    )
    law = _head(_get(client, "/wetten/BWBR0007846").text)
    assert 'href="/wetten/BWBR0007846/artikel/enig-artikel"' in law["main"]
    assert f"Enig artikel {title}" in law["main"]


def test_a_judgment_has_its_summary(client: TestClient) -> None:
    response = _get(client, "/uitspraken/ECLI:NL:HR:2019:2006")
    page = _head(response.text)
    assert (
        page["title"]
        == "HR 20 december 2019 (Urgenda), ECLI:NL:HR:2019:2006, Concordans"
    )
    assert page["description"].startswith("Klimaatzaak.")
    assert 'href="/wetten/BWBR0005289/artikel/6:162"' in page["main"]
    assert "rechtspraak.nl" in page["main"]
    assert page["data"]["@graph"][0]["author"]["name"] == "Hoge Raad"


def test_a_judgment_of_the_echr_links_hudoc(
    client: TestClient, store: GraphStore
) -> None:
    """Its item id is in its props alone (not in its light props): the page reads it."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node("ecli_ce_echr_2020_0101jud000100018", "judgment",
               ecli="ECLI:CE:ECHR:2020:0101JUD000100018", source="echr",
               external_id="001-200001", court="EHRM",
               date="2020-01-01", text="The whole text.")],
    )  # fmt: skip
    html = _get(client, "/uitspraken/ECLI:CE:ECHR:2020:0101JUD000100018").text
    assert '<html lang="en"' in html  # an ECHR judgment, by its source
    page = _head(html)
    assert 'href="https://hudoc.echr.coe.int/eng?i=001-200001"' in page["main"]
    assert "De uitspraak op HUDOC" in page["main"]


def test_a_judgment_of_the_court_of_justice_links_eur_lex(
    client: TestClient, store: GraphStore
) -> None:
    """Its CELEX number is in its props alone, as the item id of the ECHR is."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node("ecli_eu_c_2022_101", "judgment", ecli="ECLI:EU:C:2022:101",
               source="cjeu", external_id="62020CJ0160", celex="62020CJ0160",
               court="Hof van Justitie van de Europese Unie", date="2022-02-22",
               case_number="C-160/20", text="Het verzoek.")],
    )  # fmt: skip
    html = _get(client, "/uitspraken/ECLI:EU:C:2022:101").text
    assert '<html lang="nl"' in html
    head = _head(html)
    # cited with its case number, alike in the page and in the app
    cite = "HvJ EU 22 februari 2022, C-160/20"
    assert head["title"] == f"{cite}, ECLI:EU:C:2022:101, Concordans"
    node = client.get("/api/nodes/judgments/ecli_eu_c_2022_101").json()
    assert node["node"]["cite"]["short"] == cite
    main = head["main"]
    assert (
        'href="https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:62020CJ0160"'
        in main
    )
    assert "De uitspraak op EUR-Lex" in main


def _withdrawn(store: GraphStore, key: str, ecli: str, how: str, **props: Any) -> None:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node(key, "judgment", ecli=ecli, stub=True, withdrawn=how,
               withdrawn_on="2026-10-15", court="Rechtbank Zeeland-West-Brabant",
               court_code=ecli.split(":")[2], date_eff="2026-05-26", **props)],
    )  # fmt: skip


def test_a_judgment_the_rechtspraak_withdrew_is_gone_with_what_cites_it(
    client: TestClient, store: GraphStore
) -> None:
    """410, not 404: the source withdrew it for good, and a search engine drops a page
    that is gone at once. The page says so, with its court and date and what refers to
    it; an ECLI the graph never had stays a 404."""
    _withdrawn(store, "ecli_nl_rbzwb_2026_5617", "ECLI:NL:RBZWB:2026:5617", "doc")
    store.bulk_insert_or_update_edges(
        [_edge("cites", "judgments/ecli_nl_hr_2019_2006",
               "judgments/ecli_nl_rbzwb_2026_5617", "REFERS_TO")]
    )  # fmt: skip
    response = _get(client, "/uitspraken/ECLI:NL:RBZWB:2026:5617")
    assert_status(response, 410)
    page = _head(response.text)
    assert "ECLI:NL:RBZWB:2026:5617" in page["title"]
    assert page["robots"] == "noindex"
    main = html.unescape(page["main"])
    assert "Ingetrokken door de bron op 15 oktober 2026" in main
    assert "Rechtbank Zeeland-West-Brabant" in main and "26 mei 2026" in main
    assert 'href="/uitspraken/ECLI:NL:HR:2019:2006"' in main
    assert_status(_get(client, "/uitspraken/ECLI:NL:RBZWB:2026:5618"), 404)


def test_an_ecli_given_in_error_links_the_one_the_source_names(
    client: TestClient, store: GraphStore
) -> None:
    _withdrawn(store, "ecli_nl_rbzwb_2026_1", "ECLI:NL:RBZWB:2026:1", "ecli",
               replaced_by="ECLI:NL:RBZWB:2026:2")  # fmt: skip
    _withdrawn(store, "ecli_nl_rbzwb_2026_3", "ECLI:NL:RBZWB:2026:3", "ecli")
    replaced = _get(client, "/uitspraken/ECLI:NL:RBZWB:2026:1")
    assert_status(replaced, 410)
    main = html.unescape(_head(replaced.text)["main"])
    assert "ECLI vervallen op 15 oktober 2026" in main
    assert 'href="/uitspraken/ECLI:NL:RBZWB:2026:2"' in main
    # no new ECLI named, none made up
    lone = html.unescape(
        _head(_get(client, "/uitspraken/ECLI:NL:RBZWB:2026:3").text)["main"]
    )
    assert "ECLI vervallen" in lone and "vervangen door" not in lone.lower()


def test_a_motion_has_its_submitter_and_the_vote(client: TestClient) -> None:
    page = _head(_get(client, "/kamerstukken/36496/71").text)
    # its number first, its whole subject; the outcome, which a vote changes, in the
    # description alone (the title is the same in the API, which reads no vote)
    assert page["title"] == "Motie 36496-71 Bolhuis over een AI-killswitch, Concordans"
    assert "aangenomen" not in page["title"] and "aangenomen" in page["description"]
    assert "Ingediend door Bolhuis" in page["description"]
    assert "voor: VVD" in page["description"]
    assert "Voor: VVD" in page["main"] and "Tegen: PVV" in page["main"]
    assert 'href="/dossiers/36496"' in page["main"]
    assert "De Kamer, gehoord" in page["main"]  # its text


def test_a_law_by_its_abbreviation_redirects_to_its_bwb_id(client: TestClient) -> None:
    """A law at ``/wetten`` by the abbreviation it is cited by (its WTI short title), a
    book of a code by the code and the book of the number: a 301 to the BWB id; an
    abbreviation of no law is a real 404."""
    for path, location in (
        ("/wetten/sr/artikel/287?lezen=1", "/wetten/BWBR0001854/artikel/287?lezen=1"),
        ("/wetten/Sr", "/wetten/BWBR0001854"),
        ("/wetten/bw/artikel/6:162", "/wetten/BWBR0005289/artikel/6:162"),
    ):
        moved = _get(client, path)
        assert (moved.status_code, moved.headers.get("location")) == (301, location), (
            moved.text
        )
    for path in ("/wetten/xyz/artikel/1", "/wetten/xyz", "/wetten/bw/artikel/162"):
        gone = _get(client, path)
        assert gone.status_code == 404, path
        assert _head(gone.text)["title"] == "Niet gevonden, Concordans"


def test_a_law_at_its_short_address_redirects_to_its_bwb_id(
    client: TestClient,
) -> None:
    """The short address an abbreviation makes (``/sr/287``, ``/bw/6/162``): a 301 to the
    readable address; a page of the app goes first, an abbreviation of no law is 404."""
    for path, location in (
        ("/sr", "/wetten/BWBR0001854"),
        ("/Sr/287?lezen=1", "/wetten/BWBR0001854/artikel/287?lezen=1"),
        ("/bw/6", "/wetten/BWBR0005289"),
        ("/bw/6/162", "/wetten/BWBR0005289/artikel/6:162"),
        ("/bw/6:162", "/wetten/BWBR0005289/artikel/6:162"),
    ):
        moved = _get(client, path)
        assert (moved.status_code, moved.headers.get("location")) == (301, location), (
            path
        )
    assert_status(_get(client, "/actueel"), 200)
    for path in ("/xyz", "/xyz/1", "/bw", "/bw/99/1"):
        assert _get(client, path).status_code == 404, path


def test_a_page_of_the_app_goes_before_the_abbreviation_of_a_law(
    client: TestClient, store: GraphStore
) -> None:
    """Every page of the app (``spa-routes.json``) stays itself where a law has its name
    as abbreviation; an abbreviation two laws share redirects to neither."""
    names = {r["path"].strip("/").split("/")[0] for r in ROUTES} - {""}
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            *(
                _node(f"bwbr009000{i}", "instrument", bwb_id=f"BWBR009000{i}",
                      citation_title=f"Wet {name}", short_title=name.capitalize())
                for i, name in enumerate(sorted(names))
            ),
            *(
                _node(f"bwbr009100{i}", "instrument", bwb_id=f"BWBR009100{i}",
                      citation_title=f"Wet {i}", short_title="Dup")
                for i in range(2)
            ),
        ],
    )  # fmt: skip
    version_cache.clear()
    for route in ROUTES:
        path = route["path"].replace("[id]", "x")
        assert_status(_get(client, path), 200)
    assert_status(_get(client, "/actueel/1"), 301)  # no page of the app: the law
    assert_status(_get(client, "/dup"), 404)


def test_a_dossier_lists_its_papers(client: TestClient) -> None:
    page = _head(_get(client, "/dossiers/36496").text)
    assert page["title"] == "36496 Wet AI-toezicht, Concordans"
    assert "1 stukken" in page["description"]
    assert 'href="/kamerstukken/36496/71"' in page["main"]


def test_another_spelling_and_the_explorer_redirect_to_the_readable_address(
    client: TestClient,
) -> None:
    lower = _get(client, "/uitspraken/ecli:nl:hr:2019:2006?lezen=1")
    assert_status(lower, 301)
    assert lower.headers["location"] == "/uitspraken/ECLI:NL:HR:2019:2006?lezen=1"
    focus = _get(client, "/explore?focus=articles/bwbr0005289_162&lezen=1")
    assert_status(focus, 301)
    assert focus.headers["location"] == "/wetten/BWBR0005289/artikel/6:162?lezen=1"
    # a decision by its key; a node without a readable address stays the explorer
    vote = _get(client, "/explore?focus=decisions/s_1")
    assert (vote.status_code, vote.headers["location"]) == (301, "/stemmingen/s_1"), (
        vote.text
    )
    explorer = _get(client, "/explore?focus=activities/a1")
    assert_status(explorer, 200)
    assert _head(explorer.text)["title"] == "Verkenner, Concordans"


@pytest.mark.parametrize(
    "path",
    ["/uitspraken/ECLI:NL:HR:1900:1", "/wetten/BWBR9999999", "/kamerstukken/36496/999",
     "/stemmingen/s_999",
     "/bestaat/niet", "/wetten/xyz"],
)  # fmt: skip
def test_what_is_not_there_is_not_found(client: TestClient, path: str) -> None:
    response = _get(client, path)
    assert_status(response, 404)
    assert response.headers["cache-control"] == "no-cache"
    page = _head(response.text)
    assert page["title"] == "Niet gevonden, Concordans"
    assert page["robots"] == "noindex"
    assert page["main"] is None


def test_a_page_of_the_app_has_its_own_title(client: TestClient) -> None:
    for path, title in (("/", "Concordans"), ("/actueel", "Actueel, Concordans")):
        response = _get(client, path)
        assert_status(response, 200)
        assert _head(response.text)["title"] == title


def test_a_page_is_asked_again_with_its_etag(client: TestClient) -> None:
    first = _get(client, "/wetten/BWBR0005289")
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"
    again = _get(client, "/wetten/BWBR0005289", **{"If-None-Match": etag})
    assert_status(again, 304)
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "no-cache"


def test_without_the_list_of_pages_every_other_path_is_the_shell(
    client: TestClient, tmp_path: Path
) -> None:
    """Before the front end lists its pages, no path is turned away: the SPA says it."""
    (tmp_path / "spa-routes.json").unlink()
    shell.forget()
    response = _get(client, "/bestaat/niet")
    assert_status(response, 200)
    assert _head(response.text)["main"] is None


def test_a_node_in_the_app_has_the_title_and_address_of_its_page(
    client: TestClient,
) -> None:
    """``title``, ``description`` and ``path`` of ``/api/nodes``: the SPA shows the same
    title when it opens a node, from the same templates, and the server HTML of its page has
    it whole (one source: the tab does not change when the app takes over)."""
    for node, title, path in (
        ("articles/bwbr0005289_162", "Art. 6:162 BW, Onrechtmatige daad",
         "/wetten/BWBR0005289/artikel/6:162"),
        ("documents/kst_36496_71", "Motie 36496-71 Bolhuis over een AI-killswitch",
         "/kamerstukken/36496/71"),
        ("judgments/ecli_nl_hr_2019_2006",
         "HR 20 december 2019 (Urgenda), ECLI:NL:HR:2019:2006",
         "/uitspraken/ECLI:NL:HR:2019:2006"),
        ("dossiers/36496", "36496 Wet AI-toezicht",
         "/dossiers/36496"),
        ("decisions/s_1", "Stemming, 8 september 2026: aangenomen", "/stemmingen/s_1"),
    ):  # fmt: skip
        body = client.get(f"/api/nodes/{node}").json()
        assert (body["title"], body["path"]) == (title, path), node
        assert body["description"]
        assert _head(_get(client, path).text)["title"] == f"{title}, Concordans", node


def test_a_decision_has_its_page(client: TestClient) -> None:
    response = _get(client, "/stemmingen/s_1")
    assert_status(response, 200)
    assert _focus(response.text) == "decisions/s_1"


@pytest.mark.parametrize(
    "focus", ["decisions/nothing", "activities/a1", "geen/collectie", "zonder-slash"]
)
def test_the_explorer_of_a_node_that_is_not_there_is_the_explorer(
    client: TestClient, focus: str
) -> None:
    """No 500: a focus on a node the graph lacks, or on no node at all, is the page of the
    explorer, which says so itself."""
    response = _get(client, f"/explore?focus={focus}")
    assert_status(response, 200)
    assert _head(response.text)["title"] == "Verkenner, Concordans"


def test_a_dossier_with_a_suffix_by_its_label(
    client: TestClient, store: GraphStore
) -> None:
    """The key of a dossier is its label made a key (36600_viii): the page, its address
    and the redirect from the explorer go by the label; its title writes the number as a
    citation does (36600 VIII), here and in the API."""
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("36600_viii", "dossier", label="36600-VIII", number="36600",
               suffix="VIII", title="Begroting Onderwijs")],
    )  # fmt: skip
    page = _head(_get(client, "/dossiers/36600-VIII").text)
    assert page["canonical"] == "https://concordans.nl/dossiers/36600-VIII"
    assert page["title"] == "36600 VIII Begroting Onderwijs, Concordans"
    focus = _get(client, "/explore?focus=dossiers/36600_viii")
    assert focus.headers["location"] == "/dossiers/36600-VIII"
    node = client.get("/api/nodes/dossiers/36600_viii").json()
    assert node["path"] == "/dossiers/36600-VIII"
    assert node["title"] == "36600 VIII Begroting Onderwijs"


def test_a_paper_of_a_dossier_with_a_suffix_links_its_dossier(
    client: TestClient, store: GraphStore
) -> None:
    """A paper of 36600-VIII has its dossier in the breadcrumb and the page, as a paper of a
    dossier of figures alone does."""
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("kst_36600_viii_2", "document", kind="Memorie van toelichting",
               date="2024-09-17", dossier_number="36600", dossier_suffix="VIII",
               dossier_numbers=["36600-VIII"], sequence=2,
               title="Vaststelling van de begrotingsstaten van Onderwijs")],
    )  # fmt: skip
    page = _head(_get(client, "/kamerstukken/36600-VIII/2").text)
    assert page["canonical"] == "https://concordans.nl/kamerstukken/36600-VIII/2"
    assert 'href="/dossiers/36600-VIII"' in page["main"]
    crumbs = next(
        item for item in page["data"]["@graph"] if item["@type"] == "BreadcrumbList"
    )["itemListElement"]
    # after the home of the site, the dossier, then the paper
    assert [c["name"] for c in crumbs][:2] == ["Concordans", "Dossier 36600 VIII"]
    assert crumbs[1]["item"] == "https://concordans.nl/dossiers/36600-VIII"


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
    assert_status(response, 200)
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
    page = _head(_get(client, f"/leden/{slug}").text)
    assert page["title"] == f"{title}, Concordans"
    # a person of the TK's records whose seat the data does not hold: not indexed
    assert page["robots"] == ("noindex" if slug == "j-de-vries" else None)


def test_the_page_of_a_bare_record_of_a_member_is_theirs(
    client: TestClient, store: GraphStore
) -> None:
    """A bare Persoon that is the same person as a member with a role (``semantic
    tk-person-duplicates``): its page is a 301 to theirs."""
    _seed_people(store)
    store.bulk_insert_or_update_nodes(
        "members",
        [
            {
                "key": "m_jetten_ek",
                "type": "member",
                "labels": ["TK"],
                "props": {"name": "Rob Jetten", "slug": "rob-jetten-1987"},
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            {
                "key": "same_as_jetten",
                "from_id": "members/m_jetten_ek",
                "to_id": "members/m_jetten",
                "relation": "SAME_AS",
                "source": "tk-person-duplicates",
            }
        ]
    )
    response = _get(client, "/leden/rob-jetten-1987")
    assert_status(response, 301)
    assert response.headers["location"] == "/leden/rob-jetten"


def test_a_faction_lists_its_members_now(client: TestClient, store: GraphStore) -> None:
    _seed_people(store)
    page = _head(_get(client, "/fracties/d66").text)
    assert page["title"] == "D66, fractie in de Tweede Kamer, Concordans"
    # its name and its years: no seats, nothing that changes with a day of the data
    assert page["description"] == (
        "Democraten 66 (D66), fractie in de Tweede Kamer, actief sinds 30 november 2006"
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
        "Kabinet-Jetten, sinds 23 februari 2026, D66, minister-president Rob Jetten"
    )
    assert 'href="/leden/rob-jetten"' in page["main"]
    assert "Minister-president; Minister van Algemene Zaken" in page["main"]
    assert 'href="/fracties/d66"' in page["main"]
    assert 'href="/kabinetten/schoof"' in page["main"]
    assert page["data"]["@graph"][0]["foundingDate"] == "2026-02-23"
    before = _head(_get(client, "/kabinetten/schoof").text)
    assert before["title"] == "Kabinet-Schoof (2024–2026), Concordans"


def test_a_ministry_has_its_names_and_its_bewindspersonen(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    store.bulk_insert_or_update_nodes(
        "ministries",
        [
            _node("az", "ministry", name="Algemene Zaken", abbreviation="AZ",
                  periods=[{"from_date": None, "to_date": None}]),
            _node("hn", "ministry", name="Handel en Nijverheid", to_date="1946-07-02",
                  successor="ez",
                  periods=[{"from_date": "1945-06-24", "to_date": "1946-07-02"}]),
            _node("ez", "ministry", name="Economische Zaken"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("s2", "members/m_jetten", "ministries/az", "SERVED_IN",
                  posts=[{"function": "Minister van Algemene Zaken"}]),
            _edge("n1", "ministries/ez", "ministries/hn", "CONTINUES"),
        ]
    )  # fmt: skip
    page = _head(_get(client, "/ministeries/az").text)
    assert page["title"] == "Ministerie van Algemene Zaken, Concordans"
    assert 'href="/leden/rob-jetten"' in page["main"]
    assert "Minister van Algemene Zaken" in page["main"]
    assert page["data"]["@graph"][0]["@type"] == "GovernmentOrganization"
    former = _head(_get(client, "/ministeries/hn").text)
    assert (
        former["title"] == "Ministerie van Handel en Nijverheid (tot 1946), Concordans"
    )
    assert 'href="/ministeries/ez"' in former["main"]  # what followed it
    assert (
        'href="/ministeries/hn"' in _head(_get(client, "/ministeries/ez").text)["main"]
    )
    assert_status(_get(client, "/ministeries/nope"), 404)


def test_a_committee_lists_its_members_with_their_role(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    page = _head(_get(client, "/commissies/szw").text)
    assert page["title"] == (
        "Vaste commissie voor Sociale Zaken en Werkgelegenheid (SZW), Concordans"
    )
    assert "Tweede Kamer" in page["description"]
    assert "actief sinds 17 juni 2010" in page["description"]
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
    assert_status(_get(client, path), 404)


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
        [
            _node(
                "sr_288_oud",
                "article",
                bwb_id="BWBR0001854",
                article_number="288",
                instrument_citation_title="Wetboek van Strafrecht",
                instrument_abbreviation="Sr",
            )
        ],  # fmt: skip
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("am1", "instruments/stb_2025_263", "articles/bwbr0005289_162",
                  "AMENDS"),
            _edge("am2", "instruments/stb_2025_263", "articles/sr_288_oud", "REPEALS"),
            _edge("ab1", "commitments/tz_1", "dossiers/36496", "ABOUT", basis="nakoming"),
            _edge("an1", "documents/kst_36496_80", "commitments/tz_1", "ANSWERS"),
        ]
    )  # fmt: skip


def test_a_publication_has_its_title_and_what_it_changes(
    client: TestClient, store: GraphStore
) -> None:
    _seed_publications(store)
    response = _get(client, "/stb/2025/263")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == (
        "Stb. 2025, 263: Besluit tot wijziging van het Mediabesluit 2008, Concordans"
    )
    assert "gepubliceerd 2 september 2025" in page["description"]
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


def test_the_publication_that_enacted_a_law_establishes_it(
    client: TestClient, store: GraphStore
) -> None:
    """Stb. 2026, 187 enacted the Cyberbeveiligingswet: it sets the law's articles
    (``ESTABLISHES``) and changes another law in the same act."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("stb_2026_187", "instrument", kind="publicatie",
               citation_title="Stb. 2026, 187", official_id="stb-2026-187",
               publication_kind="Stb", publication_year=2026, publication_number=187,
               date_published="2026-07-20"),
         _node("bwbr0052872", "instrument", bwb_id="BWBR0052872",
               citation_title="Cyberbeveiligingswet"),
         _node("bwbr0009950", "instrument", bwb_id="BWBR0009950",
               citation_title="Telecommunicatiewet")],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [_edge("e1", "instruments/stb_2026_187", "articles/bwbr0052872_1", "ESTABLISHES"),
         _edge("e2", "instruments/stb_2026_187", "articles/bwbr0009950_7", "AMENDS")]
    )  # fmt: skip
    page = _head(_get(client, "/stb/2026/187").text)
    assert page["robots"] is None
    assert 'href="/wetten/BWBR0052872"' in page["main"]
    assert "(stelt vast)" in page["main"]
    assert "(wijzigt)" in page["main"]


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
    # the letter without its text: named, not linked (its page is not indexed)
    assert 'href="/kamerstukken/36496/80"' not in page["main"]
    assert "Nakoming van de toezegging over AI-toezicht" in page["main"]
    assert "Openstaand" in page["main"]
    assert "Verwachte afdoening" not in page["main"]  # 0001-01-01: none named
    assert page["data"]["@graph"][0]["identifier"] == "TZ202609-124"
    assert "<h2>Dossiers</h2>" in page["main"]
    # one no letter fulfils is about the agenda of its debate: discussed there
    store.bulk_insert_or_update_edges(
        [_edge("ab1", "commitments/tz_1", "dossiers/36496", "ABOUT", basis="agenda")]
    )
    agenda = _head(_get(client, "/toezeggingen/TZ202609-124").text)["main"]
    assert "<h2>Besproken in het debat over</h2>" in agenda
    assert "<h2>Dossiers</h2>" not in agenda


def test_a_vote_on_one_motion_is_found_on_the_page_of_the_motion(
    client: TestClient,
) -> None:
    """Its page is indexed with the page of the motion as its canonical address: the vote is
    there too (Thijs, 16 Oct)."""
    response = _get(client, "/stemmingen/s_1")
    page = _head(response.text)
    assert page["title"] == "Stemming, 8 september 2026: aangenomen, Concordans"
    assert page["description"].endswith("voor: VVD; tegen: PVV")
    assert page["canonical"] == "https://concordans.nl/kamerstukken/36496/71"
    assert page["robots"] is None
    assert 'href="/kamerstukken/36496/71"' in page["main"]
    assert "Voor: VVD" in page["main"] and "Tegen: PVV" in page["main"]
    graph = page["data"]["@graph"]
    assert (
        graph[1]["itemListElement"][-1]["item"]
        == "https://concordans.nl/stemmingen/s_1"
    )


def test_a_vote_on_several_papers_or_on_no_motion_is_not_indexed(
    client: TestClient, store: GraphStore
) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36496_72", "document", kind="Motie", date="2026-09-01",
                  dossier_number="36496", sequence=72,
                  subject="Motie van het lid Bolhuis over een register"),
            _node("kst_36496_2", "document", kind="Voorstel van wet", date="2025-09-01",
                  dossier_number="36496", sequence=2,
                  subject="Regels over kunstmatige intelligentie"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases",
        [_node("z_72", "case"), _node("z_w", "case", kind="Wetgeving")],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [_node("s_2", "decision", date="2026-09-08", passed=False),
         _node("s_w", "decision", date="2026-09-15", passed=True)],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("p72", "documents/kst_36496_72", "cases/z_72", "PART_OF"),
            _edge("a2a", "decisions/s_2", "cases/z_1", "ABOUT"),
            _edge("a2b", "decisions/s_2", "cases/z_72", "ABOUT"),
            _edge("pw", "documents/kst_36496_2", "cases/z_w", "PART_OF"),
            _edge("aw", "decisions/s_w", "cases/z_w", "ABOUT"),
        ]
    )
    for key in ("s_2", "s_w"):
        page = _head(_get(client, f"/stemmingen/{key}").text)
        assert page["canonical"] == f"https://concordans.nl/stemmingen/{key}", key
        assert page["robots"] == "noindex", key


def test_what_a_publication_changes_reads_no_article_keyed_by_its_law(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
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
    seen = recorded(store, monkeypatch, "_stream")
    laws = seo._changed(store, ["instruments/stb_2026_94"])
    assert [(law["name"], law["relations"]) for law in laws] == [
        ("Burgerlijk Wetboek Boek 6", ["AMENDS"])
    ]
    ((statement, params, *_),) = seen
    plan = explain(store, statement, params, analyze=True)
    ran = [
        (node["Node Type"], node.get("Actual Loops", 0))
        for node in plan_nodes(plan)
        if node.get("Relation Name") == "articles"
    ]
    assert all(loops == 0 for _, loops in ran), ran


def test_a_page_of_the_app_may_keep_out_of_the_index(client: TestClient) -> None:
    """``"index": false`` in ``spa-routes.json``: the page with its title, ``noindex``."""
    own = _head(_get(client, "/bundels").text)
    assert own["title"] == "Bundels, Concordans"
    assert own["robots"] == "noindex"
    # the others as ever
    assert _head(_get(client, "/actueel").text)["robots"] is None


def test_a_page_of_the_app_by_a_pattern_takes_any_one_segment(
    client: TestClient,
) -> None:
    """``/bundels/[id]`` in ``spa-routes.json``: ``/bundels/<id>`` is that page at its own
    address; a path of more segments is not."""
    response = _get(client, "/bundels/m-1a2b")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == "Bundel, Concordans"
    assert page["robots"] == "noindex"
    assert page["canonical"] == "https://concordans.nl/bundels/m-1a2b"
    assert_status(_get(client, "/bundels/m-1a2b/meer"), 404)


def test_the_addresses_of_the_bundels_before_move_with_the_app(
    client: TestClient, tmp_path: Path
) -> None:
    """``/gemarkeerd`` is ``/bundels`` now and ``/gemarkeerd/bundel?id=<id>`` the page of
    the bundel (the fragment of a shared link stays in the browser), once the front end
    lists the new pages and no longer the old one."""
    moved = {
        "/gemarkeerd": "/bundels",
        "/gemarkeerd/": "/bundels",
        "/gemarkeerd?lezen=1": "/bundels?lezen=1",
        "/gemarkeerd/bundel?id=m-1a2b": "/bundels/m-1a2b",
        "/gemarkeerd/bundel?id=a%2Fb": "/bundels/a%2Fb",
        "/gemarkeerd/bundel": "/bundels",
    }
    for old, new in moved.items():
        response = _get(client, old)
        assert response.status_code == 301, old
        assert response.headers["location"] == new
    # a front end of before, with its page at /gemarkeerd: that stays its page
    (tmp_path / "spa-routes.json").write_text(
        json.dumps(
            [
                {"path": "/"},
                {"path": "/gemarkeerd", "title": "Gemarkeerd, Concordans",
                 "index": False},
            ]
        )
    )  # fmt: skip
    shell.forget()
    response = _get(client, "/gemarkeerd")
    assert_status(response, 200)
    assert _head(response.text)["title"] == "Gemarkeerd, Concordans"
    assert_status(_get(client, "/gemarkeerd/bundel?id=m-1a2b"), 404)


def test_a_bare_collection_moves_where_the_front_end_says(
    client: TestClient, tmp_path: Path
) -> None:
    """``moved.json`` beside the shell: ``/wetten`` (no source of its own) is the list of
    the laws in the app, ``/zoeken`` the field on the start page, each a 301 with the query
    after its own (B17). A front end of before, without the file: a 404 as before."""
    assert_status(_get(client, "/wetten"), 404)
    (tmp_path / "moved.json").write_text(
        json.dumps(
            {
                "/wetten": "/explore?mode=index&kind=instruments",
                "/zoeken": "/#zoeken",
                "/elders": "https://elders.example",
            }
        )
    )
    shell.forget()
    for old, new in {
        "/wetten": "/explore?mode=index&kind=instruments",
        "/wetten/": "/explore?mode=index&kind=instruments",
        "/wetten?q=huur": "/explore?mode=index&kind=instruments&q=huur",
        "/zoeken": "/#zoeken",
        "/zoeken?q=huur": "/?q=huur#zoeken",
    }.items():
        response = _get(client, old)
        assert response.status_code == 301, old
        assert response.headers["location"] == new, old
    # never off the site; a source keeps its own address
    assert_status(_get(client, "/elders"), 404)
    assert_status(_get(client, "/wetten/BWBR0005289/artikel/6:162"), 200)


def _focus(html: str) -> str | None:
    m = re.search(r'<meta name="focus" content="([^"]*)" data-seo />', html)
    return m[1] if m else None


def test_every_page_of_a_node_names_it_and_no_other_page_does(
    client: TestClient,
) -> None:
    """``<meta name="focus">``: the node of the page, which the app opens without a lookup
    (a 301 from ``/explore?focus=`` drops it); a page of the app and a 404 have none."""
    for path, node in (
        ("/wetten/BWBR0005289/artikel/6:162", "articles/bwbr0005289_162"),
        ("/uitspraken/ECLI:NL:HR:2019:2006", "judgments/ecli_nl_hr_2019_2006"),
        ("/stemmingen/s_1", "decisions/s_1"),
    ):
        assert _focus(_get(client, path).text) == node, path
    assert _focus(_get(client, "/actueel").text) is None
    assert _focus(_get(client, "/bestaat/niet").text) is None


def _seed_annex_and_case(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("bwbr0001941", "instrument", bwb_id="BWBR0001941",
               citation_title="Opiumwet", kind="wet")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "annexes",
        [
            _node("bwbr0001941_annex_ii", "annex", bwb_id="BWBR0001941", label="II",
                  title="Lijst II", instrument_citation_title="Opiumwet",
                  description="Middelen als bedoeld in artikel 3",
                  entries=[{"index": 1, "name": "Cannabis", "description": "hennep"}]),
            _node("bwbr0001941_annex_iii", "annex", bwb_id="BWBR0001941",
                  label="III", stub=True, instrument_citation_title="Opiumwet"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            _node("z_2", "case", number="2025Z15468", kind="Wetgeving",
                  title="Regels over kunstmatige intelligentie", started_on="2025-08-01",
                  dossier_numbers=["36496"]),
            _node("z_3", "case", number="2025Z15469", kind="Motie",
                  title="Motie van het lid Bolhuis over een AI-killswitch"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("p2", "documents/kst_36496_71", "cases/z_2", "PART_OF"),
            _edge("a2", "decisions/s_1", "cases/z_2", "ABOUT"),
        ]
    )


def test_a_treaty_its_article_and_annex_have_their_pages(
    client: TestClient, store: GraphStore
) -> None:
    """A treaty of the BWB (``BWBV``) is a law at ``/wetten`` as one of its regulations
    is: its page, its article's and its annex's are a 200, another spelling a 301 to
    them, never a 301 to the same address (a loop)."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("bwbv0007162", "instrument", bwb_id="BWBV0007162", kind="verdrag",
               citation_title="Verdrag inzake de rechten van het kind")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [_node("bwbv0007162_15", "article", bwb_id="BWBV0007162", article_number="15",
               position=15, text="De Staten die partij zijn …",
               instrument_citation_title="Verdrag inzake de rechten van het kind")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "annexes",
        [_node("bwbv0007162_annex_i", "annex", bwb_id="BWBV0007162", label="I",
               title="Bijlage I",
               instrument_citation_title="Verdrag inzake de rechten van het kind")],
    )  # fmt: skip
    for path in (
        "/wetten/BWBV0007162",
        "/wetten/BWBV0007162/artikel/15",
        "/wetten/BWBV0007162/bijlage/I",
    ):
        assert_status(_get(client, path), 200)
        lower = _get(client, path.lower())
        assert (lower.status_code, lower.headers.get("location")) == (301, path), (
            lower.text
        )


def test_an_annex_has_its_law_and_entries(
    client: TestClient, store: GraphStore
) -> None:
    _seed_annex_and_case(store)
    response = _get(client, "/wetten/BWBR0001941/bijlage/II")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == "Bijlage II Opiumwet: lijst II, Concordans"
    assert page["description"] == "Middelen als bedoeld in artikel 3"
    assert page["canonical"] == "https://concordans.nl/wetten/BWBR0001941/bijlage/II"
    assert page["robots"] is None
    assert page["og_image"] == "https://concordans.nl/og/wet.png"
    assert 'href="/wetten/BWBR0001941"' in page["main"]
    assert "Cannabis" in page["main"] and "hennep" in page["main"]
    graph = page["data"]["@graph"]
    assert graph[0]["@type"] == "Legislation"
    assert graph[0]["legislationIdentifier"] == "BWBR0001941 bijlage II"
    assert graph[0]["isPartOf"]["legislationIdentifier"] == "BWBR0001941"
    assert [i["name"] for i in graph[1]["itemListElement"]] == [
        "Concordans",
        "Opiumwet",
        "Bijlage II Opiumwet: lijst II",
    ]
    assert _focus(response.text) == "annexes/bwbr0001941_annex_ii"
    # another spelling, and the explorer of the annex, to its readable address
    lower = _get(client, "/wetten/bwbr0001941/bijlage/ii")
    assert (lower.status_code, lower.headers["location"]) == (
        301,
        "/wetten/BWBR0001941/bijlage/II",
    ), lower.text
    focus = _get(client, "/explore?focus=annexes/bwbr0001941_annex_ii")
    assert focus.headers["location"] == "/wetten/BWBR0001941/bijlage/II"
    # an annex only cited (a stub) has nothing to read: not indexed
    stub = _head(_get(client, "/wetten/BWBR0001941/bijlage/III").text)
    assert stub["robots"] == "noindex"
    assert_status(_get(client, "/wetten/BWBR0001941/bijlage/IX"), 404)


def test_a_zaak_has_its_dossier_papers_and_votes(
    client: TestClient, store: GraphStore
) -> None:
    _seed_annex_and_case(store)
    response = _get(client, "/zaken/2025Z15468")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == (
        "Regels over kunstmatige intelligentie (2025Z15468), Concordans"
    )
    assert "gestart 1 augustus 2025" in page["description"]
    assert "dossier 36496" in page["description"]
    assert "aangenomen" in page["description"]
    assert page["canonical"] == "https://concordans.nl/zaken/2025Z15468"
    assert page["robots"] is None
    assert 'href="/dossiers/36496"' in page["main"]
    assert 'href="/kamerstukken/36496/71"' in page["main"]
    assert 'href="/stemmingen/s_1"' in page["main"]
    graph = page["data"]["@graph"]
    assert graph[0]["@type"] == "CreativeWork"
    assert graph[0]["identifier"] == "2025Z15468"
    crumbs = graph[1]["itemListElement"]
    assert [i["name"] for i in crumbs] == [
        "Concordans",
        "Dossier 36496",
        "Regels over kunstmatige intelligentie (2025Z15468)",
    ]
    assert crumbs[1]["item"] == "https://concordans.nl/dossiers/36496"
    assert _focus(response.text) == "cases/z_2"
    lower = _get(client, "/zaken/2025z15468")
    assert (lower.status_code, lower.headers["location"]) == (
        301,
        "/zaken/2025Z15468",
    ), lower.text
    focus = _get(client, "/explore?focus=cases/z_2&lezen=1")
    assert focus.headers["location"] == "/zaken/2025Z15468?lezen=1"
    # a motion: its paper is the page to find; without a dossier, no crumb to one
    motion = _head(_get(client, "/zaken/2025Z15469").text)
    assert motion["title"].startswith(
        "Motie Bolhuis over een AI-killswitch (2025Z15469)"
    )
    assert motion["robots"] == "noindex"
    assert len(motion["data"]["@graph"][1]["itemListElement"]) == 2
    assert_status(_get(client, "/zaken/2025Z99999"), 404)


@pytest.mark.parametrize(
    ("path", "focus", "title"),
    [
        ("/zaken/2025Z15468", "cases/",
         "Regels over kunstmatige intelligentie (2025Z15468), Concordans"),
        # of an annex the name of its law its props hold
        ("/wetten/BWBR0001941/bijlage/II", "annexes/bwbr0001941_annex_ii",
         "Bijlage II Opiumwet: lijst II, Concordans"),
    ],
)  # fmt: skip
def test_a_page_whose_reads_take_too_long_keeps_its_title(
    client: TestClient,
    store: GraphStore,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    focus: str,
    title: str,
) -> None:
    """Past the render budget (a zaak with many votes, cold on prod: 10 Oct) the page is not
    the shell titled "Concordans": its own title and description from its node, its node
    as focus, without its content, as a 503 with ``Retry-After`` (never a 200 with an
    empty ``<main>``: a soft 404) and not kept (the next request may have it whole)."""
    from lawgraph.db.request_context import ReadTimedOut

    _seed_annex_and_case(store)

    def slow(*args: Any, **kwargs: Any) -> Any:
        raise ReadTimedOut("past the budget")

    monkeypatch.setattr(render, "_source_page", slow)
    response = _get(client, path)
    assert_status(response, 503)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["retry-after"] == render.LATE_RETRY_AFTER
    assert response.headers[render.LATE_HEADER] == "1"
    page = _head(response.text)
    assert page["title"] == title
    assert page["description"]
    assert page["main"] is None
    assert f'<meta name="focus" content="{focus}' in response.text


def _seed_debate(store: GraphStore) -> None:
    """A wetgevingsoverleg with its verslag, a motion submitted in it and a commitment made
    in it, led by a committee; and the vote of another day, with nothing made in it."""
    store.bulk_insert_or_update_nodes(
        "activities",
        [
            _node("wgo_1", "activity", number="2026A01323", kind="Wetgevingsoverleg",
                  date="2026-03-23", status="Uitgevoerd",
                  agenda_title="Cyberbeveiligingswet (36764)",
                  dossier_numbers=["36764", "36765"]),
            _node("stem_1", "activity", number="2026A01400", kind="Stemmingen",
                  date="2026-03-24", status="Uitgevoerd", agenda_title="Stemmingen"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "committees",
        [_node("jenv", "committee", name="Justitie en Veiligheid", slug="jenv")],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36764_32", "document", kind="Verslag van een wetgevingsoverleg",
                  dossier_number="36764", sequence=32, date="2026-04-20",
                  title="Verslag van een wetgevingsoverleg"),
            _node("kst_36764_28", "document", kind="Motie", dossier_number="36764",
                  sequence=28, date="2026-03-23",
                  title="Motie van het lid Kathmann over de vitaalbeoordeling"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "commitments",
        [_node("tz_64", "commitment", number="TZ202604-064",
               text="De minister zegt toe de samenwerkingsafspraken te delen.",
               made_on="2026-04-10", minister_name="D.M. van Weel",
               status="Afgedaan")],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("l1", "activities/wgo_1", "committees/jenv", "LED_BY"),
            _edge("m1", "documents/kst_36764_32", "activities/wgo_1", "MADE_IN"),
            _edge("m2", "documents/kst_36764_28", "activities/wgo_1", "MADE_IN",
                  reason="ingediend"),
            _edge("m3", "commitments/tz_64", "activities/wgo_1", "MADE_IN"),
        ]
    )  # fmt: skip


def test_a_debate_has_its_page_with_what_was_made_in_it(
    client: TestClient, store: GraphStore
) -> None:
    _seed_debate(store)
    response = _get(client, "/activiteiten/2026A01323")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == (
        "Wetgevingsoverleg van 23 maart 2026: Cyberbeveiligingswet (36764), Concordans"
    )
    assert page["canonical"] == "https://concordans.nl/activiteiten/2026A01323"
    assert page["robots"] is None
    assert 'href="/commissies/jenv"' in page["main"]
    assert (
        'href="/dossiers/36764"' in page["main"]
        and 'href="/dossiers/36765"' in (page["main"])
    )
    # its verslag and motion without a text: named, not linked (their pages not indexed)
    assert "/kamerstukken/36764/32" not in page["main"]
    assert "/kamerstukken/36764/28" not in page["main"]
    assert "Verslag van een wetgevingsoverleg" in page["main"]
    assert "Kathmann over de vitaalbeoordeling" in page["main"]
    assert 'href="/toezeggingen/TZ202604-064"' in page["main"]
    assert page["data"]["@graph"][0]["@type"] == "Event"
    assert page["data"]["@graph"][0]["startDate"] == "2026-03-23"
    assert _focus(response.text) == "activities/wgo_1"
    lower = _get(client, "/activiteiten/2026a01323")
    assert (lower.status_code, lower.headers["location"]) == (
        301,
        "/activiteiten/2026A01323",
    ), lower.text
    focus = _get(client, "/explore?focus=activities/wgo_1")
    assert focus.headers["location"] == "/activiteiten/2026A01323"
    # a vote with nothing made in it has nothing to read
    assert _head(_get(client, "/activiteiten/2026A01400").text)["robots"] == "noindex"
    assert_status(_get(client, "/activiteiten/2026A09999"), 404)
    # the commitment says in which debate it was made, and when the Kamer registered it
    commitment = _head(_get(client, "/toezeggingen/TZ202604-064").text)
    assert (
        'Toegezegd in het <a href="/activiteiten/2026A01323">wetgevingsoverleg van '
        "23 maart 2026</a>" in commitment["main"]
    )
    assert "Geregistreerd op 10 april 2026" in commitment["main"]
    assert commitment["data"]["@graph"][0]["dateCreated"] == "2026-03-23"


def _seed_eu(store: GraphStore) -> None:
    title = (
        "Richtlijn (EU) 2022/2555 van het Europees Parlement en de Raad van 14 december "
        "2022 betreffende maatregelen voor een hoog gezamenlijk niveau van "
        "cyberbeveiliging in de Unie (NIS 2-richtlijn)"
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("32022l2555", "instrument", celex="32022L2555", jurisdiction="eu",
                  citation_title="Richtlijn (EU) 2022/2555",
                  display_name="Richtlijn (EU) 2022/2555", title=title),
            # an act whose text was not read: its title alone
            _node("32019r0881", "instrument", celex="32019R0881", jurisdiction="eu",
                  citation_title="Verordening (EU) 2019/881",
                  display_name="Verordening (EU) 2019/881"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("32022l2555_21", "article", celex="32022L2555", article_number="21",
                  heading="Maatregelen voor het beheer van cyberbeveiligingsrisico's",
                  position=21, text="1. De lidstaten zorgen ervoor dat …"),
            _node("32022l2555_2", "article", celex="32022L2555", article_number="2",
                  heading="Toepassingsgebied", position=2, text="1. Deze richtlijn …"),
        ],
    )  # fmt: skip


def test_an_eu_act_by_its_celex_number_lists_its_articles(
    client: TestClient, store: GraphStore
) -> None:
    _seed_eu(store)
    response = _get(client, "/wetten/32022L2555")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == "Richtlijn (EU) 2022/2555, Concordans"
    assert page["description"].startswith("Richtlijn (EU) 2022/2555 van het Europees")
    assert page["canonical"] == "https://concordans.nl/wetten/32022L2555"
    assert page["robots"] is None
    assert page["og_image"] == "https://concordans.nl/og/wet.png"
    main = page["main"]
    # its articles in their order, at the address they already had
    assert main.index('href="/wetten/32022L2555/artikel/2"') < main.index(
        'href="/wetten/32022L2555/artikel/21"'
    )
    assert "Artikel 21 Richtlijn (EU) 2022/2555" in main
    assert "eur-lex.europa.eu" in main and "CELEX:32022L2555" in main
    law = page["data"]["@graph"][0]
    assert law["legislationIdentifier"] == "32022L2555"
    assert law["legislationJurisdiction"] == "EU"
    assert _focus(response.text) == "instruments/32022l2555"
    # another spelling, and the explorer of the act, to its readable address
    lower = _get(client, "/wetten/32022l2555")
    assert (lower.status_code, lower.headers["location"]) == (
        301,
        "/wetten/32022L2555",
    ), lower.text
    focus = _get(client, "/explore?focus=instruments/32022l2555")
    assert (focus.status_code, focus.headers["location"]) == (
        301,
        "/wetten/32022L2555",
    ), focus.text
    # an act whose text was not read has no content of its own: not indexed
    bare = _get(client, "/wetten/32019R0881")
    assert_status(bare, 200)
    assert _head(bare.text)["robots"] == "noindex"
    assert_status(_get(client, "/wetten/32099L9999"), 404)


def test_an_article_of_an_eu_act_links_its_act(
    client: TestClient, store: GraphStore
) -> None:
    _seed_eu(store)
    page = _head(_get(client, "/wetten/32022L2555/artikel/21").text)
    assert page["title"].startswith("Art. 21 Richtlijn (EU) 2022/2555, Maatregelen")
    assert 'href="/wetten/32022L2555"' in page["main"]
    article = page["data"]["@graph"][0]
    assert article["legislationIdentifier"] == "32022L2555 Artikel 21"
    assert article["legislationJurisdiction"] == "EU"
    assert article["isPartOf"]["legislationIdentifier"] == "32022L2555"


def test_the_image_of_a_page_is_that_of_its_kind(
    client: TestClient, store: GraphStore
) -> None:
    _seed_people(store)
    _seed_annex_and_case(store)
    _seed_debate(store)
    images = {
        "/wetten/BWBR0005289": "wet",
        "/wetten/BWBR0005289/artikel/6:162": "artikel",
        "/uitspraken/ECLI:NL:HR:2019:2006": "uitspraak",
        "/kamerstukken/36496/71": "kamerstuk",
        "/dossiers/36496": "dossier",
        "/wetten/BWBR0001941/bijlage/II": "wet",
        "/zaken/2025Z15468": "dossier",
        "/activiteiten/2026A01323": "dossier",
        "/leden/rob-jetten": "bewindspersoon",
        "/leden/jan-paternotte": "lid",
        "/stemmingen/s_1": "stemming",
        "/kabinetten/jetten": "kabinet",
    }
    for path, image in images.items():
        page = _head(_get(client, path).text)
        assert page["og_image"] == f"https://concordans.nl/og/{image}.png", path


def _all_node_ids(store: GraphStore) -> list[str]:
    return sorted(store.query("SELECT id FROM nodes"))


def test_a_node_has_one_title_in_the_api_its_neighbours_and_its_page(
    client: TestClient, store: GraphStore
) -> None:
    """``title`` of every node: of the node itself (``node.title`` and ``title`` of
    ``/api/nodes``), of it as a neighbour of every other node, and the ``<title>`` of its
    page are one, from ``core.names.title_of`` (the explorer shows it in its tab)."""
    _seed_people(store)
    _seed_publications(store)
    _seed_annex_and_case(store)
    version_cache.clear()
    titles: dict[str, str] = {}
    bodies: dict[str, Any] = {}
    for node in _all_node_ids(store):
        body = bodies[node] = client.get(f"/api/nodes/{node}").json()
        assert body["node"]["title"] == body["title"], node
        titles[node] = body["title"]
        page = _get(client, body["path"]) if body["path"] else None
        if page is not None and page.status_code == 200:
            title = html.unescape(_head(page.text)["title"])
            assert title == f"{body['title']}, Concordans", node
    as_neighbour = {
        (item["id"], item["title"])
        for body in bodies.values()
        for bucket in body["neighbors"]["buckets"]
        for item in bucket["items"]
    }
    # and as a node of a neighbourhood
    as_neighbour |= {
        (item["id"], item["title"])
        for node in titles
        for item in client.get(f"/api/nodes/{node}/neighborhood").json()["nodes"]
    }
    assert as_neighbour
    assert {
        (node, title) for node, title in as_neighbour if title != titles[node]
    } == set()


def test_a_judgment_is_cited_alike_as_a_node_a_neighbour_and_in_its_detail(
    client: TestClient, store: GraphStore
) -> None:
    """``cite`` of a judgment, and P-G for a conclusion a procureur-generaal signed (its
    ``advocate_general_role``), in its title too."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node("ecli_nl_phr_2019_887", "judgment", ecli="ECLI:NL:PHR:2019:887",
               court="Parket bij de Hoge Raad", court_code="PHR", date="2019-09-13",
               advocate_general="F.F. Langemeijer",
               advocate_general_role="plaatsvervangend procureur-generaal")],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [_edge("r2", "judgments/ecli_nl_phr_2019_887", "articles/bwbr0005289_162",
               "REFERS_TO")]
    )  # fmt: skip
    hr = "HR 20 december 2019"
    pg = "Conclusie P-G Langemeijer 13 september 2019"
    cites = {
        "judgments/ecli_nl_hr_2019_2006": {
            "short": hr,
            "full": f"{hr}, ECLI:NL:HR:2019:2006",
        },
        "judgments/ecli_nl_phr_2019_887": {
            "short": pg,
            "full": f"{pg}, ECLI:NL:PHR:2019:887",
        },
    }
    neighbours = client.get("/api/nodes/articles/bwbr0005289_162").json()["neighbors"]
    assert {
        item["id"]: item["cite"]
        for bucket in neighbours["buckets"]
        for item in bucket["items"]
        if item["collection"] == "judgments"
    } == cites
    for node, cite in cites.items():
        body = client.get(f"/api/nodes/{node}").json()
        assert body["node"]["cite"] == cite
        ecli = cite["full"].rsplit(", ", 1)[1]
        assert client.get(f"/api/judgments/{ecli}").json()["judgment"]["cite"] == cite
    assert (
        client.get("/api/nodes/judgments/ecli_nl_phr_2019_887").json()["title"]
        == f"{pg}, ECLI:NL:PHR:2019:887"
    )
    # a node of another collection has none
    assert "cite" not in client.get("/api/nodes/dossiers/36496").json()["node"]


def test_a_judgment_as_a_neighbour_has_its_tier_and_source(
    client: TestClient, store: GraphStore
) -> None:
    """Its ``tier`` by its court code, of code XX by the court it names (one of the
    Rechtspraak of the Court of Justice), and its ``source`` by its ECLI: what the explorer
    splits HvJ EU and EHRM from Dutch judgments by."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [_node("ecli_nl_xx_2004_ar1234", "judgment", ecli="ECLI:NL:XX:2004:AR1234",
               court="Hof van Justitie van de Europese Unie", date="2004-01-01"),
         _node("ecli_ce_echr_2020_0101jud000100018", "judgment",
               ecli="ECLI:CE:ECHR:2020:0101JUD000100018", source="echr",
               date="2020-01-01")],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [_edge(f"t{n}", f"judgments/{key}", "articles/bwbr0005289_162", "REFERS_TO")
         for n, key in enumerate(("ecli_nl_xx_2004_ar1234",
                                  "ecli_ce_echr_2020_0101jud000100018"))]
    )  # fmt: skip
    neighbours = client.get("/api/nodes/articles/bwbr0005289_162").json()["neighbors"]
    assert {
        item["id"]: (item["props"].get("tier"), item["props"].get("source"))
        for bucket in neighbours["buckets"]
        for item in bucket["items"]
        if item["collection"] == "judgments"
    } == {
        "judgments/ecli_nl_hr_2019_2006": ("hoge_raad", "rechtspraak"),
        "judgments/ecli_nl_xx_2004_ar1234": ("hvj_eu", "rechtspraak"),
        "judgments/ecli_ce_echr_2020_0101jud000100018": ("ehrm", "echr"),
    }


# ── the text of a source and the sources it links (Search Console, 16 Oct: thin pages) ──

_CONSIDERATION = (
    "Appellante ontving tot de dag waarop haar jongste kind achttien jaar werd een "
    "nabestaandenuitkering op grond van de Algemene nabestaandenwet. "
)


def _seed_texts(store: GraphStore) -> None:
    """A judgment of the CRvB with its paragraphs, one that cites it, its earlier instance
    and a stub that cites it; an article before 6:162 BW and one that refers to it; a
    memorie van toelichting with its text and sections that explains 6:162, signed by a
    minister."""
    paragraphs = [
        {"id": "p-1a2b3c4d", "kind": "subheading",
         "text": "15/2587 ANW\n\nDatum uitspraak: 3 mei 2018"},
        {"id": "p-toc", "kind": "toc", "text": "Inhoudsopgave van de uitspraak"},
        {"id": "kop-procesverloop", "kind": "heading", "text": "PROCESVERLOOP"},
        {"id": "p-5e6f7a8b", "kind": "body",
         "text": "Namens appellante heeft mr. C.A.J. de Rooij hoger beroep ingesteld."},
        {"id": "kop-overwegingen", "kind": "heading", "text": "OVERWEGINGEN"},
        *({"id": f"rov-1.{n}", "number": f"1.{n}", "kind": "body",
           "text": _CONSIDERATION * 3} for n in range(1, 9)),
        {"id": "kop-beslissing", "kind": "heading", "text": "BESLISSING"},
        {"id": "p-9c0d1e2f", "kind": "body",
         "text": "De Centrale Raad van Beroep bevestigt de aangevallen uitspraak."},
    ]  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("ecli_nl_crvb_2018_1335", "judgment", ecli="ECLI:NL:CRVB:2018:1335",
                  court="Centrale Raad van Beroep", court_code="CRVB",
                  date="2018-05-03", date_eff="2018-05-03",
                  summary="Nabestaandenuitkering. Geen schending van artikel 14 EVRM.",
                  paragraphs=paragraphs,
                  text="\n\n".join(p["text"] for p in paragraphs)),
            _node("ecli_nl_crvb_2018_4314", "judgment", ecli="ECLI:NL:CRVB:2018:4314",
                  court="Centrale Raad van Beroep", court_code="CRVB",
                  date="2018-12-18", date_eff="2018-12-18", text="…"),
            _node("ecli_nl_rbams_2015_1", "judgment", ecli="ECLI:NL:RBAMS:2015:1",
                  court="Rechtbank Amsterdam", court_code="RBAMS",
                  date="2015-06-01", date_eff="2015-06-01", text="…"),
            _node("ecli_nl_crvb_2019_9", "judgment", ecli="ECLI:NL:CRVB:2019:9",
                  court="Centrale Raad van Beroep", court_code="CRVB", stub=True),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr0005289_161", "article", bwb_id="BWBR0005289",
                  article_number="161", position=161, text="Een eerder artikel."),
            # in its law, without a text: no page to link
            _node("bwbr0005289_161a", "article", bwb_id="BWBR0005289",
                  article_number="161a", position=161.5),
        ],
    )  # fmt: skip
    text_lines = [
        "ALGEMEEN",
        "Dit wetsvoorstel regelt het toezicht op kunstmatige intelligentie. " * 8,
        "ARTIKELSGEWIJS",
        "Artikel 1",
        "In dit artikel worden de begrippen van de wet omschreven. " * 8,
    ]
    text = "\n".join(text_lines)
    starts = [text.index(line) for line in text_lines]
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("kst_36496_70", "document", kind="Memorie van toelichting",
               date="2025-09-01", dossier_number="36496", dossier_numbers=["36496"],
               sequence=70, title="Regels over kunstmatige intelligentie",
               subject="Memorie van toelichting", text=text,
               sections=[
                   {"id": "s-1", "heading": "ALGEMEEN", "level": 1, "parent": None,
                    "kind": "algemeen", "char_start": starts[0],
                    "char_end": starts[2]},
                   {"id": "s-2", "heading": "ARTIKELSGEWIJS", "level": 1,
                    "parent": None, "kind": "artikelsgewijs", "char_start": starts[2],
                    "char_end": len(text)},
                   {"id": "s-3", "heading": "Artikel 1", "level": 2, "parent": "s-2",
                    "kind": "article", "char_start": starts[3],
                    "char_end": len(text)},
               ])],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "members",
        [_node("m_minister", "member", name="Rob Jetten", slug="rob-jetten",
               government_functions=[{"function": "Minister-president",
                                      "from_date": "2026-02-23"}]),
         # a signature of no one the data seats: no page to link
         _node("m_niemand", "member", name="J. de Vries", slug="j-de-vries")],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("c1", "judgments/ecli_nl_crvb_2018_4314",
                  "judgments/ecli_nl_crvb_2018_1335", "REFERS_TO"),
            _edge("c2", "judgments/ecli_nl_crvb_2019_9",
                  "judgments/ecli_nl_crvb_2018_1335", "REFERS_TO"),
            _edge("c3", "judgments/ecli_nl_crvb_2018_1335",
                  "judgments/ecli_nl_rbams_2015_1", "APPEAL_OF"),
            _edge("c4", "judgments/ecli_nl_crvb_2018_1335",
                  "articles/bwbr0005289_162", "REFERS_TO"),
            _edge("r1", "articles/bwbr0005289_163", "articles/bwbr0005289_162",
                  "REFERS_TO"),
            _edge("e1", "documents/kst_36496_70", "articles/bwbr0005289_162",
                  "EXPLAINS"),
            _edge("e2", "documents/kst_36496_70", "instruments/bwbr0001854",
                  "REFERS_TO"),
            _edge("w1", "members/m_minister", "documents/kst_36496_70", "AUTHORED"),
            _edge("w2", "members/m_niemand", "documents/kst_36496_70", "AUTHORED"),
        ]
    )  # fmt: skip


def _text(main: str) -> str:
    """What a reader without JavaScript reads of a page."""
    return html.unescape(re.sub(r"<[^>]+>", "", main))


def _hrefs(main: str) -> list[str]:
    return re.findall(r'href="([^"]*)"', main)


def test_a_judgment_has_its_whole_text_and_the_judgments_of_its_case(
    client: TestClient, store: GraphStore
) -> None:
    _seed_texts(store)
    page = _head(_get(client, "/uitspraken/ECLI:NL:CRVB:2018:1335").text)
    main = page["main"]
    assert len(_text(main)) >= 2000
    assert "<h3>PROCESVERLOOP</h3>" in main and "<h3>BESLISSING</h3>" in main
    assert f'<p id="rov-1.2">1.2 {_CONSIDERATION.strip()}' in main
    assert "15/2587 ANW<br>Datum uitspraak: 3 mei 2018" in main  # the kop
    assert "Inhoudsopgave" not in main  # no table of contents
    hrefs = _hrefs(main)
    assert "/uitspraken/ECLI:NL:CRVB:2018:4314" in hrefs  # cites it
    assert "/uitspraken/ECLI:NL:RBAMS:2015:1" in hrefs  # its earlier instance
    assert "/wetten/BWBR0005289/artikel/6:162" in hrefs
    assert "/uitspraken/ECLI:NL:CRVB:2019:9" not in hrefs  # a stub: not indexed
    assert len(hrefs) >= 5
    assert page["robots"] is None


def test_a_text_past_the_limit_is_cut_after_a_whole_paragraph(
    client: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lawgraph.api.seo.pages import base

    _seed_texts(store)
    monkeypatch.setattr(base, "TEXT_MAX", 600)
    main = _head(_get(client, "/uitspraken/ECLI:NL:CRVB:2018:1335").text)["main"]
    assert 'id="rov-1.1"' in main and 'id="rov-1.8"' not in main
    assert "De tekst gaat verder: <a" in main
    assert "uitspraken.rechtspraak.nl" in main


def test_a_paper_has_its_text_with_its_headings_and_the_sources_it_names(
    client: TestClient, store: GraphStore
) -> None:
    _seed_texts(store)
    page = _head(_get(client, "/kamerstukken/36496/70").text)
    main = page["main"]
    assert len(_text(main)) >= 1000
    assert "<h3>ALGEMEEN</h3>" in main and "<h4>Artikel 1</h4>" in main
    assert "<p>In dit artikel worden de begrippen" in main
    hrefs = _hrefs(main)
    assert "/dossiers/36496" in hrefs
    assert "/wetten/BWBR0005289/artikel/6:162" in hrefs  # it explains it
    assert "/wetten/BWBR0001854" in hrefs  # it names it
    assert "/leden/rob-jetten" in hrefs  # signed it
    assert "/leden/j-de-vries" not in hrefs  # no role: not indexed
    assert "/kamerstukken/36496/71" in hrefs  # the next paper of its dossier
    assert len(hrefs) >= 6


def test_an_article_links_its_neighbours_and_what_refers_to_it(
    client: TestClient, store: GraphStore
) -> None:
    _seed_texts(store)
    main = _head(_get(client, "/wetten/BWBR0005289/artikel/6:162").text)["main"]
    hrefs = _hrefs(main)
    assert "/wetten/BWBR0005289/artikel/6:161" in hrefs
    assert "/wetten/BWBR0005289/artikel/6:161a" not in hrefs  # no text
    assert "/wetten/BWBR0005289/artikel/6:163" in hrefs
    assert "/kamerstukken/36496/70" in hrefs  # its memorie van toelichting
    assert "/uitspraken/ECLI:NL:CRVB:2018:1335" in hrefs
    assert len(hrefs) >= 6


def test_a_page_shows_its_breadcrumbs(client: TestClient, store: GraphStore) -> None:
    """The breadcrumbs of its JSON-LD, readable: the site, the dossier, the paper."""
    _seed_texts(store)
    main = _head(_get(client, "/kamerstukken/36496/70").text)["main"]
    nav = re.search(r'<nav aria-label="Kruimelpad">(.*?)</nav>', main)
    assert nav is not None
    assert _hrefs(nav[1]) == ["/", "/dossiers/36496"]
    assert '<span aria-current="page">Memorie van toelichting' in nav[1]


def test_a_rich_page_links_only_pages_that_are_indexed(
    client: TestClient, store: GraphStore
) -> None:
    """Every link of a page is to a page that is indexed; a paper without its text (the one
    before 70) is in its lists as plain text."""
    _seed_texts(store)
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("kst_36496_69", "document", kind="Brief regering", date="2025-08-01",
               dossier_number="36496", dossier_numbers=["36496"], sequence=69,
               subject="Brief over de AI-verordening")],
    )  # fmt: skip
    for path in (
        "/uitspraken/ECLI:NL:CRVB:2018:1335",
        "/kamerstukken/36496/70",
        "/wetten/BWBR0005289/artikel/6:162",
        "/dossiers/36496",
    ):
        main = _head(_get(client, path).text)["main"]
        if path.startswith("/kamerstukken") or path.startswith("/dossiers"):
            assert "Brief over de AI-verordening" in main, path
        for href in _hrefs(main):
            if not href.startswith("/") or href == "/":
                continue
            linked = _get(client, href)
            assert linked.status_code == 200, (path, href)
            assert _head(linked.text)["robots"] is None, (path, href)


def test_a_dossier_without_papers_is_not_indexed(
    client: TestClient, store: GraphStore
) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("36999", "dossier", label="36999", number="36999")]
    )
    assert _head(_get(client, "/dossiers/36999").text)["robots"] == "noindex"
    assert _head(_get(client, "/dossiers/36496").text)["robots"] is None


def test_a_document_without_a_text_is_not_indexed_nor_linked(
    client: TestClient, store: GraphStore
) -> None:
    """A paper whose text is not in the data is its title alone: ``noindex``, and no page
    links it; a motion or an amendment with its dictum is indexed without a text (as the
    sitemaps list it)."""
    _seed_texts(store)
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("kst_36496_69", "document", kind="Brief regering", date="2025-08-01",
               dossier_number="36496", dossier_numbers=["36496"], sequence=69,
               subject="Brief over de AI-verordening"),
         _node("kst_36496_80", "document", kind="Bijlage", date="2025-09-01",
               dossier_number="36496", dossier_numbers=["36496"], sequence=80,
               subject="Advies van de Raad van State"),
         _node("kst_36496_81", "document", kind="Motie", date="2025-10-01",
               dossier_number="36496", dossier_numbers=["36496"], sequence=81,
               subject="Motie van het lid Bolhuis over toezicht",
               dictum="verzoekt de regering het toezicht te regelen"),
         _node("kst_36496_82", "document", kind="Motie", date="2025-10-01",
               dossier_number="36496", dossier_numbers=["36496"], sequence=82,
               subject="Motie van het lid Bolhuis over niets")],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("x1", "documents/kst_36496_80", "documents/kst_36496_70",
                  "ACCOMPANIES"),
            _edge("x2", "documents/kst_36496_70", "documents/kst_36496_81",
                  "REFERS_TO"),
            _edge("x3", "documents/kst_36496_70", "documents/kst_36496_82",
                  "REFERS_TO"),
        ]
    )  # fmt: skip
    for path in ("/kamerstukken/36496/69", "/kamerstukken/36496/80",
                 "/kamerstukken/36496/82"):  # fmt: skip
        assert _head(_get(client, path).text)["robots"] == "noindex", path
    assert _head(_get(client, "/kamerstukken/36496/81").text)["robots"] is None
    for path in ("/kamerstukken/36496/70", "/dossiers/36496"):
        hrefs = _hrefs(_head(_get(client, path).text)["main"])
        assert "/kamerstukken/36496/69" not in hrefs, path  # the one before 70
        assert "/kamerstukken/36496/80" not in hrefs, path  # an attachment of 70
        assert "/kamerstukken/36496/82" not in hrefs, path
        assert "/kamerstukken/36496/81" in hrefs, path
    # the dossier keeps its whole list: the papers without a page to find as plain text
    main = _head(_get(client, "/dossiers/36496").text)["main"]
    assert "Brief over de AI-verordening" in main
    assert "Advies van de Raad van State" in main


def _seed_staatsblad_law(store: GraphStore) -> None:
    """The new Wetboek van Strafvordering as ``normalize staatsblad-laws`` writes it."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("wet_stb_2026_56", "instrument", official_id="stb-2026-56",
                  kind="wet", citation_title="Wetboek van Strafvordering",
                  title="Wetboek van Strafvordering",
                  display_name="Wetboek van Strafvordering (Stb. 2026, 56)",
                  status="vastgesteld", in_force=False),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(f"stb_2026_56_{n.replace('.', '_')}", "article",
                  official_id="stb-2026-56", article_number=n, position=i,
                  instrument_citation_title="Wetboek van Strafvordering",
                  text=f"De tekst van artikel {n}.")
            for i, n in enumerate(("2.8.6", "2.8.16"))
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge(f"s{i}", f"articles/stb_2026_56_{n}", "instruments/wet_stb_2026_56",
                  "PART_OF")
            for i, n in enumerate(("2_8_6", "2_8_16"))
        ]
    )  # fmt: skip


def test_a_law_of_the_staatsblad_and_its_article(
    client: TestClient, store: GraphStore
) -> None:
    _seed_staatsblad_law(store)
    law = _head(_get(client, "/wetten/STB-2026-56").text)
    assert law["title"] == "Wetboek van Strafvordering (Stb. 2026, 56), Concordans"
    assert "Vastgesteld, nog niet in werking (Stb. 2026, 56)." in law["main"]
    assert 'href="/wetten/STB-2026-56/artikel/2.8.16"' in law["main"]
    assert law["canonical"] == "https://concordans.nl/wetten/STB-2026-56"
    response = _get(client, "/wetten/STB-2026-56/artikel/2.8.6")
    assert_status(response, 200)
    article = _head(response.text)
    assert article["description"] == "De tekst van artikel 2.8.6."
    assert 'href="/wetten/STB-2026-56"' in article["main"]
    assert 'href="/wetten/STB-2026-56/artikel/2.8.16"' in article["main"]  # the next
    assert _get(client, "/wetten/stb-2026-56").headers["location"] == (
        "/wetten/STB-2026-56"
    )


def test_a_law_of_the_staatsblad_the_bwb_holds_now_leads_to_the_bwb(
    client: TestClient, store: GraphStore
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0051234", "instrument", bwb_id="BWBR0051234", kind="wet",
                  enacted_publication="stb-2026-56"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr0051234_2_8_6", "article", bwb_id="BWBR0051234",
                  article_number="2.8.6", text="De tekst."),
        ],
    )  # fmt: skip
    moved = _get(client, "/wetten/STB-2026-56/artikel/2.8.6")
    assert_status(moved, 301)
    assert moved.headers["location"] == "/wetten/BWBR0051234/artikel/2.8.6"
    # a number the BWB does not hold: the law
    other = _get(client, "/wetten/STB-2026-56/artikel/2.8.16")
    assert other.headers["location"] == "/wetten/BWBR0051234"
    assert _get(client, "/wetten/STB-2026-56").headers["location"] == (
        "/wetten/BWBR0051234"
    )
    # a law the BWB holds no regulation of, and the graph no law: not found
    assert_status(_get(client, "/wetten/STB-2026-99"), 404)


def test_the_start_page_is_its_core_without_a_read(
    client: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/``: the heading, what Concordans does, a search form that works without scripts
    (the SearchAction), three features and three questions, read of nothing."""

    def no_read(*_: Any, **__: Any) -> None:
        raise AssertionError("the start page reads nothing")

    monkeypatch.setattr(store, "get_document", no_read)
    monkeypatch.setattr(version_cache, "current_version", no_read)
    response = _get(client, "/")
    assert_status(response, 200)
    page = _head(response.text)
    assert page["title"] == "Concordans"
    assert page["description"] == "Wetten en Kamerstukken."
    assert page["canonical"] == "https://concordans.nl/"
    main = page["main"]
    assert (
        '<h1 class="blad__titel">Zie hoe wetten, rechtspraak en parlement '
        "samenhangen.</h1>" in main
    )
    # One self-description, and no name of the maker (A171).
    assert "onderzoeksinstrument" not in response.text and "TMvE" not in response.text
    form = re.search(r'<form action="/" method="get"[^>]*>(.*?)</form>', main, re.S)
    assert form and 'name="q"' in form[1]
    hrefs = re.findall(r'href="([^"]*)"', main)
    assert "/wetten/BWBR0005289/artikel/6:162" in hrefs
    assert "/stemmingen" in hrefs and "/bundels" in hrefs
    assert "Probeer" not in main and "stappen" not in main
    assert "onderschrift" not in main and "kenmerken" not in main
    assert re.findall(r"<h2[^>]*>(.*?)</h2>", main) == ["Begin met een vraag"]
    assert re.findall(r"<h3[^>]*>(.*?)</h3>", main) == [
        "Wie haalt dit artikel aan?",
        "Hoe stemde de Kamer?",
        "Hoe houd ik bij wat ik vind?",
    ]
    (site,) = [g for g in page["data"]["@graph"] if g["@type"] == "WebSite"]
    assert site["url"] == "https://concordans.nl/"
    assert site["potentialAction"] == {
        "@type": "SearchAction",
        "target": {
            "@type": "EntryPoint",
            "urlTemplate": "https://concordans.nl/?q={search_term_string}",
        },
        "query-input": "required name=search_term_string",
    }
    (org,) = [g for g in page["data"]["@graph"] if g["@type"] == "Organization"]
    assert site["publisher"] == {"@id": org["@id"]}
    # no breadcrumbs on the home of the site
    assert "Kruimelpad" not in main


def test_the_start_page_takes_its_text_from_the_front_end(
    client: TestClient, tmp_path: Path
) -> None:
    """``start.json`` beside the shell is the text of ``/``; without it, or when it is not
    whole, the text the server holds."""
    start = json.loads(json.dumps(home.START))
    start["heading"] = "Een andere kop"
    start["lede"] = "Een andere lede"
    (tmp_path / "start.json").write_text(json.dumps(start))
    shell.forget()
    main = _head(_get(client, "/").text)["main"]
    assert '<h1 class="blad__titel">Een andere kop</h1>' in main
    assert '<p class="lede">Een andere lede</p>' in main

    (tmp_path / "start.json").write_text(json.dumps({"heading": "Half"}))
    shell.forget()
    main = _head(_get(client, "/").text)["main"]
    assert "Zie hoe wetten, rechtspraak en parlement samenhangen." in main
    assert "Half" not in main


def _painted(text: str) -> dict[str, Any] | None:
    """What the page gives the front end's first paint, or None."""
    found = re.search(
        r'<script type="application/json" id="first-paint-data">(.*?)</script>',
        text,
        re.S,
    )
    return json.loads(found[1].replace("<\\/", "</")) if found else None


@pytest.fixture()
def painting(client: TestClient, tmp_path: Path) -> TestClient:
    """A front end with the script of its first paint beside its shell."""
    (tmp_path / "first-paint.js").write_text("paint()")
    shell.forget()
    return client


def test_an_article_is_painted_first_with_what_the_head_of_its_reader_shows(
    painting: TestClient, store: GraphStore
) -> None:
    store.bulk_insert_or_update_edges(
        [_edge("po1", "articles/bwbr0005289_162", "instruments/bwbr0005289", "PART_OF")]
    )
    response = _get(painting, "/wetten/BWBR0005289/artikel/6:162")
    assert_status(response, 200)
    paint = _painted(response.text)
    assert paint is not None
    assert paint["kind"] == "article"
    article = paint["article"]
    assert article["text"].startswith("1. Hij die jegens een ander")
    assert (article["law_id"], article["article_number"]) == ("BWBR0005289", "162")
    assert paint["law"]["props"]["citation_title"] == "Burgerlijk Wetboek Boek 6"
    # 163 follows in its law's list; nothing stands before it there
    assert paint["steps"] == {"listed": True, "prev": False, "next": True}
    assert paint["versions"] == [] and paint["explained"] == []
    assert paint["mvt"] is None and paint["delegations"] == []
    # the data after the content, the script that paints it after the data
    text = response.text
    assert text.index("</main>") < text.index("first-paint-data")
    assert text.index("first-paint-data") < text.index("<script>paint()</script>")


def test_an_article_in_a_recodification_is_not_painted_first(
    painting: TestClient, store: GraphStore
) -> None:
    """Its reader names its successor or predecessor in its head; the paint does not."""
    store.bulk_insert_or_update_edges(
        [
            _edge("t1", "articles/bwbr0001854_287", "articles/bwbr0005289_163",
                  "TRANSPOSED_TO"),
        ]
    )  # fmt: skip
    for path in (
        "/wetten/BWBR0001854/artikel/287",
        "/wetten/BWBR0005289/artikel/6:163",
    ):
        response = _get(painting, path)
        assert_status(response, 200)
        assert _painted(response.text) is None, path


def test_a_page_whose_first_paint_takes_too_long_goes_without(
    painting: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "PAINT_BUDGET", 0.0)
    response = _get(painting, "/wetten/BWBR0005289/artikel/6:162")
    assert_status(response, 200)
    assert _head(response.text)["main"] is not None
    assert _painted(response.text) is None


def test_a_judgment_without_paragraphs_is_not_painted_first(
    painting: TestClient,
) -> None:
    response = _get(painting, "/uitspraken/ECLI:NL:HR:2019:2006")
    assert_status(response, 200)
    assert "first-paint" not in response.text


def _judgment(key: str, ecli: str, **props: Any) -> dict[str, Any]:
    return _node(key, "judgment", ecli=ecli, court="Hoge Raad", parties=[], **props)


def test_a_judgment_is_painted_first_with_its_first_paragraphs_and_its_band(
    painting: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its answer with its first paragraphs (more than a screen) without their citations,
    the numbers of all, its light node of its procesgang and conclusie, and the instances
    before its eerdere aanleg, the nearest first."""
    monkeypatch.setattr(paint, "_JUDGMENT_TEXT", 20)
    paragraphs = [
        {"id": "kop-1", "kind": "heading", "number": "1", "text": "Beoordeling"},
        {"id": "rov-1.1", "kind": "body", "number": "1.1", "text": "Verworpen, want …"},
        {"id": "rov-1.2", "kind": "body", "number": "1.2", "text": "Ook dit faalt."},
    ]
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("ecli_nl_hr_2020_9", "ECLI:NL:HR:2020:9", outcome="verworpen",
                      paragraphs=paragraphs, summary="Cassatie."),
            _judgment("ecli_nl_ghdha_2019_9", "ECLI:NL:GHDHA:2019:9"),
            _judgment("ecli_nl_rbdha_2018_9", "ECLI:NL:RBDHA:2018:9"),
            _judgment("ecli_nl_rbdha_2017_9", "ECLI:NL:RBDHA:2017:9"),
            _judgment("ecli_nl_phr_2020_9", "ECLI:NL:PHR:2020:9"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("ap1", "judgments/ecli_nl_hr_2020_9", "judgments/ecli_nl_ghdha_2019_9",
                  "APPEAL_OF", procedure_type="Cassatie"),
            _edge("ap2", "judgments/ecli_nl_ghdha_2019_9", "judgments/ecli_nl_rbdha_2018_9",
                  "APPEAL_OF"),
            _edge("ap3", "judgments/ecli_nl_rbdha_2018_9", "judgments/ecli_nl_rbdha_2017_9",
                  "APPEAL_OF"),
            _edge("ad1", "judgments/ecli_nl_phr_2020_9", "judgments/ecli_nl_hr_2020_9",
                  "ADVISES_ON"),
            _edge("ci1", "judgments/ecli_nl_hr_2020_9", "articles/bwbr0005289_162",
                  "REFERS_TO"),
        ]
    )  # fmt: skip
    response = _get(painting, "/uitspraken/ECLI:NL:HR:2020:9")
    assert_status(response, 200)
    painted = _painted(response.text)
    assert painted is not None and painted["kind"] == "judgment"
    judgment = painted["judgment"]
    assert [p["paragraph_id"] for p in judgment["paragraphs"]] == ["kop-1", "rov-1.1"]
    assert painted["whole"] is False
    assert painted["numbers"] == ["1", "1.1", "1.2"]
    cited = [p["paragraph_id"] for p in judgment["paragraphs"] if p["citations"]]
    assert cited == [], "a painted paragraph keeps no citations"
    assert "paragraphs" not in judgment["props"] and "text" not in judgment["props"]
    assert painted["light"]["node"] == {"props": {"outcome": "verworpen"}}
    buckets = {
        (b["relation"], b["direction"]): [i["key"] for i in b["items"]]
        for b in painted["light"]["neighbors"]["buckets"]
    }
    assert buckets == {
        ("APPEAL_OF", "outbound"): ["ecli_nl_ghdha_2019_9"],
        ("ADVISES_ON", "inbound"): ["ecli_nl_phr_2020_9"],
    }
    assert [c["key"] for c in painted["chain"]] == [
        "ecli_nl_rbdha_2018_9",
        "ecli_nl_rbdha_2017_9",
    ]


def test_a_law_is_painted_first_with_its_first_articles_and_their_text(
    painting: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its answer, its articles in force counted and the first of them, each with its text
    of today (a preview only where that is not there), its basis and the bill that made it."""
    # its six reads on a cold test database, however slow the runner
    monkeypatch.setattr(render, "PAINT_BUDGET", 30.0)
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node("av_162", "article_version", bwb_id="BWBR0005289", article_number="162",
                  valid_from="1992-01-01", current=True, text="1. Hij die …",
                  parts=[{"id": "lid-1", "kind": "lid", "number": "1", "start": 3,
                          "end": 12}]),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [
            _node(
                "iv_6",
                "instrument_version",
                bwb_id="BWBR0005289",
                valid_from="1992-01-01",
            )
        ],
    )
    store.bulk_insert_or_update_edges(
        [_edge("li1", "instruments/bwbr0005289", "dossiers/36496", "LEGISLATED_IN")]
    )
    response = _get(painting, "/wetten/BWBR0005289")
    assert_status(response, 200)
    painted = _painted(response.text)
    assert painted is not None and painted["kind"] == "law"
    assert painted["bwb_id"] == "BWBR0005289"
    assert painted["instrument"]["citation_title"] == "Burgerlijk Wetboek Boek 6"
    assert (painted["total"], painted["annexes"]) == (2, 0)
    articles = {a["article_number"]: a for a in painted["articles"]}
    assert set(articles) == {"162", "163"}
    assert [t["article_number"] for t in painted["texts"]] == ["162"]
    assert painted["texts"][0]["text"] == "1. Hij die …"
    # the preview stands only where the text of today does not
    assert articles["162"]["text_preview"] is None
    assert articles["163"]["text_preview"].startswith("Geen verplichting")
    assert painted["basis"] == []
    (bucket,) = painted["light"]["neighbors"]["buckets"]
    assert (bucket["relation"], [i["key"] for i in bucket["items"]]) == (
        "LEGISLATED_IN",
        ["36496"],
    )


def test_a_kamerstuk_is_painted_first_with_its_first_alineas(
    painting: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its answer with its text up to the end of an alinea past the cut, the widest numbers
    of all its alineas, a later heading a line repeats, its light node, the vote on it and
    what it explains."""
    monkeypatch.setattr(render, "PAINT_BUDGET", 30.0)
    monkeypatch.setattr(paint, "_DOCUMENT_TEXT", 20)
    text = "Voorzitter: Kops\nDe eerste alinea.\nDe tweede.\nVoorzitter: Kops\nEind."
    lines = [(0, 16), (17, 34), (35, 45), (46, 62), (63, 68)]
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36496_80", "document", kind="Verslag", date="2026-08-01",
                  dossier_number="36496", dossier_numbers=["36496"], sequence=80,
                  title="Verslag van een overleg", text=text,
                  paragraphs=[{"id": f"p-{i}", "number": i, "kind": "body",
                               "char_start": a, "char_end": b}
                              for i, (a, b) in enumerate(lines, start=1)],
                  sections=[{"id": "s-1", "heading": "Voorzitter: Kops", "level": 1,
                             "kind": "other",
                             "char_start": 46, "char_end": 68}]),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("p80", "documents/kst_36496_80", "cases/z_1", "PART_OF"),
            _edge(
                "e80", "documents/kst_36496_80", "articles/bwbr0005289_162", "EXPLAINS"
            ),
        ]
    )
    response = _get(painting, "/kamerstukken/36496/80")
    assert_status(response, 200)
    painted = _painted(response.text)
    assert painted is not None and painted["kind"] == "paper"
    doc = painted["document"]
    assert doc["text"] == "Voorzitter: Kops\nDe eerste alinea."
    assert [p["id"] for p in doc["paragraphs"]] == ["p-1", "p-2"]
    assert doc["sections"] == []
    assert (painted["whole"], painted["section_count"]) == (False, 1)
    assert painted["headings"] == ["voorzitter: kops"]
    assert painted["numbers"][0] in {"1", "2", "3", "4", "5"}
    # the vote on it, which its head says
    assert [d["key"] for d in doc["decisions"]] == ["s_1"]
    # and the article it explains, which its section Licht toe counts
    assert [e["key"] for e in doc["explains"]] == ["bwbr0005289_162"]


def test_a_judgment_whose_parties_were_not_read_is_not_painted_first(
    painting: TestClient, store: GraphStore
) -> None:
    """The reader reads its parties from its whole text, which the paint has not."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("ecli_nl_hr_2020_8", "judgment", ecli="ECLI:NL:HR:2020:8",
                  paragraphs=[{"id": "rov-1", "kind": "body", "number": "1",
                               "text": "Verworpen."}]),
        ],
    )  # fmt: skip
    response = _get(painting, "/uitspraken/ECLI:NL:HR:2020:8")
    assert_status(response, 200)
    assert _painted(response.text) is None


def test_the_first_paint_lists_the_versions_of_an_article_lightly(
    painting: TestClient, store: GraphStore
) -> None:
    """Its versions as the history lists them, each with what made it, read without what a
    version holds beside its wording (its parts)."""
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node("av_162", "article_version", bwb_id="BWBR0005289", article_number="162",
                  valid_from="1992-01-01", current=True, text="1. Hij die …",
                  parts=[{"id": "lid-1", "kind": "lid", "number": "1", "start": 3,
                          "end": 12}],
                  origin_publication={"dossiers": ["17541"]}),
        ],
    )  # fmt: skip
    paint = _painted(_get(painting, "/wetten/BWBR0005289/artikel/6:162").text)
    assert paint is not None
    (version,) = paint["versions"]
    assert (version["valid_from"], version["current"], version["text_changed"]) == (
        "1992-01-01",
        True,
        True,
    )
    assert [d["number"] for d in version["amended_by"]["dossiers"]] == ["17541"]
    assert set(version) == {
        "key",
        "valid_from",
        "valid_until",
        "current",
        "change",
        "text_changed",
        "changes",
        "amended_by",
    }
