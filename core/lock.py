"""Dateibasierter Lock-Mechanismus für iCloud-Synchronisation.

Legt eine Lock-Datei neben der DB ab. Da diese über iCloud synchronisiert
wird, können andere Macs erkennen, dass die App bereits geöffnet ist.

Der Lock enthält einen Heartbeat-Timestamp der alle paar Sekunden
aktualisiert wird. Ein Lock gilt als abgelaufen wenn der Heartbeat
älter als STALE_SECONDS ist – das macht den Mechanismus robust gegen
iCloud-Sync-Verzögerungen und nicht sauber beendete Instanzen.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path

STALE_SECONDS = 30


def _hostname() -> str:
    return platform.node() or "unbekannt"


class AppLock:
    def __init__(self, db_path: Path):
        self.lock_file = db_path.parent / "cutstock.lock"
        self.shutdown_file = db_path.parent / "cutstock.shutdown"
        self.hostname = _hostname()

    def read_lock(self) -> dict | None:
        if not self.lock_file.exists():
            return None
        try:
            data = json.loads(self.lock_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "hostname" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def is_locked_by_other(self) -> bool:
        lock = self.read_lock()
        if not lock:
            return False
        if lock.get("hostname") == self.hostname:
            return False
        age = time.time() - lock.get("heartbeat", lock.get("timestamp", 0))
        if age > STALE_SECONDS:
            return False
        return True

    def lock_owner_info(self) -> str:
        lock = self.read_lock()
        if not lock:
            return "Niemand"
        host = lock.get("hostname", "?")
        ts = lock.get("heartbeat", lock.get("timestamp", 0))
        if ts:
            import datetime
            dt = datetime.datetime.fromtimestamp(ts)
            zeit = dt.strftime("%d.%m.%Y %H:%M:%S")
            age = int(time.time() - ts)
            if age > STALE_SECONDS:
                return f"{host} (letzter Heartbeat vor {age}s – vermutlich nicht mehr aktiv)"
        else:
            zeit = "?"
        return f"{host} (aktiv seit {zeit})"

    def acquire(self):
        now = time.time()
        data = {
            "hostname": self.hostname,
            "timestamp": now,
            "heartbeat": now,
        }
        self.lock_file.write_text(
            json.dumps(data, indent=2), encoding="utf-8")
        if self.shutdown_file.exists():
            try:
                self.shutdown_file.unlink()
            except OSError:
                pass

    def heartbeat(self):
        """Heartbeat aktualisieren – zeigt dass die Instanz noch lebt."""
        lock = self.read_lock()
        if lock and lock.get("hostname") == self.hostname:
            lock["heartbeat"] = time.time()
            try:
                self.lock_file.write_text(
                    json.dumps(lock, indent=2), encoding="utf-8")
            except OSError:
                pass

    def release(self):
        lock = self.read_lock()
        if lock and lock.get("hostname") == self.hostname:
            try:
                self.lock_file.unlink()
            except OSError:
                pass

    def request_remote_shutdown(self):
        data = {
            "requested_by": self.hostname,
            "timestamp": time.time(),
        }
        self.shutdown_file.write_text(
            json.dumps(data, indent=2), encoding="utf-8")

    def is_shutdown_requested(self) -> bool:
        if not self.shutdown_file.exists():
            return False
        try:
            data = json.loads(self.shutdown_file.read_text(encoding="utf-8"))
            return data.get("requested_by") != self.hostname
        except (json.JSONDecodeError, OSError):
            return False

    def clear_shutdown_signal(self):
        try:
            if self.shutdown_file.exists():
                self.shutdown_file.unlink()
        except OSError:
            pass
