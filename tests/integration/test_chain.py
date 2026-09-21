"""The chain as it is run: seed raw records, ``normalize all``, ``semantic all``, ``check``."""

from __future__ import annotations

from typing import Any

from lawgraph.commands.check import check
from lawgraph.db import ArangoStore
from tests.integration.seed import seed

COLLECTIONS = (
    "cases",
    "documents",
    "dossiers",
    "decisions",
    "activities",
    "commitments",
    "members",
    "factions",
    "committees",
    "instruments",
    "articles",
    "judgments",
    "edges",
)


def _counts(store: ArangoStore) -> dict[str, int]:
    return {name: store.db.collection(name).count() for name in COLLECTIONS}


def _edge_keys(store: ArangoStore) -> set[str]:
    return set(store.query("FOR e IN edges RETURN e._key"))


def test_the_whole_chain_runs_and_a_second_run_changes_nothing(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=500, judgments=100, regulations=20)

    cli("normalize", "all")
    cli("semantic", "all")
    first, first_edges = _counts(store), _edge_keys(store)

    # Every part of the model came out of it, with the edges between them.
    assert first["cases"] == 500 and first["documents"] == 500
    assert first["judgments"] >= 100 and first["instruments"] >= 20
    assert all(first[name] > 0 for name in COLLECTIONS), first

    # The judgment linkers read the XML from raw_sources (it is not kept on the node): every
    # judgment cites the next one and two articles.
    linked = "FOR e IN edges FILTER STARTS_WITH(e._from, 'judgments/') RETURN e._to"
    targets = list(store.query(linked))
    assert sum(t.startswith("judgments/") for t in targets) >= 100
    assert any(t.startswith("articles/") for t in targets)
    sample = store.db.collection("judgments").random()
    assert "raw_xml" not in sample["props"]

    # Idempotent: the same input again is the same graph, not a second copy of it.
    cli("normalize", "all")
    cli("semantic", "all")
    assert _counts(store) == first
    assert _edge_keys(store) == first_edges

    report = check(store)
    assert [p for p in report.problems if not p.startswith("raw ")] == []


def test_check_says_when_a_source_was_retrieved_and_never_normalized(
    database: str,
) -> None:
    store = ArangoStore()
    seed(store, documents=20, judgments=5, regulations=2)

    problems = check(store).problems
    assert any("tk:" in p and "no node in cases" in p for p in problems)
    assert any("rechtspraak:" in p and "no node in judgments" in p for p in problems)
    # A kind of the registry that was never retrieved is a problem too (tk-zaak was, for weeks).
    assert any(p.startswith("raw staatscourant/") for p in problems)


def test_check_says_when_normalize_is_behind(database: str, cli: Any) -> None:
    """38,577 judgments retrieved and 7,442 normalized looked like a healthy database."""
    store = ArangoStore()
    seed(store, documents=20, judgments=5, regulations=2)
    cli("normalize", "rechtspraak")
    assert not [p for p in check(store, edges=False).problems if "is behind" in p]

    seed(store, documents=20, judgments=60, regulations=2)  # 55 more arrive
    behind = [p for p in check(store, edges=False).problems if "is behind" in p]
    assert behind and behind[0].startswith(
        "rechtspraak: 60 rs-content records and 5 nodes"
    )


def test_check_finds_an_edge_without_its_node(database: str, cli: Any) -> None:
    store = ArangoStore()
    seed(store, documents=50, judgments=5, regulations=2)
    cli("normalize", "all")
    assert not [p for p in check(store).problems if p.startswith("edges")]

    victim = next(iter(store.query("FOR e IN edges LIMIT 1 RETURN e._to")))
    collection, key = victim.split("/")
    store.db.collection(collection).delete(key)
    assert [p for p in check(store).problems if p.startswith("edges")]


def test_the_basis_and_the_eu_acts_of_a_regulation_are_linked_from_its_node(
    database: str, cli: Any
) -> None:
    """``normalize bwb`` keeps them on the regulation; the semantic steps read no XML."""
    from lawgraph.config.constants import (
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_EU_CELEX,
        SOURCE_BWB,
        SOURCE_EURLEX,
    )
    from lawgraph.db import RawSourceWriter, raw_source_doc
    from tests.integration.seed import FIXTURES

    amvb = (FIXTURES / "bwb_amvb_toestand.xml").read_text()
    amvb = amvb.replace("</toestand>", "<!-- Richtlijn 32016R0679 --></toestand>")
    # the law it is issued under: the recorded extract, with the two articles it names
    basis_law = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
    for number, named in (("7", "125"), ("82", "133")):
        basis_law = basis_law.replace(f">{number}</nr>", f">{named}</nr>", 1)
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for bwb_id, xml in (
            ("BWBR0001950", amvb),  # "Gelet op artikel 125 en 133 van" BWBR0001947
            ("BWBR0001947", basis_law),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=xml,
                    meta={"bwb_id": bwb_id},
                )
            )
        writer.add(
            raw_source_doc(
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EU_CELEX,
                external_id="32016R0679",
                payload_text="<html><body><p>Artikel 1</p><p>Tekst.</p></body></html>",
                meta={"celex": "32016R0679"},
            )
        )
    cli("normalize", "all")
    cli("semantic", "bwb-grondslagen")
    cli("semantic", "bwb-implements")

    aql = """
    FOR e IN edges
        FILTER e._from == "instruments/bwbr0001950"
        FILTER e.relation IN ["BASED_ON", "IMPLEMENTS"]
        RETURN [e.relation, e._to]
    """
    assert sorted(store.query(aql)) == [
        ["BASED_ON", "articles/bwbr0001947_125"],
        ["BASED_ON", "articles/bwbr0001947_133"],
        ["IMPLEMENTS", "instruments/32016r0679"],
    ]


