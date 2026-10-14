"""The words of a ``q`` as the feed and the decisions match them: in any case, each from
the start of a word, and one of at most ``WHOLE_WORD_MAX`` characters as a whole word too
(``ai``: the AI-verordening, not universitaire or Airport; ``algoritme``: algoritmes, not
rekenalgoritme)."""

from __future__ import annotations

WHOLE_WORD_MAX = 4
# Words of fewer characters have no trigram: no index finds the rows that hold them.
TRIGRAM = 3


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
