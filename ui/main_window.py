"""Hauptfenster mit Tab-Leiste und Lock-Mechanismus."""

import base64
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QApplication, QMessageBox,
)
from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtGui import QIcon

from core.db import Database, DEFAULT_DB
from core.lock import AppLock
from core.settings import get_settings
from ui.i18n import t
from ui.tab_material_lager import MaterialLagerTab
from ui.tab_projekt import ProjektTab
from ui.tab_optimierung import OptimierungTab
from ui.tab_einstellungen import EinstellungenTab, THEMES


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.settings = get_settings()
        self.lock = AppLock(DEFAULT_DB)
        self._shutdown_by_remote = False
        self.setWindowTitle(t("app.title"))
        self.setMinimumSize(1000, 700)
        self._set_icon()

        self._restore_geometry()
        self._apply_saved_theme()

        tabs = QTabWidget()
        self.material_lager_tab = MaterialLagerTab(db)
        self.projekt_tab = ProjektTab(db)
        self.optimierung_tab = OptimierungTab(db)
        self.einstellungen_tab = EinstellungenTab(db)

        tabs.addTab(self.material_lager_tab, t("tab.material_stock"))
        tabs.addTab(self.projekt_tab, t("tab.projects"))
        tabs.addTab(self.optimierung_tab, t("tab.optimization"))
        tabs.addTab(self.einstellungen_tab, t("tab.settings"))

        self.setCentralWidget(tabs)
        tabs.currentChanged.connect(self._tab_changed)

        self.lock.acquire()

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._tick)
        self._heartbeat_timer.start(30000)  # 30s – passend zu STALE_SECONDS=120

    def _tick(self):
        self.lock.heartbeat()
        if self.lock.is_shutdown_requested():
            self.lock.clear_shutdown_signal()
            self._shutdown_by_remote = True
            self.close()

    def _tab_changed(self, index):
        widget = self.centralWidget().widget(index)
        if hasattr(widget, "refresh"):
            widget.refresh()

    def _set_icon(self):
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS) / "assets" / "icon.jpg"
        else:
            base = Path(__file__).resolve().parent.parent / "assets" / "icon.jpg"
        if base.exists():
            self.setWindowIcon(QIcon(str(base)))
            QApplication.instance().setWindowIcon(QIcon(str(base)))

    def _restore_geometry(self):
        if self.settings.value("window/remember_geometry", True, type=bool):
            geo = self.settings.value("window/geometry")
            state = self.settings.value("window/state")
            if geo and isinstance(geo, str):
                self.restoreGeometry(QByteArray(base64.b64decode(geo)))
            if state and isinstance(state, str):
                self.restoreState(QByteArray(base64.b64decode(state)))

    def _apply_saved_theme(self):
        theme_name = self.settings.value("appearance/theme", "Warm")
        stylesheet = THEMES.get(theme_name, "")
        QApplication.instance().setStyleSheet(stylesheet)

    def closeEvent(self, event):
        self._heartbeat_timer.stop()
        if self.settings.value("window/remember_geometry", True, type=bool):
            geo_bytes = bytes(self.saveGeometry())
            state_bytes = bytes(self.saveState())
            self.settings.setValue("window/geometry",
                                  base64.b64encode(geo_bytes).decode("ascii"))
            self.settings.setValue("window/state",
                                  base64.b64encode(state_bytes).decode("ascii"))
        self.db.conn.commit()
        if not self._shutdown_by_remote:
            self.lock.release()
        self.lock.close()
        self.db.close()
        super().closeEvent(event)
