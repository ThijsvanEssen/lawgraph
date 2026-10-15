"""``lawgraph gaps``: the report of what the graph lacks."""

from __future__ import annotations


def test_the_gaps_report_names_a_law_from_its_sru_record_without_downloading_it(
    monkeypatch, caplog
) -> None:
    """The report needs a name; the toestand is the whole law, fetched by the gaps run."""
    from lawgraph.commands import gaps

    titles = {"BWBR1": "Wet op X", "BWBR2": None}

    class _FakeClient:
        def latest_toestand(self, bwb_id: str) -> dict | None:
            if bwb_id in ("BWBR3", "BWBR4"):
                raise RuntimeError("SRU error")
            return {"bwb_id": bwb_id, "title": titles[bwb_id]}

        def fetch_toestand_xml(self, meta: dict) -> str:
            raise AssertionError("the toestand is not needed for a name")

    monkeypatch.setattr(gaps, "BWBClient", _FakeClient)
    with caplog.at_level("DEBUG"):
        result = gaps._resolve_names_from_bwb(
            ["BWBR1", "BWBR2", "BWBR3", "BWBR4"], {"BWBR9": "Bekend"}
        )
    assert result == {"BWBR9": "Bekend", "BWBR1": "Wet op X"}
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        (
            "WARNING",
            "2 law titles not fetched; the first, BWBR3: RuntimeError: SRU error",
        )
    ]
