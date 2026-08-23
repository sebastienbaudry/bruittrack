-- BruitTrack : purge des événements sous min_event_hz (I35, défaut 2.0 Hz)
-- À exécuter sur le serveur (HP T620), service arrêté :
--   systemctl stop bruittrack
--   sqlite3 data/bruittrack.db < scripts/purge_lowfreq.sql
--
-- Critère : STRICTEMENT sous min_event_hz (valeur issue de config.toml,
-- défaut 2.0 Hz — matériel non fiable sous 2 Hz).

-- Aperçu avant purge :
SELECT COUNT(*) AS nbr_a_purger
FROM events
WHERE freq < 2.0;

DELETE FROM events
WHERE freq < 2.0;

-- Vérification a posteriori : doit renvoyer 0.
SELECT COUNT(*) AS restants_sous_2hz
FROM events
WHERE freq < 2.0;

VACUUM;
