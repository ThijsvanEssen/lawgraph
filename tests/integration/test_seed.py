"""What ``seed`` writes, and the judgments ``judgment_xml`` makes: the rows the integration
tests build on, held fixed."""

from __future__ import annotations

import hashlib
import json

from lawgraph.config.constants import COLLECTION_RAW_SOURCES
from lawgraph.db import GraphStore
from tests.integration.seed import judgment_xml, seed, seed_judgment_xml


def _rows(store: GraphStore) -> list[dict[str, object]]:
    docs = [
        {**row["doc"], "key": row["key"]}
        for row in store.query(f"SELECT key, doc FROM {COLLECTION_RAW_SOURCES}")
    ]
    return sorted(
        (
            {
                "source": doc["source"],
                "kind": doc["kind"],
                "external_id": doc["external_id"],
                "meta": doc.get("meta"),
                "payload_json": doc.get("payload_json"),
                "payload_text": doc.get("payload_text"),
            }
            for doc in store.with_payloads(docs)
        ),
        key=lambda row: (str(row["source"]), str(row["kind"]), str(row["external_id"])),
    )


def test_seed_writes_the_same_rows(database: str) -> None:
    store = GraphStore()
    assert seed(store) == 1847
    rows = _rows(store)
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row["source"]), str(row["kind"]))
        counts[key] = counts.get(key, 0) + 1
    assert counts == {
        ("bwb", "bwb-toestand-xml"): 20,
        ("rechtspraak", "rs-content"): 100,
        ("tk", "tk-activiteit"): 50,
        ("tk", "tk-commissie"): 5,
        ("tk", "tk-document"): 500,
        ("tk", "tk-dossier"): 50,
        ("tk", "tk-fractie"): 12,
        ("tk", "tk-persoon"): 60,
        ("tk", "tk-stemming"): 500,
        ("tk", "tk-toezegging"): 50,
        ("tk", "tk-zaak"): 500,
    }
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    assert digest == (
        "9b6f815dfed09a036c770a82ff6a1389e3815fe28c43660536b9c06d1a0ba3e8"
    )


def test_a_judgment_of_the_seed() -> None:
    assert seed_judgment_xml(3, paragraphs=1) == (
        '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dcterms="http://purl.org/dc/terms/"><rdf:RDF><rdf:Description>'
        "<dcterms:identifier>ECLI:NL:HR:2020:3</dcterms:identifier>"
        "<dcterms:creator>Hoge Raad</dcterms:creator><dcterms:date>2020-01-02</dcterms:date>"
        "</rdf:Description></rdf:RDF><inhoudsindicatie><para>Samenvatting.</para>"
        "</inhoudsindicatie><uitspraak><section><title><nr>1</nr>Overwegingen</title>"
        "<paragroup><nr>1.0</nr><para>De rechtbank overweegt (3.0) dat artikel 1 van de "
        "Grondwet en artikel 8:1 Awb van toepassing zijn, zie ook ECLI:NL:HR:2020:4."
        "</para></paragroup></section></uitspraak></open>"
    )


def test_a_judgment_of_numbered_paragraphs() -> None:
    assert judgment_xml(
        "ECLI:NL:HR:2020:1", "2020-03-01", [("1.1", "Zie art. 1.")]
    ) == (
        '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dcterms="http://purl.org/dc/terms/"><rdf:RDF><rdf:Description>'
        "<dcterms:identifier>ECLI:NL:HR:2020:1</dcterms:identifier>"
        "<dcterms:creator>Een rechter</dcterms:creator><dcterms:date>2020-03-01</dcterms:date>"
        "</rdf:Description></rdf:RDF><uitspraak><section>"
        "<title><nr>1</nr>Overwegingen</title>"
        "<paragroup><nr>1.1</nr><para>Zie art. 1.</para></paragroup>"
        "</section></uitspraak></open>"
    )
