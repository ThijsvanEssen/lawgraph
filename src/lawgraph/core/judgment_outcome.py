"""How a judgment ended and what a conclusion proposes, as the decision says it (pure
functions, no I/O).

**The outcome of a judgment** stands in its decision ("Beslissing", "De beslissing",
"Dictum", "Uitspraak"): the paragraphs after the last such heading, up to the signature ("Dit
arrest is gewezen door …", "Aldus gewezen …") or the next heading. Its first dispositive
clause, from the verb up to the next ``;``, full stop, line or verb, is what the court did
first, and so how the case ended there:

- ``verwerpt het beroep`` → ``verworpen``;
- ``vernietigt …`` → ``vernietigd`` (``gedeeltelijk vernietigd`` with "voor zover", "maar
  uitsluitend", "behoudens"), ``vernietigd en verwezen`` when the decision also refers the
  case to a court (``verwijst het geding naar het gerechtshof``, ``wijst … terug``);
- ``bekrachtigt …`` → ``bekrachtigd``; ``bevestigt …`` → ``bevestigd``;
- ``verklaart het (hoger) beroep gegrond / ongegrond / niet-ontvankelijk``, and anyone
  ``niet-ontvankelijk`` → ``gegrond``, ``ongegrond``, ``niet-ontvankelijk`` (``gegrond``
  with a vernietiging and a verwijzing → ``vernietigd en verwezen``);
- ``wijst het verzoek (de vordering, het gevorderde) af`` → ``afgewezen``, ``… toe`` →
  ``toegewezen``;
- ``draagt het bestuursorgaan op …`` (an order to repair a defect, a bestuurlijke lus) →
  ``tussenuitspraak``: the case is not decided yet.

A heading that only names the court under the heading of the decision ("De Afdeling
bestuursrechtspraak van de Raad van State") is not its end.

A first clause that is none of these (``verklaart bewezen``, ``veroordeelt``, ``bepaalt``)
gives no outcome: a conviction or an order to pay is told by its sentence, not by a word. Of 13,816
judgments and decisions on the small database 80% have one; of 1,197 conclusions 82% say
what they propose.

**What a conclusion proposes** (its strekking) stands at its end: "De conclusie strekt tot
verwerping van het beroep", "Ik geef de Hoge Raad in overweging het beroep in cassatie
ongegrond te verklaren", "concludeer ik dat Uw Raad het arrest zal vernietigen en de zaak
zal verwijzen". The last such sentence names it by its first word of a kind:
``verwerping``, ``vernietiging`` (``vernietiging en verwijzing``),
``niet-ontvankelijkverklaring``, ``gegrondverklaring``, ``ongegrondverklaring`` or
``beantwoording`` (of preliminary questions).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from lawgraph.core.display import shorten
from lawgraph.core.echr_findings import EchrFinding
from lawgraph.core.judgment_kinds import KIND_CONCLUSIE
from lawgraph.core.judgment_paragraphs import ParagraphKind
from lawgraph.core.xml import collapse_ws

# The outcomes of a judgment; of the ECHR its finding (``core.echr_findings``).
JudgmentOutcome = Literal[
    "verworpen",
    "vernietigd",
    "gedeeltelijk vernietigd",
    "vernietigd en verwezen",
    "bekrachtigd",
    "bevestigd",
    "gegrond",
    "ongegrond",
    "niet-ontvankelijk",
    "afgewezen",
    "toegewezen",
    "tussenuitspraak",
    EchrFinding,
]
REJECTED: Final[JudgmentOutcome] = "verworpen"
QUASHED: Final[JudgmentOutcome] = "vernietigd"
PARTLY_QUASHED: Final[JudgmentOutcome] = "gedeeltelijk vernietigd"
QUASHED_REFERRED: Final[JudgmentOutcome] = "vernietigd en verwezen"
AFFIRMED: Final[JudgmentOutcome] = "bekrachtigd"
CONFIRMED: Final[JudgmentOutcome] = "bevestigd"
WELL_FOUNDED: Final[JudgmentOutcome] = "gegrond"
UNFOUNDED: Final[JudgmentOutcome] = "ongegrond"
INADMISSIBLE: Final[JudgmentOutcome] = "niet-ontvankelijk"
DISMISSED: Final[JudgmentOutcome] = "afgewezen"
GRANTED: Final[JudgmentOutcome] = "toegewezen"
INTERIM: Final[JudgmentOutcome] = "tussenuitspraak"

# What a conclusion proposes.
ConclusionOutcome = Literal[
    "verwerping",
    "vernietiging",
    "vernietiging en verwijzing",
    "niet-ontvankelijkverklaring",
    "gegrondverklaring",
    "ongegrondverklaring",
    "beantwoording",
]
TO_REJECT: Final[ConclusionOutcome] = "verwerping"
TO_QUASH: Final[ConclusionOutcome] = "vernietiging"
TO_QUASH_REFER: Final[ConclusionOutcome] = "vernietiging en verwijzing"
TO_INADMISSIBLE: Final[ConclusionOutcome] = "niet-ontvankelijkverklaring"
TO_WELL_FOUNDED: Final[ConclusionOutcome] = "gegrondverklaring"
TO_UNFOUNDED: Final[ConclusionOutcome] = "ongegrondverklaring"
TO_ANSWER: Final[ConclusionOutcome] = "beantwoording"

# The characters of the sentence kept at most.
SENTENCE_CHARS = 300

# The heading of the decision, numbered or not.
_DECISION_HEADING = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2})*\.?\s*|[IVX]{1,4}\.?\s+)?(?:de\s+)?"
    r"(?:beslissing|dictum|uitspraak|beslist)"
    r"(?:\s+(?:op\s+het\s+(?:hoger\s+)?beroep|in\s+(?:hoger\s+beroep|cassatie)))?\s*:?$",
    re.IGNORECASE,
)
# The heading in front of the decision in one paragraph, as old judgments of the Hoge Raad
# print it ("5. Beslissing De Hoge Raad: verwerpt het beroep").
_INLINE_HEADING = re.compile(
    r"^(?:\d{1,2}\.?\s+)?(?i:de\s+)?(?i:beslissing|dictum)\s*:?\s+(?=[A-Z(\[-])"
)
# The court that speaks, printed as a heading right under the heading of the decision ("De
# Afdeling bestuursrechtspraak van de Raad van State"): no end of the decision.
_COURT_HEADING = re.compile(
    r"^(?:de|het)\s+(?:(?:voorzieningenrechter|voorzitter)\s+van\s+(?:de|het)\s+)?"
    r"(?:afdeling|hoge\s+raad|raad|rechtbank|centrale\s+raad|college|(?:gerechts)?hof|"
    r"kantonrechter|president|voorzieningenrechter)\b",
    re.IGNORECASE,
)
# Where the decision ends: its signature.
_SIGNATURE = re.compile(
    r"^(?:(?:dit|deze)\s+(?:arrest|uitspraak|vonnis|beschikking|beslissing)\s+is\s+"
    r"(?:gewezen|gedaan|uitgesproken|gegeven|vastgesteld)|aldus\s+(?:gewezen|gedaan|"
    r"vastgesteld|beslist|gegeven)|w\.g\.|\(getekend\))",
    re.IGNORECASE,
)
# The paragraphs of a decision read at most.
_DECISION_PARAGRAPHS = 20
# The verbs a dispositive clause opens with: the first of them opens the first clause, and
# each ends the clause before it.
_VERB = re.compile(
    r"\b(?:verwerpt|vernietigt|bekrachtigt|bevestigt|verklaart|wijst|veroordeelt|bepaalt|"
    r"gelast|draagt|stelt|legt|spreekt|beveelt|herstelt|verbetert|verleent|ontzegt|kent|"
    r"schorst|houdt|machtigt|benoemt|wijzigt|ontbindt|verstaat|heropent|verwijst|treft|"
    r"neemt|doet|laat|vermindert|vermeerdert|matigt|ontslaat|wijst)\b",
    re.IGNORECASE,
)
# Where a clause ends besides the next verb: a semicolon, a line, a full stop before a capital
# (not the one of "B.V." or "nr.").
_CLAUSE_END = re.compile(r"[;\n]|\.(?=\s+[A-Z(\[]|\s*$)")
_PARTLY = re.compile(
    r"\bvoor\s*zover\b|\bmaar\s+(?:uitsluitend|alleen)\b|\buitsluitend\s+wat\s+betreft\b"
    r"|\bbehoudens\b",
    re.IGNORECASE,
)
# A referral of the case to a court after the quashing (not "verwijst de zaak naar de rol").
_REFERRED = re.compile(
    r"\bverwijst\s+(?:het\s+geding|de\s+zaak|de\s+zaken|de\s+gedingen)\b[^;\n]{0,80}?"
    r"\bnaar\s+(?:het|de)\s+(?:gerechtshof|hof|rechtbank|centrale\s+raad|college)"
    r"|\bwijst\b[^;\n]{0,80}?\bterug\b|\bterug\s*(?:ver)?wijzing\b",
    re.IGNORECASE,
)
_QUASHES = re.compile(r"\bvernietigt\b", re.IGNORECASE)
# "niet-ontvankelijk", also with a non-breaking hyphen or a space.
_NOT_ADMISSIBLE = r"\bniet[-\u2010\u2011\s]?ontvankelijk\b"
# What a court allows or dismisses.
_CLAIM = r"(?:verzoek(?:en)?|vordering(?:en)?|gevorderde|verzet)\b"
# A clause and the outcome it gives, tried in this order.
_CLAUSES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^verwerpt\s+(?:\S+\s+){0,4}?(?:\w*beroep(?:en)?|verzet)\b", re.I),
        REJECTED,
    ),
    (re.compile(r"^vernietigt\b", re.I), QUASHED),
    (re.compile(r"^bekrachtigt\b", re.I), AFFIRMED),
    (re.compile(r"^bevestigt\b", re.I), CONFIRMED),
    (re.compile(rf"^verklaart\b.*{_NOT_ADMISSIBLE}", re.I), INADMISSIBLE),
    (re.compile(r"^verklaart\b.*\bongegrond\b", re.I), UNFOUNDED),
    (re.compile(r"^verklaart\b.*\bgegrond\b", re.I), WELL_FOUNDED),
    (
        re.compile(
            rf"^wijst\s+(?:af\s+)?(?:\S+\s+){{0,12}}?{_CLAIM}.*\baf\b|^wijst\s+af\b",
            re.I,
        ),
        DISMISSED,
    ),
    (re.compile(rf"^wijst\s+(?:\S+\s+){{0,12}}?{_CLAIM}.*\btoe\b", re.I), GRANTED),
    # an order to a body to repair a defect (bestuurlijke lus) leaves the case open; not the
    # one to the registry to tell the parties something
    (re.compile(r"^draagt\s+(?!de\s+griffi)(?:\S+\s+){0,12}?op\b", re.I), INTERIM),
)

# The sentence that says what a conclusion proposes.
_STREKKING = re.compile(
    r"\bconclusie\s+strek(?:t|ken)\b|\bstrekt\s+(?:deze|mijn)\s+conclusie\b"
    r"|\bin\s+overweging\b|\bconcludeer(?:t|en)?\s+(?:ik\s+)?tot\b"
    r"|\bconcludeer\s+ik\b[^.]{0,200}?\b(?:uw\s+raad|de\s+hoge\s+raad)\b",
    re.IGNORECASE,
)
# The words of a proposal, the earliest in the sentence naming it.
_PROPOSALS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bniet[-\s]?ontvankelijk", re.I), TO_INADMISSIBLE),
    (re.compile(r"\bvernieti?g", re.I), TO_QUASH),
    (re.compile(r"\bverwerp", re.I), TO_REJECT),
    (re.compile(r"\bongegrond", re.I), TO_UNFOUNDED),
    (re.compile(r"\bgegrond", re.I), TO_WELL_FOUNDED),
    (
        re.compile(r"\bbeantwoord|\bbeantwoording\b|\bte\s+beantwoorden\b", re.I),
        TO_ANSWER,
    ),
)
_REFERRAL = re.compile(
    r"\b(?:terug)?(?:ver)?wijzing\b|\b(?:terug\s+te\s+|te\s+)?(?:ver|terug)wijzen\b"
    r"|\bverwijzen\b|\bterug\s+te\s+wijzen\b",
    re.IGNORECASE,
)
# A sentence ends at a full stop before a space or the end.
_SENTENCE_END = re.compile(r"\.(?:\s|$)")


@dataclass(frozen=True)
class Outcome:
    """An outcome (or a proposal), the sentence of the source that says it and the id of its
    paragraph."""

    label: str
    text: str
    paragraph_id: str | None


def _text(paragraph: Mapping[str, Any]) -> str:
    return str(paragraph.get("text") or "").strip()


def _decision(
    paragraphs: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """The paragraphs of the decision: after the last decision heading, up to the signature
    or the next heading."""
    start, inline = None, None
    for n, paragraph in enumerate(paragraphs):
        text = _text(paragraph)
        if _DECISION_HEADING.match(text):
            start, inline = n, None
        elif heading := _INLINE_HEADING.match(text):
            start, inline = n, {**paragraph, "text": text[heading.end() :]}
    if start is None:
        return []
    found: list[Mapping[str, Any]] = [inline] if inline else []
    for paragraph in paragraphs[start + 1 : start + 1 + _DECISION_PARAGRAPHS]:
        text = _text(paragraph)
        if paragraph.get("kind") == ParagraphKind.HEADING:
            if found or not _COURT_HEADING.match(text):
                break
            continue
        if _SIGNATURE.match(text):
            break
        found.append(paragraph)
    return found


def _clauses(
    paragraphs: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Every dispositive clause of the decision with its paragraph, in order."""
    clauses = []
    for paragraph in paragraphs:
        text = _text(paragraph)
        verbs = list(_VERB.finditer(text))
        for n, verb in enumerate(verbs):
            nxt = verbs[n + 1].start() if n + 1 < len(verbs) else len(text)
            end = _CLAUSE_END.search(text, verb.start(), nxt)
            clause = text[verb.start() : end.start() if end else nxt]
            clause = re.sub(r"(?:,|\s+en|\s+ook)\s*$", "", collapse_ws(clause))
            clauses.append((clause, paragraph))
    return clauses


