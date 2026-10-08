"""The words of a ``q`` as the feed and the decisions match them: in any case, each from
the start of a word, and one of at most ``WHOLE_WORD_MAX`` characters as a whole word too
(``ai``: the AI-verordening, not universitaire or Airport; ``algoritme``: algoritmes, not
rekenalgoritme)."""

from __future__ import annotations

WHOLE_WORD_MAX = 4
# Words of fewer characters have no trigram: no index finds the rows that hold them.
TRIGRAM = 3

# A LIKE pattern of ``q`` (the bind ``q``: in lower case) anywhere: every row whose text
# holds the words is one it matches, on a trigram index on that text folded as the search
# folds (``lg_fold``) or in lower case.
FOLDED_LIKE = "'%%' || lg_like(lg_fold(%(q)s)) || '%%'"
LOWER_LIKE = "'%%' || lg_like(%(q)s) || '%%'"


def words(q: str) -> str:
    """*q* as it is matched: trimmed, in lower case."""
    return q.strip().lower()


def word_pattern(q: str) -> str:
    """The regular expression of the words *q* (``words``): a character that is no letter,
    digit or space escaped; a word start before it and, when it is short, a word end after
    it, where it starts or ends with a letter or digit (``c.v.``: none after its last
    dot)."""
    escaped = "".join(c if c.isalnum() or c == " " else f"\\{c}" for c in q)
    start = r"\m" if q[:1].isalnum() else ""
    end = r"\M" if len(q) <= WHOLE_WORD_MAX and q[-1:].isalnum() else ""
    return f"{start}{escaped}{end}"


def holds(text: str) -> str:
    """SQL: the SQL *text* holds the words of the bind ``q_word`` (``word_pattern``)."""
    return f"lower({text}) ~ %(q_word)s"
