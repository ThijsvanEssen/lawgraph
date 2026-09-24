"""Series of parallel judgments (``core.judgment_series``): the pair rule and the grouping."""

from __future__ import annotations

import random

from lawgraph.core.judgment_series import (
    LONG_TEXT_WORDS,
    SAMPLE_RATE,
    SeriesCandidate,
    group_series,
    is_pair,
    jaccard,
    series_props,
    shingles,
    summary_fingerprint,
    words,
)


def _text(seed: int, length: int) -> list[str]:
    rng = random.Random(seed)
    return [f"woord{rng.randrange(5000)}" for _ in range(length)]


def _vary(tokens: list[str], every: int, seed: int) -> str:
    """*tokens* with every *every*-th word replaced: another party, another amount."""
    return " ".join(
        f"ander{seed}x{i}" if i % every == 0 else token
        for i, token in enumerate(tokens)
    )


def _judgment(
    ecli: str,
    text: str,
    *,
    summary: str | None = None,
    case_number: str | None = None,
    document_type: str = "Uitspraak",
) -> SeriesCandidate:
    return SeriesCandidate.of(
        ecli,
        text=text,
        summary=summary,
        document_type=document_type,
        case_number_keys=[case_number or ecli.lower()],
    )


LONG = _text(1, 1500)


def test_words_are_lower_case_and_without_punctuation() -> None:
    assert words("De Hoge Raad: verwerpt het beroep.") == [
        "de",
        "hoge",
        "raad",
        "verwerpt",
        "het",
        "beroep",
    ]


def test_the_sample_is_stable_and_about_one_in_eight() -> None:
    sample = shingles(LONG)
    assert sample == shingles(list(LONG))
    assert all(h % SAMPLE_RATE == 0 for h in sample)
    assert 1500 / SAMPLE_RATE / 2 < len(sample) < 1500 / SAMPLE_RATE * 2


def test_jaccard() -> None:
    assert jaccard(frozenset({1, 2}), frozenset({2, 3})) == 1 / 3
    assert jaccard(frozenset(), frozenset()) == 0.0


def test_near_copies_with_their_own_case_numbers_are_a_pair() -> None:
    a = _judgment("ECLI:NL:GHAMS:2026:2679", _vary(LONG, 200, 1))
    b = _judgment("ECLI:NL:GHAMS:2026:2680", _vary(LONG, 200, 2))
    assert is_pair(a, b, set())


def test_one_case_published_twice_is_no_pair() -> None:
    a = _judgment("ECLI:NL:RBMNE:2024:5485", " ".join(LONG), case_number="utr_23_3439")
    b = _judgment("ECLI:NL:RBMNE:2024:5863", " ".join(LONG), case_number="utr_23_3439")
    assert not is_pair(a, b, set())


def test_a_rectification_is_no_pair() -> None:
    text = " ".join(LONG)
    a = _judgment("ECLI:NL:RBMNE:2024:1", text, summary="Wabo. Beroep ongegrond.")
    b = _judgment(
        "ECLI:NL:RBMNE:2024:2", text, summary="Gerectificeerd. Wabo. Beroep ongegrond."
    )
    assert not is_pair(a, b, set())


def test_a_conclusion_and_a_judgment_are_no_pair() -> None:
    text = " ".join(LONG)
    a = _judgment("ECLI:NL:HR:2025:1", text)
    b = _judgment("ECLI:NL:HR:2025:2", text, document_type="Conclusie")
    assert not is_pair(a, b, set())


def test_different_texts_are_no_pair() -> None:
    a = _judgment("ECLI:NL:HR:2025:1", " ".join(LONG))
    b = _judgment("ECLI:NL:HR:2025:2", " ".join(_text(2, 1500)))
    assert not is_pair(a, b, set())


def test_long_texts_need_less_overlap() -> None:
    a = _judgment("ECLI:NL:HR:2025:1", _vary(LONG, 60, 1))
    b = _judgment("ECLI:NL:HR:2025:2", _vary(LONG, 60, 2))
    assert 0.7 <= jaccard(a.shingles, b.shingles) < 0.85
    assert is_pair(a, b, set())
    short = LONG[: LONG_TEXT_WORDS - 100]
    c = _judgment("ECLI:NL:HR:2025:3", _vary(short, 60, 1))
    d = _judgment("ECLI:NL:HR:2025:4", _vary(short, 60, 2))
    assert 0.5 <= jaccard(c.shingles, d.shingles) < 0.85
    assert not is_pair(c, d, set())


def test_the_same_summary_lowers_the_bar_unless_it_is_a_template() -> None:
    """The short art. 81 RO judgments of the Hoge Raad: one template, different cases."""
    template = _text(3, 500)
    summary = "HR: 81.1 RO."
    a = _judgment("ECLI:NL:HR:2025:10", _vary(template, 40, 1), summary=summary)
    b = _judgment("ECLI:NL:HR:2025:11", _vary(template, 40, 2), summary=summary)
    assert 0.5 <= jaccard(a.shingles, b.shingles) < 0.85
    assert is_pair(a, b, set())
    assert not is_pair(a, b, {summary_fingerprint(summary)})


def test_series_are_connected_pairs_in_the_order_of_their_numbers() -> None:
    judgments = [
        _judgment("ECLI:NL:HR:2025:1000", _vary(LONG, 200, 1)),
        _judgment("ECLI:NL:HR:2025:999", _vary(LONG, 200, 2)),
        _judgment("ECLI:NL:HR:2025:1001", _vary(LONG, 200, 3)),
        _judgment("ECLI:NL:HR:2025:5", " ".join(_text(9, 1500))),
    ]
    series = group_series(judgments, set())
    assert series == [
        ["ECLI:NL:HR:2025:999", "ECLI:NL:HR:2025:1000", "ECLI:NL:HR:2025:1001"]
    ]
    assert series_props([j.ecli for j in judgments], series) == {
        "ECLI:NL:HR:2025:999": ("ECLI:NL:HR:2025:999", 3),
        "ECLI:NL:HR:2025:1000": ("ECLI:NL:HR:2025:999", 3),
        "ECLI:NL:HR:2025:1001": ("ECLI:NL:HR:2025:999", 3),
        "ECLI:NL:HR:2025:5": (None, None),
    }