def judgment_outcome(paragraphs: Sequence[Mapping[str, Any]] | None) -> Outcome | None:
    """The outcome of a judgment with these *paragraphs* (``{id, kind, text}``, as
    ``core.judgment_paragraphs.judgment_text`` reads them); None when its decision does not say one
    of them in its first clause (see the module)."""
    clauses = _clauses(_decision(paragraphs or []))
    if not clauses:
        return None
    clause, paragraph = clauses[0]
    label = next((label for pattern, label in _CLAUSES if pattern.search(clause)), None)
    if label is None:
        return None
    if label == QUASHED and _PARTLY.search(clause):
        label = PARTLY_QUASHED
    rest = " ".join(text for text, _ in clauses)
    if (
        label in (QUASHED, PARTLY_QUASHED, WELL_FOUNDED)
        and _QUASHES.search(rest)
        and _REFERRED.search(rest)
    ):
        label = QUASHED_REFERRED
    return Outcome(label, shorten(clause, SENTENCE_CHARS), paragraph.get("id"))


def _sentence_at(text: str, at: int) -> str:
    """The sentence of *text* around the position *at*."""
    starts = [m.end() for m in _SENTENCE_END.finditer(text, 0, at)]
    start = starts[-1] if starts else 0
    end = _SENTENCE_END.search(text, at)
    return collapse_ws(text[start : end.start() + 1 if end else len(text)])


