"""The post and ministry of a government function, however a source writes it."""

from __future__ import annotations

import pytest

from lawgraph.core.ministries import (
    MINISTRIES,
    MINISTRY_BY_KEY,
    classify_function,
    protocol_rank,
)

# Every distinct function string of lawgraph_small on 25 Sep 2026 (Wikidata posts,
# commitment roles, signatures), with the post and ministry it names.
FUNCTIONS = [
    ("minister-president van Nederland", "minister-president", "az"),
    ("Nederlands minister van Algemene Zaken", "minister", "az"),
    ("viceminister-president van Nederland", "viceminister-president", None),
    ("Nederlands minister van Financiën", "minister", "fin"),
    ("minister van Financiën", "minister", "fin"),
    ("Minister van Economische Zaken en Klimaat", "minister", "ezk"),
    ("minister van Volkshuisvesting en Ruimtelijke Ordening", "minister", "vro"),
    (
        "Nederlands minister van Volkshuisvesting, Ruimtelijke Ordening en Milieu",
        "minister",
        "vrom",
    ),
    ("Nederlands minister van Verkeer en Waterstaat", "minister", "venw"),
    ("minister van Veiligheid en Justitie", "minister", "venj"),
    ("minister van Justitie", "minister", "justitie"),
    ("Minister van Landbouw, Visserij, Voedselzekerheid en Natuur", "minister", "lvvn"),
    ("Minister van landbouw, natuur en voedselkwaliteit", "minister", "lnv"),
    ("minister van Onderwijs en Wetenschappen", "minister", "ow"),
    ("Minister van Buitenlandse Handel en Ontwikkelingssamenwerking", "minister", "bz"),
    ("Minister van Werk en Participatie", "minister", "szw"),
    ("minister van Langdurige Zorg, Jeugd en Sport", "minister", "vws"),
    ("Minister van Asiel en Migratie", "minister", "aenm"),
    ("minister van Klimaat en Groene Groei", "minister", "kgg"),
    ("Minister van Algemene Oorlogvoering", "minister", "aok"),
    ("minister van openbare werken", "minister", "opw"),
    # a minister without portfolio: the ministry the post is placed under
    ("Minister voor Klimaat en Energie", "minister_zonder_portefeuille", "ezk"),
    (
        "Minister voor Basis- en Voortgezet Onderwijs en Media",
        "minister_zonder_portefeuille",
        "ocw",
    ),
    ("Minister voor Rechtsbescherming", "minister_zonder_portefeuille", "jenv"),
    ("Minister voor Ontwikkelingssamenwerking", "minister_zonder_portefeuille", "bz"),
    ("minister voor Jeugd en Gezin", "minister_zonder_portefeuille", "vws"),
    (
        "Minister voor Wonen, Wijken en Integratie",
        "minister_zonder_portefeuille",
        "vrom",
    ),
    ("minister voor Wonen en Rijksdienst", "minister_zonder_portefeuille", "bzk"),
    # the name of a ministry, but a post without portfolio at BZK (Rutte IV)
    (
        "minister voor Volkshuisvesting en Ruimtelijke Ordening",
        "minister_zonder_portefeuille",
        "bzk",
    ),
    (
        "minister voor Nederlands-Antilliaanse Zaken",
        "minister_zonder_portefeuille",
        "bzk",
    ),
    ("minister voor Natuur en Stikstof", "minister_zonder_portefeuille", "lvvn"),
    ("minister zonder portefeuille", "minister_zonder_portefeuille", None),
    ("Nederlands staatssecretaris van Economische Zaken", "staatssecretaris", "ez"),
    ("staatssecretaris van Financiën", "staatssecretaris", "fin"),
    (
        "Staatssecretaris van Justitie en Veiligheid - Rechtsbescherming en "
        "Gevangeniswezen",
        "staatssecretaris",
        "jenv",
    ),
    (
        "Staatssecretaris van Economische Zaken – Digitale Economie en Soevereiniteit",
        "staatssecretaris",
        "ez",
    ),
    ("Staatssecretaris Herstel Toeslagen", "staatssecretaris", "fin"),
    ("Staatssecretaris voor Toeslagen en Douane", "staatssecretaris", "fin"),
    ("Staatssecretaris Herstel Groningen", "staatssecretaris", "bzk"),
    ("Staatssecretaris mijnbouw", "staatssecretaris", "ezk"),
    ("Staatssecretaris Onderwijs en Emancipatie", "staatssecretaris", "ocw"),
    (
        "Staatssecretaris van Landbouw Visserij Voedselzekerheid en Natuur",
        "staatssecretaris",
        "lvvn",
    ),
    ("Nederlandse minister", "minister", None),
    ("Tweede Kamerlid", None, None),
]


@pytest.mark.parametrize(("function", "post", "ministry"), FUNCTIONS)
def test_a_function_names_its_post_and_ministry(
    function: str, post: str | None, ministry: str | None
) -> None:
    assert classify_function(function) == (post, ministry)


def test_a_former_name_after_its_time_means_the_successor() -> None:
    # "Binnenlandse Zaken" was renamed in 1998; the Tweede Kamer still shortens BZK to it
    role = "Staatssecretaris van Binnenlandse Zaken - Koninkrijksrelaties"
    assert classify_function(role, on="1990-01-01") == ("staatssecretaris", "biza")
    assert classify_function(role, on="2025-01-01") == ("staatssecretaris", "bzk")
    # a chain of renamings: Justitie -> Veiligheid en Justitie -> Justitie en Veiligheid
    assert classify_function("minister van Justitie", on="2020-01-01")[1] == "jenv"


def test_the_ministries_name_existing_successors_and_rank_after_them() -> None:
    for ministry in MINISTRIES:
        if ministry.successor:
            assert ministry.successor in MINISTRY_BY_KEY
            assert protocol_rank(ministry.key) > protocol_rank(ministry.successor)
    assert protocol_rank("az") == 0
    assert protocol_rank(None) == len(MINISTRIES)


def test_a_ministry_with_a_successor_names_the_last_day_of_its_name() -> None:
    from lawgraph.core.ministries import MINISTRIES

    # the Rijksoverheid pages show no handover for these: their end stays unknown
    unknown = {"aok", "bzbpbo", "opw", "ahn", "szv", "arbeid"}
    assert {m.key for m in MINISTRIES if m.successor and not m.until} == unknown
