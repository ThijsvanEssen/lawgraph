"""What every client asks of its source, recorded: the URL with its parameters, the headers,
the timeout and whether the body is streamed. A change to a client that changes a request
shows here."""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import urlsplit

import pytest

from lawgraph.clients.bwb import BWBClient
from lawgraph.clients.echr import EchrClient
from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.clients.eu import EUClient
from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.clients.kiesraad import KiesraadClient
from lawgraph.clients.koop_publications import (
    AMVB,
    MINISTERIAL_REGULATION,
    KoopPublicationClient,
)
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.clients.rijksoverheid import RijksoverheidClient
from lawgraph.clients.tk import TKClient
from lawgraph.clients.tooi import TooiClient
from lawgraph.clients.verdragenbank import VerdragenbankClient
from lawgraph.config.sources import HOSTS
from lawgraph.core.bwb_wti import SKOS_PREF_LABEL
from tests.fakes import ScriptedSession, answer
from tests.paths import FIXTURES

USER_AGENT = "Concordans (https://github.com/ThijsvanEssen/lawgraph)"

# An SRU answer without records, and one with the treaties of a real page.
NO_RECORDS = (
    '<searchRetrieveResponse xmlns="http://docs.oasis-open.org/ns/search-ws/sruResponse">'
    "<numberOfRecords>0</numberOfRecords></searchRetrieveResponse>"
)
TREATIES = (
    (FIXTURES / "sru_verdragenbank_nl_page.xml")
    .read_text()
    .replace("<sru:numberOfRecords>7769<", "<sru:numberOfRecords>2<")
)
XML = "<?xml version='1.0' encoding='UTF-8'?><document/>"
SPARQL_EMPTY: dict[str, Any] = {"results": {"bindings": []}}
TK_EMPTY = {"@odata.count": 0, "value": []}
TOESTAND = {
    "bwb_id": "BWBR0001840",
    "title": "Grondwet",
    "locatie_toestand": "https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0001840/2023-02-22_0/xml/BWBR0001840_2023-02-22_0.xml",
    "locatie_wti": "https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0001840/BWBR0001840.WTI",
    "locatie_manifest": None,
    "geldigheidsperiode_startdatum": "2023-02-22",
    "geldigheidsperiode_einddatum": None,
}
SINCE = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def _docx() -> bytes:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as docx:
        docx.writestr("word/document.xml", "<w:document/>")
    return body.getvalue()


def _tk(call: Callable[[TKClient], Any]) -> Callable[[TKClient], Any]:
    return lambda client: list(call(client))


