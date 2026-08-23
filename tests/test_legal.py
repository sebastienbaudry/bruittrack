"""Tests des règles d'émergence légale (CSP Art. R1336-7)."""

import pytest

from bruittrack.legal import (
    correctif_duration,
    emergence_limit,
    evaluate_conformity,
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
