"""SQLite storage layer for BruitTrack.

Features:
- Write-Ahead Logging (WAL) and synchronous=NORMAL for SSD endurance
- In-memory batching of insertions (50 events or 30 seconds)
- Fast indexed queries on (t0) and (cluster)
- Automatic retention policy enforcement
- Cluster metadata and triage status management
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from bruittrack.events import FLAG_EXEMPLAR, FLAG_OVER_LEGAL, SoundEvent


@contextmanager
def cursor(
    db_path: str | Path,
    *,
    readonly: bool = False,
    timeout_s: float = 10.0,
) -> Iterator[sqlite3.Connection]:
    """Open a short-lived, fully thread-safe SQLite connection.

    Each call creates its own connection closed in ``finally``.
    With WAL enabled, concurrent readers + a single writer are safe
    across threads/processes (viz dashboard + capture daemon).

    Args:
        db_path: Path to the SQLite database file.
        readonly: Open with ``PRAGMA query_only=ON`` for read queries.
        timeout_s: Busy-timeout in seconds before raising on lock contention.
    """
    if db_path == ":memory:":
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            if readonly:
                conn.execute("PRAGMA query_only = ON;")
            yield conn
        finally:
            conn.close()
        return
    path = Path(db_path)
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=timeout_s, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        if readonly:
            conn.execute("PRAGMA query_only = ON;")
        else:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA temp_store = MEMORY;")
        yield conn
    finally:
        conn.close()


class EventStore:
    """Manages SQLite storage of sound events and clusters with batching.

    Thread safety: all DB access uses :func:`cursor` (one connection per
    operation) — the batch buffer itself is guarded by a lock.
    Safe to share between the capture process's flush path and the viz server.
    """

    def __init__(
        self,
        db_path: str | Path = "data/bruittrack.db",
        batch_size: int = 50,
        batch_timeout_s: float = 30.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.batch_size = batch_size
        self.batch_timeout_s = batch_timeout_s

        self._buffer: list[SoundEvent] = []
        self._spec_buffer: list[tuple[float, float, int, bytes]] = []
        self._last_flush_time = time.monotonic()
        # RLock : _db() is re-entered by flush()/add_event() which already
        # hold the lock; a plain Lock would self-deadlock (:memory: path).
        self._lock = threading.RLock()

        # Mode :memory: — schéma non persistant entre connexions éphémères,
        # donc une seule connexion partagée (protégée par self._lock en écriture).
        self._is_memory = str(db_path) == ":memory:"
        self._mem_conn: sqlite3.Connection | None = None
        if self._is_memory:
            self._mem_conn = sqlite3.connect(":memory:")
            self._mem_conn.row_factory = sqlite3.Row

        # WAL mode is set on every connection inside cursor(); the schema
        # itself migrates from any prior (non-WAL) database on first open.
        self._init_db()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        self.close()

    @contextmanager
    def _db(
        self,
        readonly: bool = False,
        timeout_s: float = 10.0,
    ) -> Iterator[sqlite3.Connection]:
        """Connexion : persistante en mode :memory:, éphémère sinon (WAL)."""
        if self._is_memory:
            with self._lock:
                assert self._mem_conn is not None
                yield self._mem_conn
            return
        with cursor(self.db_path, readonly=readonly, timeout_s=timeout_s) as conn:
            yield conn

    def _init_db(self) -> None:
        """Initialize tables and indices if not present."""
        with self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    t0 REAL NOT NULL,
                    dur REAL NOT NULL,
                    bin_i INTEGER NOT NULL,
                    freq REAL NOT NULL,
                    lvl_g REAL NOT NULL,
                    lvl_d REAL NOT NULL,
                    off_ms REAL NOT NULL,
                    fp BLOB NOT NULL,
                    flags INTEGER NOT NULL DEFAULT 0,
                    cluster INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_events_t0 ON events(t0);
                CREATE INDEX IF NOT EXISTS idx_events_cluster ON events(cluster);

                CREATE TABLE IF NOT EXISTS clusters (
                    id INTEGER PRIMARY KEY,
                    label TEXT DEFAULT '',
                    flags INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS spectrum (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    t0 REAL NOT NULL,
                    dur REAL NOT NULL,
                    n_bands INTEGER NOT NULL,
                    data BLOB NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_spectrum_t0 ON spectrum(t0);
                """
            )
            conn.commit()

    def add_event(self, event: SoundEvent) -> None:
        """Add an event to the in-memory batch buffer."""
        with self._lock:
            self._buffer.append(event)
            self._maybe_do_flush()

    def add_spectrum(self, t0: float, dur: float, n_bands: int, data: bytes) -> None:
        """Add a spectrum history row (blob uint8 n_bands×[min_g,max_g,min_d,max_d])."""
        with self._lock:
            self._spec_buffer.append((t0, dur, n_bands, data))
            self._maybe_do_flush()

    def _maybe_do_flush(self) -> None:
        """Déclenche le flush si l'un des deux buffers atteint la taille du lot."""
        if len(self._buffer) >= self.batch_size or len(self._spec_buffer) >= self.batch_size:
            self._do_flush()

    def maybe_flush(self) -> int:
        """Flush buffer if batch size or timeout condition is met."""
        now = time.monotonic()
        with self._lock:
            if (
                self._buffer or self._spec_buffer
            ) and now - self._last_flush_time >= self.batch_timeout_s:
                return self._do_flush()
            return 0

    def _do_flush(self) -> int:
        """Write buffered events + spectrum rows to SQLite (caller holds self._lock)."""
        if not self._buffer and not self._spec_buffer:
            self._last_flush_time = time.monotonic()
            return 0

        events_to_write = list(self._buffer)
        rows = [
            (
                e.t0,
                e.dur,
                e.bin_i,
                e.freq,
                e.lvl_g,
                e.lvl_d,
                e.off_ms,
                e.fp,
                e.flags,
                e.cluster,
            )
            for e in events_to_write
        ]
        spec_rows = list(self._spec_buffer)

        try:
            with self._db() as conn:
                cursor_obj = conn.cursor()
                if rows:
                    cursor_obj.executemany(
                        """
                        INSERT INTO events (t0, dur, bin_i, freq, lvl_g, lvl_d, off_ms, fp, flags, cluster)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        rows,
                    )

                    # Ensure cluster entries exist in clusters table
                    clusters_seen = {e.cluster for e in events_to_write if e.cluster is not None}
                    for c_id in clusters_seen:
                        cursor_obj.execute(
                            """
                            INSERT OR IGNORE INTO clusters (id, label, flags, created_at)
                            VALUES (?, '', 0, ?);
                            """,
                            (c_id, time.time()),
                        )
                if spec_rows:
                    cursor_obj.executemany(
                        """
                        INSERT INTO spectrum (t0, dur, n_bands, data)
                        VALUES (?, ?, ?, ?);
                        """,
                        spec_rows,
                    )
                conn.commit()

            # Only clear buffers after successful write
            n_written = len(rows) + len(spec_rows)
            self._buffer.clear()
            self._spec_buffer.clear()
            self._last_flush_time = time.monotonic()
            return n_written
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "EventStore flush failed; events preserved in buffer for retry"
            )
            return 0

    def flush(self) -> int:
        """Flush all pending buffered events to SQLite (thread-safe)."""
        with self._lock:
            return self._do_flush()

    # Read path: each call opens a fresh short-lived connection, so no
    # connection is ever shared across threads.

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        """Check a table exists without erroring on fresh/empty DB."""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def load_all_cluster_fingerprints(self, limit: int = 100_000) -> dict[int, bytes]:
        """Load representative fingerprints for all known clusters.

        Capped at ``limit`` groups (safeguard RAM T620) ; logged warning if truncated.
        """
        with self._db(readonly=True) as conn:
            if not self._table_exists(conn, "events"):
                return {}  # base vide/DB initialisée : aucun cluster connu
            rows = conn.execute(
                """
                SELECT cluster, MIN(id) AS first_id
                FROM events WHERE cluster IS NOT NULL
                GROUP BY cluster
                ORDER BY MIN(id)
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()
            if len(rows) >= limit:
                import logging

                logging.getLogger(__name__).warning(
                    f"ClusterIndex: cap {limit} atteint, troncature possible"
                )
            result: dict[int, bytes] = {}
            for group in rows:
                rid, cid = group["first_id"], group["cluster"]
                row = conn.execute("SELECT fp FROM events WHERE id = ?", (rid,)).fetchone()
                if row is not None:
                    result[cid] = bytes(row["fp"])
            return result

    def merge_quasi_duplicate_clusters(
        self,
        max_bin_delta: int = 1,
        exemplars_dir: str | Path | None = None,
    ) -> int:
        """I59 : fusionner les clusters quasi-doublons (fp compatibles). Le plus
        petit id reste canonique ; les exemplaires sont renommés en conséquence.

        Deterministe : paires parcourues par ordre d'id croissant.
        Retour : nombre de paires effectivement fusionnees.
        """
        from .events import fingerprints_match  # local : pas de cycle au chargement

        logger = logging.getLogger(__name__)
        merged = 0
        with self._db() as conn:
            if not self._table_exists(conn, "events"):
                return 0
            groups = conn.execute(
                "SELECT cluster, MIN(id) AS fid FROM events "
                "WHERE cluster IS NOT NULL GROUP BY cluster"
            ).fetchall()
            fps: dict[int, bytes] = {}
            for g in groups:
                row = conn.execute(
                    "SELECT fp FROM events WHERE id = ?", (g["fid"],)
                ).fetchone()
                if row is not None and row["fp"]:
                    fps[g["cluster"]] = bytes(row["fp"])
            cids = sorted(fps)
            merges: list[tuple[int, int]] = []
            for i in range(len(cids)):
                a = cids[i]
                for b in cids[i + 1:]:
                    try:
                        compatible = fingerprints_match(
                            fps[a], fps[b], max_bin_delta
                        )
                    except Exception as exc:  # corruption fp tollerale
                        logger.debug(f"I59: paire ({a},{b}) inanalysable: {exc}")
                        continue
                    if not compatible:
                        continue
                    cur = conn.execute(
                        "UPDATE events SET cluster = ? WHERE cluster = ?",
                        (a, b),
                    )
                    if cur.rowcount:
                        merged += 1
                        merges.append((a, b))
                        logger.info(
                            f"I59: fusion cluster {b} -> {a} ({cur.rowcount} evts)"
                        )
            if merged:
                conn.commit()
        if merged and exemplars_dir is not None:
            self._rename_merged_exemplars(exemplars_dir, merges)
        return merged

    def _rename_merged_exemplars(
        self, exemplars_dir: str | Path, merges: list[tuple[int, int]]
    ) -> None:
        """I59 : renommer ex_<fusi>_<id>.raw vers le cluster canonique."""
        d = Path(exemplars_dir)
        if not d.is_dir():
            return
        for canon, old in merges:
            try:
                with self._db(readonly=True) as conn:
                    rows = conn.execute(
                        "SELECT id FROM events "
                        "WHERE cluster = ? AND (flags & ?) != 0",
                        (canon, FLAG_EXEMPLAR),
                    ).fetchall()
            except sqlite3.Error:
                continue
            by_id = {r["id"]: r for r in rows}
            for f in sorted(d.glob(f"ex_{old}_*.raw")):
                m = re.fullmatch(rf"ex_{old}_(\d+)\.raw", f.name)
                if not m:
                    continue
                eid = int(m.group(1))
                if eid in by_id:
                    target = d / f"ex_{canon}_{eid}.raw"
                    try:
                        os.replace(f, target)
                    except OSError:
                        pass

    def get_events(
        self,
        limit: int = 100,
        offset: int = 0,
        since: float | None = None,
        cluster: int | None = None,
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        """Fetch events with optional filters (thread-safe read).

        order: "desc" (plus récents d'abord, défaut historique) ou "asc"
        (plus anciens ≥ since d'abord) — le fenêtrage UI utilise "asc" pour
        garantir un chargement continu depuis ``since`` même si plus de
        ``limit`` événements plus récents existent (I59).
        """
        if order not in ("asc", "desc"):
            raise ValueError("order doit valoir 'asc' ou 'desc'")
        self.flush()
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            query += " AND t0 >= ?"
            params.append(since)

        if cluster is not None:
            query += " AND cluster = ?"
            params.append(cluster)

        query += f" ORDER BY t0 {'ASC' if order == 'asc' else 'DESC'} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._db(readonly=True) as conn:
            results = []
            for row in conn.execute(query, params).fetchall():
                d = dict(row)
                d["over_legal"] = bool(int(d.get("flags") or 0) & FLAG_OVER_LEGAL)
                if isinstance(d.get("fp"), (bytes, memoryview)):
                    d["fp_hex"] = bytes(d["fp"]).hex()
                    del d["fp"]
                results.append(d)
            return results

    def get_spectrum(
        self,
        since: float | None = None,
        until: float | None = None,
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """Fetch spectrum history rows (thread-safe read), oldest first.

        Chaque ligne : {t0, dur, n_bands, data} avec data en base64 (blob uint8
        n_bands×[min_g, max_g, min_d, max_d]).
        """
        self.flush()
        query = "SELECT t0, dur, n_bands, data FROM spectrum WHERE 1=1"
        params: list[Any] = []
        if since is not None:
            query += " AND t0 >= ?"
            params.append(since)
        if until is not None:
            query += " AND t0 <= ?"
            params.append(until)
        query += " ORDER BY t0 ASC LIMIT ?"
        params.append(limit)
        with self._db(readonly=True) as conn:
            return [
                {
                    "t0": row["t0"],
                    "dur": row["dur"],
                    "n_bands": row["n_bands"],
                    "data": base64.b64encode(bytes(row["data"])).decode("ascii"),
                }
                for row in conn.execute(query, params).fetchall()
            ]

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics (thread-safe read)."""
        self.flush()
        cutoff_24h = time.time() - 86_400.0
        with self._db(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as total_events,
                    COUNT(DISTINCT cluster) as total_clusters,
                    MIN(t0) as min_t0,
                    MAX(t0) as max_t0,
                    AVG(dur) as avg_dur,
                    SUM(CASE WHEN t0 >= ? THEN 1 ELSE 0 END) as events_last_24h
                FROM events;
                """,
                (cutoff_24h,),
            ).fetchone()
            stats = dict(row) if row else {}

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        stats["db_size_bytes"] = db_size
        return stats

    def get_clusters_summary(self) -> list[dict[str, Any]]:
        """Get summary list of all clusters (thread-safe read)."""
        self.flush()
        with self._db(readonly=True) as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        e.cluster as cluster_id,
                        COUNT(e.id) as event_count,
                        MIN(e.t0) as first_seen,
                        MAX(e.t0) as last_seen,
                        ROUND(AVG(e.freq), 2) as avg_freq,
                        ROUND(MAX(e.lvl_g), 1) as max_lvl_g,
                        ROUND(MAX(e.lvl_d), 1) as max_lvl_d,
                        COALESCE(c.label, '') as label,
                        COALESCE(c.flags, 0) as flags
                    FROM events e
                    LEFT JOIN clusters c ON e.cluster = c.id
                    WHERE e.cluster IS NOT NULL
                    GROUP BY e.cluster
                    ORDER BY event_count DESC;
                    """
                )
            ]
        # Clusters triaged before any event was assigned must stay visible.
        with self._db(readonly=True) as conn:
            orphans = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        c.id AS cluster_id,
                        0 AS event_count,
                        NULL AS first_seen,
                        NULL AS last_seen,
                        0.0 AS avg_freq,
                        0.0 AS max_lvl_g,
                        0.0 AS max_lvl_d,
                        COALESCE(c.label, '') AS label,
                        COALESCE(c.flags, 0) AS flags
                    FROM clusters c
                    WHERE NOT EXISTS (
                        SELECT 1 FROM events e WHERE e.cluster = c.id
                    );
                    """
                )
            ]
        rows.extend(orphans)
        return rows

    def set_cluster_triage(self, cluster_id: int, flags: int, label: str | None = None) -> bool:
        """Set triage flags (known/ignored) and optional label on a cluster."""
        with self._db() as conn:
            if label is not None:
                rowcount = conn.execute(
                    """
                    INSERT INTO clusters (id, label, flags, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET flags = ?, label = ?;
                    """,
                    (cluster_id, label, flags, time.time(), flags, label),
                ).rowcount
            else:
                rowcount = conn.execute(
                    """
                    INSERT INTO clusters (id, label, flags, created_at)
                    VALUES (?, '', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET flags = ?;
                    """,
                    (cluster_id, flags, time.time(), flags),
                ).rowcount
            conn.commit()
            return rowcount > 0

    def apply_retention(
        self,
        retention_days: int,
        exemplars_dir: str | Path | None = None,
        spectrum_days: int | None = None,
    ) -> int:
        """Delete events older than retention period.

        When ``exemplars_dir`` is given, orphaned exemplar files (clusters
        no longer present in DB) are pruned after the delete (I52).
        ``spectrum_days`` : rétention dédiée de la table spectrum (indépendante
        de celle des événements ; None = pas de purge spectre).
        """
        if retention_days <= 0:
            return 0

        cutoff = time.time() - (retention_days * 86400.0)
        with self._db() as conn:
            deleted = conn.execute("DELETE FROM events WHERE t0 < ?", (cutoff,)).rowcount
            if spectrum_days is not None and spectrum_days > 0:
                cutoff_spec = time.time() - (spectrum_days * 86400.0)
                conn.execute("DELETE FROM spectrum WHERE t0 < ?", (cutoff_spec,))
            conn.commit()
        if deleted > 0 and exemplars_dir is not None:
            self.prune_orphaned_exemplars(exemplars_dir)
        return deleted

    def prune_orphaned_exemplars(self, exemplars_dir: str | Path) -> int:
        """Delete `ex_<cluster>.raw` files whose cluster no longer exists in DB.

        Returns the number of orphaned files removed. Missing dir → 0.
        """
        d = Path(exemplars_dir)
        if not d.is_dir():
            return 0
        with self._db(readonly=True) as conn:
            known = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT cluster FROM events WHERE cluster IS NOT NULL"
                )
            }
        removed = 0
        for f in d.glob("ex_*.raw"):
            m = re.fullmatch(r"ex_(\d+)\.raw", f.name)
            if not m:
                continue
            if int(m.group(1)) not in known:
                f.unlink(missing_ok=True)
                removed += 1
        return removed

    def close(self) -> None:
        """Flush pending buffer, then release the persistent :memory: connection."""
        self.flush()
        if self._mem_conn is not None:
            self._mem_conn.close()
            self._mem_conn = None
