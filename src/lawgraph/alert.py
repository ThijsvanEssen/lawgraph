"""The alert of a run in one line of fixed form (docs/operations.md, "Alerts"):

    <run> <step>: <outcome>, <cause> [<follow-up>]
    Dag check: mislukt, db-weg [herhaalt]

    python -m lawgraph.alert <script> [<chain or script>] < record

The script is ``daily``, ``weekly``, ``step`` (a step of the weekly run), ``poll <chain>``,
``ops <script>`` or ``night <script>``. The record (``scripts/_run.sh``, ``scripts/weekly.sh``,
``ops/_steps.sh``, ``ops/_night.sh``) has a line per step that did not end well: its kind, its
command line and the reason it left (``LAWGRAPH_OUTCOME_FILE``), separated by tabs. The kinds:

    failed       the step failed
    unavailable  a source refused us and the rest went on (exit 3)
    skipped      the step waited for the lock and gave its turn up (exit 75)
    stuck        a step in slices that went no further
    held         the run was not started N times in a row (the reason): another held the lock

The step is the address of the pipeline or the command, without its options; of a parent that
names its failed step (``semantic tk failed: …``), that step. Steps with the same outcome and
cause are one item, the first named and the others counted (``+2``); items are separated by
``; ``. The codes come from here and from ``KNOWN_FAILURES``; the docs list each of them.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lawgraph.pipelines.command import KNOWN_FAILURES
from lawgraph.sources.addresses import PHASES

# The runs, by the script that runs them; ``<…>`` is the chain or the script given after it.
RUNS: dict[str, str] = {
    "daily": "Dag",
    "weekly": "Week",
    "step": "Week",  # scripts/step.sh: one step of the weekly run
    "poll": "Poll <bron>",
    "night": "Nacht <script>",  # an ops script at night (ops/_night.sh)
    "ops": "Ops <script>",  # the steps of an ops script (ops/_steps.sh)
}

OUTCOMES: dict[str, str] = {
    "mislukt": "the step failed",
    "bron-weg": "a source refused us; the rest went on",
    "overgeslagen": "not run, another run held the lock (`3x`: the run, so often in a row)",
    "vast": "a step in slices went no further",
}

# The causes besides those of KNOWN_FAILURES; ``<…>`` is filled in.
CAUSES: dict[str, str] = {
    "http-<N>": "the source answered with this status (401, 403)",
    "challenge": "the source answered with a challenge page",
    "geweigerd": "the source refused us otherwise",
    "geen-voortgang": "a slice named the same key again, or there were too many",
    "exit-<N>": "the command ended with this exit code without saying why",
    "onverwacht <Type> <tekst>": "any other failure: its exception and its first 60 characters",
    "server-ongewijzigd": "the deploy failed before it changed the server",
    "teruggezet": "the deploy failed; the previous version runs again",
    "terugzetten-faalt": "the deploy failed and the previous version does not answer",
}

FOLLOW_UPS: dict[str, str] = {
    "herhaalt": "the next run tries again by itself",
    "actie": "someone has to look",
}

# How much of an unexpected message the alert keeps; the log has all of it.
MESSAGE_CHARS = 60

_KNOWN = {cls.__name__: known for cls, known in KNOWN_FAILURES.items()}
_PHASE = "|".join(PHASES)
_FAILED_STEP = re.compile(rf"\b((?:{_PHASE}) [a-z0-9-]+) failed\b")
_UNAVAILABLE_STEP = re.compile(rf"(?:^|; )((?:{_PHASE}) [a-z0-9-]+): ")
_TYPE = re.compile(r"(?:^|[:;(] )([A-Z][A-Za-z0-9_]*): ")
_PARENT = re.compile(rf"^(?:(?:{_PHASE}) [a-z0-9-]+ failed: )+")
_MORE = re.compile(r" \(and \d+ more\)$")
_EXIT_CODE = re.compile(r"exit code (\d+)")
_HTTP = re.compile(r"\bHTTP (\d{3})\b")


@dataclass(frozen=True)
class _Line:
    kind: str
    label: str
    why: str


@dataclass(frozen=True)
class _Item:
    outcome: str
    cause: str
    follow_up: str


def run_code(args: Sequence[str]) -> str:
    script, *rest = args or [""]
    code = RUNS.get(script, script).split(" <")[0]
    return " ".join([code, *rest[:1]])


def told(args: Sequence[str], record: str) -> str:
    """The alert of the run *args* from its *record*, in one line."""
    run = run_code(args)
    repeats = bool(args) and args[0] not in ("ops", "night")
    items: dict[_Item, list[str]] = {}
    for text in record.splitlines():
        line = _Line(*(text.split("\t") + ["", ""])[:3])
        outcome, cause, passes = _ended(line)
        follow_up = "herhaalt" if passes and repeats else "actie"
        items.setdefault(_Item(outcome, cause, follow_up), []).extend(_steps(line))
    if not items:
        return f"{run}: mislukt, onverwacht [actie]"
    said = []
    for item, steps in items.items():
        _in_the_tables(item)
        # a poll is not named twice: `Poll tk`, not `Poll tk poll tk`
        named = [s for s in _unique(steps) if s and s.lower() != run.lower()]
        step = f" {named[0]}" if named else ""
        more = f" +{len(named) - 1}" if len(named) > 1 else ""
        said.append(
            f"{run}{step}{more}: {item.outcome}, {item.cause} [{item.follow_up}]"
        )
    return "; ".join(said)


def _in_the_tables(item: _Item) -> None:
    """Every code an alert gives is one of the tables (docs/operations.md, "Alerts")."""
    outcome = item.outcome.split("x ", 1)[-1]  # "3x overgeslagen"
    causes = [*CAUSES, *(known.code for known in KNOWN_FAILURES.values())]
    cause = any(
        item.cause == code
        or ("<" in code and item.cause.startswith(code.split("<")[0]))
        for code in causes
    )
    if outcome not in OUTCOMES or item.follow_up not in FOLLOW_UPS or not cause:
        raise ValueError(f"a code that is not in the tables: {item}")


def _ended(line: _Line) -> tuple[str, str, bool]:
    """Outcome, cause and whether that passes by itself."""
    if line.kind == "held":
        return f"{line.why or 3}x overgeslagen", "lock-bezet", False
    if line.kind == "skipped":
        return "overgeslagen", "lock-bezet", True
    if line.kind == "stuck":
        return "vast", "geen-voortgang", False
    if line.kind == "unavailable":
        status = _HTTP.search(line.why)
        if status:
            return "bron-weg", f"http-{status.group(1)}", True
        return "bron-weg", "challenge" if "challenge" in line.why else "geweigerd", True
    for name in _TYPE.findall(line.why):
        if name in _KNOWN:
            return "mislukt", _KNOWN[name].code, _KNOWN[name].passes
    code = _EXIT_CODE.fullmatch(line.why)
    if code:
        return "mislukt", f"exit-{code.group(1)}", False
    return "mislukt", _unexpected(line.why), False


def _unexpected(why: str) -> str:
    message = _MORE.sub("", _PARENT.sub("", why))
    typed = re.match(r"([A-Z][A-Za-z0-9_]*): (.*)", message)
    kind, text = (typed.group(1), typed.group(2)) if typed else ("", message)
    words = ("onverwacht", kind, text[:MESSAGE_CHARS].rstrip())
    return " ".join(word for word in words if word)


def _steps(line: _Line) -> list[str]:
    """What did not end well: the steps of a parent its reason names, else the step."""
    pattern = _UNAVAILABLE_STEP if line.kind == "unavailable" else _FAILED_STEP
    return _unique(pattern.findall(line.why)) or [_step(line.label)]


def _step(label: str) -> str:
    """``semantic rechtspraak`` of ``lawgraph semantic rechtspraak --after x --limit 9``."""
    words: list[str] = []
    for word in label.removeprefix("lawgraph ").split():
        if word.startswith("-"):
            break
        words.append(word)
    return " ".join(words)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def main() -> None:
    print(told(sys.argv[1:], sys.stdin.read()))


if __name__ == "__main__":
    main()
