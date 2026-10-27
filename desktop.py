#!/usr/bin/env python3
"""CutStock Desktop – lokaler FastAPI-Server, Oberfläche im Standard-Browser.

Die Web-Oberfläche läuft identisch wie im Docker-Container, nur lokal:

* der FastAPI-Server läuft lokal auf 127.0.0.1 auf einem freien Port,
* die Oberfläche öffnet sich automatisch im Standard-Browser,
* die Daten liegen wie bisher lokal (SQLite); auf macOS im iCloud-Ordner,
* ein Heartbeat-Lock verhindert gleichzeitiges Bearbeiten von zwei Macs.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.db import DEFAULT_DB, Database, seed_data

# Datenbank-Pfad für das Backend festlegen, BEVOR web.app importiert wird.
os.environ.setdefault("CUTSTOCK_DB", str(DEFAULT_DB))
os.environ["CUTSTOCK_DESKTOP"] = "1"
# Denselben Pfad für Seed und Lock verwenden wie das Backend.
DB_PATH = Path(os.environ["CUTSTOCK_DB"])


def _free_port() -> int:
    """Einen freien lokalen Port ermitteln."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _seed_if_empty() -> None:
    db = Database(DB_PATH)
    try:
        if not db.list_materials():
            seed_data(db)
    finally:
        db.close()


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    import urllib.request

    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def _lock_worker(stop_event: threading.Event, on_remote_takeover) -> None:
    """iCloud-sicherer Lock samt Heartbeat in einem eigenen Thread.

    Beim Start wird ein aktiver Lock einer anderen Maschine übernommen
    (die andere Instanz beendet sich beim nächsten Heartbeat selbst).
    """
    from core.lock import AppLock

    lock = AppLock(DB_PATH)
    try:
        if lock.is_locked_by_other():
            print(f"CutStock ist geöffnet auf: {lock.lock_owner_info()} – übernehme.",
                  file=sys.stderr)
            lock.request_remote_shutdown()
            time.sleep(2)
        lock.acquire()

        while not stop_event.wait(10):
            lock.heartbeat()
            if lock.is_shutdown_requested():
                on_remote_takeover()
                break
    finally:
        lock.release()
        lock.close()


def main() -> None:
    _seed_if_empty()

    from core.settings import Settings
    settings = Settings(DB_PATH.parent / "settings.json")
    api_enabled = settings.value("api/enabled", False)
    api_port = settings.value("api/port", 8421, type=int)

    if api_enabled and api_port:
        port = api_port
        host = "0.0.0.0"
    else:
        port = _free_port()
        host = "127.0.0.1"

    # PyInstaller auf Windows setzt sys.stderr/stdout auf None (kein Konsolenfenster).
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")

    import uvicorn
    from web.app import app

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        print("CutStock: Server konnte nicht gestartet werden.", file=sys.stderr)
        sys.exit(1)

    webbrowser.open(f"http://127.0.0.1:{port}/")

    stop_event = threading.Event()

    def on_remote_takeover() -> None:
        stop_event.set()

    lock_thread = threading.Thread(
        target=_lock_worker, args=(stop_event, on_remote_takeover), daemon=True)
    lock_thread.start()

    # SIGTERM (macOS Dock-Quit, systemd stop) sauber abfangen
    def _handle_term(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_term)

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
