"""Tests for the judgment appeal detection logic."""

from __future__ import annotations

from lawgraph.pipelines.semantic.judgment_appeal import _APPEAL_PATTERN


def _is_appeal(procedure: str) -> bool:
    """Replicate the word-boundary check used in JudgmentAppealPipeline."""
    return bool(_APPEAL_PATTERN.search(procedure.strip()))


class TestAppealDetection:
    def test_hoger_beroep_matches(self) -> None:
        assert _is_appeal("Hoger beroep")

    def test_cassatie_matches(self) -> None:
        assert _is_appeal("Cassatie")

    def test_case_insensitive(self) -> None:
        assert _is_appeal("HOGER BEROEP")
        assert _is_appeal("cassatie")

    def test_appeal_keyword_as_word_substring_does_not_match(self) -> None:
        # "hoger beroepschrift" contains "hoger beroep" as a prefix of a word;
        # the word-boundary check must prevent a false positive.
        assert not _is_appeal("hoger beroepschrift")

    def test_cassatie_as_substring_does_not_match(self) -> None:
        # "cassatieadvocaat" contains "cassatie" as a prefix.
        assert not _is_appeal("cassatieadvocaat")

    def test_unrelated_procedure_does_not_match(self) -> None:
        assert not _is_appeal("Eerste aanleg")
        assert not _is_appeal("Prejudiciële beslissing")
        assert not _is_appeal("")
