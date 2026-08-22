# BruitTrack — Progress

## Goal
Corriger toutes les erreurs listées dans BUGS.md.

## Done (batches 4-5)
- store.py: cursor() par opération, _init_db unique, Lock sur buffer → 26 tests OK (dfd2d08)
- BUG-11: set_initial_state supprimée + tests de signe compute_channel_delay_ms (4e36373)
- Notes statut BUGS.md (eb34d96), test concurrent writer/readers (1d01e28)

## Next
- [ ] BUGS.md: réviser pointers obsolètes après suppression set_initial_state
- [ ] ruff check . && ruff format --check.

