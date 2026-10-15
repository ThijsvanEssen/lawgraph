"""The courts and their tiers (``core/courts.py``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from tests.paths import FIXTURES


def test_the_tier_filters_of_the_api_are_the_tiers() -> None:
    import typing

    from lawgraph.api.routes import articles, judgments
    from lawgraph.core.courts import TIERS

    for route in (articles.get_article_cited_by_passages, judgments.list_judgments):
        hint = typing.get_type_hints(route, include_extras=True)["tier"]
        enum = next(
            a for a in typing.get_args(typing.get_args(hint)[0]) if a is not type(None)
        )
        assert [member.value for member in enum] == list(TIERS), route.__name__


def test_every_court_of_the_rechtspraak_has_a_tier_and_a_kind() -> None:
    """The waardelijst of the Rechtspraak (``/Waardelijst/Instanties``) names every court an
    ECLI can have; each has the tier of its Type and a kind, and none is a catch-all."""

    from lawgraph.core.courts import court_of

    root = ET.parse(FIXTURES / "rechtspraak_instanties.xml")
    codes = {
        (instance.findtext("Afkorting") or "").strip(): instance.findtext("Type") or ""
        for instance in root.getroot()
    }
    codes.pop("", None)  # the military and colonial courts without an ECLI code
    assert len(codes) > 150
    missing = sorted(code for code in codes if court_of(code) is None)
    assert missing == []
    by_type: dict[str, set[str]] = {}
    for code, kind in codes.items():
        by_type.setdefault(kind, set()).add(str(getattr(court_of(code), "tier", None)))
    assert by_type["Rechtbank"] == {"rechtbank"}
    assert by_type["Gerechtshof"] == {"gerechtshof"}
    assert by_type["Kantongerecht"] == {"kantongerecht"}
    assert by_type["TuchtrechtelijkeInstantie"] == {"tuchtcollege"}
    assert by_type["AndereGerechtelijkeInstantie"] == {"andere_instantie"}
    assert by_type["Koninkrijksinstantie"] == {"koninkrijksinstantie"}
    assert getattr(court_of("XX", "KB"), "tier", None) == "kroon"
    assert (
        getattr(
            court_of("XX", "Europees Hof voor de Rechten van de Mens"), "tier", None
        )
        == "ehrm"
    )
    assert (
        getattr(court_of("XX", "Hof van Justitie van de Europese Unie"), "tier", None)
        == "hvj_eu"
    )
    assert getattr(court_of("XX", "Hoge Raad van Belgie"), "tier", None) == (
        "buitenlandse_instantie"
    )
