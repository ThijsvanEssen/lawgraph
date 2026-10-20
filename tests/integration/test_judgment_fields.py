"""The text of a conclusion, the judgments a judgment cites and the publications of one
decision: the real ``normalize rechtspraak``, the semantic steps and the API on their answer.

The headers follow the open data of the Rechtspraak: ECLI:NL:PHR:2025:311 (a conclusion,
its text in ``<conclusie>``), and ECLI:NL:HR:1985:AW8335 with BH3435 and BV4163 (one arrest
published three times; the two old publications carry no text and name the one that
replaces them in ``dcterms:isReplacedBy``).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lawgraph.db import GraphStore
from tests.databases import Api, module_store
from tests.integration.seed import RECHTSPRAAK_NS, write_judgments

CONCLUSION = "ECLI:NL:PHR:2025:311"
RULING = "ECLI:NL:HR:2021:10"
CITED = "ECLI:NL:HR:2015:1"
KEPT = "ECLI:NL:HR:1985:AW8335"
REPLACED = ("ECLI:NL:HR:1985:BH3435", "ECLI:NL:HR:1985:BV4163")
# replaced by a publication that is not loaded: nothing to count it with
ORPHAN = "ECLI:NL:HR:2003:BV5502"


def _header(ecli: str, court: str, date: str, case_number: str, extra: str = "") -> str:
    return (
        f"<open-rechtspraak {RECHTSPRAAK_NS}><rdf:RDF><rdf:Description>"
        f"<dcterms:identifier>{ecli}</dcterms:identifier>{extra}"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        f"<psi:zaaknummer>{case_number}</psi:zaaknummer>"
    )


def _conclusion() -> str:
    return (
        _header(CONCLUSION, "Parket bij de Hoge Raad", "2025-03-28", "24/01234")
        + "<dcterms:type>Conclusie</dcterms:type></rdf:Description></rdf:RDF>"
        "<inhoudsindicatie><para>Cassatie; bestuursrecht.</para></inhoudsindicatie>"
        "<conclusie><para>PROCUREUR-GENERAAL BIJ DE HOGE RAAD DER NEDERLANDEN</para>"
        "<para>CONCLUSIE</para><para>R.J. Koopman</para>"
        "<section><title><nr>1</nr>Inleiding</title><paragroup><nr>1.1</nr>"
        "<para>De advocaat-generaal concludeert tot verwerping van het beroep.</para>"
        "</paragroup></section></conclusie></open-rechtspraak>"
    )


def _judgment(
    ecli: str, date: str, case_number: str, *, text: str | None, extra: str = ""
) -> str:
    body = (
        "<uitspraak><section><title><nr>1</nr>Beoordeling</title><paragroup>"
        f"<nr>1.1</nr><para>{text}</para></paragroup></section></uitspraak>"
        if text
        else ""
    )
    return (
        _header(ecli, "Hoge Raad", date, case_number, extra)
        + "<dcterms:type>Uitspraak</dcterms:type></rdf:Description></rdf:RDF>"
        f"{body}</open-rechtspraak>"
    )


def _replaced_by(ecli: str) -> str:
    return f"<dcterms:isReplacedBy>{ecli}</dcterms:isReplacedBy>"


JUDGMENTS = {
    CONCLUSION: _conclusion(),
    RULING: _judgment(
        RULING,
        "2021-03-05",
        "20/00001",
        text=f"Zoals eerder geoordeeld (HR 1 mei 2015, {CITED}; HR 6 maart 1985, "
        f"{REPLACED[0]}), faalt het middel.",
    ),
    CITED: _judgment(CITED, "2015-05-01", "14/00001", text="Het middel slaagt."),
    KEPT: _judgment(
        KEPT,
        "1985-03-06",
        "22 825",
        text="De Hoge Raad verwerpt het beroep.",
        extra="".join(f"<dcterms:replaces>{e}</dcterms:replaces>" for e in REPLACED),
    ),
    **{
        ecli: _judgment(
            ecli, "1985-03-06", "22 825", text=None, extra=_replaced_by(KEPT)
        )
        for ecli in REPLACED
    },
    ORPHAN: _judgment(
        ORPHAN,
        "2003-02-11",
        "00709/02",
        text=None,
        extra=_replaced_by("ECLI:NL:HR:2003:AF2343"),
    ),
}


# The tests read one database built for them all (``store``), on the worker that built it.
pytestmark = pytest.mark.xdist_group("judgment_fields")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        write_judgments(store, JUDGMENTS)
        cli("normalize", "rechtspraak")
        cli("semantic", "rechtspraak-duplicates")
        cli("semantic", "rechtspraak-citations")
        cli("semantic", "graph-list-stats")
        yield store


def test_a_conclusion_has_its_text_and_paragraphs(api: Api) -> None:
    judgment = api.get_json(f"/api/judgments/{CONCLUSION}")["judgment"]

    assert judgment["decision_kind"] == "conclusie"
    assert judgment["advocate_general"] == "R.J. Koopman"
    assert [(p["number"], p["text"]) for p in judgment["paragraphs"][-2:]] == [
        ("1", "Inleiding"),
        ("1.1", "De advocaat-generaal concludeert tot verwerping van het beroep."),
    ]
    assert "concludeert tot verwerping" in judgment["props"]["text"]


def test_a_judgment_lists_the_judgments_it_cites_and_counts_them(
    api: Api,
) -> None:
    detail = api.get_json(f"/api/judgments/{RULING}")
    listed = api.get_json("/api/judgments", q=RULING)["items"]

    assert sorted(j["ecli"] for j in detail["cited_judgments"]) == [
        "ECLI:NL:HR:1985:BH3435",
        CITED,
    ]
    assert [(j["ecli"], j["outbound_citation_count"]) for j in listed] == [(RULING, 2)]


def test_the_publications_of_one_decision_are_linked_and_counted_once(
    api: Api, store: GraphStore
) -> None:
    same_as = {
        (row["from_ecli"], row["to_ecli"])
        for row in store.query(
            "SELECT f.ecli AS from_ecli, t.ecli AS to_ecli FROM edges e"
            " LEFT JOIN judgments f ON f.id = e.from_id"
            " LEFT JOIN judgments t ON t.id = e.to_id"
            " WHERE e.relation = 'SAME_AS'"
        )
    }
    assert same_as == {(ecli, KEPT) for ecli in REPLACED}

    kept = api.get_json(f"/api/judgments/{KEPT}")
    replaced = api.get_json(f"/api/judgments/{REPLACED[0]}")
    assert sorted(j["ecli"] for j in kept["same_as"]) == sorted(REPLACED)
    assert replaced["judgment"]["same_as"] == KEPT
    assert [j["ecli"] for j in replaced["same_as"]] == [KEPT]

    # the list shows the decision once, counted with the citations of its other publications
    hr_1985 = api.get_json(
        "/api/judgments", **{"from": "1985-01-01", "to": "1985-12-31"}
    )
    assert [(j["ecli"], j["inbound_citation_count"]) for j in hr_1985["items"]] == [
        (KEPT, 1)
    ]
    assert hr_1985["total"] == 1
    assert {"value": "1985", "count": 1} in hr_1985["facets"]["year"]
    everything = api.get_json("/api/judgments")
    assert everything["total"] == len(JUDGMENTS) - len(REPLACED)
    # asked for by its ECLI, a replaced publication is found
    asked = api.get_json("/api/judgments", q=REPLACED[1])
    assert [j["ecli"] for j in asked["items"]] == [REPLACED[1]]
    # one whose replacing publication is not loaded stands alone
    orphan = api.get_json(f"/api/judgments/{ORPHAN}")
    assert (orphan["judgment"]["same_as"], orphan["same_as"]) == (None, [])


def test_the_stats_count_a_decision_once_and_its_replaced_publications_apart(
    api: Api,
) -> None:
    listed = api.get_json("/api/judgments", limit=1)["total"]
    stats = api.get_json("/api/stats")
    coverage = api.get_json("/api/stats/coverage")

    assert stats["nodes"]["judgments"] == coverage["total"] == listed
    assert sum(tier["count"] for tier in coverage["tiers"]) == listed
    assert stats["replaced"] == {"judgments": len(REPLACED)}
    assert coverage["replaced"] == len(REPLACED)


def test_a_publication_names_the_one_that_replaces_it_loaded_or_not(
    api: Api,
) -> None:
    def replaced_by(ecli: str) -> str | None:
        judgment = api.get_json(f"/api/judgments/{ecli}")["judgment"]
        return judgment["replaced_by"]

    assert replaced_by(REPLACED[0]) == KEPT
    assert replaced_by(ORPHAN) == "ECLI:NL:HR:2003:AF2343"
    assert replaced_by(KEPT) is None
