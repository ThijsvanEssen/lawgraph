"""The sections of ``lawgraph gaps``: a banner, a line when there is nothing, else the first
items and how many more."""

from __future__ import annotations

import pytest

from lawgraph.commands import gaps


def test_a_list_section_shows_the_first_items_and_how_many_more(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gaps._print_echr_stub_report([f"ECLI:CE:ECHR:{n}" for n in range(22)])
    gaps._print_celex_stub_report([])
    out = capsys.readouterr().out
    assert out.startswith(
        "\n" + "═" * 60 + "\n  ECHR JUDGMENT STUBS\n" + "═" * 60 + "\n"
    )
    assert "\n  22 ECHR judgment stub(s) (`retrieve echr --mode gaps`):\n\n" in out
    assert "    ECLI:CE:ECHR:19\n    … and 2 more\n" in out
    assert "ECLI:CE:ECHR:20" not in out
    assert out.endswith(
        "  EU CELEX STUB GAPS\n" + "═" * 60 + "\n\n  No EU stub instruments found.\n"
    )


def test_the_judgment_section_lists_referrals_before_the_stubs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gaps._print_judgment_stub_report(["ECLI:NL:HR:2024:1"], [])
    out = capsys.readouterr().out
    assert out.endswith(
        "\n  1 judgment(s) cited and not loaded (`retrieve rechtspraak --mode gaps`):\n\n"
        "    ECLI:NL:HR:2024:1\n"
    )
