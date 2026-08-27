"""Tests des règles d'émergence légale (CSP Art. R1336-7)."""

import pytest

from bruittrack.legal import (
    correctif_duration,
    emergence_limit,
    evaluate_conformity,
    generate_legal_report,
    periode_of_horaire,
)


def test_periode_bordures() -> None:
    assert periode_of_horaire(7, 0) == "DIURNE"
    assert periode_of_horaire(21, 59) == "DIURNE"
    assert periode_of_horaire(22, 0) == "NOCTURNE"
    assert periode_of_horaire(6, 59) == "NOCTURNE"
    assert periode_of_horaire(0) == "NOCTURNE"


def test_periode_invalide() -> None:
    with pytest.raises(ValueError):
        periode_of_horaire(24)


def test_correctif_petit_et_grand() -> None:
    assert correctif_duration(0) == 6.0
    assert correctif_duration(60) == 6.0
    assert correctif_duration(61) == 5.0
    assert correctif_duration(300) == 5.0
    assert correctif_duration(1200) == 4.0
    assert correctif_duration(7200) == 3.0
    assert correctif_duration(14400) == 2.0
    assert correctif_duration(28800) == 1.0
    assert correctif_duration(28_801) == 0.0


def test_correctif_negatif() -> None:
    with pytest.raises(ValueError):
        correctif_duration(-1)


def test_limites_base() -> None:
    # Minuit, nuisance de 1 h -> NOCTURNE 3 + 3 = 6 dB(A).
    assert emergence_limit(0, 0, 3600) == pytest.approx(6.0)
    # Midi, nuisance courte -> DIURNE 5 + 6 = 11 dB(A).
    assert emergence_limit(12, 0, 30) == pytest.approx(11.0)


def test_conformite_et_invalidite() -> None:
    # Nuisance 15 s, mesure ambiant 30 s : limite MI +3 h = 8 dB.
    assert evaluate_conformity(48, 42, 13, 0, 30, 15) == "CONFORME"  # 6 <= 8
    assert evaluate_conformity(55, 42, 13, 0, 30, 15) == "NON_CONFORME"  # 13 > 8
    # Nuisance et mesure toutes deux < 10 s -> INVALIDE même si conforme.
    assert evaluate_conformity(45, 42, 13, 0, 9, 9) == "INVALIDE"


def test_generate_legal_report_empty() -> None:
    """Rapport sur liste vide."""
    rep = generate_legal_report([])
    assert rep["total_events"] == 0
    assert rep["infraction_count"] == 0
    assert rep["verdict"] == "CONFORME (Aucune infraction)"


def test_generate_legal_report_with_infractions() -> None:
    """Rapport avec mélange d'événements conformes et non-conformes."""
    # 1700000000 -> 2023-11-14 22:13:20 (NOCTURNE)
    # limite nocturne courte = 3 + 6 = 9 dB
    ev1 = {
        "id": 1,
        "t0": 1700000000.0,
        "dur": 5.0,
        "freq": 45.0,
        "lvl_g": 15.0,
        "lvl_d": 10.0,
        "flags": 1 << 3,
        "over_legal": True,
        "cluster": 1,
    }
    # 1700040000 -> 2023-11-15 09:20:00 (DIURNE)
    # limite diurne = 5 + 6 = 11 dB
    ev2 = {
        "id": 2,
        "t0": 1700040000.0,
        "dur": 12.0,
        "freq": 30.0,
        "lvl_g": 6.0,
        "lvl_d": 4.0,
        "flags": 0,
        "over_legal": False,
        "cluster": 2,
    }
    # Event invalide
    ev3 = {
        "id": 3,
        "t0": 1700045000.0,
        "dur": 4.0,
        "freq": 50.0,
        "lvl_g": 20.0,
        "lvl_d": 20.0,
        "flags": 1 << 4,
        "is_invalid": True,
        "cluster": 3,
    }

    rep = generate_legal_report([ev1, ev2, ev3])
    assert rep["total_events"] == 3
    assert rep["infraction_count"] == 1
    assert rep["nocturne_infractions"] == 1
    assert rep["diurne_infractions"] == 0
    assert rep["invalid_count"] == 1
    assert rep["conforming_count"] == 1
    assert rep["max_emergence_db"] == 20.0
    assert "NON_CONFORME" in rep["verdict"]
    assert len(rep["infractions"]) == 1
    assert rep["infractions"][0]["id"] == 1
    assert rep["infractions"][0]["depassement_db"] == 6.0
