"""Replay the goldens against another API and compare every answer strictly.

    python -m tests.parity.replay --goldens ~/Development/lawgraph-parity/2026-09-30 \\
        --base http://localhost:8003 [--only /api/judgments] [--only /api/search]

Asks each recorded request again, compares status, headers and body (``compare.py``), and
asks it once more with the ``ETag`` it got in ``If-None-Match``, which must give a 304. The
search ranking is held to D3: an answer may differ in its hits only, and per type of hit the
first is the same in at least 90 % of the questions; the overlap of the hits is reported.
Prints a summary per route and writes the differences to ``<goldens>/replay-<port>.json``;
exits 1 when anything differs beyond D3 and D9. With ``--latency-against`` every request is
timed on that API too: p50 and p95 per route, side by side.
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from tests.parity.catalogue import Request
from tests.parity.compare import compare, parse, search_agreement
from tests.parity.record import Client

D3_FIRST_HIT = 0.9


def goldens(directory: pathlib.Path, only: list[str]) -> Iterator[dict[str, Any]]:
    with gzip.open(directory / "goldens.jsonl.gz", "rt", encoding="utf-8") as rows:
        for line in rows:
            row = json.loads(line)
            if not only or any(row["path"].startswith(prefix) for prefix in only):
                yield row


def route_of(path: str) -> str:
    """``/api/judgments/ECLI:…`` → ``/api/judgments/…``: the route a request belongs to."""
    parts = path.split("/")
    return "/".join(parts[:3] + ["…"] * (len(parts) > 3))


def check(
    client: Client, golden: dict[str, Any], reference: Client | None = None
) -> dict[str, Any]:
    request = Request.from_json(golden)
    answer = client.fetch(request)
    result = compare(golden["path"], dict(request.query), golden, answer)
    row: dict[str, Any] = {
        "url": request.url,
        "route": route_of(golden["path"]),
        "same": result.same,
        "allowed": result.allowed,
        "where": result.where,
        "detail": result.detail,
        "ms": answer["ms"],
    }
    if reference is not None:
        row["ms_reference"] = reference.fetch(request)["ms"]
    etag = answer["headers"].get("etag")
    if etag and answer["status"] == 200:
        again = client.fetch(request, {"If-None-Match": etag})
        if again["status"] != 304:
            row.update(
                same=False, where="304", detail=f"If-None-Match gave {again['status']}"
            )
    if golden["path"] == "/api/search" and golden["status"] == 200 == answer["status"]:
        row["search"] = search_agreement(parse(golden["body"]), parse(answer["body"]))
    return row


def summary(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    lines = []
    by_route: dict[str, Counter[str]] = {}
    for row in rows:
        outcome = "same" if row["same"] else row["allowed"] or "DIFFERS"
        by_route.setdefault(row["route"], Counter())[outcome] += 1
    for route, counts in sorted(by_route.items()):
        lines.append(
            f"{route:48} " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        )
    differs = sum(c["DIFFERS"] for c in by_route.values())
    groups = [group for r in rows for group in r.get("search", [])]
    share = sum(first for first, _ in groups) / len(groups) if groups else 1.0
    overlap = sum(o for _, o in groups) / len(groups) if groups else 1.0
    lines.append(f"\n{len(rows)} requests, {differs} differ")
    if groups:
        lines.append(
            f"D3: per type of hit, the same first hit in {share:.1%} and an overlap of"
            f" {overlap:.1%} of the hits ({len(groups)} lists of hits)"
        )
    lines += latency(rows)
    return differs == 0 and share >= D3_FIRST_HIT, "\n".join(lines)


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def latency(rows: list[dict[str, Any]]) -> list[str]:
    """p50 and p95 per route (ms), and of the reference API when it was timed too; a route
    whose p95 is more than 10 % slower than the reference's is marked."""
    by_route: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_route.setdefault(row["route"], []).append(row)
    lines = [
        "\nlatency (ms)                                     p50     p95   ref p50  ref p95"
    ]
    for route, found in sorted(by_route.items()):
        ms = [r["ms"] for r in found]
        line = f"{route:44} {_percentile(ms, 0.5):7.1f} {_percentile(ms, 0.95):7.1f}"
        ref = [r["ms_reference"] for r in found if "ms_reference" in r]
        if ref:
            p95, ref95 = _percentile(ms, 0.95), _percentile(ref, 0.95)
            line += f"  {_percentile(ref, 0.5):7.1f}  {ref95:7.1f}"
            line += "  SLOWER" if p95 > ref95 * 1.1 else ""
        lines.append(line)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--goldens", required=True, type=pathlib.Path)
    parser.add_argument("--base", default="http://localhost:8003")
    parser.add_argument(
        "--only", action="append", default=[], help="path prefix to replay"
    )
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument(
        "--latency-against",
        help="an API to time every request against (the Arango one)",
    )
    args = parser.parse_args()
    directory: pathlib.Path = args.goldens.expanduser()
    client = Client(args.base)
    reference = Client(args.latency_against) if args.latency_against else None
    with ThreadPoolExecutor(args.jobs) as pool:
        rows = list(
            pool.map(
                lambda g: check(client, g, reference), goldens(directory, args.only)
            )
        )
    ok, text = summary(rows)
    print(text)
    port = urlparse(args.base).port
    report = directory / f"replay-{port}.json"
    report.write_text(
        json.dumps([r for r in rows if not r["same"]], ensure_ascii=False, indent=1)
    )
    print(f"differences: {report}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
