"""What the ECHR found per article (``core/echr_findings.py``)."""

from __future__ import annotations

from lawgraph.core.echr_findings import echr_findings, echr_outcome_props


def test_a_finding_per_article_split_outside_the_parentheses() -> None:
    conclusion = (
        "No violation of Article 8 - Right to respect for private and family life (Article "
        "8-1 - Respect for correspondence;Respect for home);No violation of Article 13+8-1 - "
        "Right to an effective remedy (Article 13 - Effective remedy);Non-pecuniary damage - "
        "award (Article 41 - Non-pecuniary damage;Just satisfaction)"
    )
    found = echr_findings(conclusion)
    assert [(f["article"], f["combined_with"], f["finding"]) for f in found] == [
        ("8", None, "geen schending"),
        ("13", "8", "geen schending"),
    ]
    assert found[0]["text"].startswith("No violation of Article 8 - Right to respect")


def test_aspects_protocols_and_french() -> None:
    found = echr_findings(
        "Violation of Article 3 - Prohibition of torture (Article 3 - Effective "
        "investigation) (Procedural aspect);Violation of Article 1 of Protocol No. 1 - "
        "Protection of property;Violation de l'article 5 - Droit à la liberté"
    )
    assert [(f["article"], f["protocol"], f["aspect"]) for f in found] == [
        ("3", None, "procedureel"),
        ("1", "1", None),
        ("5", None, None),
    ]
    assert {f["finding"] for f in found} == {"schending"}


def test_the_outcome_is_schending_when_one_finding_is() -> None:
    props = echr_outcome_props(
        "No violation of Article 3 - Prohibition of torture;Violation of Article 5 - "
        "Right to liberty and security"
    )
    assert props["outcome"] == "schending"
    assert (
        props["outcome_text"]
        == "Violation of Article 5 - Right to liberty and security"
    )
    assert echr_outcome_props("Remainder inadmissible") == {
        "echr_findings": None,
        "outcome": None,
        "outcome_text": None,
    }
