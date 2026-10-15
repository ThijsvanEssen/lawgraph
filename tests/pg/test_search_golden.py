"""What the search answers, pinned: the hits of every type, full and while typing, at a few
limits, with a period and a kind, and the types cut off at their budget.

``tests/fixtures/search_golden.json`` holds the expected answers. A change in it is a change
in what the search finds or how it orders: check every line of the diff before writing the
file anew with ``LAWGRAPH_WRITE_GOLDEN=1 pytest tests/pg/test_search_golden.py``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_LEGISLATED_IN
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import search as search_queries
from lawgraph.db.queries import search_candidates
from lawgraph.db.queries.search import (
    SEARCH_TYPES,
    Period,
    load_notation_parser,
    search_all,
    search_full,
    search_live,
)
from tests.paths import FIXTURES

GOLDEN = FIXTURES / "search_golden.json"
TYPES = sorted(SEARCH_TYPES)

QUERIES = [
    "wet",
    "strafbaar",
    "strafbaar sv",
    "art. 1 sr",
    "art 1",
    "artikel 6:162",
    "Sr",
    "wvsr",
    "Wetboek van Strafrecht",
    "ECLI:NL:HR:1919:1",
    "Lindenbaum/Cohen",
    "lindenb",
    "R. van Gelder",
    "van geld",
    "vermeulen",
    "de vries",
    "yesilgoz",
    "cda",
    "kabinet schoof",
    "klimaat",
    "stemming klimaat",
    "stemming",
    "noodweer",
    "cbw",
    "cbw dossier",
    "zorgplicht cbw",
    "huur",
    "huurovereenkomst",
    "belasting",
    "36000",
    "TZ202609-011",
    "stik",
    "hu",
    "dossier",
    "onrechtmatige daad",
]


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    labels = props.pop("labels", [])
    return {"_key": key, "type": node_type, "labels": labels, "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _person(name: str, role: str) -> dict[str, Any]:
    return {"name": name, "role": role, "place": None, "capacity": None}


def _party(name: str, role: str, side: str, *people: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "roles": [role],
        "role_stated": True,
        "side": side,
        "alias": None,
        "representatives": list(people),
    }


def _instruments() -> list[dict[str, Any]]:
    return [
        _node("bwbr0001854", "instrument", bwb_id="BWBR0001854",
              title="Wetboek van Strafrecht", citation_title="Wetboek van Strafrecht",
              short_title="Sr", aliases=["WvSr", "Sr"], article_count=500,
              date_in_force="1886-09-01"),
        _node("bwbr0001903", "instrument", bwb_id="BWBR0001903",
              title="Wetboek van Strafvordering",
              citation_title="Wetboek van Strafvordering", short_title="Sv",
              article_count=600, date_in_force="1926-01-01"),
        _node("bwbr0005289", "instrument", bwb_id="BWBR0005289",
              title="Burgerlijk Wetboek Boek 6", citation_title="Burgerlijk Wetboek Boek 6",
              aliases=["BW", "Boek 6 BW"], article_count=300, date_in_force="1992-01-01"),
        _node("bwbr0050000", "instrument", bwb_id="BWBR0050000",
              title="Cyberbeveiligingswet", citation_title="Cyberbeveiligingswet",
              short_title="Cbw", article_count=40, date_in_force="2026-06-01"),
        _node("bwbr9", "instrument", bwb_id="BWBR9", title="Klimaatwet",
              citation_title="Klimaatwet", date_in_force="2019-09-01"),
        _node("bwbr8", "instrument", bwb_id="BWBR8", title="Oude klimaatwet",
              citation_title="Oude klimaatwet", date_in_force="2010-01-01"),
        _node("bwbr7", "instrument", bwb_id="BWBR7", title="Stikstofwet",
              citation_title="Stikstofwet", article_count=12),
        _node("celex1", "instrument", celex="32016R0679",
              title="Algemene verordening gegevensbescherming", short_title="AVG"),
    ]  # fmt: skip


def _articles() -> list[dict[str, Any]]:
    articles = [
        _node("bwbr0001854_1", "article", bwb_id="BWBR0001854", article_number="1",
              display_name="Artikel 1 Wetboek van Strafrecht",
              text="Geen feit is strafbaar dan uit kracht van een daaraan voorafgegane "
              "wettelijke strafbepaling.",
              breadcrumb=[{"title": "Algemene bepalingen"}, {"label": "x"}],
              inbound_citation_count=5),
        _node("bwbr0001854_41", "article", bwb_id="BWBR0001854", article_number="41",
              display_name="Artikel 41 Wetboek van Strafrecht",
              text="Niet strafbaar is hij die een feit begaat, geboden door de"
              " noodzakelijke verdediging van eigen of eens anders lijf.",
              inbound_citation_count=20),
        _node("bwbr0001903_1", "article", bwb_id="BWBR0001903", article_number="1",
              display_name="Artikel 1 Wetboek van Strafvordering",
              text="Strafvordering heeft alleen plaats op de wijze bij de wet voorzien.",
              inbound_citation_count=9),
        _node("bwbr0005289_6-162", "article", bwb_id="BWBR0005289",
              article_number="6:162", display_name="Artikel 6:162 Burgerlijk Wetboek",
              heading="Onrechtmatige daad",
              text="Hij die jegens een ander een onrechtmatige daad pleegt, welke hem kan"
              " worden toegerekend, is verplicht de schade te vergoeden.",
              breadcrumb=[{"title": "Onrechtmatige daad"}], inbound_citation_count=900),
        _node("bwbr0050000_21", "article", bwb_id="BWBR0050000", article_number="21",
              display_name="Artikel 21 Cyberbeveiligingswet", heading="Zorgplicht",
              text="Een essentiële entiteit neemt passende maatregelen.",
              inbound_citation_count=1),
        _node("bwbr7_1", "article", bwb_id="BWBR7", article_number="1",
              display_name="Artikel 1 Stikstofwet", text="Stikstof en de wet.",
              inbound_citation_count=2),
        _node("celex1_6", "article", celex="32016R0679", article_number="6",
              display_name="Artikel 6 AVG", text="Rechtmatigheid van de verwerking.",
              inbound_citation_count=40),
    ]  # fmt: skip
    articles += [
        _node(f"bwbr{n}_1", "article", bwb_id=f"BWBR{n}", article_number="1",
              display_name=f"Artikel 1 Klimaatwet {n}", text="Klimaat en de wet.")
        for n in (8, 9)
    ]  # fmt: skip
    articles += [
        _node(f"bwbr0001903_{n}", "article", bwb_id="BWBR0001903",
              article_number=str(n), display_name=f"Artikel {n} Wetboek van Strafvordering",
              text=f"Over belasting en huur van de wet {n}.", inbound_citation_count=n)
        for n in range(2, 40)
    ]  # fmt: skip
    return articles


def _judgments() -> list[dict[str, Any]]:
    judgments = [
        _node("ecli_nl_hr_1919_1", "judgment", ecli="ECLI:NL:HR:1919:1",
              display_name="Hoge Raad 1919 Lindenbaum/Cohen", names=["Lindenbaum/Cohen"],
              summary="Onrechtmatige daad.", date_eff="1919-01-31",
              inbound_citation_count=50),
        _node("ecli_nl_rvs_2007_bb0782", "judgment", ecli="ECLI:NL:RVS:2007:BB0782",
              display_name="Raad van State, 2007-08-01 / 200604968/1",
              summary="Bestemmingsplan Esse Zoom.", date_eff="2007-08-01",
              parties=[
                  _party("[appellanten]", "Appellant", "first",
                         _person("mr. drs. R. van Gelder", "advocaat")),
                  _party("het college van gedeputeerde staten van Zuid-Holland",
                         "Verweerder", "second",
                         _person("mr. I.T.F. Vermeulen", "gemachtigde")),
              ]),
        _node("ecli_nl_rvs_2010_1", "judgment", ecli="ECLI:NL:RVS:2010:1",
              display_name="Raad van State, 2010-01-01 / 1",
              summary="Een geschil over huur.", date_eff="2010-01-01",
              parties=[_party("[appellant]", "Appellant", "first",
                              _person("mr. P. van Gelder", "advocaat"))]),
        _node("ecli_nl_rbams_2021_1", "judgment", ecli="ECLI:NL:RBAMS:2021:1",
              display_name="Rechtbank Amsterdam 2021-01-01 / C/13/1 HA ZA",
              summary="Ontbinding van de huurovereenkomst.", date_eff="2021-01-01",
              inbound_citation_count=2),
        _node("ecli_nl_ghams_2021_2", "judgment", ecli="ECLI:NL:GHAMS:2021:2",
              display_name="Gerechtshof Amsterdam 2021-06-01 / 200.1",
              summary="Huurovereenkomst, hoger beroep.", date_eff="2021-06-01",
              same_as="judgments/ecli_nl_rbams_2021_1"),
    ]  # fmt: skip
    judgments += [
        _node(f"klimaat_{y}", "judgment", ecli=f"ECLI:NL:HR:{y}:9",
              display_name=f"Hoge Raad {y}", summary="Klimaat en de staat.",
              date_eff=f"{y}-06-06")
        for y in (2015, 2019, 2020)
    ]  # fmt: skip
    judgments += [
        _node(f"j_{n}", "judgment", ecli=f"ECLI:NL:HR:2026:{n}",
              display_name=f"Hoge Raad 2026-01-01 / {n}",
              summary=("Een geschil over belasting." if n % 3 == 0
                       else "Een geschil over pacht."),
              inbound_citation_count=n % 7, date_eff=f"2026-01-{n % 28 + 1:02d}")
        for n in range(60)
    ]  # fmt: skip
    return judgments


def _tk(key: str, **props: Any) -> dict[str, Any]:
    return _node(key, "document", labels=["TK"], **props)


def _documents() -> list[dict[str, Any]]:
    documents = [
        _tk("amendement_36000_12", title="Amendement van het lid Jansen over de"
            " huurovereenkomst", kind="Amendement", sequence=12, dossier_numbers=["36000"],
            dossier_number="36000", date="2025-11-04", external_id="kst-36000-12"),
        _tk("brief_36000_13", title="Brief over de Stikstofwet", kind="Brief regering",
            sequence=13, dossier_numbers=["36000"], dossier_number="36000",
            date="2025-11-05", external_id="kst-36000-13"),
        _node("ek_36000_a", "document", labels=["EK"], title="Memorie van antwoord"
              " huur", kind="Memorie van antwoord", number="A", dossier_numbers=["36000"],
              dossier_number="36000", date="2026-01-10"),
        _tk("d2019", title="Brief over klimaat", kind="Brief regering",
            date="2019-12-31T14:00:00"),
        _tk("d2020", title="Brief over klimaat", kind="Brief regering",
            date="2020-01-01"),
    ]  # fmt: skip
    documents += [
        _tk(f"doc_{n}", title=f"Brief over belasting {n}" if n % 2 else f"Brief {n}",
            kind="Brief regering", date=f"2026-02-{n % 28 + 1:02d}")
        for n in range(30)
    ]  # fmt: skip
    return documents


def _dossiers() -> list[dict[str, Any]]:
    return [
        _node("36000", "dossier", number="36000", label="36000",
              title="Wijziging van de Huurprijzenwet (Wet betaalbare huur)",
              kind="Wetsvoorstel", opened_on="2022-03-01", last_activity="2025-11-05"),
        _node("36764", "dossier", number="36764", label="36764",
              title="Regels over de beveiliging van netwerk- en informatiesystemen",
              kind="Wetsvoorstel", opened_on="2025-01-01", last_activity="2026-05-01"),
        _node("2018", "dossier", number="2018", label="2018", title="Klimaatakkoord",
              kind="Overig", opened_on="2018-03-01"),
        _node("2019", "dossier", number="2019", label="2019", title="Klimaatakkoord",
              kind="Overig", opened_on="2019-03-01"),
        _node("31000", "dossier", number="31000", label="31000",
              title="Middensegment huur", kind="Overig", opened_on="2008-01-01"),
    ]  # fmt: skip


def _people() -> dict[str, list[dict[str, Any]]]:
    return {
        "members": [
            _node("m1", "member", name="Jan de Vries", party="VVD", active=True,
                  faction_memberships=[{"abbreviation": "VVD", "name": "Volkspartij"}]),
            _node("m2", "member", name="Piet de Vries", party="CDA", active=False,
                  roles=[{"role": "lid"}]),
            _node("m3", "member", name="Dilan Yeşilgöz-Zegerius", party="VVD",
                  active=True),
            _node("m4", "member", name="Jan Jansen", faction_memberships=[
                {"name": "Christen-Democratisch Appèl"}]),
        ],
        "factions": [
            _node("cda", "faction", name="Christen-Democratisch Appèl",
                  abbreviation="CDA", active=True, seats=5),
            _node("vvd", "faction", name="Volkspartij voor Vrijheid en Democratie",
                  abbreviation="VVD", active=True, seats=24),
        ],
        "committees": [
            _node("bzk", "committee", name="Binnenlandse Zaken", abbreviation="BiZa",
                  slug="binnenlandse-zaken"),
            _node("vro", "committee", name="Volkshuisvesting en Ruimtelijke Ordening",
                  abbreviation="VRO", slug="volkshuisvesting"),
        ],
        "cabinets": [
            _node("schoof", "cabinet", name="kabinet-Schoof", from_date="2024-07-02"),
            _node("rutte4", "cabinet", name="kabinet-Rutte IV", from_date="2022-01-10",
                  to_date="2024-07-02"),
        ],
        "commitments": [
            _node(f"c{y}", "commitment", display_name="Klimaatbrief", text="klimaat",
                  number=f"TZ{y}09-011", made_on=f"{y}-02-02", status="open")
            for y in (2018, 2019, 2026)
        ] + [
            _node("c_huur", "commitment", display_name="Huurbrief",
                  text="Een brief over huur en de wet", number="TZ202609-011",
                  made_on="2026-09-01"),
        ],
        "decisions": [
            _node(f"v{y}", "decision", subject="Motie over klimaat", kind="Motie",
                  date=f"{y}-05-05", passed=True, chamber="TK")
            for y in (2018, 2019)
        ] + [
            _node("v_huur", "decision", subject="Wet betaalbare huur",
                  kind="Wetgeving", date="2024-03-01", passed=True,
                  dossier_numbers=["36000"]),
        ],
    }  # fmt: skip


def seed(store: GraphStore) -> None:
    """A graph with hits of every type: names, identifiers, words of every frequency, a
    period and the terms and laws a word stands for."""
    version_cache.clear()
    store.bulk_insert_or_update_nodes("instruments", _instruments())
    store.bulk_insert_or_update_nodes("articles", _articles())
    store.bulk_insert_or_update_nodes("judgments", _judgments())
    store.bulk_insert_or_update_nodes("documents", _documents())
    store.bulk_insert_or_update_nodes("dossiers", _dossiers())
    for collection, nodes in _people().items():
        store.bulk_insert_or_update_nodes(collection, nodes)
    store.bulk_insert_or_update_edges(
        [
            _edge("cbw_bill", "instruments/bwbr0050000", "dossiers/36764",
                  RELATION_LEGISLATED_IN),
        ]
    )  # fmt: skip
    store.execute(
        "INSERT INTO lg_article_terms (article_id, terms) VALUES"
        " ('articles/bwbr0001854_41', lg_tokens('noodweer')),"
        " ('articles/bwbr0005289_6-162', lg_tokens('wanprestatie belasting'))"
    )
    for table in ("articles", "judgments", "documents", "instruments", "dossiers"):
        store.execute(f"ANALYZE {table}")
    load_notation_parser(
        store
    )  # kept: no search takes the query as words for want of it


def _hits(found: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {t: [dict(hit) for hit in hits] for t, hits in found.items()}


def answers(store: GraphStore) -> dict[str, Any]:
    """Every case: its name and what the search answers."""
    found: dict[str, Any] = {}
    for q in QUERIES:
        found[f"all {q}"] = _hits(search_all(store, q=q, types=TYPES))
        hits, partial = search_full(store, q=q, types=TYPES, limit=3)
        found[f"full 3 {q}"] = {"hits": _hits(hits), "partial": sorted(partial)}
        hits, partial = search_live(store, q=q, types=TYPES)
        found[f"live {q}"] = {"hits": _hits(hits), "partial": sorted(partial)}
        hits, partial = search_live(store, q=q, types=TYPES, limit=1)
        found[f"live 1 {q}"] = {"hits": _hits(hits), "partial": sorted(partial)}
    period = Period("2019-01-01", "2019-12-31")
    for q in ("klimaat", "wet", "ECLI:NL:HR:2019:9", "van gelder"):
        found[f"all period {q}"] = _hits(
            search_all(store, q=q, types=TYPES, period=period)
        )
        hits, partial = search_live(store, q=q, types=TYPES, period=period)
        found[f"live period {q}"] = {"hits": _hits(hits), "partial": sorted(partial)}
    for kinds in (["amendement"], ["wetsvoorstel"], ["Brief regering", "overig"]):
        for q in ("huur", "brief", "klimaat"):
            name = f"{','.join(kinds)} {q}"
            found[f"all kinds {name}"] = _hits(
                search_all(store, q=q, types=["documents", "dossiers"], kinds=kinds)
            )
            hits, partial = search_live(
                store, q=q, types=["documents", "dossiers"], kinds=kinds
            )
            found[f"live kinds {name}"] = {
                "hits": _hits(hits),
                "partial": sorted(partial),
            }
    found["all one type"] = _hits(search_all(store, q="wet", types=["articles"]))
    found["all no words"] = _hits(search_all(store, q="x", types=TYPES))
    return found


def _within_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Budgets no type of the small graph runs past, however cold or busy the server."""
    monkeypatch.setattr(search_queries, "LIVE_BUDGET", 30.0)
    monkeypatch.setattr(search_queries, "FULL_BUDGET", 30.0)


def test_the_search_answers_as_pinned(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(store)
    _within_budgets(monkeypatch)
    found = answers(store)
    # the hits kept of the words searched most rank to the same answers
    search_candidates.write(store, ["belasting", "wet", "huur"])
    found["kept"] = {
        q: _hits(search_all(store, q=q, types=TYPES)) for q in ("belasting", "wet")
    }
    found["kept signatures"] = {
        table: search_candidates._search(store, table, "belasting").signature
        for table in ("articles", "judgments", "documents")
    }
    # past the budget: every type cut off, without hits
    monkeypatch.setattr(search_queries, "LIVE_BUDGET", 0.0)
    hits, partial = search_live(store, q="wet", types=TYPES)
    found["live past the budget"] = {"hits": _hits(hits), "partial": sorted(partial)}
    if os.environ.get("LAWGRAPH_WRITE_GOLDEN"):
        GOLDEN.write_text(
            json.dumps(found, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        )
    expected = json.loads(GOLDEN.read_text())
    assert found.keys() == expected.keys()
    for case, answer in expected.items():
        assert json.loads(json.dumps(found[case])) == answer, case
