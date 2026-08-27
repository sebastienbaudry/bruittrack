"""Règles légales d'émergence acoustique (CSP Art. R1336-7).

Référence : AGENTS.md — section émergence autorisée par la loi.
Seuils : DIURNE 5 dB(A) [07:00–21:59], NOCTURNE 3 dB(A) [22:00–06:59],
correctif selon durée cumulée ; relevé INVALIDE si nuisance < 10 s
et enregistrement ambiant < 10 s.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = [
    "correctif_duration",
    "emergence_limit",
    "evaluate_conformity",
    "generate_legal_report",
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


def generate_legal_report(
    events: list[dict[str, Any]],
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict[str, Any]:
    """Génère un rapport de synthèse acoustique et légale selon le CSP Art. R1336-7.

    Args:
        events: Liste des événements sous forme de dictionnaires.
        start_time: Timestamp Unix optionnel de début de période.
        end_time: Timestamp Unix optionnel de fin de période.

    Returns:
        Dictionnaire structuré contenant les statistiques de conformité et le détail des infractions.
    """
    total_events = len(events)
    infractions: list[dict[str, Any]] = []
    invalid_count = 0
    total_duration_s = 0.0
    diurne_infractions = 0
    nocturne_infractions = 0
    max_emergence_db = 0.0

    t0_list = [float(e["t0"]) for e in events if "t0" in e and e["t0"] is not None]
    period_start = start_time if start_time is not None else (min(t0_list) if t0_list else None)
    period_end = end_time if end_time is not None else (max(t0_list) if t0_list else None)

    for ev in events:
        dur = float(ev.get("dur", 0.0))
        total_duration_s += dur
        t0 = float(ev.get("t0", 0.0))
        lvl_g = float(ev.get("lvl_g", 0.0))
        lvl_d = float(ev.get("lvl_d", 0.0))
        peak_db = max(lvl_g, lvl_d)
        max_emergence_db = max(max_emergence_db, peak_db)

        flags = int(ev.get("flags", 0))
        is_invalid = bool(ev.get("is_invalid") or (flags & (1 << 4)))
        if is_invalid:
            invalid_count += 1

        over_legal = bool(ev.get("over_legal") or (flags & (1 << 3)))
        t = datetime.fromtimestamp(t0)  # noqa: DTZ006
        per = periode_of_horaire(t.hour, t.minute)
        lim = emergence_limit(t.hour, t.minute, dur)

        if over_legal or (peak_db > lim and not is_invalid):
            if per == "DIURNE":
                diurne_infractions += 1
            else:
                nocturne_infractions += 1
            infractions.append(
                {
                    "id": ev.get("id"),
                    "t0": t0,
                    "datetime": t.strftime("%Y-%m-%d %H:%M:%S"),
                    "periode": per,
                    "freq_hz": float(ev.get("freq", 0.0)),
                    "emergence_db": round(peak_db, 1),
                    "limite_db": round(lim, 1),
                    "depassement_db": round(peak_db - lim, 1),
                    "duration_s": round(dur, 2),
                    "cluster": ev.get("cluster"),
                }
            )

    infraction_count = len(infractions)
    conforming_count = max(0, total_events - infraction_count - invalid_count)
    verdict = (
        "NON_CONFORME (Infractions détectées)"
        if infraction_count > 0
        else "CONFORME (Aucune infraction)"
    )

    return {
        "title": "Rapport de conformité acoustique (CSP Art. R1336-7)",
        "period_start": period_start,
        "period_end": period_end,
        "period_start_iso": (
            datetime.fromtimestamp(period_start).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006
            if period_start
            else None
        ),
        "period_end_iso": (
            datetime.fromtimestamp(period_end).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006
            if period_end
            else None
        ),
        "total_events": total_events,
        "conforming_count": conforming_count,
        "infraction_count": infraction_count,
        "invalid_count": invalid_count,
        "diurne_infractions": diurne_infractions,
        "nocturne_infractions": nocturne_infractions,
        "total_duration_s": round(total_duration_s, 1),
        "max_emergence_db": round(max_emergence_db, 1),
        "verdict": verdict,
        "infractions": infractions,
    }