# (client, what is asked, the answers): every public method of every client.
CASES: dict[str, tuple[Callable[..., Any], Callable[[Any], Any], list[Any]]] = {
    "bwb-enumerate": (
        BWBClient,
        lambda c: c.enumerate_toestanden(types=("wet",)),
        [NO_RECORDS],
    ),
    "bwb-search": (
        BWBClient,
        lambda c: c.search_toestanden("BWBR0001840"),
        [NO_RECORDS],
    ),
    "bwb-toestand": (BWBClient, lambda c: c.fetch_toestand_xml(TOESTAND), [XML]),
    "bwb-wti": (
        BWBClient,
        lambda c: c.fetch_wti_general_info(TOESTAND),
        ["<wti><algemene-informatie/></wti>"],
    ),
    "echr-search": (
        EchrClient,
        lambda c: c.search_judgments(since_date="2026-01-01"),
        [{"resultcount": 0, "results": []}],
    ),
    "echr-ecli": (
        EchrClient,
        lambda c: c.fetch_by_ecli(["ECLI:CE:ECHR:2008:1127JUD003639102"]),
        [{"results": []}],
    ),
    "echr-document": (
        EchrClient,
        lambda c: c.fetch_document_xml("001-252192"),
        [_docx()],
    ),
    "eerstekamer": (
        EerstekamerClient,
        lambda c: list(c.iter_kamerstukken(since="2026-10-01")),
        [NO_RECORDS],
    ),
    "eerstekamer-site-page": (
        EerstekamerSiteClient,
        lambda c: c.page("/stemmingen"),
        ["<html/>"],
    ),
    "eerstekamer-site-page-at": (
        EerstekamerSiteClient,
        lambda c: c.page_at("/menukeuze_plenair"),
        ["<html/>"],
    ),
    "eu-acts": (EUClient, lambda c: c.enumerate_all_ids(), [SPARQL_EMPTY]),
    "eu-nim-acts": (EUClient, lambda c: c.enumerate_nim_ids(), [SPARQL_EMPTY]),
    "eu-measures": (
        EUClient,
        lambda c: list(c.national_measures(since="2026-10-01")),
        [SPARQL_EMPTY],
    ),
    "eu-cjeu-country": (EUClient, lambda c: c.enumerate_cjeu_ids(), [SPARQL_EMPTY]),
    "eu-cjeu-citing": (
        EUClient,
        lambda c: c.enumerate_cjeu_ids(celex_ids=["32016R0679", "31995L0046"]),
        [SPARQL_EMPTY],
    ),
    "eu-com": (
        EUClient,
        lambda c: c.enumerate_com_ids(celex_ids=["32016R0679"]),
        [SPARQL_EMPTY],
    ),
    "eu-celex": (EUClient, lambda c: c.fetch_celex_html("32016R0679"), ["<html/>"]),
    "kamerstuk": (
        KamerstukClient,
        lambda c: c.fetch_kamerstuk_xml("kst-37020-X-2"),
        [XML],
    ),
    "kamerstuk-tables": (KamerstukClient, lambda c: c.search_tables(), [NO_RECORDS]),
    "kamerstuk-pdf": (
        KamerstukClient,
        lambda c: c.fetch_pdf(
            "https://repository.overheid.nl/frbr/officielepublicaties/blg/onopgemaakt/"
            "blg-1081574/1/pdf/blg-1081574.pdf"
        ),
        [b"%PDF-1.7"],
    ),
    "kiesraad": (KiesraadClient, lambda c: c.election("EK20230530"), ["<html/>"]),
    "rechtspraak-instanties": (
        RechtspraakClient,
        lambda c: c.instanties(),
        ["<Instanties><Instantie>HR</Instantie></Instanties>"],
    ),
    "rechtspraak-index": (
        RechtspraakClient,
        lambda c: list(
            c.iter_index(
                courts=["Hoge_Raad_der_Nederlanden"],
                from_date=dt.date(2026, 9, 1),
                to_date=dt.date(2026, 10, 1),
            )
        ),
        ['<feed xmlns="http://www.w3.org/2005/Atom"/>'],
    ),
    "rechtspraak-content": (
        RechtspraakClient,
        lambda c: c.fetch_ecli_content("ECLI:NL:HR:2026:1"),
        [XML],
    ),
    "rijksoverheid-slugs": (
        RijksoverheidClient,
        lambda c: c.cabinet_slugs(),
        [
            '<a href="/regering/over-de-regering/kabinetten-sinds-1945/kabinet-schoof">'
            "</a>"
        ],
    ),
    "rijksoverheid-page": (
        RijksoverheidClient,
        lambda c: c.cabinet_page("kabinet-schoof"),
        ["<html/>"],
    ),
    "staatsblad-search": (
        partial(KoopPublicationClient, AMVB),
        lambda c: c.search(since="2026-10-01"),
        [NO_RECORDS],
    ),
    "staatsblad-xml": (
        partial(KoopPublicationClient, AMVB),
        lambda c: c.fetch_publication_xml("stb-2009-601"),
        [XML],
    ),
    "staatscourant-search": (
        partial(KoopPublicationClient, MINISTERIAL_REGULATION),
        lambda c: c.search(since="2026-10-01"),
        [NO_RECORDS],
    ),
    "staatscourant-creators": (
        partial(KoopPublicationClient, MINISTERIAL_REGULATION),
        lambda c: c.creators("minister voor Klimaat", "2024-07-02", "2025-06-03"),
        [NO_RECORDS],
    ),
    "staatscourant-xml": (
        partial(KoopPublicationClient, MINISTERIAL_REGULATION),
        lambda c: c.fetch_publication_xml("stcrt-2024-15433"),
        [XML],
    ),
    "tk-cases": (
        TKClient,
        _tk(
            lambda c: c.zaken_modified_since(
                SINCE, keyword_fields=["Titel"], keywords=["wet"]
            )
        ),
        [
            {
                "value": [{"Id": "1"}],
                "@odata.nextLink": "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Zaak?$skip=100",
            },
            {"value": []},
        ],
    ),
    "tk-dossiers": (
        TKClient,
        _tk(lambda c: c.fetch_dossiers(number=36600)),
        [TK_EMPTY],
    ),
    "tk-activities": (TKClient, _tk(lambda c: c.fetch_activiteiten(SINCE)), [TK_EMPTY]),
    "tk-votes": (TKClient, _tk(lambda c: c.fetch_stemmingen(SINCE)), [TK_EMPTY]),
    "tk-decisions": (
        TKClient,
        _tk(
            lambda c: c.fetch_bill_decisions(("Wetgeving",), SINCE, without_votes=True)
        ),
        [TK_EMPTY],
    ),
    "tk-commitments": (
        TKClient,
        _tk(lambda c: c.fetch_toezeggingen(SINCE)),
        [TK_EMPTY],
    ),
    "tk-committees": (TKClient, _tk(lambda c: c.fetch_commissies()), [TK_EMPTY]),
    "tk-documents": (
        TKClient,
        _tk(lambda c: c.fetch_documents(SINCE, dossier_number=36600)),
        [TK_EMPTY],
    ),
    "tk-document-links": (
        TKClient,
        _tk(lambda c: c.fetch_document_links(SINCE)),
        [TK_EMPTY],
    ),
    "tk-case-actors": (TKClient, _tk(lambda c: c.fetch_case_actors(SINCE)), [TK_EMPTY]),
    "tk-persons": (TKClient, _tk(lambda c: c.fetch_personen()), [TK_EMPTY]),
    "tk-factions": (TKClient, _tk(lambda c: c.fetch_fracties()), [TK_EMPTY]),
    "tk-vacancies": (
        TKClient,
        _tk(lambda c: c.fetch_fractie_zetel_vacatures()),
        [TK_EMPTY],
    ),
    "tk-seats": (TKClient, _tk(lambda c: c.fetch_fractie_zetel_personen()), [TK_EMPTY]),
    "tooi-ministries": (
        TooiClient,
        lambda c: c.ministries(),
        ["rwc_ministeries_compleet%2F6", [{"@type": "Ministerie"}]],
    ),
    "tooi-thesaurus": (
        TooiClient,
        lambda c: c.thesaurus("tooi/set/scw_bwb_themas"),
        ["scw_bwb_themas%2F2", [{SKOS_PREF_LABEL: "x"}]],
    ),
    "verdragenbank-treaties": (
        VerdragenbankClient,
        lambda c: c.enumerate_treaties(),
        [TREATIES, NO_RECORDS],
    ),
    "verdragenbank-xml": (
        VerdragenbankClient,
        lambda c: c.fetch_treaty_xml(
            "https://repository.overheid.nl/frbr/vd/001610/1/xml/001610.xml"
        ),
        [XML],
    ),
}

