"""Pydantic DTO for ``/api/health``."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PoolUsageDTO(BaseModel):
    """One connection pool of the API process."""

    size: int = Field(description="Its connections.")
    free: int = Field(description="Those not reading now.")
    waiting: int = Field(description="Reads waiting for a connection of it.")


class BusyCallDTO(BaseModel):
    """A call a thread of a shared pool runs now (queries side by side, the searches)."""

    thread: str
    call: str = Field(
        description="The function: module, name and, of a lambda, its line."
    )
    seconds: float = Field(description="How long it has run.")


class HealthDTO(BaseModel):
    """Whether the API reaches its database, and how warm and busy it is."""

    status: str
    database: str
    warm: bool | None = Field(
        description=(
            "The answers every visitor asks are computed for the data as it is now; "
            "null when the API does not warm up."
        )
    )
    warm_version: str | None = Field(
        default=None,
        description="The data version the last warm-up was done for (null before it).",
    )
    data_version: str | None = Field(
        default=None, description="The data version now (null without warm-up)."
    )
    computing: bool | None = Field(
        default=None,
        description="A warm-up waits or runs, or an answer of the cache is computed.",
    )
    pools: dict[str, PoolUsageDTO | None] = Field(
        description=(
            "Per connection pool (`requests`, `background`; null before the background "
            "one is first needed) its use."
        )
    )
    busy: list[BusyCallDTO] = Field(
        default_factory=list,
        description="The calls the threads of the shared pools run now, longest first.",
    )
