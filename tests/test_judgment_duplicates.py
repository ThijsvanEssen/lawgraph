"""Which publication of a decision is kept (``semantic rechtspraak-duplicates``)."""

from __future__ import annotations

from lawgraph.core.judgments import replacing_ecli
from lawgraph.pipelines.semantic.rechtspraak_duplicates import kept_publications


def test_a_replaced_publication_is_kept_by_the_last_loaded_one_that_replaces_it() -> (
    None
):
    replaced_by = {"A": "B", "B": "C", "D": "E", "X": "Y", "Y": "X"}

    assert kept_publications(replaced_by, loaded={"B", "C", "X", "Y"}) == {
        "A": "C",
        "B": "C",
        # publications that replace each other: the lowest is kept
        "Y": "X",
    }
    # the one that replaces it is not loaded: it stands alone
    assert kept_publications({"D": "E"}, loaded=set()) == {}


def test_only_an_ecli_replaces() -> None:
    assert replacing_ecli(" ecli:nl:hr:1985:aw8335 ") == "ECLI:NL:HR:1985:AW8335"
    assert replacing_ecli("AW8335") is None
    assert replacing_ecli(None) is None
