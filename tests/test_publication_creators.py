"""Who issued a publication of the Staatsblad or the Staatscourant, from what the SRU says of
its ``dcterms:creator`` (``core/publication_creators.py``)."""

from __future__ import annotations

from lawgraph.core.publication_creators import NO_CREATOR, UNLINKED, creator_props
from lawgraph.pipelines.retrieve._creators import with_creators
from lawgraph.pipelines.retrieve.base import record_doc


def _meta(*names: str, published: str | None = "2020-01-01") -> dict[str, object]:
    return {
        "creators": [{"name": n, "scheme": "OVERHEID.Ministerie"} for n in names],
        "published": published,
    }


def test_nothing_before_the_sru_was_asked() -> None:
    assert creator_props({"identifier": "stb-2020-1"}, "2020-01-01") == {}


def test_a_ministry_as_it_was_named_on_the_day_of_publication() -> None:
    """``Justitie`` was Justitie until 30 November 2010; the same words later mean its
    successor Veiligheid en Justitie (the source lagging behind a renaming)."""
    assert creator_props(
        _meta("Ministerie van Justitie", published="2005-03-01"), None
    ) == {
        "creators": ["Ministerie van Justitie"],
        "ministries": ["justitie"],
        "ministry_missing": None,
    }
    later = creator_props(
        _meta("Ministerie van Justitie", published="2011-06-01"), None
    )
    assert later["ministries"] == ["venj"]


def test_the_date_of_the_document_when_the_sru_gives_none() -> None:
    props = creator_props(
        _meta("Ministerie van Justitie", published=None), "2012-01-01"
    )
    assert props["ministries"] == ["venj"]


def test_two_ministries_each_and_once() -> None:
    props = creator_props(
        _meta(
            "Ministerie van Financiën",
            "Ministerie van Defensie",
            "Ministerie van Financiën",
        ),
        None,
    )
    assert props["ministries"] == ["fin", "def"]


def test_a_creator_that_is_no_ministry_is_a_gap() -> None:
    """A municipality, a body under a ministry: kept as written, linked to nothing."""
    props = creator_props(_meta("Oost Gelre", "Dienst Justitiële Inrichtingen"), None)
    assert props == {
        "creators": ["Oost Gelre", "Dienst Justitiële Inrichtingen"],
        "ministries": [],
        "ministry_missing": UNLINKED,
    }
    mixed = creator_props(_meta("Oost Gelre", "Ministerie van Financiën"), None)
    assert (mixed["ministries"], mixed["ministry_missing"]) == (["fin"], None)


def test_no_creator_is_a_gap_of_its_own() -> None:
    assert creator_props({"creators": [], "published": None}, None) == {
        "creators": [],
        "ministries": [],
        "ministry_missing": NO_CREATOR,
    }


def test_the_record_keeps_its_payload_and_gets_the_creators_in_its_meta() -> None:
    stored = {
        "id": "raw_sources/x",
        "key": "x",
        "source": "staatscourant",
        "kind": "stcrt-regeling-xml",
        "external_id": "stcrt-2020-1",
        "payload_ref": "db/staatscourant/stcrt-regeling-xml/abc.gz",
        "payload_sha1": "abc",
        "payload_text": "<xml/>",
        "fetched_at": "2020-01-01T00:00:00Z",
        "meta": {"identifier": "stcrt-2020-1"},
    }
    found = {"creators": [{"name": "Oost Gelre", "scheme": "OVERHEID.Gemeente"}]}
    doc = record_doc(with_creators(stored, found | {"published": "2020-02-27"}))
    assert "id" not in doc and "payload_text" not in doc
    assert (doc["payload_ref"], doc["payload_sha1"]) == (stored["payload_ref"], "abc")
    assert doc["fetched_at"] > stored["fetched_at"]
    assert doc["meta"] == {
        "identifier": "stcrt-2020-1",
        "creators": [{"name": "Oost Gelre", "scheme": "OVERHEID.Gemeente"}],
        "published": "2020-02-27",
    }
    unknown = record_doc(with_creators(stored, None))
    assert unknown["meta"]["creators"] == [] and unknown["meta"]["published"] is None
