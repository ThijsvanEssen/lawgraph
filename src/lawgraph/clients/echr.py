"""Client for the European Court of Human Rights HUDOC database.

API: https://hudoc.echr.coe.int/app/query/results
Docs: https://www.echr.coe.int/Documents/HUDOC_instruction_ENG.pdf

Paginates via start/length parameters. Filters by respondent country (NLD).
"""

from __future__ import annotations

from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import ECHR_HUDOC_BASE_URL
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_PAGE_SIZE = 100


class EchrClient(BaseClient):
    """Client for HUDOC ECHR case law database."""

    def __init__(self, session=None) -> None:
        super().__init__(
            base_url=ECHR_HUDOC_BASE_URL,
            session=session,
        )
        self.session.headers.update({"Accept": "application/json"})

    def search_judgments(
        self,
        *,
        respondent: str = "NLD",
        doc_type: str = "JUDGMENTS",
        since_date: str | None = None,
        max_records: int = 10000,
    ) -> list[dict[str, Any]]:
        """Fetch ECHR judgments for a given respondent country.

        Args:
            respondent: Three-letter country code (default: NLD = Netherlands).
            doc_type: HUDOC document type (JUDGMENTS, DECISIONS, ADVISORYOPINIONS).
            since_date: Start date as YYYY-MM-DD for incremental fetching.
            max_records: Maximum number of records to fetch.

        Returns:
            List of result metadata dicts (the ``columns`` of each HUDOC result). A failing
            request raises.
        """
        query_parts = [f"respondent:{respondent}", f"documentcollectionid2:{doc_type}"]
        if since_date:
            query_parts.append(f"kpdate>={since_date}T00:00:00.000Z")

        query = " AND ".join(query_parts)
        results: list[dict[str, Any]] = []

        for start in range(0, max_records, _PAGE_SIZE):
            params = {
                "query": query,
                "select": (
                    "appno,docname,doctype,itemid,languageisocode,"
                    "originatingbody,kpdate,respondent,importance,"
                    "applicability,article,conclusion"
                ),
                "sort": "kpdate Descending",
                "start": str(start),
                "length": str(_PAGE_SIZE),
                "rankingModelId": "11111111-0000-0000-0000-000000000000",
            }

            resp = self._get_raw_with_retry(
                "/app/query/results",
                params=params,
                timeout=60,
            )
            # HUDOC returns {"results": [{"columns": {"itemid": ..., ...}}, ...]}
            items = resp.json().get("results", [])
            if not items:
                break

            results.extend(item["columns"] for item in items)
            logger.debug(
                "ECHR: fetched %d records (total so far: %d).", len(items), len(results)
            )

            if len(items) < _PAGE_SIZE:
                break

        logger.info(
            "ECHR HUDOC: fetched %d %s judgments for respondent=%s.",
            len(results),
            doc_type,
            respondent,
        )
        return results
