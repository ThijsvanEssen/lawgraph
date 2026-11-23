"""The concepts of the curated list ``concepts`` and the query that names one."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.core import concept_articles
from lawgraph.core.concepts import (
    BLOCK,
    concept_named,
    concepts,
    eu_names,
    short_title,
)
from lawgraph.core.curated import LISTS
from lawgraph.core.models import make_node_key
from tests.optional import present


def test_a_term_names_its_article_however_it_is_written() -> None:
    article = make_node_key("BWBR0005289", "74")
    for q in (
        "wanprestatie",
        "Wanprestatie",
        " WANPRESTATIE ",
        "tekortkoming in de nakoming",
    ):
        named = present(concept_named(q, q.split()))
        assert (named.term, named.collection, named.key) == (
            "wanprestatie",
            COLLECTION_ARTICLES,
            article,
        ), q
    # its words without the stop words: what the search is asked for
    assert (
        present(concept_named("wat is wanprestatie", ["wanprestatie"])).key == article
    )
    # accents and punctuation
    assert (
        present(concept_named("Woo verzoek", ["woo", "verzoek"])).term == "woo-verzoek"
    )
    # the source that ties the term to its article: its ``why``
    assert present(concept_named("wanprestatie", ["wanprestatie"])).why == (
        "art. 6:74 BW: elke tekortkoming in de nakoming verplicht tot schadevergoeding"
    )


def test_a_term_without_an_article_names_its_law() -> None:
    gdpr = present(concept_named("GDPR", ["gdpr"]))
    assert (gdpr.collection, gdpr.key) == (
        COLLECTION_INSTRUMENTS,
        make_node_key("32016R0679"),
    )


def test_a_term_of_a_block_names_the_block() -> None:
    named = present(concept_named("bezwaar maken", ["bezwaar", "maken"]))
    assert (named.term, named.collection, named.key) == (
        "bezwaar maken",
        BLOCK,
        "bezwaar-en-beroep",
    )
    assert named.why
    blocks = concept_articles.concepts()
    assert {c.key for c in concepts().values() if c.collection == BLOCK} <= set(blocks)


def test_a_query_that_holds_a_term_names_nothing() -> None:
    for q in ("wanprestatie huur", "wanpres", "huur", ""):
        assert concept_named(q, q.split()) is None, q


def test_every_term_and_variant_names_its_own_concept() -> None:
    named = concepts()
    for term, value in LISTS["concepts"].entries().items():
        for name in (term, *(value.get("variants") or [])):
            assert present(concept_named(name, name.split())).term == term, name
    listed = {c.term for c in named.values() if c.term in LISTS["concepts"].entries()}
    assert len(listed) == len(LISTS["concepts"].entries())


def test_the_terms_of_police_and_criminal_procedure_name_their_article() -> None:
    for q, law, article in (
        ("staandehouding", "BWBR0001903", "52"),
        ("identificatiefouillering", "BWBR0001903", "55b"),
        ("fouilleren", "BWBR0001903", "56"),
        ("strafbaar feit", "BWBR0001854", "1"),
        ("benadeelde partij", "BWBR0001903", "51f"),
        ("artikel-100-brief", "BWBR0001840", "100"),
        ("artikel 100 brief", "BWBR0001840", "100"),
    ):
        named = present(concept_named(q, q.split()))
        assert named.key == make_node_key(law, article), q


def test_the_words_of_the_news_name_their_article() -> None:
    """Words a reader of the news types (NOS, nov 2026), each tied to the article read."""
    for q, law, article in (
        ("belastingschalen", "BWBR0011353", "2.10"),
        ("belastingschijven", "BWBR0011353", "2.10"),
        ("salderen", "BWBR0050714", "2.31"),
        ("salderingsregeling", "BWBR0050714", "2.31"),
        ("helmplicht", "BWBR0004825", "60"),
        ("treinkaartje", "BWBR0011470", "70"),
        ("zwartrijden", "BWBR0011470", "70"),
        ("vervroegde invrijheidstelling", "BWBR0001903", "6:2:10"),
        ("tussentijdse verkiezingen gemeenteraad", "BWBR0001840", "129"),
        ("motie van wantrouwen wethouder", "BWBR0005416", "49"),
        ("Digital Services Act", "32022R2065", None),
    ):
        named = present(concept_named(q, q.split()))
        key = make_node_key(law, article) if article else make_node_key(law)
        assert named.key == key, q


def test_an_eu_act_is_named_by_its_names() -> None:
    """The name of an act of ``eu-core``, its abbreviation or English name in brackets
    and the short title CELLAR gives name the act, with its name as the term."""
    dsa = make_node_key("32022R2065")
    for q in ("DSA", "dsa", "Digitaledienstenverordening"):
        named = present(concept_named(q, q.split()))
        assert (named.collection, named.key, named.term) == (
            COLLECTION_INSTRUMENTS,
            dsa,
            "Digitaledienstenverordening (DSA)",
        ), q
        # no source ties a name of the act to it: it is its own name
        assert named.why is None, q
    ai = make_node_key("32024R1689")
    for q in ("AI Act", "AI-verordening", "verordening artificiële intelligentie"):
        assert present(concept_named(q, q.split())).key == ai, q
    # each of two names in one bracket
    assert present(concept_named("AVG", ["avg"])).key == make_node_key("32016R0679")
    # a name before a comma
    assert present(concept_named("NIS2", ["nis2"])).key == make_node_key("32022L2555")


def test_a_term_of_the_list_goes_before_an_eu_name() -> None:
    assert present(concept_named("GDPR", ["gdpr"])).term == "gdpr"


def test_a_name_two_eu_acts_share_names_neither() -> None:
    # RED II and RED III are both "Hernieuwbare energie"
    assert concept_named("Hernieuwbare energie", ["hernieuwbare", "energie"]) is None
    assert present(concept_named("RED III", ["red", "iii"])).key == make_node_key(
        "32023L2413"
    )


def test_what_is_no_name_of_an_eu_act() -> None:
    # a bracket of words in lower case says what the act is about
    assert eu_names("Geldovermakingen en cryptoactiva (traceerbaarheid)", "x") == [
        "Geldovermakingen en cryptoactiva"
    ]
    assert eu_names("Mededingingsregels (artt. 101-102 VWEU)", "x") == [
        "Mededingingsregels"
    ]
    assert short_title("Verordening (EU) nr. 604/2013 (herschikking)") is None
    assert short_title("Richtlijn 2019/770 (Voor de EER relevante tekst.)") is None
    assert (
        short_title(
            "Verordening (EU) 2022/2065 (digitaledienstenverordening) "
            "(Voor de EER relevante tekst)"
        )
        == "digitaledienstenverordening"
    )
    assert short_title(
        "Richtlijn 2005/29/EG („Richtlijn oneerlijke handelspraktijken”)"
    ) == ("Richtlijn oneerlijke handelspraktijken")
