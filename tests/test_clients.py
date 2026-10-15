"""What the TK, Rechtspraak and EU clients ask, and how a body is decoded."""

from __future__ import annotations

import datetime as dt

import pytest
import requests

from lawgraph.clients.eu import EUClient
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.clients.tk import TKClient
from lawgraph.config.sources import TWEEDE_KAMER
from tests.fakes import ScriptedSession, answer

EMPTY = {"@odata.count": 0, "value": []}
# What the paging adds to the parameters of every query of TKClient.
_PAGING = {"$top", "$skip", "$count"}


def _tk(*script) -> tuple[TKClient, ScriptedSession]:
    session = ScriptedSession(*script)
    return TKClient(session=session), session


def _asked(session: ScriptedSession) -> list[tuple[str, dict]]:
    """``(entity, parameters)`` of every request, without those of the paging."""
    return [
        (
            sent.url.removeprefix(TWEEDE_KAMER.base_url),
            {k: v for k, v in sent.params.items() if k not in _PAGING},
        )
        for sent in session.sent
    ]


# --------------------------------------------------------------------
# TKClient tests
# --------------------------------------------------------------------


def test_tkclient_zaken_modified_since_builds_correct_url_and_params() -> None:
    client, session = _tk({"value": [{"Id": 1, "Titel": "Testzaak"}]})
    since = dt.datetime(2025, 1, 1, 12, 0, 0)

    # The fetchers are lazy: a page is requested when the records are read.
    result = list(client.zaken_modified_since(since, top=10))

    assert len(session.sent) == 1
    sent = session.sent[0]
    assert sent.url == f"{TWEEDE_KAMER.base_url}Zaak"
    assert sent.params.get("$top") == 10
    flt = sent.params.get("$filter", "")
    assert "ApiGewijzigdOp ge " in flt
    assert "2025-01-01T12:00:00" in flt
    assert result[0]["Id"] == 1
    # the case it replaces comes with each case
    assert "VervangenVanuit($select=Id,Verwijderd)" in sent.params["$expand"]
    assert "VervangenVanuit/any()" not in flt


def test_tkclient_reads_only_the_replacing_cases_when_asked() -> None:
    """The backfill of ``Zaak.VervangenVanuit``: only the cases that replace another."""
    client, session = _tk({"value": []})
    list(client.zaken_modified_since(dt.datetime(1995, 1, 1), top=None, replacing=True))
    assert session.sent[0].params["$filter"].endswith(" and VervangenVanuit/any()")


def test_the_cases_follow_the_next_link_of_every_page() -> None:
    next_link = f"{TWEEDE_KAMER.base_url}Zaak?$skip=1"
    client, session = _tk(
        {"value": [{"Id": "1"}], "@odata.nextLink": next_link}, {"value": [{"Id": "2"}]}
    )
    cases = list(client.zaken_modified_since(dt.datetime(2025, 1, 1)))
    assert [case["Id"] for case in cases] == ["1", "2"]
    assert session.sent[1].url == next_link


def test_a_page_without_records_raises() -> None:
    client, _ = _tk({"error": "unknown entity"})
    with pytest.raises(KeyError):
        list(client.zaken_modified_since(dt.datetime(2025, 1, 1)))


def test_the_decisions_without_a_vote_are_asked_for_alone() -> None:
    """A withdrawn, postponed or lapsed amendment or motion has a Besluit ``Stemmen - …``
    that no Stemming carries: asked for on its own, by the kinds of its case."""
    client, session = _tk(EMPTY, EMPTY)
    list(client.fetch_bill_decisions(("Amendement", "Motie"), without_votes=True))
    asked = session.sent[0].params["$filter"]
    assert "not Stemming/any()" in asked
    assert "z/Soort eq 'Amendement' or z/Soort eq 'Motie'" in asked
    list(client.fetch_bill_decisions(("Wetgeving",)))
    assert "Stemming/any()" not in session.sent[1].params["$filter"]


# --------------------------------------------------------------------
# RechtspraakClient tests
# --------------------------------------------------------------------


def test_rechtspraak_fetch_ecli_content_uses_correct_path_and_param() -> None:
    xml_body = "<uitspraak>ECLI content</uitspraak>"
    session = ScriptedSession(xml_body)
    result = RechtspraakClient(session=session).fetch_ecli_content(
        "ECLI:NL:HR:2024:1234"
    )
    assert len(session.sent) == 1
    assert session.sent[0].url == "https://data.rechtspraak.nl/uitspraken/content"
    assert session.sent[0].params == {"id": "ECLI:NL:HR:2024:1234"}
    assert result == xml_body


# --------------------------------------------------------------------
# EUClient tests
# --------------------------------------------------------------------


def test_euclient_fetch_celex_html_builds_correct_url() -> None:
    html_body = "<html>CELEX</html>"
    session = ScriptedSession(html_body)
    result = EUClient(session=session).fetch_celex_html("32019L1158", lang="NL")
    # the CELLAR publications server, not eur-lex.europa.eu
    assert len(session.sent) == 1
    assert (
        session.sent[0].url
        == "https://publications.europa.eu/resource/celex/32019L1158"
    )
    assert session.sent[0].params is None
    assert result == html_body


# --------------------------------------------------------------------
# Single-quote escaping in TK OData filter
# --------------------------------------------------------------------


