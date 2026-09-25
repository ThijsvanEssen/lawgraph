"""Series of judgments: parallel cases one court decided on one day in (nearly) the same words.

A court that decides a batch of cases alike (fifteen Dexia effectenlease appeals, nine BPM
cassations) publishes one judgment per case number, each with the text of the others. Two
judgments are a pair when their texts are near copies (:func:`is_pair`); a series is a set of
judgments that pairs connect (:func:`group_series`). Only judgments of one court, one day and
one document type are compared: the caller hands in one such group at a time.

A text is compared as its word 8-shingles, one in eight kept by a stable hash (so the same
text gives the same sample in every run), by their Jaccard similarity.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from collections.abc import Container, Iterable
from dataclasses import dataclass

SHINGLE_WORDS = 8
SAMPLE_RATE = 8

# Pair thresholds (text Jaccard of the sampled shingles).
TEXT_JACCARD = 0.85
LONG_TEXT_JACCARD = 0.7
LONG_TEXT_WORDS = 600
# The same summary lowers the bar, when it is not a template.
SUMMARY_JACCARD = 0.97
SUMMARY_TEXT_JACCARD = 0.5
SUMMARY_LONG_TEXT_JACCARD = 0.3
# A summary written on this many distinct dates is a template ("kopje volgt", "HR: 81.1 RO").
GENERIC_SUMMARY_DATES = 3

_WORD = re.compile(r"\w+")
# A corrected judgment republished beside the original is not a parallel case.
_RECTIFICATION = re.compile(r"gerectificeerd|rectificatie", re.IGNORECASE)


def words(text: str | None) -> list[str]:
    """The words of *text*, in lower case."""
    return _WORD.findall((text or "").lower())


def shingles(tokens: list[str]) -> frozenset[int]:
    """The sampled word shingles of *tokens*: CRC-32 of each run of ``SHINGLE_WORDS``
    words, the one in ``SAMPLE_RATE`` whose hash is a multiple of it."""
    runs = (
        " ".join(tokens[i : i + SHINGLE_WORDS])
        for i in range(len(tokens) - SHINGLE_WORDS + 1)
    )
    hashes = (zlib.crc32(run.encode()) for run in runs)
    return frozenset(h for h in hashes if h % SAMPLE_RATE == 0)


def jaccard(
    a: frozenset[int] | frozenset[str], b: frozenset[int] | frozenset[str]
) -> float:
    """``|a ∩ b| / |a ∪ b|``; 0 for two empty sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def summary_fingerprint(summary: str) -> str:
    """The MD5 of a summary as the database computes it (``MD5()`` in AQL)."""
    return hashlib.md5(summary.encode()).hexdigest()


@dataclass(frozen=True)
class SeriesCandidate:
    """What the pair rule reads of one judgment."""

    ecli: str
    document_type: str | None
    case_number_keys: frozenset[str]
    word_count: int
    shingles: frozenset[int]
    summary_words: frozenset[str]
    summary_fingerprint: str | None
    rectified: bool

    @classmethod
    def of(
        cls,
        ecli: str,
        *,
        text: str | None,
        summary: str | None,
        document_type: str | None,
        case_number_keys: Iterable[str],
    ) -> SeriesCandidate:
        tokens = words(text)
        return cls(
            ecli=ecli,
            document_type=document_type,
            case_number_keys=frozenset(case_number_keys),
            word_count=len(tokens),
            shingles=shingles(tokens),
            summary_words=frozenset(words(summary)),
            summary_fingerprint=summary_fingerprint(summary) if summary else None,
            rectified=bool(summary and _RECTIFICATION.search(summary)),
        )


def _same_summary(
    a: SeriesCandidate, b: SeriesCandidate, generic: Container[str]
) -> bool:
    """Both judgments carry (nearly) the same summary, and it is no template."""
    return (
        a.summary_fingerprint is not None
        and b.summary_fingerprint is not None
        and a.summary_fingerprint not in generic
        and b.summary_fingerprint not in generic
        and jaccard(a.summary_words, b.summary_words) >= SUMMARY_JACCARD
    )


def is_pair(a: SeriesCandidate, b: SeriesCandidate, generic: Container[str]) -> bool:
    """Whether two judgments of one court and day are parallel cases.

    *generic* holds the fingerprints of template summaries. Never a pair: two document
    types, a shared case number (one case, published twice) or a rectification.
    """
    if a.document_type != b.document_type or a.case_number_keys & b.case_number_keys:
        return False
    if a.rectified or b.rectified:
        return False
    small, large = sorted((len(a.shingles), len(b.shingles)))
    if not small or small / large < SUMMARY_LONG_TEXT_JACCARD:
        return False  # the Jaccard cannot reach the lowest threshold
    similarity = jaccard(a.shingles, b.shingles)
    long = min(a.word_count, b.word_count) >= LONG_TEXT_WORDS
    if similarity >= TEXT_JACCARD or (long and similarity >= LONG_TEXT_JACCARD):
        return True
    if similarity < SUMMARY_TEXT_JACCARD and not (
        long and similarity >= SUMMARY_LONG_TEXT_JACCARD
    ):
        return False
    return _same_summary(a, b, generic)


def ecli_order(ecli: str) -> tuple[int, str]:
    """Sort key of the ECLIs of one court and year in the order of their numbers
    (``...:999`` before ``...:1000``)."""
    return len(ecli), ecli


def group_series(
    candidates: list[SeriesCandidate], generic: Container[str]
) -> list[list[str]]:
    """The series among *candidates* (one court, one day): the connected components of
    their pairs, each as its ECLIs in :func:`ecli_order`, in the order of their first."""
    parent = list(range(len(candidates)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            if root(i) != root(j) and is_pair(a, candidates[j], generic):
                parent[root(j)] = root(i)
    groups: dict[int, list[str]] = {}
    for i, candidate in enumerate(candidates):
        groups.setdefault(root(i), []).append(candidate.ecli)
    return sorted(
        (
            sorted(members, key=ecli_order)
            for members in groups.values()
            if len(members) > 1
        ),
        key=lambda members: ecli_order(members[0]),
    )


def series_props(
    eclis: Iterable[str], series: list[list[str]]
) -> dict[str, tuple[str | None, int | None]]:
    """``(series_id, series_size)`` of every ECLI of *eclis*: the lowest ECLI of its series
    and the number of judgments in it, ``(None, None)`` outside a series."""
    props: dict[str, tuple[str | None, int | None]] = dict.fromkeys(eclis, (None, None))
    for members in series:
        for ecli in members:
            props[ecli] = (members[0], len(members))
    return props
