"""The XML helpers of ``core/xml.py``: names without their namespace, the text of an element
and of the first of several names."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from lawgraph.core import xml as core_xml

NS = "http://example.org/ns"


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("plain", "plain"),
        (f"{{{NS}}}tag", "tag"),
        ("", ""),
        (f"{{{NS}}}", ""),
    ],
)
def test_local_name(tag: str, expected: str) -> None:
    assert core_xml.local_name(tag) == expected


def test_find_text_skips_empty_matches_and_joins_itertext_without_separator() -> None:
    root = _el("<r><t> </t><t>a<b>b</b> c</t></r>")
    assert core_xml.find_text(root, "t") == "ab c"


def test_find_text_returns_none_when_missing_or_all_empty() -> None:
    assert core_xml.find_text(_el("<r><t/></r>"), "t") is None
    assert core_xml.find_text(_el("<r/>"), "t") is None


def test_find_text_matches_namespaced_and_any_of_several_names() -> None:
    root = _el(f'<r xmlns:n="{NS}"><n:two>2</n:two><one>1</one></r>')
    assert core_xml.find_text(root, "one", "two") == "2"  # document order wins


def test_find_text_includes_the_element_itself() -> None:
    assert core_xml.find_text(_el("<t>self</t>"), "t") == "self"


def test_annex_first_text_returns_first_match_even_if_empty_and_collapses() -> None:
    def first(root: ET.Element) -> str | None:
        return core_xml.find_text(root, "nr", collapse=True, skip_empty=False)

    assert first(_el("<r><nr>  a \n  b<x> c</x> </nr></r>")) == "a b c"
    # first match wins even when it is empty (skip_empty=True would try the next)
    assert first(_el("<r><nr/><nr>2</nr></r>")) is None
    assert first(_el("<r/>")) is None
    root = _el("<r><nr/><nr>2</nr></r>")
    assert core_xml.find_text(root, "nr", collapse=True) == "2"


def test_sru_find_text_uses_own_text_only_and_first_match_wins() -> None:
    assert core_xml.find_own_text(_el("<r><a> x </a></r>"), "a") == "x"
    assert core_xml.find_own_text(_el("<r><a>x<b>y</b></a></r>"), "a") == "x"
    assert core_xml.find_own_text(_el("<r><a/><a>2</a></r>"), "a") is None
    assert core_xml.find_own_text(_el("<r><a>  </a></r>"), "a") is None
    assert core_xml.find_own_text(_el("<a>self</a>"), "a") == "self"
    assert (
        core_xml.find_own_text(_el(f'<r xmlns:n="{NS}"><n:a>ns</n:a></r>'), "a") == "ns"
    )


def test_extract_section_text_joins_itertext_with_space() -> None:
    root = _el("<r><s>a<b>b</b>c</s></r>")
    assert core_xml.extract_section_text(root, "s") == "a b c"


def test_extract_section_text_first_match_wins_even_if_empty() -> None:
    assert core_xml.extract_section_text(_el("<r><s/><s>x</s></r>"), "s") is None
    assert core_xml.extract_section_text(_el("<r><s>  </s></r>"), "s") is None
    assert core_xml.extract_section_text(_el("<r/>"), "s") is None


def test_extract_section_text_any_name_and_self() -> None:
    assert (
        core_xml.extract_section_text(_el("<r><b>1</b><a>2</a></r>"), "a", "b") == "1"
    )
    assert core_xml.extract_section_text(_el("<s>me</s>"), "s") == "me"


def test_rechtspraak_xml_clean_joins_with_space_and_strips() -> None:
    assert core_xml.text_of(_el("<p> a<b>b</b>c </p>"), " ") == "a b c"
    assert core_xml.text_of(_el("<p/>"), " ") == ""


def test_own_texts_are_each_text_once_in_document_order() -> None:
    root = _el(
        f'<r xmlns:n="{NS}"><n:c> B </n:c><c>A</c><c/><x><c>B</c><c>C</c></x></r>'
    )
    assert core_xml.own_texts(root, "c") == ["B", "A", "C"]
    assert core_xml.own_texts(root, "missing") == []


def test_children_named_and_child_named() -> None:
    root = _el('<a xmlns="urn:x"><b>1</b><c><b>deep</b></c><b>2</b></a>')
    assert [b.text for b in core_xml.children_named(root, "b")] == ["1", "2"]
    assert core_xml.children_named(None, "b") == []
    first = core_xml.child_named(root, "b")
    assert first is not None and first.text == "1"
    assert core_xml.child_named(root, "d") is None
    assert core_xml.child_named(None, "b") is None


def test_words_of() -> None:
    assert core_xml.words_of(_el("<p> a\n<b>b </b> c</p>")) == "a b c"
    assert core_xml.words_of(None) == ""


def test_collapse_ws_and_text_of() -> None:
    assert core_xml.collapse_ws(" a \n b\t c ") == "a b c"
    assert core_xml.collapse_ws("") == ""
    assert core_xml.collapse_ws(None) == ""
    assert core_xml.text_of(None) == ""
    assert core_xml.text_of(None, " ") == ""
    element = _el("<p>a<b>b</b>c</p>")
    assert core_xml.text_of(element) == "abc"
    assert core_xml.text_of(element, " ") == "a b c"


def test_first_named_and_find_own_text() -> None:
    root = _el("<r><a>1</a><b>2</b></r>")
    first = core_xml.first_named(root, "b", "a")
    assert first is not None and first.tag == "a"
    assert core_xml.first_named(root, "z") is None
    assert core_xml.find_own_text(root, "z") is None
