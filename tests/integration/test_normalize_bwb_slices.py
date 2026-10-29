"""``normalize bwb`` in slices (``ops/renormalize-bwb.sh``) on a real database: every toestand
is read once, each slice names where the next one starts, and the one that reaches the end
says so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND
from lawgraph.db import GraphStore
from tests.integration.seed import write_toestanden

XML = (
    Path(__file__).resolve().parents[1] / "fixtures/bwb_grondwet_toestand.xml"
).read_text()
LAWS = ["BWBR0001840", "BWBR0001841", "BWBR0001842"]


def _instruments(store: GraphStore) -> set[str]:
    return set(store.query("SELECT bwb_id FROM instruments WHERE bwb_id IS NOT NULL"))


def _next_after(output: str) -> str | None:
    """The key a slice says the next one starts past, or None for the end."""
    line = next(ln for ln in output.splitlines() if "The last read was" in ln)
    if "the end, nothing to go on" in line:
        return None
    return line.split("--after ")[1].rstrip(").").strip()


def test_slices_read_every_toestand_once_and_the_last_says_so(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    write_toestanden(
        store,
        [
            (
                RAW_KIND_BWB_TOESTAND,
                law,
                XML,
                {"bwb_id": law, "state_url": f"https://repo/{law}"},
            )
            for law in LAWS
        ],
    )

    first = cli("normalize", "bwb", "--limit", "2")
    after = _next_after(first.stdout + first.stderr)
    assert after is not None and len(_instruments(store)) == 2

    second = cli("normalize", "bwb", "--after", after, "--limit", "2")
    assert _next_after(second.stdout + second.stderr) is None  # read 1 of 2: the end
    assert _instruments(store) == set(LAWS)

    (last,) = store.query(
        "SELECT max(key) FROM raw_sources WHERE kind = %(kind)s",
        {"kind": RAW_KIND_BWB_TOESTAND},
    )
    past = cli("normalize", "bwb", "--after", last, "--limit", "2")
    assert "The last read was None: the end" in past.stdout + past.stderr
