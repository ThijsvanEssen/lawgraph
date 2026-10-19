"""The sitemaps of Concordans on a real PostgreSQL (``lawgraph sitemaps``): per kind of
page the readable addresses, with the day each last changed; what has no page, or is
too old, left out."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.seo import shell
from lawgraph.api.seo.pages.government import publication_page
from lawgraph.commands import sitemaps as command
from lawgraph.config import settings
from lawgraph.core.publications import note_key
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import seo
from lawgraph.db.queries import sitemaps as queries


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": ["TK"], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {"key": key, "from_id": source, "to_id": target, "relation": relation,
            "source": "test", "meta": {}}  # fmt: skip


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0005289", "instrument", bwb_id="BWBR0005289", kind="wet"),
            _node("bwbr0001854", "instrument", bwb_id="BWBR0001854", kind="wet"),
            _node("bwbr0099999", "instrument", bwb_id="BWBR0099999", stub=True),
            _node("stb_2026_94", "instrument", official_id="stb-2026-94"),
            # a law of the Staatsblad the BWB does not hold, and its publication
            _node(
                "wet_stb_2026_56",
                "instrument",
                official_id="stb-2026-56",
                kind="wet",
                citation_title="Wetboek van Strafvordering",
                date_published="2026-03-13",
                status="vastgesteld",
            ),
            _node(
                "stb_2026_56",
                "instrument",
                official_id="stb-2026-56",
                kind="publicatie",
            ),
            # an EU act with its articles, and one whose text was not read
            _node("32022l2555", "instrument", celex="32022L2555"),
            _node("32019r0881", "instrument", celex="32019R0881"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [
            _node("v_old", "version", bwb_id="BWBR0005289", valid_from="2020-01-01",
                  current=False),
            _node("v_now", "version", bwb_id="BWBR0005289", valid_from="2025-07-01",
                  current=True),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("stb_2026_56_2_8_6", "article", official_id="stb-2026-56",
                  article_number="2.8.6", position=1, text="De officier van justitie"),
            # without a text: nothing to read
            _node("stb_2026_56_2_8_7", "article", official_id="stb-2026-56",
                  article_number="2.8.7", position=2),
            _node("bwbr0005289_163", "article", bwb_id="BWBR0005289",
                  article_number="163", position=163, inbound_citation_count=5,
                  text="Geen verplichting tot schadevergoeding …"),
            _node("bwbr0005289_162", "article", bwb_id="BWBR0005289",
                  article_number="162", position=162, inbound_citation_count=900,
                  text="1. Hij die jegens een ander …"),
            _node("bwbr0005289_164", "article", bwb_id="BWBR0005289",
                  article_number="164", position=164, repealed=True, text="…"),
            # without a text: nothing to read on its page
            _node("bwbr0005289_165", "article", bwb_id="BWBR0005289",
                  article_number="165", position=165, inbound_citation_count=3),
            _node("bwbr0001854_1", "article", bwb_id="BWBR0001854",
                  article_number="1", position=1, inbound_citation_count=10,
                  text="Geen feit is strafbaar …"),
            _node("32022l2555_21", "article", celex="32022L2555", article_number="21",
                  position=21, text="1. De lidstaten …"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36496_71", "document", kind="Motie", dossier_number="36496",
                  dossier_numbers=["36496"], sequence=71,
                  dictum="verzoekt de regering een AI-killswitch te regelen"),
            _node("kst_36600_viii_12", "document", kind="Amendement",
                  dossier_number="36600", dossier_suffix="VIII",
                  dossier_numbers=["36600-VIII"], sequence=12, text="Het amendement …"),
            # voted on, without a text or a dictum: its title alone
            _node("kst_36496_74", "document", kind="Motie", dossier_number="36496",
                  dossier_numbers=["36496"], sequence=74),
            _node("kst_30000_5", "document", kind="Motie", dossier_number="30000",
                  sequence=5),
            _node("kst_36496_72", "document", kind="Motie", dossier_number="36496",
                  sequence=72),
            _node("kst_36496_73", "document", kind="Motie", dossier_number="36496",
                  sequence=73),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases",
        [_node(f"z_{n}", "case") for n in (*range(1, 6), 10)],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node("s_1", "decision", date="2026-09-08", passed=True),
            _node("s_1b", "decision", date="2026-09-15", passed=False),
            _node("s_2", "decision", date="2025-03-01", passed=True),
            _node("s_3", "decision", date="2016-05-01", passed=False),
            # withdrawn: a decision without an outcome, no vote
            _node(
                "s_5",
                "decision",
                date="2026-09-20",
                decision_kind="Stemmen - ingetrokken",
            ),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("p1", "documents/kst_36496_71", "cases/z_1", "PART_OF"),
            _edge("a1", "decisions/s_1", "cases/z_1", "ABOUT"),
            _edge("a1b", "decisions/s_1b", "cases/z_1", "ABOUT"),
            _edge("p2", "documents/kst_36600_viii_12", "cases/z_2", "PART_OF"),
            _edge("a2", "decisions/s_2", "cases/z_2", "ABOUT"),
            # decided before 2018
            _edge("p3", "documents/kst_30000_5", "cases/z_3", "PART_OF"),
            _edge("a3", "decisions/s_3", "cases/z_3", "ABOUT"),
            # never decided: kst_36496_72 is PART_OF a case without a decision
            _edge("p4", "documents/kst_36496_72", "cases/z_4", "PART_OF"),
            # withdrawn, never voted on
            _edge("p5", "documents/kst_36496_73", "cases/z_5", "PART_OF"),
            _edge("a5", "decisions/s_5", "cases/z_5", "ABOUT"),
            _edge("p10", "documents/kst_36496_74", "cases/z_10", "PART_OF"),
            _edge("a10", "decisions/s_1", "cases/z_10", "ABOUT"),
        ]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36600_viii", "dossier", number="36600-VIII", label="36600-VIII",
                  last_activity="2026-09-30"),
            _node("36496", "dossier", number="36496", label="36496"),
            # without a paper in the data: its title alone
            _node("36999", "dossier", number="36999", label="36999"),
        ],
    )  # fmt: skip


def _paths(kinds: dict[str, Any], kind: str) -> list[tuple[str, str | None]]:
    return [(e.path, e.lastmod) for e in kinds[kind]]


def test_each_kind_by_its_readable_address(store: GraphStore) -> None:
    _seed(store)
    kinds = command.kinds(store)
    # no stub, no publication; the day of the version in force; an EU act with articles
    # a law of the Staatsblad on the day it was published
    assert _paths(kinds, "wetten") == [
        ("/wetten/32022L2555", None),
        ("/wetten/BWBR0001854", None),
        ("/wetten/BWBR0005289", "2025-07-01"),
        ("/wetten/STB-2026-56", "2026-03-13"),
    ]
    # per law in its order; a repealed article left out; every article with a text of a
    # law of the Staatsblad
    assert _paths(kinds, "artikelen") == [
        ("/wetten/BWBR0001854/artikel/1", None),
        ("/wetten/BWBR0005289/artikel/6:162", "2025-07-01"),
        ("/wetten/BWBR0005289/artikel/6:163", "2025-07-01"),
        ("/wetten/STB-2026-56/artikel/2.8.6", None),
    ]
    # voted on since 2018, on the last day; one withdrawn is no page of a vote
    assert _paths(kinds, "moties") == [("/kamerstukken/36496/71", "2026-09-15")]
    assert _paths(kinds, "amendementen") == [
        ("/kamerstukken/36600-VIII/12", "2025-03-01")
    ]
    assert _paths(kinds, "dossiers") == [
        ("/dossiers/36496", None),
        ("/dossiers/36600-VIII", "2026-09-30"),
    ]


def test_annexes_and_zaken(store: GraphStore) -> None:
    """An annex with a label and something to read of a law that is no stub; a zaak
    voted on since 2018 that is no motion or amendment (their papers are listed)."""
    _seed(store)
    store.bulk_insert_or_update_nodes(
        "annexes",
        [
            _node("bwbr0005289_annex_ii", "annex", bwb_id="BWBR0005289", label="II",
                  entries=[{"index": 1, "name": "Cannabis"}]),
            _node("bwbr0005289_annex_a", "annex", bwb_id="BWBR0005289", label="A",
                  description="Model"),
            # only cited; without a label; nothing to read; of a stub law
            _node("bwbr0005289_annex_iii", "annex", bwb_id="BWBR0005289", label="III",
                  stub=True, description="x"),
            _node("bwbr0005289_annex", "annex", bwb_id="BWBR0005289",
                  description="x"),
            _node("bwbr0005289_annex_iv", "annex", bwb_id="BWBR0005289", label="IV"),
            _node("bwbr0005289_annex_v", "annex", bwb_id="BWBR0005289", label="V",
                  entries=[]),
            _node("bwbr0099999_annex_i", "annex", bwb_id="BWBR0099999", label="I",
                  description="x"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            _node("z_6", "case", number="2026Z00006", kind="Wetgeving"),
            _node("z_7", "case", number="2016Z00007", kind="Wetgeving"),
            _node("z_8", "case", number="2026Z00008", kind="Motie"),
            _node("z_9", "case", number="2026Z00009", kind="Brief regering"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("a6", "decisions/s_1", "cases/z_6", "ABOUT"),
            _edge("a6b", "decisions/s_2", "cases/z_6", "ABOUT"),
            _edge("a7", "decisions/s_3", "cases/z_7", "ABOUT"),
            _edge("a8", "decisions/s_1", "cases/z_8", "ABOUT"),
        ]
    )
    kinds = command.kinds(store)
    assert _paths(kinds, "bijlagen") == [
        ("/wetten/BWBR0005289/bijlage/A", "2025-07-01"),
        ("/wetten/BWBR0005289/bijlage/II", "2025-07-01"),
    ]
    assert _paths(kinds, "zaken") == [("/zaken/2026Z00006", "2026-09-08")]


def test_members_factions_cabinets_and_committees(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node("m_1", "member", slug="rob-jetten",
                  government_functions=[{"function": "Minister-president"}]),
            _node("m_2", "member", slug="jan-paternotte",
                  faction_memberships=[{"faction_key": "d66"}]),
            _node("m_3", "member", slug="paul-van-meenen", ek={"faction": "ek_d66"}),
            # a former senator: their periods from their page, no seat in the composition
            _node("m_6", "member", slug="kim-putters",
                  ek_faction_memberships=[{"faction": "PvdA"}]),
            # never seated, no post: no page worth a search engine
            _node("m_4", "member", slug="j-de-vries", faction_memberships=[]),
            _node("m_5", "member", name="Zonder slug",
                  faction_memberships=[{"faction_key": "d66"}]),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node("d66", "faction", name="Democraten 66",
                  seats_changed_on="2026-03-01T10:00:00"),
            _node("ek_d66", "faction", chamber="EK", abbreviation="D66"),
            # neither a name nor an abbreviation: no page worth a search engine
            _node("naamloos", "faction"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node("jetten", "cabinet", from_date="2026-02-23",
                  phases=[{"from_date": "2026-01-05"}, {"from_date": "2026-02-23"}]),
            _node("schoof", "cabinet", from_date="2024-07-02", to_date="2026-02-23",
                  phases=[{"from_date": "2025-06-03"}]),
            _node("drees", "cabinet", from_date="1948-08-07"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "committees",
        [
            _node("szw", "committee", slug="szw", name="Sociale Zaken"),
            _node("ek_jenv", "committee", slug="ek-jenv", chamber="EK",
                  title="Vaste commissie voor Justitie en Veiligheid"),
            _node("geen", "committee", name="Zonder slug"),
            _node("naamloos", "committee", slug="naamloos"),
        ],
    )  # fmt: skip
    kinds = command.kinds(store)
    assert _paths(kinds, "leden") == [
        ("/leden/rob-jetten", None),
        ("/leden/jan-paternotte", None),
        ("/leden/paul-van-meenen", None),
        ("/leden/kim-putters", None),
    ]
    assert _paths(kinds, "fracties") == [
        ("/fracties/d66", "2026-03-01"),
        ("/fracties/ek_d66", None),
    ]
    # its end, else the start of its last phase, else its beëdiging; none before 1970
    assert _paths(kinds, "kabinetten") == [
        ("/kabinetten/drees", None),
        ("/kabinetten/jetten", "2026-02-23"),
        ("/kabinetten/schoof", "2026-02-23"),
    ]
    assert _paths(kinds, "commissies") == [
        ("/commissies/ek-jenv", None),
        ("/commissies/szw", None),
    ]


def test_publications_and_commitments(store: GraphStore) -> None:
    def publication(official: str, published: str) -> dict[str, Any]:
        series, year, number = official.split("-")
        return _node(official.replace("-", "_"), "instrument", kind="publicatie",
                     official_id=official, date_published=published,
                     publication_year=int(year), publication_number=int(number))  # fmt: skip

    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            publication("stb-2025-263", "2025-09-02"),  # a title of its own
            publication("stb-2025-300", "2025-10-01"),  # changes a regulation
            publication("trb-2024-12", "2024-03-05"),  # changes a regulation
            publication("stb-2025-301", "2025-10-02"),  # neither: no page to find
            publication("stb-2026-94", "2026-03-01"),  # the masthead as its title
            publication("stb-2017-5", "2017-01-10"),  # before 2018
            publication("stcrt-2025-9", "2025-02-01"),  # the Staatscourant
            publication("stb-2026-187", "2026-07-20"),  # enacts a law: establishes it
            # changes only what has no name: a law without a title, a paper
            publication("stb-2025-302", "2025-10-03"),
            publication("stb-2025-303", "2025-10-04"),
            _node("bwbr0077777", "instrument", bwb_id="BWBR0077777", kind="wet"),
            _node(
                "bwbr0005289",
                "instrument",
                bwb_id="BWBR0005289",
                kind="wet",
                citation_title="Burgerlijk Wetboek Boek 6",
            ),
            _node(
                "bwbr0052872",
                "instrument",
                bwb_id="BWBR0052872",
                kind="wet",
                citation_title="Wet een",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("stb_stb_2025_263", "document", identifier="stb-2025-263",
                  title="Besluit tot wijziging van het Mediabesluit 2008"),
            _node("stb_stb_2025_301", "document", identifier="stb-2025-301",
                  title="Staatsblad 2025/301"),
            _node("stb_stb_2026_94", "document", identifier="stb-2026-94",
                  title="Staatsblad"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("c1", "instruments/stb_2025_300", "instruments/bwbr0005289", "AMENDS"),
            _edge("c2", "instruments/trb_2024_12", "instruments/bwbr0005289",
                  "INTRODUCES"),
            _edge("c3", "instruments/stcrt_2025_9", "instruments/bwbr0005289",
                  "AMENDS"),
            _edge("c4", "instruments/stb_2026_187", "articles/bwbr0052872_1",
                  "ESTABLISHES"),
            _edge("c5", "instruments/stb_2025_302", "instruments/bwbr0077777",
                  "AMENDS"),
            _edge("c6", "instruments/stb_2025_303", "documents/stb_stb_2025_263",
                  "AMENDS"),
        ]
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "commitments",
        [
            _node("tz_1", "commitment", number="TZ202609-124", text="Een brief.",
                  made_on="2026-09-10"),
            _node("tz_2", "commitment", number="TZ201701-1", text="Oud.",
                  made_on="2017-01-05"),
            _node("tz_3", "commitment", number="TZ202609-125", made_on="2026-09-11"),
        ],
    )  # fmt: skip
    # a debate with its record, one with nothing made in it, an old one and one of the
    # Eerste Kamer, which has no number
    store.bulk_insert_or_update_nodes(
        "activities",
        [
            _node("wgo", "activity", number="2026A01323", date="2026-03-23"),
            _node("leeg", "activity", number="2026A01400", date="2026-03-24"),
            _node("oud", "activity", number="2017A00001", date="2017-03-01"),
            _node("ek_20260310_jenv", "activity", date="2026-03-10"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("act1", "documents/stb_stb_2025_301", "activities/wgo", "MADE_IN"),
            _edge("act2", "commitments/tz_1", "activities/wgo", "MADE_IN"),
            _edge("act3", "commitments/tz_2", "activities/oud", "MADE_IN"),
            _edge("act4", "commitments/tz_3", "activities/ek_20260310_jenv", "MADE_IN"),
        ]
    )
    kinds = command.kinds(store)
    assert _paths(kinds, "activiteiten") == [("/activiteiten/2026A01323", "2026-03-23")]
    assert _paths(kinds, "publicaties") == [
        ("/stb/2025/263", "2025-09-02"),
        ("/stb/2025/300", "2025-10-01"),
        ("/stb/2026/187", "2026-07-20"),
        ("/trb/2024/12", "2024-03-05"),
    ]
    assert _paths(kinds, "toezeggingen") == [
        ("/toezeggingen/TZ202609-124", "2026-09-10")
    ]
    # the sitemap names exactly the publications (of its series) whose page is indexed
    listed = {row["id"] for row in queries.publications(store)}
    for official in ("stb-2025-263", "stb-2025-300", "trb-2024-12", "stb-2025-301",
                     "stb-2026-94", "stb-2026-187", "stb-2025-302",
                     "stb-2025-303"):  # fmt: skip
        node_id = f"instruments/{official.replace('-', '_')}"
        page = publication_page(seo.publication(store, node_id) or {})
        assert page.index == (node_id in listed), official


def test_only_the_most_cited_laws_have_their_articles(store: GraphStore) -> None:
    _seed(store)
    listed = [row["id"] for row in queries.articles(store, top=1)]
    assert listed == [
        "articles/bwbr0005289_162",
        "articles/bwbr0005289_163",
        "articles/stb_2026_56_2_8_6",  # a law of the Staatsblad, cited by none yet
    ]


def test_the_command_writes_the_index_and_its_parts(
    store: GraphStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store)
    index = tmp_path / "build" / "index.html"
    index.parent.mkdir()
    index.write_text("<!doctype html><html><head></head><body></body></html>")
    (index.parent / "spa-routes.json").write_text(
        json.dumps(
            [
                {"path": "/", "title": "Concordans"},
                {"path": "/actueel"},
                # a reader's own maps: no page for a search engine
                {"path": "/gemarkeerd", "index": False},
            ]
        )
    )
    monkeypatch.setattr(settings, "SPA_INDEX", str(index))
    monkeypatch.setattr(command, "GraphStore", lambda: store)
    shell.forget()
    out = tmp_path / "sitemaps"
    try:
        result = command.main(
            ["--output", str(out), "--base", "https://concordans.nl/"]
        )
    finally:
        shell.forget()
    assert result.updated == 14
    listed = (out / "sitemap.xml").read_text()
    assert "<loc>https://concordans.nl/sitemap-moties.xml</loc>" in listed
    assert "<lastmod>2026-09-15</lastmod>" in listed
    pages = (out / "sitemap-paginas.xml").read_text(encoding="utf-8")
    assert "<loc>https://concordans.nl/actueel</loc>" in pages
    assert "gemarkeerd" not in pages


@pytest.mark.parametrize("official", ["stb-2026-94", "trb-2024-12", "stcrt-2020-00012"])
def test_the_note_id_in_sql_is_the_note_key(store: GraphStore, official: str) -> None:
    (note_id,) = store.query(f"SELECT {queries.note_id_sql('%(official)s')}",
                             {"official": official})  # fmt: skip
    assert note_id == f"documents/{note_key(official)}"


def test_every_page_the_sitemaps_list_is_indexed(
    store: GraphStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sitemap lists no page its own HTML keeps out of the index (``noindex``), nor a page
    with nothing to read: an article without a text, a dossier without a paper, a faction or
    committee without a name, a motion without a text or a dictum (each ``noindex``)."""
    _seed(store)
    store.bulk_insert_or_update_nodes(
        "factions",
        [_node("d66", "faction", name="Democraten 66"), _node("naamloos", "faction")],
    )
    store.bulk_insert_or_update_nodes(
        "committees",
        [_node("szw", "committee", slug="szw", name="Sociale Zaken"),
         _node("naamloos", "committee", slug="naamloos")],
    )  # fmt: skip
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><html><head></head><body></body></html>")
    monkeypatch.setattr(settings, "SPA_INDEX", str(index))
    monkeypatch.setattr(seo, "CITED_BUDGET", 5.0)
    version_cache.clear()
    shell.forget()
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = {
            entry.path
            for kind, entries in command.kinds(store).items()
            if kind != "paginas"
            for entry in entries
        }
        assert listed
        for path in sorted(listed):
            page = client.get(f"/render{path}", follow_redirects=False)
            assert page.status_code == 200, path
            assert 'name="robots" content="noindex"' not in page.text, path
        for path in (
            "/kamerstukken/36496/74",
            "/wetten/BWBR0005289/artikel/6:165",
            "/dossiers/36999",
            "/fracties/naamloos",
            "/commissies/naamloos",
        ):
            assert path not in listed, path
            page = client.get(f"/render{path}", follow_redirects=False)
            assert 'name="robots" content="noindex"' in page.text, path
    finally:
        app.dependency_overrides.pop(get_store, None)
        shell.forget()
