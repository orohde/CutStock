"""DB-basierter Lock-Mechanismus für iCloud-Synchronisation.

Der Lock wird direkt in der SQLite-Datenbank gespeichert (Tabelle app_lock).
Da die DB über iCloud synchronisiert wird, ist kein separates Lock-File nötig.

Heartbeat-Timestamp wird regelmäßig aktualisiert. Ein Lock gilt als
abgelaufen wenn der Heartbeat älter als STALE_SECONDS ist.
"""

from __future__ import annotations

import platform
import time
from pathlib import Path

STALE_SECONDS = 120


def _hostname() -> str:
    return platform.node() or "unbekannt"


class AppLock:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.hostname = _hostname()
        # Eigene DB-Verbindung für Lock (unabhängig von der Haupt-DB)
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            import sqlite3
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode = DELETE")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS app_lock (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    hostname TEXT NOT NULL DEFAULT '',
                    heartbeat REAL NOT NULL DEFAULT 0
                )""")
            self._conn.commit()
        return self._conn

    def read_lock(self) -> dict | None:
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT hostname, heartbeat FROM app_lock WHERE id=1"
            ).fetchone()
            if row:
                return {"hostname": row[0], "heartbeat": row[1]}
        except Exception:
            pass
        return None

    def is_locked_by_other(self) -> bool:
        lock = self.read_lock()
        if not lock:
            return False
        if lock["hostname"] == self.hostname:
            return False
        age = time.time() - lock["heartbeat"]
        if age > STALE_SECONDS:
            return False
        return True

    def lock_owner_info(self) -> str:
        lock = self.read_lock()
        if not lock:
            return "Niemand"
        host = lock["hostname"]
        ts = lock["heartbeat"]
        if ts:
            import datetime
            dt = datetime.datetime.fromtimestamp(ts)
            zeit = dt.strftime("%d.%m.%Y %H:%M:%S")
            age = int(time.time() - ts)
            if age > STALE_SECONDS:
                return f"{host} (letzter Heartbeat vor {age}s)"
        else:
            zeit = "?"
        return f"{host} (aktiv seit {zeit})"

    def acquire(self):
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO app_lock (id, hostname, heartbeat) "
            "VALUES (1, ?, ?)", (self.hostname, now))
        conn.commit()

    def heartbeat(self):
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE app_lock SET heartbeat=? WHERE id=1 AND hostname=?",
                (time.time(), self.hostname))
            conn.commit()
        except Exception:
            pass

    def release(self):
        try:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM app_lock WHERE id=1 AND hostname=?",
                (self.hostname,))
            conn.commit()
        except Exception:
            pass

    def request_remote_shutdown(self):
        """Shutdown-Signal: hostname auf spezielle Markierung setzen."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO app_lock (id, hostname, heartbeat) "
            "VALUES (1, ?, ?)",
            (f"SHUTDOWN_BY:{self.hostname}", time.time()))
        conn.commit()

    def is_shutdown_requested(self) -> bool:
        lock = self.read_lock()
        if not lock:
            return False
        return (lock["hostname"].startswith("SHUTDOWN_BY:") and
                not lock["hostname"].endswith(self.hostname))

    def clear_shutdown_signal(self):
        pass  # acquire() überschreibt den SHUTDOWN-Eintrag

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
