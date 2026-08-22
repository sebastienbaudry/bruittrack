# BruitTrack — Progress

## Goal
Corriger toutes les erreurs listées dans BUGS.md.

## Done
- [x] store.py : connexions SQLite par opération (`cursor()` module-level), `_init_db` unique (schéma + index), `_lock` protège seulement le buffer (commit dfd2d08).
- [x] tests/test_bugfixes.py adaptés au nouveau design ; 28/28 tests verts.
- [x] BUG-11 : `set_initial_state` supprimée (code mort) — commit 4e36373.
- [x] BUG-06 : convention de signe VÉRIFIÉE par tests déterministes (`TestChannelDelaySign`) ; code conforme à la docstring.
- [x] Notes de statut ajoutées dans BUGS.md — commit eb34d96.

## Next (improvements)
- [ ] Test régression reader/writer concurrents sur EventStore (tests/test_store.py).
- [ ] Corriger les pointages « Lieu » décalés dans BUGS.md après suppressions.
- [ ] `ruff check . && ruff format --check .`.

## Notes
- get_stats/get_events appellent flush() en préambule (comportement couvert par test_add_event_autoflush_no_deadlock).
- Tests top-level `tests/`, DB temp via fixtures tmp_path.

## Iteration 10
- [ ] ruff non installé localement (supposition documentée en ASSUMPTIONS.md).
- [x] Test de régression concurrent writer/readers ajouté (à venir ci-dessous).
- [x] Test de régression concurrent writer/readers — commit 1d01e28, 29/29 verts.
