"""When the words around a link to a whole law leave a matter to that law."""

from __future__ import annotations

import pytest

from lawgraph.core.delegations import leaves_to


def _leaves(text: str, law: str = "Grondwet") -> bool:
    start = text.index(law)
    return leaves_to(text, start, start + len(law))


@pytest.mark.parametrize(
    "text",
    [
        # Statuut art. 5, 42, 50 and 51, as the source has them
        "de uitoefening van de macht worden voor zover het Statuut hierin niet voorziet "
        "geregeld in de Grondwet voor het Koninkrijk.",
        "1. In het Koninkrijk vindt de staatsinrichting van Nederland regeling in de "
        "Grondwet, die van Aruba in de Staatsregeling.",
        "2. Voor Nederland wordt in dit onderwerp voor zover nodig in de Grondwet voorzien.",
    ],
)
def test_a_law_that_leaves_a_matter_to_another(text: str) -> None:
    assert _leaves(text)


@pytest.mark.parametrize(
    "text",
    [
        "2. De Grondwet neemt de bepalingen van het Statuut in acht.",
        "3. Op een voorstel tot verandering in de Grondwet is dit artikel van toepassing.",
        "De regels zijn zoals geregeld in de Grondwet.",
        "De aanvraag wordt ingediend, zoals geregeld in de Grondwet.",
        "Dit wordt beslist. Het is geregeld in de Grondwet.",
        "De zaak wordt behandeld in de Grondwet genoemde gevallen.",
    ],
)
def test_a_law_that_only_names_another(text: str) -> None:
    assert not _leaves(text)
