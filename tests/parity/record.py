"""Record the goldens of the parity harness from the API that runs on the Arango database.

    python -m tests.parity.record --base http://localhost:8002 \\
        --out ~/Development/lawgraph-parity/$(date +%F)

Makes the catalogue (``catalogue.py``) from that API, asks every request of it, follows the
feed from its first page to the end of its cursor chain, and writes ``catalogue.json`` and
``goldens.jsonl.gz`` to *out*. The API only reads; record on the same day as the other build,
since answers depend on today's date.
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import json
import pathlib
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from tests.parity.catalogue import Request, build

KEEP_HEADERS = ("content-type", "cache-control", "etag", "vary", "location")
CHAIN_PAGES = (
    50  # pages followed per filtered feed chain; the unfiltered one goes to the end
)


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Accept-Encoding"] = "identity"

    def fetch(
        self, request: Request, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        answer = self.session.get(self.base + request.url, headers=headers, timeout=300)
        return {
            **request.as_json(),
            "status": answer.status_code,
            "headers": {
                k: answer.headers[k] for k in KEEP_HEADERS if k in answer.headers
            },
            "body": answer.content.decode("utf-8", errors="replace"),
            "ms": answer.elapsed.total_seconds() * 1000,
        }

    def get_json(self, url: str) -> Any:
        """The JSON answer to *url*; ``None`` for an error (a not-found sample, a 422)."""
        answer = self.session.get(self.base + url, timeout=300)
        json_ = "json" in answer.headers.get("content-type", "")
        return answer.json() if answer.status_code == 200 and json_ else None

    def fetch_all(
        self, requests_: Iterable[Request], jobs: int = 8
    ) -> Iterator[dict[str, Any]]:
        with ThreadPoolExecutor(jobs) as pool:
            yield from pool.map(self.fetch, requests_)


def cursor_chains(
    client: Client, recorded: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """The next pages of every feed page recorded, until the cursor is ``null``."""
    for row in recorded:
        if row["path"] != "/api/feed" or row["status"] != 200:
            continue
        query = [tuple(p) for p in row["query"] if p[0] != "cursor"]
        pages = None if not query else CHAIN_PAGES
        cursor = json.loads(row["body"]).get("next_cursor")
        n = 0
        while cursor and (pages is None or n < pages):
            page = client.fetch(
                Request("/api/feed", (*query, ("cursor", cursor)), "cursor")
            )
            yield page
            cursor = (
                json.loads(page["body"]).get("next_cursor")
                if page["status"] == 200
                else None
            )
            n += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://localhost:8002")
    parser.add_argument("--out", required=True, type=pathlib.Path)
    # More at once runs the Docker VM out of memory next to the other databases.
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out: pathlib.Path = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.base)
    openapi = client.get_json("/openapi.json")
    catalogue = build(openapi, client.get_json)
    print(f"catalogue: {len(catalogue)} requests")
    recorded = list(client.fetch_all(catalogue, args.jobs))
    recorded += list(cursor_chains(client, recorded))
    if any(row["status"] == 429 for row in recorded):
        raise SystemExit(
            "rate limited: run the API with LAWGRAPH_RATE_LIMIT_CALLS=1000000"
        )
    (out / "catalogue.json").write_text(
        json.dumps(
            {
                "base": args.base,
                "date": datetime.date.today().isoformat(),
                "api_version": openapi["info"]["version"],
                "requests": [Request.from_json(r).as_json() for r in recorded],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    with gzip.open(out / "goldens.jsonl.gz", "wt", encoding="utf-8") as goldens:
        for row in recorded:
            goldens.write(json.dumps(row, ensure_ascii=False) + "\n")
    statuses: dict[int, int] = {}
    for row in recorded:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    print(
        f"recorded {len(recorded)} responses to {out}: status {dict(sorted(statuses.items()))}"
    )


if __name__ == "__main__":
    main()
