"""What a search that found nothing suggests instead (``/api/search``, ``suggestions``).

A name looks like the query by its trigrams, as ``pg_trgm`` compares them (``similarity``:
the trigrams both have over those either has, of the words folded): a term or variant of
the list of concepts or a name of an act of ``eu-core`` (``core.concepts``), or a word of
the title of a law or a dossier (``db.queries.search.suggestions``). A query of one word
that is two such words together, a linking ``s`` between them or not, also suggests them
apart (``coalitiecrisis``: ``coalitie crisis``). Each suggestion finds something: a
concept its article or law, a word the titles that hold it."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lawgraph.core.text_fold import plain_words

# The least similarity of a name to the query (``pg_trgm`` has 0.3 by default; at 0.4 a
# typo or another form of a long word is in, a word that only shares a part is out).
SIMILAR = 0.4
# The most suggestions.
MOST = 3
# The fewest characters of a word of a title, and of each part of a compound.
WORD = 4


def trigrams(key: str) -> set[str]:
    """The trigrams of the words of *key* (``plain_words``), each word with two spaces
    before and one after, as ``pg_trgm`` makes them."""
    found: set[str] = set()
    for word in key.split():
        padded = f"  {word} "
        found.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return found


@dataclass(frozen=True)
class Vocabulary:
    """The names a search suggests: each as suggested, what it names (the term of its
    concept, a word itself), how much it weighs (a concept above every word, a word by the
    titles that hold it), its number of trigrams, and per trigram the names that have it;
    ``words`` the words of the titles."""

    names: tuple[str, ...]
    named: tuple[str, ...]
    weights: tuple[int, ...]
    sizes: tuple[int, ...]
    grams: Mapping[str, list[int]]
    words: Mapping[str, int]


def vocabulary(
    concepts: Iterable[tuple[str, str]], words: Mapping[str, int]
) -> Vocabulary:
    """The vocabulary of *concepts*, each name with the term of its concept, and the
    *words* of the titles, folded (``plain_words``), with the number of titles that hold
    each (one shorter than ``WORD`` left out); a word that is the name of a concept,
    folded, is that name."""
    words = {word: n for word, n in words.items() if len(word) >= WORD}
    first = max(words.values(), default=0) + 1
    by_key = {word: (word, word, n) for word, n in words.items()}
    by_key.update((plain_words(name), (name, term, first)) for name, term in concepts)
    keys = [key for key in by_key if key]
    entries = [by_key[key] for key in keys]
    grams: dict[str, list[int]] = {}
    sizes = []
    for i, key in enumerate(keys):
        found = trigrams(key)
        sizes.append(len(found))
        for gram in found:
            grams.setdefault(gram, []).append(i)
    return Vocabulary(
        names=tuple(name for name, _, _ in entries),
        named=tuple(named for _, named, _ in entries),
        weights=tuple(weight for _, _, weight in entries),
        sizes=tuple(sizes),
        grams=grams,
        words=words,
    )


def _similar(vocab: Vocabulary, q: str) -> list[str]:
    """The names of *vocab* at least ``SIMILAR`` like *q*, the most like it first, then
    the one that weighs most, one of a concept; not one of the trigrams of *q* (*q*
    itself)."""
    asked = trigrams(plain_words(q))
    shared: Counter[int] = Counter()
    for gram in asked:
        shared.update(vocab.grams.get(gram, ()))
    scored = []
    for i, n in shared.items():
        similarity = n / (len(asked) + vocab.sizes[i] - n)
        if SIMILAR <= similarity < 1:
            scored.append((-round(similarity, 2), -vocab.weights[i], vocab.names[i], i))
    found: dict[str, str] = {}
    for *_, name, i in sorted(scored):
        found.setdefault(vocab.named[i], name)
    return list(found.values())


def _parts(vocab: Vocabulary, q: str) -> str | None:
    """*q*, one word, as two words of the titles of ``WORD`` characters or more, a linking
    ``s`` between them or not: of several splits the one whose rarer word is in the most
    titles; None when there is none."""
    words = plain_words(q).split()
    if len(words) != 1:
        return None
    word = words[0]
    best: tuple[int, str] | None = None
    for i in range(WORD, len(word) - WORD + 1):
        head, tail = word[:i], word[i:]
        for rest in (tail, tail[1:] if tail.startswith("s") else ""):
            if len(rest) < WORD or head not in vocab.words or rest not in vocab.words:
                continue
            found = (min(vocab.words[head], vocab.words[rest]), f"{head} {rest}")
            best = max(best or found, found)
    return best[1] if best else None


def suggest(vocab: Vocabulary, q: str) -> list[str]:
    """At most ``MOST`` queries to try instead of *q*: its words apart (``_parts``), then
    the names most like it (``_similar``)."""
    found = [part for part in (_parts(vocab, q),) if part]
    for name in _similar(vocab, q):
        if name not in found:
            found.append(name)
    return found[:MOST]
