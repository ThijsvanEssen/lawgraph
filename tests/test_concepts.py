"""The concepts of the curated list ``concepts`` and the query that names one."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.core.concepts import concept_named, concepts
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


def test_a_term_without_an_article_names_its_law() -> None:
    gdpr = present(concept_named("GDPR", ["gdpr"]))
    assert (gdpr.collection, gdpr.key) == (
        COLLECTION_INSTRUMENTS,
        make_node_key("32016R0679"),
    )


def test_a_query_that_holds_a_term_names_nothing() -> None:
    for q in ("wanprestatie huur", "wanpres", "huur", ""):
        assert concept_named(q, q.split()) is None, q


def test_every_term_and_variant_names_its_own_concept() -> None:
    named = concepts()
    for term, value in LISTS["concepts"].entries().items():
        for name in (term, *(value.get("variants") or [])):
            assert present(concept_named(name, name.split())).term == term, name
    assert len({c.term for c in named.values()}) == len(LISTS["concepts"].entries())


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
