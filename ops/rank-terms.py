#!/usr/bin/env python3
"""The order the search gives the articles a lawyer looks for, before and after a change of the
ranking: the first ten hits of /api/search for a few core terms (and the law's own name among
the instruments), as read-only GETs on the public API.

    python3 ops/rank-terms.py https://concordans.nl out.json
    python3 ops/rank-terms.py https://concordans.nl out.json \
        --compare ops/rank-terms-before-0.79.43.json

Standard library only. Each hit is its key, its score (the tier of ``score_hit``) and its name;
``--compare`` prints, per term, where each hit of the earlier measurement stands now.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

TERMS = [
    ("onrechtmatige daad", "articles"),
    ("wanprestatie", "articles"),
    ("ontslag op staande voet", "articles"),
    ("huurprijs", "articles"),
    ("Wet conflictenrecht onrechtmatige daad", "instruments"),
    ("Wet conflictenrecht onrechtmatige daad", "articles"),
]


def measure(base: str) -> dict[str, list[list[object]]]:
    found: dict[str, list[list[object]]] = {}
    for q, kind in TERMS:
        query = urllib.parse.urlencode({"q": q, "types": kind, "limit": 10})
        with urllib.request.urlopen(f"{base}/api/search?{query}", timeout=60) as answer:
            hits = json.load(answer)["results"].get(kind, [])
        found[f"{q} | {kind}"] = [
            [
                h["key"],
                round(h.get("score") or 0, 3),
                (h.get("display_name") or "")[:55],
            ]
            for h in hits
        ]
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base", help="The site, e.g. https://concordans.nl")
    parser.add_argument(
        "out", type=Path, help="Where to write this measurement (JSON)."
    )
    parser.add_argument("--compare", type=Path, help="An earlier measurement (JSON).")
    args = parser.parse_args()
    now = measure(args.base.rstrip("/"))
    args.out.write_text(json.dumps(now, indent=1, ensure_ascii=False) + "\n")
    before = json.loads(args.compare.read_text()) if args.compare else {}
    for term, hits in now.items():
        print(f"\n## {term}")
        keys = [h[0] for h in hits]
        for n, (key, score, name) in enumerate(hits, 1):
            print(f"  {n:2} {score:6} {key:24} {name}")
        for n, (key, _, name) in enumerate(before.get(term, []), 1):
            where = keys.index(key) + 1 if key in keys else "-"
            print(f"     before {n:2} -> now {where!s:>2}  {key:24} {name}")


if __name__ == "__main__":
    main()
