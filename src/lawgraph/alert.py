"""The alert of a run in plain Dutch: what went wrong, and whether it is tried again by itself
or waits for someone. The command lines, exceptions and logs stay in runs.log and the log of
the run.

    python -m lawgraph.alert <script> [<chain or ops script>] < record

The script is ``daily``, ``weekly``, ``step`` (a step of the weekly run), ``poll <chain>`` or
``ops <script>``. The record (``scripts/_run.sh``, ``scripts/weekly.sh``, ``ops/_steps.sh``)
has a line per step that did not end well: its kind, its command line and the reason it left
(``LAWGRAPH_OUTCOME_FILE``), separated by tabs. The kinds:

    failed       the step failed
    unavailable  a source refused us and the rest went on (exit 3)
    skipped      the step waited for the lock and gave its turn up (exit 75)
    stuck        a step in slices that went no further
    held         the run was not started three times in a row: another run held the lock

A step is named by what it does (``Pipeline.plain``, ``commands.table``); a step of a parent
that names it (``semantic tk failed: …``) by that step. A known failure
(``KNOWN_FAILURES``) is said in its own words; any other is an unexpected failure with the
start of its message.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lawgraph.commands.table import COMMANDS, PHASE_ALL
from lawgraph.pipelines.command import KNOWN_FAILURES
from lawgraph.sources.addresses import PHASES, SOURCES
from lawgraph.sources.registry import find


@dataclass(frozen=True)
class Run:
    name: str
    # when it is tried again by itself ("bij de volgende dagelijkse update"); None: an ops
    # script, which stops at a failure and waits for someone
    again: str | None


_WEEKLY = Run("Wekelijkse update", "volgende week")
RUNS: dict[str, Run] = {
    "daily": Run("Dagelijkse update", "bij de volgende dagelijkse update"),
    "weekly": _WEEKLY,
    "step": _WEEKLY,  # scripts/step.sh: one step of the weekly run
}
# The chains of ``lawgraph poll`` (``commands/poll.py``).
POLL_RUNS: dict[str, str] = {
    "tk": "Ophalen van nieuwe stukken van de Tweede Kamer",
    "ek": "Ophalen van nieuwe stukken van de Eerste Kamer",
    "rechtspraak": "Ophalen van nieuwe uitspraken van de Rechtspraak",
    "echr": "Ophalen van nieuwe uitspraken van het EHRM",
}
_POLL_AGAIN = "bij de volgende ophaalronde"

# How much of an unexpected message the alert keeps; the log has all of it.
MESSAGE_CHARS = 120

_KNOWN = {cls.__name__: known for cls, known in KNOWN_FAILURES.items()}
_PHASE = "|".join(PHASES)
_FAILED_STEP = re.compile(rf"\b({_PHASE}) ([a-z0-9-]+) failed\b")
_UNAVAILABLE_STEP = re.compile(rf"(?:^|; )({_PHASE}) ([a-z0-9-]+): ")
_TYPE = re.compile(r"(?:^|[:;(] )([A-Z][A-Za-z0-9_]*): ")
_PARENT = re.compile(rf"^(?:(?:{_PHASE}) [a-z0-9-]+ failed: )+")
_MORE = re.compile(r" \(and \d+ more\)$")
_EXIT_CODE = re.compile(r"exit code (\d+)")


@dataclass(frozen=True)
class _Line:
    kind: str
    label: str
    why: str


def run_of(args: Sequence[str]) -> Run:
    script, *rest = args or [""]
    if script == "poll":
        chain = rest[0] if rest else ""
        return Run(POLL_RUNS.get(chain, "Ophalen van nieuwe stukken"), _POLL_AGAIN)
    if script == "ops":
        return Run(" ".join(["Onderhoudstaak", *rest[:1]]), None)
    return RUNS.get(script, Run(script, None))


def told(args: Sequence[str], record: str) -> str:
    """The alert of the run *args* from its *record*, in one line."""
    run = run_of(args)
    lines = [_Line(*(line.split("\t") + ["", ""])[:3]) for line in record.splitlines()]
    if any(line.kind == "held" for line in lines):
        return (
            f"{run.name}: drie keer achter elkaar niet gestart, omdat een andere run de "
            "database bezet hield. Kijk of die run vastzit."
        )
    sentences, needs_action = _failures(
        [x for x in lines if x.kind in ("failed", "stuck")]
    )
    skipped = _unique(_step(x.label) for x in lines if x.kind == "skipped")
    if skipped:
        sentences.append(
            f"{_listed(skipped)} {_is(skipped)} overgeslagen, omdat een andere run de "
            "database te lang bezet hield."
        )
    away = _unique(s for x in lines if x.kind == "unavailable" for s in _sources(x))
    if away:
        verb = "was" if len(away) == 1 else "waren"
        sentences.append(
            f"{_listed(away)} {verb} niet bereikbaar, de rest is wel bijgewerkt."
        )
    failed = any(x.kind in ("failed", "stuck") for x in lines)
    if run.again is None:
        sentences.append(
            "De taak is gestopt en wacht op actie." if failed else "De taak gaat door."
        )
    elif needs_action:
        sentences.append("Dit vraagt om actie.")
    elif sentences:
        sentences.append(f"Wordt {run.again} opnieuw geprobeerd.")
    else:
        sentences.append("Er ging iets mis. Dit vraagt om actie.")
    first, *rest = sentences
    return " ".join([f"{run.name}: {first}", *(_capital(s) for s in rest)])


def _failures(lines: list[_Line]) -> tuple[list[str], bool]:
    """A sentence for the steps that failed alike and one for why; and whether one asks
    for action."""
    causes: dict[str, list[str]] = {}
    needs_action = False
    for line in lines:
        cause, passes = _cause(line)
        needs_action = needs_action or not passes
        causes.setdefault(cause, []).extend(_steps(line))
    sentences: list[str] = []
    for cause, steps in causes.items():
        steps = _unique(steps)
        sentences += [f"{_listed(steps)} {_is(steps)} mislukt.", cause]
    return sentences, needs_action


def _steps(line: _Line) -> list[str]:
    """What failed: the steps of a parent its reason names, else the step itself."""
    inner = [find(phase, name) for phase, name in _FAILED_STEP.findall(line.why)]
    return _unique(p.plain for p in inner if p) or [_step(line.label)]


def _step(label: str) -> str:
    words = label.removeprefix("lawgraph ").split()
    if len(words) >= 2 and words[0] in PHASE_ALL:
        if words[1] == "all":
            return PHASE_ALL[words[0]].plain
        pipeline = find(words[0], words[1])
        if pipeline:
            return pipeline.plain
    if words and words[0] in COMMANDS:
        return COMMANDS[words[0]].plain
    return label


def _sources(line: _Line) -> list[str]:
    """The sources that were unavailable, by their names."""
    found = [find(phase, name) for phase, name in _UNAVAILABLE_STEP.findall(line.why)]
    words = line.label.removeprefix("lawgraph ").split()
    if not any(found) and len(words) >= 2:
        found = [find(words[0], words[1])]
    return [SOURCES[p.source] for p in found if p] or ["een bron"]


def _cause(line: _Line) -> tuple[str, bool]:
    """Why, in a sentence, and whether that passes by itself."""
    if line.kind == "stuck":
        return "De stap kwam niet verder.", False
    for name in _TYPE.findall(line.why):
        if name in _KNOWN:
            return _KNOWN[name].said, _KNOWN[name].passes
    code = _EXIT_CODE.fullmatch(line.why)
    if not line.why or code:
        said = f" (code {code.group(1)})" if code else ""
        return f"De stap stopte zonder te zeggen waarom{said}.", False
    return _unexpected(line.why), False


def _unexpected(why: str) -> str:
    message = _MORE.sub("", _PARENT.sub("", why))
    typed = re.match(r"([A-Z][A-Za-z0-9_]*): (.*)", message)
    said = f"({typed.group(1)}) {typed.group(2)}" if typed else f"({message})"
    if len(said) > MESSAGE_CHARS:
        return f"Onverwachte fout {said[:MESSAGE_CHARS].rsplit(' ', 1)[0]} …"
    return f"Onverwachte fout {said}" + ("" if said.endswith((".", "!", "?")) else ".")


def _listed(items: list[str]) -> str:
    """``a``, ``a en b``, ``a, b en c``, ``a, b en 2 andere stappen``."""
    if len(items) > 3:
        items = [*items[:2], f"{len(items) - 2} andere stappen"]
    return (
        " en ".join([", ".join(items[:-1]), items[-1]]) if len(items) > 1 else items[0]
    )


def _is(items: list[str]) -> str:
    return "is" if len(items) == 1 else "zijn"


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _capital(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:]


def main() -> None:
    print(told(sys.argv[1:], sys.stdin.read()))


if __name__ == "__main__":
    main()
