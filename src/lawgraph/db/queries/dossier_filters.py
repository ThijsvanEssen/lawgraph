"""What a dossier list keeps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DossierFilters:
    """What a dossier list keeps; None keeps everything."""

    status: str | None = None  # open, closed
    outcome: str | None = None
    kinds: tuple[str, ...] | None = None
    phases: tuple[str, ...] | None = None  # the current phase is one of them
    has_phase: tuple[str, ...] | None = None
    ministry: str | None = None
    seat: str | None = None  # an office: what is attributed to it (``queries.seats``)
    initiative: bool | None = None
    number: str | None = None  # a prefix of the label: 36264, 37020-
    subject: str | None = None
    committee_slug: str | None = None
    opened_from: str | None = None
    opened_to: str | None = None