_DEFAULT_HEADERS = {"Accept-Encoding", "Connection", "User-Agent"}


def _sent(case: str) -> ScriptedSession:
    cls, call, script = CASES[case]
    session = ScriptedSession(*script)
    call(cls(session=session))
    assert not session.script, "an answer was not asked for"
    return session


def _requests(
    session: ScriptedSession,
) -> list[tuple[str, dict[str, str | bytes], Any, bool]]:
    return [
        (
            sent.full_url,
            {k: v for k, v in sent.headers.items() if k not in _DEFAULT_HEADERS},
            sent.timeout,
            sent.stream,
        )
        for sent in session.sent
    ]


EXPECTED: dict[str, list[tuple[str, dict[str, str], Any, bool]]] = {
    "bwb-enumerate": [
        (
            # x-connection last, as every SRU search of the clients asks it
            "https://zoekservice.overheid.nl/sru/Search?operation=searchRetrieve&version=1.2&query=dcterms.type%3D%3D%22wet%22&maximumRecords=1000&startRecord=1&x-connection=BWB",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "bwb-search": [
        (
            "https://zoekservice.overheid.nl/sru/Search?operation=searchRetrieve&version=1.2&query=dcterms.identifier%3D%3DBWBR0001840&maximumRecords=500&x-connection=BWB",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "bwb-toestand": [
        (
            "https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0001840/2023-02-22_0/xml/BWBR0001840_2023-02-22_0.xml",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "bwb-wti": [
        (
            "https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0001840/BWBR0001840.WTI",
            {"Accept": "*/*"},
            30,
            True,
        ),
    ],
    "echr-document": [
        (
            "https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id=001-252192&filename=001-252192.docx",
            {"Accept": "application/json"},
            120,
            False,
        ),
    ],
    "echr-ecli": [
        (
            "https://hudoc.echr.coe.int/app/query/results?query=%28ecli%3A%22ECLI%3ACE%3AECHR%3A2008%3A1127JUD003639102%22%29+AND+%28languageisocode%3A%22ENG%22+OR+languageisocode%3A%22FRE%22%29&select=appno%2Cdocname%2Cdoctype%2Citemid%2Cecli%2Clanguageisocode%2Coriginatingbody%2Ckpdate%2Crespondent%2Cimportance%2Capplicability%2Carticle%2Cconclusion&sort=&start=0&length=500",
            {"Accept": "application/json"},
            60,
            False,
        ),
    ],
    "echr-search": [
        (
            "https://hudoc.echr.coe.int/app/query/results?query=respondent%3ANLD+AND+documentcollectionid2%3AJUDGMENTS+AND+kpdate%3E%3D%222026-01-01T00%3A00%3A00.0Z%22&select=appno%2Cdocname%2Cdoctype%2Citemid%2Cecli%2Clanguageisocode%2Coriginatingbody%2Ckpdate%2Crespondent%2Cimportance%2Capplicability%2Carticle%2Cconclusion&sort=kpdate+Descending&start=0&length=100&rankingModelId=11111111-0000-0000-0000-000000000000",
            {"Accept": "application/json"},
            60,
            False,
        ),
    ],
    "eerstekamer": [
        (
            "https://repository.overheid.nl/sru/?operation=searchRetrieve&version=1.2&query=dt.creator%3D%3D%22Eerste+Kamer+der+Staten-Generaal%22+AND+w.publicatienaam%3D%3DKamerstuk+AND+dt.type%3D%3DKamerstuk+AND+dt.modified%3E%3D2026-10-01+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=100&startRecord=1&recordSchema=gzd",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "eerstekamer-site-page": [
        ("https://www.eerstekamer.nl/stemmingen", {"Accept": "*/*"}, 60, False),
    ],
    "eerstekamer-site-page-at": [
        ("https://www.eerstekamer.nl/menukeuze_plenair", {"Accept": "*/*"}, 60, False),
    ],
    "eu-acts": [
        (
            "https://publications.europa.eu/webapi/rdf/sparql?query=PREFIX+cdm%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%23%3E+SELECT+DISTINCT+%3Fcelex+WHERE+%7B+%3Fs+a+cdm%3Adirective+%3B+cdm%3Aresource_legal_id_celex+%3Fcelex+.+FILTER%28%21CONTAINS%28%3Fcelex%2C+%22%28%22%29%29+%7D+ORDER+BY+%3Fcelex+LIMIT+500+OFFSET+0&format=application%2Fsparql-results%2Bjson",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "eu-celex": [
        (
            "https://publications.europa.eu/resource/celex/32016R0679",
            {
                "Accept": "text/html, application/xhtml+xml",
                "Accept-Language": "nl, nl-NL;q=0.9",
            },
            60,
            False,
        ),
    ],
    "eu-cjeu-citing": [
        (
            "https://publications.europa.eu/webapi/rdf/sparql?query=PREFIX+cdm%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%23%3E+SELECT+DISTINCT+%3Fjudgment_celex+WHERE+%7B+%3Fj+a+cdm%3Ajudgement+%3B+cdm%3Aresource_legal_id_celex+%3Fjudgment_celex+%3B+cdm%3Awork_cites_work+%3Fcited+.+%3Fcited+cdm%3Aresource_legal_id_celex+%3Fcited_celex+.+FILTER%28%3Fcited_celex+IN+%28%2232016R0679%22%5E%5E%3Chttp%3A%2F%2Fwww.w3.org%2F2001%2FXMLSchema%23string%3E%2C+%2231995L0046%22%5E%5E%3Chttp%3A%2F%2Fwww.w3.org%2F2001%2FXMLSchema%23string%3E%29%29+%7D+ORDER+BY+%3Fjudgment_celex+LIMIT+500+OFFSET+0&format=application%2Fsparql-results%2Bjson",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "eu-cjeu-country": [
        (
            "https://publications.europa.eu/webapi/rdf/sparql?query=PREFIX+cdm%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%23%3E+SELECT+DISTINCT+%3Fcelex+WHERE+%7B+%3Fj+a+cdm%3Ajudgement+%3B+cdm%3Aresource_legal_id_celex+%3Fcelex+%3B+cdm%3Acase-law_originates_in_country+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fresource%2Fauthority%2Fcountry%2FNLD%3E+.+%7D+ORDER+BY+%3Fcelex+LIMIT+500+OFFSET+0&format=application%2Fsparql-results%2Bjson",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "eu-com": [
        (
            "https://publications.europa.eu/webapi/rdf/sparql?query=PREFIX+cdm%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%23%3E+SELECT+DISTINCT+%3Fcom_celex+WHERE+%7B+%3Fact+cdm%3Aresource_legal_id_celex+%3Fact_celex+%3B+cdm%3Aresource_legal_adopts_resource_legal+%3Fproposal+.+%3Fproposal+cdm%3Aresource_legal_id_celex+%3Fcom_celex+.+FILTER%28%3Fact_celex+IN+%28%2232016R0679%22%5E%5E%3Chttp%3A%2F%2Fwww.w3.org%2F2001%2FXMLSchema%23string%3E%29%29+FILTER%28STRSTARTS%28%3Fcom_celex%2C+%225%22%29%29+%7D+ORDER+BY+%3Fcom_celex+LIMIT+500+OFFSET+0&format=application%2Fsparql-results%2Bjson",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "eu-measures": [
        (
            "https://publications.europa.eu/webapi/rdf/sparql?query=PREFIX+cdm%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%23%3E+PREFIX+cmr%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%2Fcmr%23%3E+SELECT+%3Fid+%3Fmodified+%3Fcelex+%3Fjournal+%3Fnumber+%3Fdate+%3Ftype+%3Ftitle+WHERE+%7B+%7B+SELECT+%3Fm+%3Fid+%3Fmodified+WHERE+%7B+%3Fm+cdm%3Ameasure_national_implementing_implemented_by_country+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fresource%2Fauthority%2Fcountry%2FNLD%3E+%3B+cdm%3Awork_id_document+%3Fid+%3B+cmr%3AlastModificationDate+%3Fmodified+.+FILTER%28%3Fmodified+%3E%3D+%222026-10-01T00%3A00%3A00%22%5E%5E%3Chttp%3A%2F%2Fwww.w3.org%2F2001%2FXMLSchema%23dateTime%3E%29+FILTER%28STR%28%3Fid%29+%3E+%22%22%29+%7D+ORDER+BY+%3Fid+LIMIT+500+%7D+OPTIONAL+%7B+%3Fm+cdm%3Ameasure_national_implementing_implements_resource_legal+%3Fact+.+%3Fact+cdm%3Aresource_legal_id_celex+%3Fcelex+%7D+OPTIONAL+%7B+%3Fm+cdm%3Ameasure_national_implementing_name_official_journal+%3Fjournal+%7D+OPTIONAL+%7B+%3Fm+cdm%3Ameasure_national_implementing_number_official_journal+%3Fnumber+%7D+OPTIONAL+%7B+%3Fm+cdm%3Ameasure_national_implementing_date_official_journal+%3Fdate+%7D+OPTIONAL+%7B+%3Fm+cdm%3Ameasure_national_implementing_type_act+%3Ftype+%7D+OPTIONAL+%7B+%3Fm+cdm%3Awork_title+%3Ftitle+%7D+%7D+ORDER+BY+%3Fid&format=application%2Fsparql-results%2Bjson",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "eu-nim-acts": [
        (
            "https://publications.europa.eu/webapi/rdf/sparql?query=PREFIX+cdm%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Fcdm%23%3E+SELECT+DISTINCT+%3Fcelex+WHERE+%7B+%3Feu_act+cdm%3Aresource_legal_id_celex+%3Fcelex+.+%3Fnim+cdm%3Ameasure_national_implementing_implements_resource_legal+%3Feu_act+%3B+cdm%3Ameasure_national_implementing_implemented_by_country+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fresource%2Fauthority%2Fcountry%2FNLD%3E+.+%7D+ORDER+BY+%3Fcelex+LIMIT+500+OFFSET+0&format=application%2Fsparql-results%2Bjson",
            {"Accept": "*/*"},
            120,
            False,
        ),
    ],
    "kamerstuk": [
        (
            "https://repository.overheid.nl/frbr/officielepublicaties/kst/37020-X/kst-37020-X-2/1/xml/kst-37020-X-2.xml",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "kamerstuk-tables": [
        (
            "https://repository.overheid.nl/sru?operation=searchRetrieve&version=1.2&query=dt.type%3DBijlage+AND+dt.title+any+%22transponeringstabel+transponeringstabellen+concordantietabel+concordantietabellen%22+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=100&startRecord=1&recordSchema=gzd&x-connection=ob",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "kamerstuk-pdf": [
        (
            "https://repository.overheid.nl/frbr/officielepublicaties/blg/onopgemaakt/blg-1081574/1/pdf/blg-1081574.pdf",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "kiesraad": [
        (
            "https://www.verkiezingsuitslagen.nl/verkiezingen/detail/EK20230530",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "rechtspraak-content": [
        (
            "https://data.rechtspraak.nl/uitspraken/content?id=ECLI%3ANL%3AHR%3A2026%3A1",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "rechtspraak-index": [
        (
            "https://data.rechtspraak.nl/uitspraken/zoeken?type=Uitspraak&return=DOC&max=1000&creator=http%3A%2F%2Fstandaarden.overheid.nl%2Fowms%2Fterms%2FHoge_Raad_der_Nederlanden&date=2026-09-01&date=2026-10-01&from=0",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "rechtspraak-instanties": [
        (
            "https://data.rechtspraak.nl/Waardelijst/Instanties",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "rijksoverheid-page": [
        (
            "https://www.rijksoverheid.nl/regering/over-de-regering/kabinetten-sinds-1945/kabinet-schoof",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "rijksoverheid-slugs": [
        (
            "https://www.rijksoverheid.nl/regering/over-de-regering/kabinetten-sinds-1945",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "staatsblad-search": [
        (
            "https://repository.overheid.nl/sru?operation=searchRetrieve&version=1.2&query=dt.type%3DAMvB+AND+dt.modified%3E%3D2026-10-01+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=100&startRecord=1&recordSchema=gzd&x-connection=ob",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "staatsblad-xml": [
        (
            "https://repository.overheid.nl/frbr/officielepublicaties/stb/2009/stb-2009-601/1/xml/stb-2009-601.xml",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "staatscourant-creators": [
        (
            "https://repository.overheid.nl/sru?operation=searchRetrieve&version=1.2&query=c.product-area%3Dofficielepublicaties+AND+%28w.publicatienaam%3DStaatscourant+OR+w.publicatienaam%3DStaatsblad%29+AND+dt.date%3E%3D2024-07-02+AND+dt.date%3C%3D2025-06-03+AND+cql.textAndIndexes%3D%22minister+voor+Klimaat%22+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=100&startRecord=1&recordSchema=gzd&x-connection=ob",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "staatscourant-search": [
        (
            "https://repository.overheid.nl/sru?operation=searchRetrieve&version=1.2&query=dt.type%3DMinisteriele-regeling+AND+dt.modified%3E%3D2026-10-01+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=100&startRecord=1&recordSchema=gzd&x-connection=ob",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "staatscourant-xml": [
        (
            "https://repository.overheid.nl/frbr/officielepublicaties/stcrt/2024/stcrt-2024-15433/1/xml/stcrt-2024-15433.xml",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "tk-activities": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Activiteit?%24expand=Agendapunt%28%24expand%3DZaak%28%24select%3DId%2CSoort%2CTitel%2CNummer%2COnderwerp%2CVolgnummer%2CVergaderjaar%3B%24expand%3DKamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%2CTitel%29%29%29%2CVervangenDoor%28%24select%3DId%2CNummer%29&%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-case-actors": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Zaak?%24select=Id%2CVerwijderd&%24expand=ZaakActor%28%24select%3DRelatie%2CFunctie%2CActorAfkorting%2CPersoon_Id%2CFractie_Id%2CCommissie_Id%29&%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-cases": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Zaak?%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z+and+%28contains%28tolower%28Titel%29%2C%27wet%27%29%29&%24expand=Kamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%29%2CGerelateerdNaar%28%24select%3DId%2CSoort%2CVerwijderd%3B%24expand%3DKamerstukdossier%28%24select%3DNummer%2CToevoeging%29%29%2CVervangenVanuit%28%24select%3DId%2CVerwijderd%29&%24top=100",
            {"Accept": "*/*"},
            30,
            False,
        ),
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Zaak?$skip=100",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-commitments": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Toezegging?%24expand=KamerbriefNakoming%28%24select%3DId%3B%24expand%3DKamerstukdossier%28%24select%3DNummer%2CToevoeging%29%29%2CActiviteit%28%24select%3DDatum%29&%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-committees": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Commissie?%24expand=CommissieZetel%28%24expand%3DCommissieZetelVastPersoon%2CCommissieZetelVervangerPersoon%29&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-decisions": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Besluit?%24filter=startswith%28BesluitSoort%2C%27Stemmen%27%29+and+Zaak%2Fany%28z%3Az%2FSoort+eq+%27Wetgeving%27%29+and+not+Stemming%2Fany%28%29+and+ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z&%24expand=Zaak%28%24select%3DId%2CSoort%2CTitel%2CNummer%2COnderwerp%2CVolgnummer%2CVergaderjaar%3B%24expand%3DKamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%2CTitel%29%29%2CAgendapunt%28%24expand%3DActiviteit%28%24select%3DId%2CDatum%2CSoort%29%2CZaak%28%24select%3DId%2CSoort%2CTitel%2CNummer%2COnderwerp%2CVolgnummer%2CVergaderjaar%3B%24expand%3DKamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%2CTitel%29%29%29&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-document-links": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Document?%24select=Id%2CVerwijderd&%24expand=Activiteit%28%24select%3DId%29%2CBijlageDocument%28%24select%3DId%29%2CBronDocument%28%24select%3DId%29&%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-documents": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Document?%24expand=Kamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%29%2CZaak%28%24select%3DId%2CSoort%2CTitel%2COnderwerp%2CNummer%3B%24expand%3DKamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%2CTitel%29%29%2CDocumentActor%28%24select%3DId%2CActorNaam%2CActorFractie%2CFunctie%2CRelatie%2CPersoon_Id%2CFractie_Id%29%2CActiviteit%28%24select%3DId%29%2CBijlageDocument%28%24select%3DId%29%2CBronDocument%28%24select%3DId%29&%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z+and+%28Kamerstukdossier%2Fany%28k%3Ak%2FNummer+eq+36600%29+or+Zaak%2Fany%28z%3Az%2FKamerstukdossier%2Fany%28k%3Ak%2FNummer+eq+36600%29%29%29&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-dossiers": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Kamerstukdossier?%24filter=Nummer+eq+36600&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-factions": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Fractie?%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-persons": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Persoon?%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-seats": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/FractieZetelPersoon?%24expand=FractieZetel%28%24select%3DId%2CFractie_Id%2CGewijzigdOp%29&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-vacancies": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/FractieZetelVacature?%24expand=FractieZetel%28%24select%3DId%2CFractie_Id%29&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tk-votes": [
        (
            "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Stemming?%24expand=Besluit%28%24expand%3DZaak%28%24select%3DId%2CSoort%2CTitel%2CNummer%2COnderwerp%2CVolgnummer%2CVergaderjaar%3B%24expand%3DKamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%2CTitel%29%29%2CAgendapunt%28%24expand%3DActiviteit%28%24select%3DId%2CDatum%2CSoort%29%2CZaak%28%24select%3DId%2CSoort%2CTitel%2CNummer%2COnderwerp%2CVolgnummer%2CVergaderjaar%3B%24expand%3DKamerstukdossier%28%24select%3DId%2CNummer%2CToevoeging%2CTitel%29%29%29%29&%24filter=ApiGewijzigdOp+ge+2026-10-01T00%3A00%3A00Z&%24top=250&%24skip=0&%24count=true",
            {"Accept": "*/*"},
            30,
            False,
        ),
    ],
    "tooi-ministries": [
        (
            "https://identifier.overheid.nl/tooi/set/rwc_ministeries_compleet",
            {"Accept": "*/*"},
            30,
            False,
        ),
        (
            "https://identifier.overheid.nl/tooi/set/rwc_ministeries_compleet/6",
            {"Accept": "application/ld+json"},
            30,
            False,
        ),
    ],
    "tooi-thesaurus": [
        (
            "https://identifier.overheid.nl/tooi/set/scw_bwb_themas",
            {"Accept": "*/*"},
            30,
            False,
        ),
        (
            "https://identifier.overheid.nl/tooi/set/scw_bwb_themas/2",
            {"Accept": "application/ld+json"},
            30,
            False,
        ),
    ],
    "verdragenbank-treaties": [
        (
            "https://repository.overheid.nl/sru/?operation=searchRetrieve&version=1.2&query=c.product-area%3D%3Dvd+AND+w.documenttype%3D%3Dverdrag+AND+dt.language%3D%3Dnl+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=250&startRecord=1&recordSchema=gzd",
            {"Accept": "*/*"},
            60,
            False,
        ),
        (
            "https://repository.overheid.nl/sru/?operation=searchRetrieve&version=1.2&query=c.product-area%3D%3Dvd+AND+w.documenttype%3D%3Dverdrag+AND+dt.language%3D%3Den+sortBy+dt.identifier%2Fsort.ascending&maximumRecords=250&startRecord=1&recordSchema=gzd",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
    "verdragenbank-xml": [
        (
            "https://repository.overheid.nl/frbr/vd/001610/1/xml/001610.xml",
            {"Accept": "*/*"},
            60,
            False,
        ),
    ],
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_client_asks_what_it_always_asked(case: str) -> None:
    assert _requests(_sent(case)) == EXPECTED[case]


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_request_names_concordans(case: str) -> None:
    assert {sent.headers["User-Agent"] for sent in _sent(case).sent} == {USER_AGENT}


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_request_goes_to_a_host_of_the_table(case: str) -> None:
    """So it is paced at the interval of its host, in the lane of its host."""
    hosts = {host.name for host in HOSTS}
    assert {urlsplit(sent.full_url).hostname for sent in _sent(case).sent} <= hosts


def test_a_request_past_the_script_fails_the_test() -> None:
    with pytest.raises(AssertionError, match="no answer scripted"):
        KiesraadClient(session=ScriptedSession()).election("EK20230530")


def test_a_scripted_status_is_what_the_client_sees() -> None:
    session = ScriptedSession(answer("", status=404))
    with pytest.raises(Exception, match="404"):
        KiesraadClient(session=session).election("EK20230530")
