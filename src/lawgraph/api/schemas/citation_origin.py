"""What links a judgment to an article it cites (``origin`` of its REFERS_TO edge)."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.mentions import CitationOrigin


class CitationOriginFields(StrictModel):
    """What names the article a judgment cites."""

    origin: list[CitationOrigin] | None = Field(
        default=None,
        description="What names the article: the judgment's `text`, its `metadata` "
        "(the `Wetsverwijzing` the court's editors entered), or both. Null for a link "
        "made before this was kept.",
    )