def _proposal(sentence: str) -> str | None:
    found = [
        (match.start(), label)
        for pattern, label in _PROPOSALS
        if (match := pattern.search(sentence))
    ]
    if not found:
        return None
    label = min(found)[1]
    if label == TO_QUASH and _REFERRAL.search(sentence):
        return TO_QUASH_REFER
    return label


def conclusion_outcome(
    paragraphs: Sequence[Mapping[str, Any]] | None,
) -> Outcome | None:
    """What the conclusion with these *paragraphs* proposes: the last sentence that says
    what it strekt tot (see the module) and names a proposal; None without one."""
    for paragraph in reversed(paragraphs or []):
        text = _text(paragraph)
        for match in reversed(list(_STREKKING.finditer(text))):
            sentence = _sentence_at(text, match.start())
            # what it proposes follows the words that say it does ("concludeer ik, het
            # middel gegrond achtend, tot verwerping")
            label = _proposal(text[match.end() : match.end() + len(sentence)])
            if label is not None:
                return Outcome(
                    label, shorten(sentence, SENTENCE_CHARS), paragraph.get("id")
                )
    return None


# The props of a judgment this keeps (``normalize rechtspraak``): of a judgment its outcome,
# of a conclusion what it proposes, each with its sentence and paragraph.
OUTCOME_PROPS = (
    "outcome",
    "outcome_text",
    "outcome_paragraph_id",
    "conclusion_outcome",
    "conclusion_outcome_text",
    "conclusion_outcome_paragraph_id",
)


def outcome_props(
    judgment_kind: str | None, paragraphs: Sequence[Mapping[str, Any]] | None
) -> dict[str, Any]:
    """The ``OUTCOME_PROPS`` of a Dutch judgment of *judgment_kind* (``conclusie`` for a
    conclusion) with these *paragraphs*: those it has none of null, so a run again clears
    what an earlier one kept."""
    conclusion = judgment_kind == KIND_CONCLUSIE
    found = (
        conclusion_outcome(paragraphs) if conclusion else judgment_outcome(paragraphs)
    )
    prefix = "conclusion_outcome" if conclusion else "outcome"
    props: dict[str, Any] = dict.fromkeys(OUTCOME_PROPS)
    if found is not None:
        props[prefix] = found.label
        props[f"{prefix}_text"] = found.text
        props[f"{prefix}_paragraph_id"] = found.paragraph_id
    return props
