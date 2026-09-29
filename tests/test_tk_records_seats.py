"""When a seat of a faction last changed: the FractieZetel of a FractieZetelPersoon record."""

from lawgraph.core.tk_records import seat_changed_on


def test_the_day_a_seat_changed() -> None:
    record = {
        "Persoon_Id": "p",
        "FractieZetel": {
            "Id": "z",
            "Fractie_Id": "f",
            "GewijzigdOp": "2026-07-15T10:00:00+02:00",
        },
    }
    assert seat_changed_on(record) == "2026-07-15"
    assert seat_changed_on({"FractieZetel": {"Id": "z"}}) is None
    assert seat_changed_on({}) is None
