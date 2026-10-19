"""The judgments of the courts of the European Union as EUR-Lex holds them: what CELLAR says
of them, their text, and the judgment ``normalize eurlex`` makes of a record.

The fixtures are real: the HTML CELLAR serves of C-160/20 (2022, the XHTML of today), C-438/05
(2007, the HTML of before) and 26/63 (1964, the oldest page), and the answer of CELLAR to the
query of ``EUClient.judgment_facts`` for them and C-562/21.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from lawgraph.clients.eu import EUClient
from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_EURLEX_CELEX,
    SOURCE_CJEU,
    SOURCE_EURLEX,
)
from lawgraph.core import cjeu
from lawgraph.core.case_numbers import Referral
from lawgraph.core.ecli import eu_ecli_mentions
from lawgraph.core.official_urls import judgment_url
from lawgraph.db.raw import raw_key
from lawgraph.pipelines.normalize.eurlex import cjeu_judgment
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from tests.fakes import InMemoryStore, ScriptedSession, Sent
from tests.paths import fixture_text

pytestmark = pytest.mark.usefixtures("raw_reads")

ROOKPREVENTIE = "62020CJ0160"
VIKING = "62005CJ0438"
PISTOJ = "61963CJ0026"
FACTS = json.loads(fixture_text("cellar_cjeu_facts.json"))


def _facts() -> dict[str, dict[str, str]]:
    return EUClient(session=ScriptedSession(lambda sent: FACTS)).judgment_facts(
        [ROOKPREVENTIE, VIKING, PISTOJ, "62021CJ0562"]
    )


# ── the CELEX number ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("celex", "number", "kind"),
    [
        ("62018CJ0311", "C-311/18", "arrest"),
        ("62021TJ0441", "T-441/21", "arrest"),
        ("62018CO0311", "C-311/18", "beschikking"),
        ("62018CC0311", "C-311/18", "conclusie"),
        ("62009FJ0012", "F-12/09", "arrest"),
        # brought before the General Court came: no letter
        (PISTOJ, "26/63", "arrest"),
        ("32016R0679", None, None),
    ],
)
def test_the_case_number_and_kind_come_from_the_celex_number(
    celex: str, number: str | None, kind: str | None
) -> None:
    assert cjeu.case_number(celex) == number
    assert cjeu.decision_kind(celex) == kind


def test_case_law_is_sector_6() -> None:
    assert [
        cjeu.is_case_law(c) for c in (ROOKPREVENTIE, "32016R0679", "52020PC0825")
    ] == [
        True,
        False,
        False,
    ]


# ── what CELLAR says of a judgment ──────────────────────────────────────────


def test_cellar_gives_the_ecli_date_title_national_decisions_and_country() -> None:
    queries: list[str] = []

    def answer(sent: Sent) -> Any:
        queries.append(sent.params["query"])
        return FACTS

    facts = EUClient(session=ScriptedSession(answer)).judgment_facts([ROOKPREVENTIE])
    rookpreventie = facts[ROOKPREVENTIE]
    assert rookpreventie["ecli"] == "ECLI:EU:C:2022:101"
    assert rookpreventie["date"] == "2022-02-22"
    assert rookpreventie["country"] == "NLD"
    assert rookpreventie["title"].startswith("Arrest van het Hof (Grote kamer)")
    assert "*A9* Rechtbank Rotterdam" in rookpreventie["national"]
    # the oldest has neither national decisions nor a country
    assert set(_facts()[PISTOJ]) == {"ecli", "date", "title"}
    assert '"62020CJ0160"^^<http://www.w3.org/2001/XMLSchema#string>' in queries[0]
    assert "language/NLD" in queries[0]


def test_of_joined_cases_one_title_is_kept_the_same_on_every_run() -> None:
    assert cjeu.parties(_facts()["62021CJ0562"]["title"]) == "X en Y"


def test_the_parties_are_the_second_part_of_the_title() -> None:
    facts = _facts()
    assert cjeu.parties(facts[ROOKPREVENTIE]["title"]) == (
        "Stichting Rookpreventie Jeugd e.a. tegen Staatssecretaris van Volksgezondheid, "
        "Welzijn en Sport"
    )
    assert cjeu.parties(facts[PISTOJ]["title"]) == (
        "Piergiovanni Pistoj tegen Commissie van de Europese Economische Gemeenschap"
    )
    assert cjeu.parties("Arrest van het Hof van 1 juli 1964.") is None


def test_the_referring_decision_is_the_a9_line_of_the_national_decisions() -> None:
    facts = _facts()
    assert cjeu.referrals(facts[ROOKPREVENTIE]["national"]) == [
        Referral(case_numbers=("ROT 19/1249",), date="2020-03-20")
    ]
    # two referring decisions; brackets inside the case number stay in it
    assert cjeu.referrals(facts["62021CJ0562"]["national"]) == [
        Referral(case_numbers=("13/751539-21",), date="2021-09-14"),
        Referral(case_numbers=("13/752022-20 (EAB III)",), date="2021-09-14"),
    ]
    # an earlier decision (*A8*) is not the referring one; the brackets that end it count
    assert cjeu.referrals(facts[VIKING]["national"]) == [
        Referral(case_numbers=("A3/2005/1393", "A3/2005/1394"), date="2005-11-23")
    ]
    by_ecli = "<p>*A9* Hoge Raad, Arrest van 01/02/2019 (ECLI:NL:HR:2019:123)</p>"
    assert cjeu.referrals(by_ecli) == [Referral(eclis=("ECLI:NL:HR:2019:123",))]


# ── the text ─────────────────────────────────────────────────────────────────


def _numbered(paragraphs: list[dict[str, Any]]) -> list[str]:
    return [p["number"] for p in paragraphs if p["number"]]


def test_the_numbered_paragraphs_are_rows_of_the_xhtml_of_today() -> None:
    read = cjeu.read_judgment(fixture_text("cjeu_62020cj0160.html"))
    assert _numbered(read.paragraphs) == [str(n) for n in range(1, 87)]
    first = next(p for p in read.paragraphs if p["number"] == "1")
    assert first["id"] == "par-1" and first["kind"] == "body"
    assert first["text"].startswith("Het verzoek om een prejudiciële beslissing")
    assert read.paragraphs[0] == {
        "id": read.paragraphs[0]["id"],
        "number": None,
        "kind": "heading",
        "text": "ARREST VAN HET HOF (Grote kamer)",
    }
    assert read.text is not None and read.text.startswith("ARREST VAN HET HOF")
    assert "\n\n1 Het verzoek om een prejudiciële beslissing" in read.text


def test_the_numbered_paragraphs_open_with_their_number_in_the_html_of_before() -> None:
    read = cjeu.read_judgment(fixture_text("cjeu_62005cj0438.html"))
    assert _numbered(read.paragraphs) == [str(n) for n in range(1, 92)]
    assert {"Toepasselijke bepalingen", "Gemeenschapsregeling"} <= {
        p["text"] for p in read.paragraphs if p["kind"] in ("heading", "subheading")
    }


def test_the_oldest_page_is_its_text_without_the_contents() -> None:
    read = cjeu.read_judgment(fixture_text("cjeu_61963cj0026.html"))
    texts = [p["text"] for p in read.paragraphs]
    assert "Samenvatting Partijen Onderwerp" not in " ".join(texts)
    assert "Avis juridique important" not in " ".join(texts)
    assert texts[-1] == "ONTZEGT HET MEER OF ANDERS GEVORDERDE ."


def test_the_court_cites_a_judgment_by_its_ecli_without_ecli() -> None:
    text = "arrest van 6 oktober 2015, Schrems, C‑362/14, EU:C:2015:650, punt 73"
    found = eu_ecli_mentions(text)
    assert found == [("ECLI:EU:C:2015:650", 46, 59)]
    assert text[46:59] == "EU:C:2015:650"
    assert eu_ecli_mentions("ECLI:EU:T:2019:1 en EU:X:2019:1") == [
        ("ECLI:EU:T:2019:1", 0, 16)
    ]


# ── retrieve and normalize ───────────────────────────────────────────────────


class _Cellar:
    """CELLAR with the HTML of every act and the facts of the fixture."""

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    def last_modified(self, celex_ids: list[str]) -> dict[str, str]:
        return {}

    def judgment_facts(self, celex_ids: list[str]) -> dict[str, dict[str, str]]:
        self.asked.append(celex_ids)
        return {c: f for c, f in _facts().items() if c in celex_ids}

    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        return f"<html>{celex}</html>"


def test_a_judgment_is_stored_with_what_cellar_says_of_it() -> None:
    store, cellar = InMemoryStore(), _Cellar()
    EurlexRetrievePipeline(store=store, eu_client=cast(EUClient, cellar)).run(
        celex_ids=["32016R0679", ROOKPREVENTIE]
    )
    assert cellar.asked == [[ROOKPREVENTIE]]  # an act has no facts to ask
    meta = store.raw[raw_key(SOURCE_EURLEX, RAW_KIND_EURLEX_CELEX, ROOKPREVENTIE)][
        "meta"
    ]
    assert meta["ecli"] == "ECLI:EU:C:2022:101" and meta["country"] == "NLD"
    act = store.raw[raw_key(SOURCE_EURLEX, RAW_KIND_EURLEX_CELEX, "32016R0679")]
    assert set(act["meta"]) == {"celex", "lang", "modified"}


def test_a_record_of_case_law_becomes_a_judgment_keyed_by_its_ecli() -> None:
    facts = {"celex": ROOKPREVENTIE, "lang": "NL", **_facts()[ROOKPREVENTIE]}
    node = cjeu_judgment(ROOKPREVENTIE, fixture_text("cjeu_62020cj0160.html"), facts)
    assert node is not None
    assert (node.collection, node.key) == (COLLECTION_JUDGMENTS, "ecli_eu_c_2022_101")
    props = node.props
    assert {
        k: props[k]
        for k in (
            "source",
            "ecli",
            "celex",
            "external_id",
            "case_number",
            "case_number_keys",
            "decision_kind",
            "court",
            "date",
        )
    } == {
        "source": SOURCE_CJEU,
        "ecli": "ECLI:EU:C:2022:101",
        "celex": ROOKPREVENTIE,
        "external_id": ROOKPREVENTIE,
        "case_number": "C-160/20",
        "case_number_keys": ["c-160/20"],
        "decision_kind": "arrest",
        "court": "Hof van Justitie van de Europese Unie",
        "date": "2022-02-22",
    }
    assert props["display_name"] == props["title"]
    assert props["title"].startswith("Stichting Rookpreventie Jeugd e.a. tegen")
    assert len(props["paragraphs"]) > 86 and props["meta"] == facts
    assert judgment_url(props) == (
        "https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:62020CJ0160"
    )


def test_a_record_of_case_law_without_its_ecli_makes_no_judgment() -> None:
    assert cjeu_judgment(ROOKPREVENTIE, "<html/>", {"celex": ROOKPREVENTIE}) is None
