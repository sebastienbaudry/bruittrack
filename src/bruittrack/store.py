"""SQLite storage layer for BruitTrack.

Features:
- Write-Ahead Logging (WAL) and synchronous=NORMAL for SSD endurance
- In-memory batching of insertions (50 events or 30 seconds)
- Fast indexed queries on (t0) and (cluster)
- Automatic retention policy enforcement
- Cluster metadata and triage status management
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator

from bruittrack.events import SoundEvent


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

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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
                """
            )
            conn.commit()

    def add_event(self, event: SoundEvent) -> None:
        """Add an event to the in-memory batch buffer."""
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self.batch_size:
                self._do_flush()

    def maybe_flush(self) -> int:
        """Flush buffer if batch size or timeout condition is met."""
        now = time.monotonic()
        with self._lock:
            if self._buffer and now - self._last_flush_time >= self.batch_timeout_s:
                return self._do_flush()
            return 0

    def _do_flush(self) -> int:
        """Write buffered events to SQLite (caller must hold self._lock)."""
        if not self._buffer:
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

        try:
            with self._db() as conn:
                cursor_obj = conn.cursor()
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
                conn.commit()

            # Only clear buffer after successful write
            self._buffer.clear()
            self._last_flush_time = time.monotonic()
            return len(events_to_write)
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

    def load_all_cluster_fingerprints(
        self, limit: int = 100_000
    ) -> dict[int, bytes]:
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
                row = conn.execute(
                    "SELECT fp FROM events WHERE id = ?", (rid,)
                ).fetchone()
                if row is not None:
                    result[cid] = bytes(row["fp"])
            return result

    def get_events(
        self,
        limit: int = 100,
        offset: int = 0,
        since: float | None = None,
        cluster: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch events with optional filters (thread-safe read)."""
        self.flush()
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            query += " AND t0 >= ?"
            params.append(since)

        if cluster is not None:
            query += " AND cluster = ?"
            params.append(cluster)

        query += " ORDER BY t0 DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._db(readonly=True) as conn:
            results = []
            for row in conn.execute(query, params).fetchall():
                d = dict(row)
                if isinstance(d.get("fp"), (bytes, memoryview)):
                    d["fp_hex"] = bytes(d["fp"]).hex()
                    del d["fp"]
                results.append(d)
            return results

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
            return [
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

    def set_cluster_triage(
        self, cluster_id: int, flags: int, label: str | None = None
    ) -> bool:
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

    def apply_retention(self, retention_days: int) -> int:
        """Delete events older than retention period."""
        if retention_days <= 0:
            return 0

        cutoff = time.time() - (retention_days * 86400.0)
        with self._db() as conn:
            deleted = conn.execute(
                "DELETE FROM events WHERE t0 < ?", (cutoff,)
            ).rowcount
            conn.commit()
            return deleted

    def close(self) -> None:
        """Flush pending buffer, then release the persistent :memory: connection."""
        self.flush()
        if self._mem_conn is not None:
            self._mem_conn.close()
            self._mem_conn = None
