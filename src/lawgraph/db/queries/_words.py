"""The words of a ``q`` as the feed and the decisions match them: in any case, each from
the start of a word, and one of at most ``WHOLE_WORD_MAX`` characters as a whole word too
(``ai``: the AI-verordening, not universitaire or Airport; ``algoritme``: algoritmes, not
rekenalgoritme)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

WHOLE_WORD_MAX = 4
# Words of fewer characters have no trigram: no index finds the rows that hold them.
TRIGRAM = 3
# A stem this long or longer finds the forms of its word (``word_sql``, ``search.types``):
# shorter ones are part of too many other words ("wet" of "wetten").
STEM_MIN = 4
# The stem of a word (the bind ``{name}``), as the search stems it (``lg_tokens``).
_STEM = "(lg_tokens(%({name})s))[1]"


def words(q: str) -> str:
    """*q* as it is matched: trimmed, in lower case."""
    return q.strip().lower()


def whole(q: str) -> bool:
    """Whether the words *q* (``words``) are matched as a whole word at their end: a short
    word that ends in a letter or digit (``ai``, ``huur``; not ``c.v.``)."""
    return len(q) <= WHOLE_WORD_MAX and q[-1:].isalnum()


def word_pattern(q: str) -> str:
    """The regular expression of the words *q* (``words``): a character that is no letter,
    digit or space escaped; a word start before it and, when it is short, a word end after
    it, where it starts or ends with a letter or digit (``c.v.``: none after its last
    dot)."""
    escaped = "".join(c if c.isalnum() or c == " " else f"\\{c}" for c in q)
    start = r"\m" if q[:1].isalnum() else ""
    end = r"\M" if whole(q) else ""
    return f"{start}{escaped}{end}"


def holds(text: str, param: str = "q_word") -> str:
    """SQL: the SQL *text* holds the words of the bind *param* (``word_pattern``)."""
    return f"lower({text}) ~ %({param})s"


# A LIKE pattern of words (the bind *param*: in lower case) anywhere: every row whose text
# holds them is one it matches, on a trigram index on that text in lower case
# (``lower_like``) or folded as the search folds (``folded_like``, ``lg_fold``).


def lower_like(param: str) -> str:
    """SQL: a LIKE pattern of the words of the bind *param* anywhere, in lower case."""
    return f"'%%' || lg_like(%({param})s) || '%%'"


def folded_like(param: str) -> str:
    """SQL: a LIKE pattern of the words of the bind *param* anywhere, folded (``lg_fold``)."""
    return f"'%%' || lg_like(lg_fold(%({param})s)) || '%%'"


# Of a word and the name it is bound as, SQL of a row that holds it too (on the index and
# in the test alike), its values bound; None: none.
Also = Callable[[str, str, dict[str, Any]], str | None]


def word_sql(
    text: str, word: str, name: str, bind: dict[str, Any], also: Also | None = None
) -> tuple[str, str]:
    """SQL: the condition of the trigram index on *text* (the words of a row in lower case;
    empty for a word of fewer than ``TRIGRAM`` letters) and the test that *text* holds
    *word* (bound as *name*), as ``/api/search`` finds a row by a word
    (``search.types._all_words``) but from the start of a word: the word
    (``word_pattern``: a short one whole), or the start of a word in its stem of
    ``STEM_MIN`` characters or more (``afkeuringen``: afkeuring), folded (``lg_fold``);
    *also* what holds a row of it besides."""
    word = words(word)
    bind[name] = word
    bind[f"{name}_word"] = word_pattern(word)
    stem = _STEM.format(name=name)
    stemmed = f"char_length({stem}) >= {STEM_MIN}"
    index = [
        f"{text} LIKE {lower_like(name)}",
        f"({stemmed} AND {text} LIKE '%%' || lg_like({stem}) || '%%')",
    ]
    test = [
        holds(text, f"{name}_word"),
        f"({stemmed} AND lg_fold({text}) ~ ('\\m' || {stem}))",
    ]
    if also is not None and (named := also(word, name, bind)):
        index.append(named)
        test.append(named)
    if len(word) < TRIGRAM:
        return "", f"({' OR '.join(test)})"
    return f"({' OR '.join(index)})", f"({' OR '.join(test)})"


def any_query(
    queries: Iterable[tuple[str, ...]],
    text: str,
    bind: dict[str, Any],
    also: Also | None = None,
    indexed: bool = True,
) -> list[str]:
    """SQL: the conditions that *text* holds every word of one of *queries* (``word_sql``),
    in any order: by the trigram index on *text* when it is *indexed* and each query has a
    word of ``TRIGRAM`` letters or more, then tested; none without a query."""
    found, tests = [], []
    for n, query in enumerate(dict.fromkeys(q for q in queries if q)):
        each = [
            word_sql(text, w, f"q_{n}_{m}", bind, also) for m, w in enumerate(query)
        ]
        found.append(" AND ".join(index for index, _ in each if index))
        tests.append(" AND ".join(test for _, test in each))
    if not tests:
        return []
    clauses = [f"(({') OR ('.join(tests)}))"]
    if indexed and all(found):
        clauses.insert(0, f"(({') OR ('.join(found)}))")
    return clauses