def test_tkclient_keyword_with_single_quote_does_not_corrupt_odata_filter() -> None:
    """A keyword containing ' must be escaped as '' to produce valid OData."""
    from lawgraph.clients.tk import _build_contains_filter

    result = _build_contains_filter(["Titel"], ["l'homme"])
    # The single quote must be doubled, not left bare (which would break OData).
    assert "l''homme" in result
    assert "l'homme'" not in result.replace("l''homme", "")


def test_every_get_is_retried_also_the_first_page_of_a_paged_fetch(slept) -> None:
    """One 503 on page one must not abort a fetch of a thousand pages."""
    client, _ = _tk(answer(status=503), {"value": [{"Id": "1"}]})
    assert list(client.zaken_modified_since(dt.datetime(2025, 1, 1))) == [{"Id": "1"}]

    session = ScriptedSession(answer(status=503), "text")
    assert RechtspraakClient(session=session).get_text("uitspraken/content") == "text"
    assert slept == [1.0, 1.0]


def test_a_tk_listing_that_ends_before_its_count_is_an_error() -> None:
    """A short page ends the paging; a server that lowers its page size would cut the rest."""
    short = {"@odata.count": 600, "value": [{"Id": str(n)} for n in range(100)]}
    client, _ = _tk(short)
    with pytest.raises(RuntimeError, match="100 records read, the API counts 600"):
        list(client.fetch_stemmingen())

    complete = {"@odata.count": 3, "value": [{"Id": "1"}, {"Id": "2"}, {"Id": "3"}]}
    client, _ = _tk(complete)
    assert len(list(client.fetch_stemmingen())) == 3


def test_a_body_is_decoded_by_its_own_declaration_not_by_the_fallback_of_requests() -> (
    None
):
    """requests reads text/xml without a charset as ISO-8859-1: "é" would become "Ã©"."""
    from lawgraph.clients.base import response_text

    def response(body: bytes, content_type: str) -> requests.Response:
        resp = requests.Response()
        resp._content, resp.status_code = body, 200
        resp.headers["Content-Type"] = content_type
        return resp

    utf8 = "<?xml version='1.0' encoding='UTF-8'?><a>Coördinatie één</a>".encode()
    assert "Coördinatie één" in response_text(response(utf8, "text/xml"))
    assert "Coördinatie één" in response_text(
        response(b"\xef\xbb\xbf" + utf8, "text/xml")
    )
    latin = "<?xml version='1.0' encoding='ISO-8859-1'?><a>één</a>".encode("latin-1")
    assert "één" in response_text(response(latin, "application/xml"))
    assert "één" in response_text(
        response("<a>één</a>".encode(), "text/html")
    )  # no declaration
    assert "één" in response_text(response(latin, "text/xml; charset=ISO-8859-1"))


def test_a_case_is_asked_for_with_the_dossier_it_belongs_to() -> None:
    """The normalizer reads the dossier number from ``Zaak.Kamerstukdossier``, and the
    request never asked for it: in the rebuild of 2026-09-20 none of 83,100 cases carried a
    dossier number and "Linked 0 cases to dossiers" was an INFO line."""
    from lawgraph.core import tk_records

    client, session = _tk(
        {"value": [{"Id": "z-1", "Kamerstukdossier": [{"Nummer": 36590}]}]}
    )
    cases = list(client.zaken_modified_since(dt.datetime(2025, 1, 1), top=None))

    ((entity, asked),) = _asked(session)
    assert entity == "Zaak"
    assert asked["$expand"].startswith("Kamerstukdossier(")
    assert "Nummer" in asked["$expand"]
    assert tk_records.dossier_numbers(cases) == ["36590"]


def test_a_dossier_is_asked_for_by_its_number() -> None:
    client, session = _tk(EMPTY)
    list(client.fetch_dossiers(number=35786))
    assert _asked(session) == [("Kamerstukdossier", {"$filter": "Nummer eq 35786"})]


def test_the_links_of_documents_are_asked_for_alone_and_with_every_document() -> None:
    client, session = _tk(EMPTY, EMPTY, EMPTY)
    links = (
        "Activiteit($select=Id),BijlageDocument($select=Id),BronDocument($select=Id)"
    )

    list(client.fetch_document_links())
    list(
        client.fetch_document_links(
            since=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
        )
    )
    list(client.fetch_documents())
    (_, every), (_, since), (_, documents) = asked = _asked(session)
    assert every == {"$select": "Id,Verwijderd", "$expand": links}
    assert since["$filter"].startswith("ApiGewijzigdOp ge 2026-10-01")
    # every Document of tk-dossiers carries its links too
    assert documents["$expand"].endswith(links)
    assert all(entity == "Document" for entity, _ in asked)


def test_the_actors_of_cases_are_asked_for_alone() -> None:
    client, session = _tk(EMPTY, EMPTY)
    list(client.fetch_case_actors())
    list(
        client.fetch_case_actors(since=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))
    )
    (entity, every), (_, since) = _asked(session)
    assert entity == "Zaak"
    assert every == {
        "$select": "Id,Verwijderd",
        "$expand": "ZaakActor($select=Relatie,Functie,ActorAfkorting,Persoon_Id,"
        "Fractie_Id,Commissie_Id)",
    }
    assert since["$filter"].startswith("ApiGewijzigdOp ge 2026-10-01")


def test_a_commitment_is_asked_for_with_the_letters_that_fulfil_it() -> None:
    client, session = _tk(EMPTY)
    list(client.fetch_toezeggingen())
    assert _asked(session) == [
        ("Toezegging", {"$expand": "KamerbriefNakoming($select=Id)"})
    ]
