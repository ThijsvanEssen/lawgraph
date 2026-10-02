"""The day a judgment was published (``core.judgments.published_on``): the ``dcterms:issued``
of the ``rdf:Description`` about the published document, not of the one about the ECLI."""

from __future__ import annotations

from lawgraph.core.judgments import parse_judgment, published_on

# The two descriptions of ECLI:NL:GHARL:2025:7995 as the open data give them; its page on
# uitspraken.rechtspraak.nl says "Datum publicatie 22-12-2025".
_RECORD = """<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:dcterms="http://purl.org/dc/terms/">
  <rdf:RDF>
    <rdf:Description>
      <dcterms:identifier>ECLI:NL:GHARL:2025:7995</dcterms:identifier>
      <dcterms:modified>2025-12-22T16:32:15</dcterms:modified>
      <dcterms:issued>2025-12-12</dcterms:issued>
      <dcterms:date>2025-12-09</dcterms:date>
    </rdf:Description>
    {document}
  </rdf:RDF>
  <uitspraak><para>Tekst.</para></uitspraak>
</open>"""
_DOCUMENT = """<rdf:Description
        rdf:about="http://deeplink.rechtspraak.nl/uitspraak?id=ECLI:NL:GHARL:2025:7995">
      <dcterms:modified>2025-12-22T14:42:28</dcterms:modified>
      <dcterms:issued>2025-12-22</dcterms:issued>
    </rdf:Description>"""


def test_the_publication_is_the_issued_of_the_published_document() -> None:
    assert published_on(parse_judgment(_RECORD.format(document=_DOCUMENT))) == (
        "2025-12-22"
    )


def test_a_record_without_the_document_has_none() -> None:
    # the issued of the ECLI's description is no publication: it can be before the date
    assert published_on(parse_judgment(_RECORD.format(document=""))) is None
