"""``lawgraph.alert``: the alert of a run in plain Dutch, from the record its script kept."""

from __future__ import annotations

import pytest

from lawgraph import alert
from lawgraph.commands.poll import POLLS
from lawgraph.commands.table import COMMANDS, PHASE_ALL
from lawgraph.sources.addresses import PHASES
from lawgraph.sources.registry import PIPELINES


def _record(*lines: tuple[str, str, str]) -> str:
    return "".join("\t".join(line) + "\n" for line in lines)


@pytest.mark.parametrize(
    ("run", "record", "said"),
    [
        (
            ["daily"],
            _record(
                (
                    "failed",
                    "lawgraph check --skip-edges",
                    "DatabaseUnavailable: Cannot connect to PostgreSQL at localhost:5432 "
                    "(db=lawgraph): refused (Writing a batch of 9 edges failed; it stays "
                    "queued.)",
                )
            ),
            "Dagelijkse update: de controle is mislukt. De database was niet "
            "bereikbaar. Wordt bij de volgende dagelijkse update opnieuw geprobeerd.",
        ),
        (
            # a step of a parent: the step that failed is named, not the parent
            ["daily"],
            _record(
                (
                    "failed",
                    "lawgraph semantic all --since last",
                    "semantic tk failed: KeyError: 'dossier' (and 2 more)",
                )
            ),
            "Dagelijkse update: het koppelen van wetsartikelen in Kamerstukken is "
            "mislukt. Onverwachte fout (KeyError) 'dossier'. Dit vraagt om actie.",
        ),
        (
            ["daily"],
            _record(
                (
                    "unavailable",
                    "lawgraph retrieve all --since last",
                    "retrieve echr: the source is unavailable (HTTP 403) after 0 records "
                    "were stored: HTTPError: 403 Forbidden",
                )
            ),
            "Dagelijkse update: ECHR (HUDOC) was niet bereikbaar, de rest is wel "
            "bijgewerkt. Wordt bij de volgende dagelijkse update opnieuw geprobeerd.",
        ),
        (
            ["poll", "tk"],
            _record(("held", "", "")),
            "Ophalen van nieuwe stukken van de Tweede Kamer: drie keer achter elkaar "
            "niet gestart, omdat een andere run de database bezet hield. Kijk of die "
            "run vastzit.",
        ),
        (
            ["weekly"],
            _record(
                ("skipped", "lawgraph check", ""),
                ("skipped", "lawgraph search-candidates", ""),
            ),
            "Wekelijkse update: de controle en het bijwerken van de zoeksuggesties zijn "
            "overgeslagen, omdat een andere run de database te lang bezet hield. Wordt "
            "volgende week opnieuw geprobeerd.",
        ),
        (
            ["ops", "relink-citations"],
            _record(
                (
                    "failed",
                    "lawgraph semantic rechtspraak-citations --after x --limit 150000",
                    "StoreUnavailable: 12 raw records could not be written: timeout",
                )
            ),
            "Onderhoudstaak relink-citations: het koppelen van verwijzingen tussen "
            "uitspraken is mislukt. De database nam de gegevens niet aan, ook niet na "
            "een paar pogingen. De taak is gestopt en wacht op actie.",
        ),
        (
            ["daily"],
            _record(("failed", "lawgraph sitemaps", "exit code 137")),
            "Dagelijkse update: het maken van de sitemaps is mislukt. De stap stopte "
            "zonder te zeggen waarom (code 137). Dit vraagt om actie.",
        ),
        (
            # a failure that does not pass by itself asks for action in any run
            ["poll", "rechtspraak"],
            _record(
                (
                    "failed",
                    "lawgraph poll rechtspraak --since 6h",
                    "normalize rechtspraak failed: SchemaOutdated: the tables are not "
                    "those of the schema: run `lawgraph check`",
                )
            ),
            "Ophalen van nieuwe uitspraken van de Rechtspraak: het verwerken van "
            "uitspraken van de Rechtspraak is mislukt. De database heeft nog niet de "
            "tabellen van deze versie. Dit vraagt om actie.",
        ),
        (
            ["weekly"],
            _record(("stuck", "lawgraph semantic rechtspraak", "no progress after k1")),
            "Wekelijkse update: het koppelen van wetsartikelen in uitspraken is "
            "mislukt. De stap kwam niet verder. Dit vraagt om actie.",
        ),
    ],
)
def test_an_alert_says_in_plain_dutch_what_went_wrong_and_what_happens(
    run: list[str], record: str, said: str
) -> None:
    assert alert.told(run, record) == said


