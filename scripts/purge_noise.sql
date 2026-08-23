-- BruitTrack : purge des événements non significatifs de data/bruittrack.db
-- À exécuter sur le serveur (HP T620), service arrêté :
--   systemctl stop bruittrack
--   sqlite3 data/bruittrack.db < scripts/purge_noise.sql
--
-- Critère : freq = 0.0 (artifact DC pré-fix 80dbfe9) ET émergence max(
-- lvl_g, lvl_d) < 10 dB (sous le seuil de détection par défaut).

-- Aperçu avant purge :
SELECT COUNT(*) AS nbr_a_purger
FROM events
WHERE freq = 0.0
  AND MAX(COALESCE(lvl_g, 0), COALESCE(lvl_d, 0)) < 10.0;

DELETE FROM events
WHERE freq = 0.0
  AND MAX(COALESCE(lvl_g, 0), COALESCE(lvl_d, 0)) < 10.0;

VACUUM;

SELECT changes() AS lignes_suppimees;