def test_check_says_when_a_regulation_lacks_what_the_semantic_steps_read(
    database: str, cli: Any
) -> None:
    """The copy on the node is only as good as the run that made it."""
    store = ArangoStore()
    seed(store, documents=0, judgments=0, regulations=3)
    cli("normalize", "bwb")
    assert not [p for p in check(store, edges=False).problems if "basis" in p]

    store.query(  # a regulation as a `normalize bwb` from before the props were kept left it
        "FOR i IN instruments FILTER i.props.source == 'bwb' LIMIT 1 "
        "UPDATE i WITH {props: {basis: null}} IN instruments OPTIONS {keepNull: false}"
    )
    problems = [p for p in check(store, edges=False).problems if "basis" in p]
    assert problems and "1 BWB regulations" in problems[0]
    assert "normalize bwb" in problems[0]


def test_check_says_when_no_case_names_a_dossier(database: str, cli: Any) -> None:
    store = ArangoStore()
    seed(
        store, documents=10, judgments=0, regulations=0
    )  # the seeded cases name theirs
    cli("normalize", "tk")
    assert not [p for p in check(store, edges=False).problems if "names a dossier" in p]

    store.query(
        "FOR c IN cases UPDATE c WITH {props: {dossier_numbers: []}} IN cases "
        "OPTIONS {mergeObjects: true}"
    )
    problems = [p for p in check(store, edges=False).problems if "names a dossier" in p]
    assert problems and "retrieve tk" in problems[0]


_LAW_WITH_AN_ANNEX = """<toestand bwb-id="BWBR9200001"><wetgeving soort="wet">
<citeertitel>Sectorenwet</citeertitel><wet-besluit><wettekst>
<artikel><kop><nr>1</nr></kop>
<al>De sectoren, vermeld in bijlage I, vallen onder deze wet.</al></artikel>
</wettekst></wet-besluit>
<bijlage><kop><label>Bijlage</label><nr>I</nr><titel>Sectoren</titel></kop>
<al>Energie.</al></bijlage>
</wetgeving></toestand>"""


def test_an_annex_is_a_node_of_normalize_and_a_link_of_semantic(
    database: str, cli: Any
) -> None:
    """The annex nodes were made by a semantic step that read and parsed every toestand
    again (1m48 of each `semantic all`); normalize parses them anyway."""
    from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
    from lawgraph.db import RawSourceWriter, raw_source_doc

    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id="BWBR9200001",
                payload_text=_LAW_WITH_AN_ANNEX,
                meta={"bwb_id": "BWBR9200001"},
            )
        )
    cli("normalize", "bwb")
    annex = store.db.collection("annexes").get("bwbr9200001_annex_i")
    assert annex["props"]["title"] == "Sectoren" and not annex["props"].get("stub")
    edges = (
        "FOR e IN edges FILTER e._from == @a OR e._to == @a "
        "RETURN [e.relation, e._from, e._to]"
    )
    assert list(store.query(edges, {"a": annex["_id"]})) == [
        ["PART_OF", annex["_id"], "instruments/bwbr9200001"]
    ]

    cli("semantic", "bwb-annexes")
    assert sorted(store.query(edges, {"a": annex["_id"]})) == [
        ["PART_OF", annex["_id"], "instruments/bwbr9200001"],
        ["SCOPED_BY", "articles/bwbr9200001_1", annex["_id"]],
    ]


def test_a_law_a_regulation_is_issued_under_is_a_gap_when_it_is_not_loaded(
    database: str, cli: Any
) -> None:
    """`bwb-grondslagen` leaves a basis out when its law is absent, and nothing listed
    that law as a gap: 466 laws of the rebuild, the Wft among them."""
    from lawgraph.pipelines.retrieve import _gaps

    store = ArangoStore()
    seed(
        store, documents=0, judgments=0, regulations=2
    )  # the AMvB: "Gelet op" BWBR0001947
    cli("normalize", "bwb")
    assert "BWBR0001947" in _gaps.bwb_gaps(store)
    assert "BWBR0001840" not in _gaps.bwb_gaps(store)  # the Grondwet is loaded


def test_an_eu_act_a_regulation_names_is_a_gap_until_it_is_retrieved(
    database: str, cli: Any
) -> None:
    """The CELEX id is an attribute of the link, not text of the article: a scan of the
    article texts found none, and the rebuild ended without one EU act (3,951 named)."""
    from lawgraph.config.constants import (
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_EU_CELEX,
        SOURCE_BWB,
        SOURCE_EURLEX,
    )
    from lawgraph.db import RawSourceWriter, raw_source_doc
    from lawgraph.pipelines.retrieve import _gaps
    from tests.integration.seed import FIXTURES

    amvb = (FIXTURES / "bwb_amvb_toestand.xml").read_text()
    link = '<extref doc="32016R0679" reeks="Celex">verordening (EU) 2016/679</extref>'
    amvb = amvb.replace("</toestand>", f"<!-- {link} --></toestand>")
    store = ArangoStore()

    def store_raw(source: str, kind: str, external_id: str, text: str) -> None:
        with RawSourceWriter(store) as writer:
            writer.add(
                raw_source_doc(
                    source=source,
                    kind=kind,
                    external_id=external_id,
                    payload_text=text,
                    meta={},
                )
            )

    store_raw(SOURCE_BWB, RAW_KIND_BWB_TOESTAND, "BWBR0001950", amvb)
    cli("normalize", "bwb")
    assert _gaps.eurlex_gaps(store) == ["32016R0679"]

    store_raw(SOURCE_EURLEX, RAW_KIND_EU_CELEX, "32016R0679", "<html></html>")
    assert _gaps.eurlex_gaps(store) == []