def test_steps_that_failed_alike_are_told_once() -> None:
    """The database down fails every step of the night: one cause, the steps counted."""
    why = "DatabaseUnavailable: Cannot connect to PostgreSQL"
    record = _record(
        ("failed", "lawgraph retrieve all --since last", f"retrieve tk failed: {why}"),
        ("failed", "lawgraph normalize all --since last", why),
        ("failed", "lawgraph feed-events", why),
        ("failed", "lawgraph check --skip-edges", why),
        ("failed", "lawgraph sitemaps", "exit code 1"),
    )
    assert alert.told(["daily"], record) == (
        "Dagelijkse update: het ophalen van de zaken van de Tweede Kamer, het "
        "verwerken van wat is opgehaald en 2 andere stappen zijn mislukt. De database "
        "was niet bereikbaar. Het maken van de sitemaps is mislukt. De stap stopte "
        "zonder te zeggen waarom (code 1). Dit vraagt om actie."
    )


def test_a_failure_and_a_source_away_in_one_run() -> None:
    record = _record(
        ("unavailable", "lawgraph poll echr --since 1d", "retrieve echr: HTTP 403"),
        ("failed", "lawgraph feed-events --days 14", "SourceDown: tk: 10 in a row"),
    )
    assert alert.told(["poll", "echr"], record) == (
        "Ophalen van nieuwe uitspraken van het EHRM: het bijwerken van de nieuwsfeed "
        "is mislukt. Een bron gaf te vaak achter elkaar geen antwoord. ECHR (HUDOC) "
        "was niet bereikbaar, de rest is wel bijgewerkt. Wordt bij de volgende "
        "ophaalronde opnieuw geprobeerd."
    )


def test_an_unknown_step_and_a_long_message_stay_short() -> None:
    long = "ProgrammingError: column x does not exist " + "word " * 80
    said = alert.told(["ops", "x"], _record(("failed", "something odd", long)))
    assert said.startswith(
        "Onderhoudstaak x: something odd is mislukt. Onverwachte fout "
        "(ProgrammingError) column x does not exist word"
    )
    assert said.endswith("… De taak is gestopt en wacht op actie.")
    assert len(said) < 300


@pytest.mark.parametrize(
    "run", [["daily"], ["weekly"], ["step", "semantic"], ["poll", "tk"], ["ops", "x"]]
)
def test_an_alert_has_no_technical_words(run: list[str]) -> None:
    why = "DatabaseUnavailable: Cannot connect (it stays queued)"
    said = alert.told(run, _record(("failed", "lawgraph check --skip-edges", why)))
    for word in ("lawgraph", "--", "daily", "Unavailable", "·", "log:"):
        assert word not in said


# ── every step and run has its words ────────────────────────────────────────


def test_every_registered_pipeline_says_what_it_does_in_dutch() -> None:
    missing = [p.address for ps in PIPELINES.values() for p in ps if not p.plain]
    assert missing == []
    plains = [p.plain for ps in PIPELINES.values() for p in ps]
    assert all(plain[0].islower() and not plain.endswith(".") for plain in plains)
    assert len(set(plains)) == len(plains)  # no two steps told alike


def test_every_command_and_phase_says_what_it_does_in_dutch() -> None:
    assert set(PHASE_ALL) == set(PHASES)
    entries = [*COMMANDS.values(), *PHASE_ALL.values()]
    assert all(entry.plain and entry.plain[0].islower() for entry in entries)


def test_every_poll_chain_has_a_name() -> None:
    assert set(alert.POLL_RUNS) == set(POLLS)
