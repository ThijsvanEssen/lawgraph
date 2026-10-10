"""The page of a motion of the Eerste Kamer, as served on 2026-10-10 (``<main>`` only)."""

from __future__ import annotations

from pathlib import Path

from lawgraph.core import ek_motions

PAGE = (Path(__file__).parent / "fixtures" / "ek_motion_37020_m.html").read_text()


def test_a_motion_page_is_read_as_the_kamer_writes_it() -> None:
    motion = ek_motions.motion_page(PAGE)
    assert motion is not None
    assert (motion.number, motion.letter, motion.label) == ("37.020", "M", "37020")
    assert motion.submitted_on == "2026-10-06"
    assert motion.debate == "de Algemene Politieke Beschouwingen"
    assert motion.status == "verworpen"
    assert motion.summary is not None and motion.summary.startswith(
        "In deze motie wordt de regering verzocht"
    )
    assert motion.pdf_path == (
        "/behandeling/20261006/motie_van_het_lid_beukering_c_s_2/document3/f=/vn1ld5bklc6v.pdf"
    )
    assert [(s.path, s.name, s.faction, s.role) for s in motion.signers] == [
        (
            "/persoon/bgen_b_d_drs_a_j_a_beukering",
            "A.J.A. Beukering",
            "Beukering",
            "indiener",
        ),
        ("/persoon/i_m_lagas_mdr_bbb", "I.M. Lagas", "BBB", "medeindiener"),
        (
            "/persoon/mr_c_a_h_van_de_sanden_ll_m",
            "C.A.H. van de Sanden",
            "Van de Sanden",
            "medeindiener",
        ),
        ("/persoon/p_schalk_sgp", "P. Schalk", "SGP", "medeindiener"),
        (
            "/persoon/drs_p_v_a_walenkamp_ma_fractie",
            "P.V.A. Walenkamp",
            "Walenkamp",
            "medeindiener",
        ),
    ]


def test_a_page_without_the_number_of_a_motion_is_none() -> None:
    assert ek_motions.motion_page("<main><p>Niets</p></main>") is None
