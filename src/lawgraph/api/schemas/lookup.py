"""DTOs of ``GET /api/lookup``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LookupKind = Literal[
    "document",
    "dossier",
    "article",
    "law",
    "judgment",
    "publication",
    "official",
    "commitment",
    "faction",
    "committee",
    "cabinet",
]


class LookupResponse(BaseModel):
    """The one node an exact lookup names, with what its URL is built back from."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    kind: str = Field(
        description="What the node is: `document`, `dossier`, `article`, `instrument`, "
        "`judgment`, `commitment`, `faction`, `committee`, `cabinet`."
    )
    display_name: str | None = None
    chamber: str | None = Field(
        default=None, description="`TK` or `EK` for a paper or a vote; null otherwise."
    )
    stub: bool = Field(
        default=False,
        description="Known only because something cites it (a judgment not loaded): the "
        "address shows it as cited only.",
    )
    props: dict[str, Any] = Field(
        default_factory=dict,
        description="The props a URL is built back from, those the node has: `ecli`; "
        "`bwb_id` or `celex` with `article_number`; `dossier_number`, `dossier_suffix`, "
        "`sequence` (a paper of the Tweede Kamer) or `number` (the letter of one of the "
        "Eerste Kamer); `number` and `suffix` of a dossier; `official_id` or "
        "`identifier` (the id of officielebekendmakingen.nl); `replaced_by` and `same_as` "
        "of a replaced publication.",
    )
