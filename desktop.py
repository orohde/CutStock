#!/usr/bin/env python3
"""CutStock Desktop – lokaler FastAPI-Server in einem nativen Fenster (pywebview).

Ersetzt die frühere PySide6/Qt-Oberfläche. Es läuft dieselbe Web-Oberfläche
wie im Docker-Container, nur in einem eigenen Fenster:

* der FastAPI-Server läuft lokal auf 127.0.0.1 auf einem freien Port,
* die Daten liegen wie bisher lokal (SQLite); auf macOS im iCloud-Ordner,
* ein Heartbeat-Lock verhindert gleichzeitiges Bearbeiten von zwei Macs.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.db import DEFAULT_DB, Database, seed_data

# Datenbank-Pfad für das Backend festlegen, BEVOR web.app importiert wird.
os.environ.setdefault("CUTSTOCK_DB", str(DEFAULT_DB))
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
            time.sleep(2)  # kurz warten, damit das Signal über iCloud sichtbar wird
        lock.acquire()

        while not stop_event.wait(10):
            lock.heartbeat()
            if lock.is_shutdown_requested():
                # Eine andere Maschine hat übernommen -> Fenster schließen
                on_remote_takeover()
                break
    finally:
        lock.release()
        lock.close()


def main() -> None:
    _seed_if_empty()

    port = _free_port()

    import uvicorn
    from web.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        print("CutStock: Server konnte nicht gestartet werden.", file=sys.stderr)
        sys.exit(1)

    import webbrowser

    import webview

    class JsApi:
        """Wird der Web-Oberfläche als window.pywebview.api bereitgestellt."""

        def open_external(self, url: str) -> bool:
            # Externe Links im System-Browser öffnen, nicht im App-Fenster
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                webbrowser.open(url)
            return True

    window = webview.create_window(
        "CutStock",
        f"http://127.0.0.1:{port}/",
        width=1200,
        height=820,
        min_size=(900, 600),
        js_api=JsApi(),
    )

    stop_event = threading.Event()

    def on_remote_takeover() -> None:
        try:
            window.destroy()
        except Exception:
            pass

    lock_thread = threading.Thread(
        target=_lock_worker, args=(stop_event, on_remote_takeover), daemon=True)
    lock_thread.start()

    try:
        webview.start()  # blockiert bis das Fenster geschlossen wird
    finally:
        stop_event.set()
        server.should_exit = True


if __name__ == "__main__":
    main()
