"""The graph the plan tests run the routes on: a node or two of every kind the routes read,
and rows that no route asks for, so that the planner does not read a table whole for
being small."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.schema import NODE_COLLECTIONS

BWB = "BWBR0001"
FILLER = 10_000
ECLI = "ECLI:NL:HR:2020:1"
CELEX = "32022L2555"


def node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def edge(
    key: str, source: str, target: str, relation: str, **extra: Any
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        "created_at": "2026-09-01T00:00:00Z",
        **extra,
    }


def seed(store: GraphStore, filler: int = FILLER) -> None:
    """The graph the plans of the routes are made on, with *filler* rows in each table."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            node(
                "bwbr0001",
                "instrument",
                bwb_id=BWB,
                title="Wet op de proef",
                citation_title="Proefwet",
                short_title="Pw",
                jurisdiction="nl",
                kind="wet",
                article_count=2,
            ),
            # an AMvB issued under the law, and a regulation issued under the AMvB
            node("bwbr0002", "instrument", bwb_id="BWBR0002", kind="amvb"),
            node(
                "bwbr0003",
                "instrument",
                bwb_id="BWBR0003",
                kind="ministeriele-regeling",
            ),
            node(
                CELEX.lower(),
                "instrument",
                celex=CELEX,
                citation_title="Richtlijn (EU) 2022/2555",
                jurisdiction="eu",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            node(
                f"bwbr0001_{n}",
                "article",
                bwb_id=BWB,
                article_number=str(n),
                stam_id=f"s{n}",
                display_name=f"Artikel {n} Proefwet",
                heading="Onrechtmatige daad",
                text="Hij die jegens een ander een onrechtmatige daad pleegt.",
                breadcrumb=[{"type": "hoofdstuk", "label": "Hoofdstuk 1"}],
            )
            for n in (1, 2)
        ]
        + [
            node(f"{law}_1", "article", bwb_id=law.upper(), article_number="1")
            for law in ("bwbr0002", "bwbr0003")
        ]
        + [
            node(
                f"{CELEX.lower()}_21",
                "article",
                celex=CELEX,
                article_number="21",
                text="De lidstaten zorgen ervoor dat …",
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            node(
                "av1",
                "article_version",
                bwb_id=BWB,
                article_number="1",
                stam_id="s1",
                valid_from="2010-01-01",
                breadcrumb=[{"type": "hoofdstuk", "label": "Hoofdstuk 1"}],
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [node("iv1", "instrument_version", bwb_id=BWB, valid_from="2010-01-01")],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            node(
                "ecli_nl_hr_2020_1",
                "judgment",
                ecli=ECLI,
                source="rechtspraak",
                court_code="HR",
                court="Hoge Raad",
                tier="hoge_raad",
                date_eff="2020-01-01",
                display_name="HR 1 januari 2020, onrechtmatige daad",
                summary="Onrechtmatige daad.",
                subjects=["Strafrecht"],
                inbound_citation_count=1,
                stub=False,
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            node(
                "d1",
                "document",
                title="Memorie van toelichting",
                kind="memorie",
                dossier_number="36000",
                dossier_numbers=["36000"],
                sequence=3,
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "annexes", [node("a1", "annex", bwb_id=BWB, title="Bijlage")]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            node(
                "36000",
                "dossier",
                number="36000",
                label="36000",
                # a law the title names: the dossier looks it up (``get_laws_named``)
                title="Wijziging van de Wet op de proef",
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [node("stb_2026_1", "instrument", kind="publicatie", official_id="stb-2026-1")],
    )
    membership = {
        "faction_id": "factions/f1",
        "faction_key": "f1",
        "abbreviation": "F",
        "from_date": "2010-01-01",
        "to_date": None,
    }
    store.bulk_insert_or_update_nodes(
        "members",
        [
            node(
                "m1",
                "member",
                name="A. Lid",
                slug="a-lid",
                faction_memberships=[membership],
            )
        ],
    )
    store.bulk_insert_or_update_nodes("factions", [node("f1", "faction", name="F")])
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            node("k1", "cabinet", name="kabinet-Een", prime_minister="m1",
                  previous="k0", factions=["f1"]),
            node("k0", "cabinet", name="kabinet-Nul"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "committees", [node("c1", "committee", name="Commissie", slug="c1")]
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [node("stb_2025_263", "instrument", kind="publicatie",
               citation_title="Stb. 2025, 263", official_id="stb-2025-263")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "commitments",
        [node("tz1", "commitment", number="TZ202609-124", text="Een brief.",
               member_key="m1", cabinet="k1")],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "decisions",
        [node(f"b{n}", "decision", date=f"2020-01-0{n}") for n in (1, 2)],
    )
    store.bulk_insert_or_update_nodes(
        "activities",
        [node("act1", "activity", number="2026A01323", kind="Wetgevingsoverleg",
               date="2026-03-23", status="Uitgevoerd", dossier_numbers=["36000"])],
    )  # fmt: skip
    article = f"articles/{BWB.lower()}_1"
    store.bulk_insert_or_update_edges(
        [
            # a debate: its committee, a paper and a commitment made in it, a vote taken
            edge("al", "activities/act1", "committees/c1", "LED_BY"),
            edge("ad", "documents/d1", "activities/act1", "MADE_IN"),
            edge("at", "commitments/tz1", "activities/act1", "MADE_IN"),
            edge("ab", "decisions/b1", "activities/act1", "MADE_IN"),
            edge("mf", "members/m1", "factions/f1", "MEMBER_OF"),
            edge("mc", "members/m1", "committees/c1", "MEMBER_OF"),
            edge("mk", "members/m1", "cabinets/k1", "SERVED_IN"),
            edge("ma", "members/m1", "documents/d1", "AUTHORED"),
            edge("fv", "factions/f1", "decisions/b1", "VOTED", meta={"choice": "Voor"}),
            edge("mv", "members/m1", "decisions/b2", "VOTED", meta={"choice": "Tegen"}),
        ]
    )
    store.bulk_insert_or_update_edges(
        [
            edge("p1", article, "instruments/bwbr0001", "PART_OF"),
            edge("p2", f"articles/{BWB.lower()}_2", "instruments/bwbr0001", "PART_OF"),
            edge(
                "r1",
                article,
                f"articles/{BWB.lower()}_2",
                "REFERS_TO",
                semantic_type="conditional_requirement",
            ),
            edge(
                "r2",
                "judgments/ecli_nl_hr_2020_1",
                article,
                "REFERS_TO",
                meta={"paragraphs": [1]},
            ),
            edge("x1", "documents/d1", article, "EXPLAINS"),
            edge(
                "b1",
                "instruments/stb_2026_1",
                article,
                "BASED_ON",
                meta={"text": "1, eerste lid"},
            ),
            edge("b2", "instruments/bwbr0002", article, "BASED_ON"),
            edge("b3", "instruments/bwbr0003", "articles/bwbr0002_1", "BASED_ON"),
            edge("r3", "articles/bwbr0002_1", article, "REFERS_TO"),
            edge("r4", "articles/bwbr0003_1", article, "REFERS_TO"),
            edge("s1", article, "annexes/a1", "SCOPED_BY"),
            # a bill: the publication that enacts it, and a paper that proposes a change
            edge("l1", "instruments/stb_2026_1", "dossiers/36000", "LEGISLATED_IN"),
            # the law the bill became
            edge("l2", "instruments/bwbr0001", "dossiers/36000", "LEGISLATED_IN"),
            edge(
                "m1",
                "instruments/stb_2026_1",
                article,
                "AMENDS",
                meta={"effective_date": "2026-01-01"},
            ),
            edge("d1p", "documents/d1", "dossiers/36000", "PART_OF"),
            edge(
                "v1",
                "documents/d1",
                f"articles/{BWB.lower()}_2",
                "AMENDS",
                status="voorgesteld",
            ),
        ]
    )
    store.execute(
        "INSERT INTO lg_article_terms (article_id, terms)"
        f" VALUES ('articles/{BWB.lower()}_1', ARRAY['noodwer'])"
    )
    fill(store, filler)
    store.vacuum_analyze()


def fill(store: GraphStore, filler: int = FILLER) -> None:
    """Rows that no route asks for: on tables of one or two rows the planner reads them
    whole whatever indexes there are; on a thousand, as on the real ones, it does not."""
    statements = [
        f"INSERT INTO {table} (id, type) SELECT '{table}/filler_' || n, 'filler'"
        f" FROM generate_series(1, {filler}) n"
        for table in NODE_COLLECTIONS
    ]
    statements.append(
        "INSERT INTO edges (key, from_id, to_id, doc)"
        " SELECT 'filler_' || n, 'judgments/filler_' || n % 9973,"
        " 'articles/filler_' || n % 9967, json_build_object('relation', 'FILLER',"
        # a moment of its own, as nearly every edge has: an index that starts with it is
        # no way to the edges of a node
        " 'created_at', '2020-01-01T00:00:00.' || lpad(n::text, 6, '0'))"
        f" FROM generate_series(1, {filler * 5}) n"
    )
    for statement in statements:
        store.execute(statement)
