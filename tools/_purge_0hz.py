"""Purge events with freq 0/NULL from hpdebian DB, then repair fk integrity."""

import sqlite3

P = "/opt/bruittrack/data/bruittrack.db"
con = sqlite3.connect(P)
cur = con.cursor()
total = cur.execute("SELECT count(*) FROM events").fetchone()[0]
nz = cur.execute("SELECT count(*) FROM events WHERE freq IS NULL OR freq=0.0").fetchone()[0]
print(f"before: zeroHz={nz} total={total}")
r = cur.execute("DELETE FROM events WHERE freq IS NULL OR freq=0.0")
print("deleted:", r.rowcount)
try:
    orphans = cur.execute(
        "SELECT count(*) FROM events e LEFT JOIN clusters c ON e.cluster=c.id "
        "WHERE e.cluster IS NOT NULL AND c.id IS NULL"
    ).fetchone()[0]
    if orphans:
        print(f"orphaned clusters={orphans} -> NULL")
        cur.execute("UPDATE events SET cluster=NULL WHERE cluster NOT IN (SELECT id FROM clusters)")
except sqlite3.OperationalError as e:
    print("clusters check skipped:", e)
con.commit()
total = cur.execute("SELECT count(*) FROM events").fetchone()[0]
nz = cur.execute("SELECT count(*) FROM events WHERE freq IS NULL OR freq=0.0").fetchone()[0]
print(f"after: zeroHz={nz} total={total}")
con.close()
