"""The cabinet detail groups its seats by ministry: a seat stands under the ministry of
its last post, also when the ministry was renamed during the cabinet (ELI to EZ, 2013)."""

from __future__ import annotations

from lawgraph.api.schemas.government import CabinetDetailDTO


def _post(seat: str, ministry: str, start: str, end: str) -> dict:
    return {
        "seat": seat,
        "post": "staatssecretaris",
        "ministry": ministry,
        "function": "Staatssecretaris van Economische Zaken",
        "from_date": start,
        "to_date": end,
    }


def test_a_renamed_ministry_keeps_its_seat_under_one_ministry() -> None:
    row = {
        "cabinet": {
            "_key": "rutte_asscher",
            "props": {
                "name": "Rutte-Asscher",
                "from_date": "2012-11-05",
                "to_date": "2017-10-26",
            },
        },
        "members": [
            {
                "member": {"key": "verdaas", "name": "C. Verdaas"},
                "posts": [
                    _post("ez/staatssecretaris", "eli", "2012-11-05", "2012-12-06")
                ],
            },
            {
                "member": {"key": "dijksma", "name": "S.A.M. Dijksma"},
                "posts": [
                    _post("ez/staatssecretaris", "eli", "2012-12-18", "2015-11-03")
                ],
            },
            {
                "member": {"key": "vandam", "name": "M.H.P. van Dam"},
                "posts": [
                    _post("ez/staatssecretaris", "ez", "2015-11-03", "2017-09-01")
                ],
            },
        ],
    }
    detail = CabinetDetailDTO.from_detail(row)
    assert [(m.ministry, [s.seat for s in m.seats]) for m in detail.ministries] == [
        ("ez", ["ez/staatssecretaris"])
    ]
    (seat,) = detail.ministries[0].seats
    assert [p.member.name for p in seat.posts] == [
        "C. Verdaas",
        "S.A.M. Dijksma",
        "M.H.P. van Dam",
    ]
