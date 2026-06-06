#!/usr/bin/env python3
"""CutStock – Einstiegspunkt."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from core.db import Database, DEFAULT_DB, seed_data
from core.lock import AppLock


def check_lock(app: QApplication, lock: AppLock) -> bool:
    """Prüft ob die App anderswo geöffnet ist. Gibt True zurück wenn wir starten dürfen."""
    if not lock.is_locked_by_other():
        return True

    owner = lock.lock_owner_info()
    msg = QMessageBox()
    msg.setWindowTitle("CutStock – bereits geöffnet")
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(
        f"CutStock ist bereits auf einem anderen Rechner geöffnet:\n\n"
        f"    {owner}\n\n"
        f"Was möchtest du tun?")

    btn_takeover = msg.addButton(
        "Hier öffnen (Remote schließen)", QMessageBox.ButtonRole.AcceptRole)
    btn_quit = msg.addButton(
        "Abbrechen (hier schließen)", QMessageBox.ButtonRole.RejectRole)
    msg.setDefaultButton(btn_quit)
    msg.exec()

    if msg.clickedButton() == btn_takeover:
        lock.request_remote_shutdown()
        # Kurz warten damit die Signaldatei über iCloud synchronisiert werden kann
        from PySide6.QtCore import QTimer, QEventLoop
        loop = QEventLoop()
        QTimer.singleShot(2000, loop.quit)
        info = QMessageBox()
        info.setWindowTitle("CutStock")
        info.setIcon(QMessageBox.Icon.Information)
        info.setText(
            "Shutdown-Signal gesendet.\n\n"
            "Die andere Instanz wird sich beim nächsten Sync beenden.\n"
            "Das kann je nach iCloud-Verbindung einige Sekunden dauern.")
        info.setStandardButtons(QMessageBox.StandardButton.Ok)
        info.exec()
        return True
    else:
        return False


def main():
    app = QApplication(sys.argv)
    lock = AppLock(DEFAULT_DB)

    # Alte Lock-Dateien aufräumen (Migration von Datei- auf DB-Lock)
    from pathlib import Path
    for old_file in [DEFAULT_DB.parent / "cutstock.lock",
                     DEFAULT_DB.parent / "cutstock.shutdown"]:
        if old_file.exists():
            try:
                old_file.unlink()
            except OSError:
                pass

    if not check_lock(app, lock):
        sys.exit(0)

    db = Database()
    if not db.list_materials():
        print("Erste Ausführung – lege Beispieldaten an …")
        seed_data(db)

    from ui.main_window import MainWindow
    window = MainWindow(db)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
