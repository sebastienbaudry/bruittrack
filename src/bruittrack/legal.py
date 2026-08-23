"""Règles légales d'émergence acoustique (CSP Art. R1336-7).

Référence : AGENTS.md — section émergence autorisée par la loi.
Seuils : DIURNE 5 dB(A) [07:00–21:59], NOCTURNE 3 dB(A) [22:00–06:59],
correctif selon durée cumulée ; relevé INVALIDE si nuisance < 10 s
et enregistrement ambiant < 10 s.
"""

from __future__ import annotations

__all__ = [
    "correctif_duration",
    "emergence_limit",
    "evaluate_conformity",
    "periode_of_horaire",
]

_BASE_DIURNE = 5.0
_BASE_NOCTURNE = 3.0

_CORRECTIFS: tuple[tuple[int, float], ...] = (
    (60, 6.0),  # <= 1 min
    (300, 5.0),  # <= 5 min
    (1200, 4.0),  # <= 20 min
    (7200, 3.0),  # <= 2 h
    (14400, 2.0),  # <= 4 h
    (28800, 1.0),  # <= 8 h
)

_MIN_RECORDING_S = 10.0


def periode_of_horaire(hh: int, mm: int = 0) -> str:
    """Retourne ``DIURNE`` ou ``NOCTURNE`` selon l'heure locale HH:MM."""
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"horaire invalide : {hh:02d}:{mm:02d}")
    mins = hh * 60 + mm
    return "DIURNE" if 420 <= mins <= 1319 else "NOCTURNE"


def correctif_duration(duree_cumulee_s: float) -> float:
    """Terme correctif (dB(A)) selon la durée cumulée de la nuisance."""
    if duree_cumulee_s < 0:
        raise ValueError("duree_cumulee_s doit être >= 0")
    for max_s, corr in _CORRECTIFS:
        if duree_cumulee_s <= max_s:
            return corr
    return 0.0  # > 8 h


def emergence_limit(hh: int, mm: int = 0, duree_cumulee_s: float = 3600.0) -> float:
    """Émergence maximale autorisée (dB(A)) : base période + correctif durée."""
    base = _BASE_DIURNE if periode_of_horaire(hh, mm) == "DIURNE" else _BASE_NOCTURNE
    return base + correctif_duration(duree_cumulee_s)


def evaluate_conformity(
    bruit_ambiant_db: float,
    bruit_residuel_db: float,
    hh: int,
    mm: int,
    ambiant_recording_s: float,
    duree_cumulee_s: float,
) -> str:
    """Évalue la conformité : ``CONFORME``, ``NON_CONFORME`` ou ``INVALIDE``."""
    if duree_cumulee_s < _MIN_RECORDING_S and ambiant_recording_s < _MIN_RECORDING_S:
        return "INVALIDE"
    emergence = bruit_ambiant_db - bruit_residuel_db
    limite = emergence_limit(hh, mm, duree_cumulee_s)
    return "CONFORME" if emergence <= limite else "NON_CONFORME"
