"""Tab: Einstellungen – Fenstergröße merken, Aussehen wählen."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
    QComboBox, QLabel, QPushButton, QFormLayout, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFileDialog,
)
from core.settings import get_settings

THEMES = {
    "Standard (System)": "",
    "Dunkel": """
        QWidget {
            background-color: #2b2b2b;
            color: #e0e0e0;
            font-size: 13px;
        }
        QTableWidget {
            background-color: #1e1e1e;
            alternate-background-color: #2a2a2a;
            gridline-color: #444;
            selection-background-color: #3a6ea5;
        }
        QHeaderView::section {
            background-color: #333;
            color: #e0e0e0;
            padding: 4px;
            border: 1px solid #444;
        }
        QTabBar::tab {
            background-color: #333;
            color: #ccc;
            padding: 8px 16px;
            border: 1px solid #444;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #3a6ea5;
            color: white;
        }
        QPushButton {
            background-color: #3a3a3a;
            color: #e0e0e0;
            border: 1px solid #555;
            padding: 6px 14px;
            border-radius: 3px;
        }
        QPushButton:hover { background-color: #4a4a4a; }
        QPushButton:pressed { background-color: #3a6ea5; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #3a3a3a;
            color: #e0e0e0;
            border: 1px solid #555;
            padding: 4px;
            border-radius: 3px;
        }
        QGroupBox {
            color: #e0e0e0;
            border: 1px solid #555;
            margin-top: 8px;
            padding-top: 16px;
        }
        QGroupBox::title { padding: 0 6px; }
        QScrollArea { border: none; }
        QFrame { border-color: #555; }
    """,
    "Hell": """
        QWidget {
            background-color: #f5f5f5;
            color: #1a1a1a;
            font-size: 13px;
        }
        QTableWidget {
            background-color: white;
            alternate-background-color: #f0f4f8;
            gridline-color: #ddd;
            selection-background-color: #0078d4;
            selection-color: white;
        }
        QHeaderView::section {
            background-color: #e8e8e8;
            color: #1a1a1a;
            padding: 4px;
            border: 1px solid #ccc;
        }
        QTabBar::tab {
            background-color: #e0e0e0;
            color: #333;
            padding: 8px 16px;
            border: 1px solid #ccc;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #0078d4;
            color: white;
        }
        QPushButton {
            background-color: #e8e8e8;
            color: #1a1a1a;
            border: 1px solid #bbb;
            padding: 6px 14px;
            border-radius: 3px;
        }
        QPushButton:hover { background-color: #d0d0d0; }
        QPushButton:pressed { background-color: #0078d4; color: white; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: white;
            color: #1a1a1a;
            border: 1px solid #bbb;
            padding: 4px;
            border-radius: 3px;
        }
        QGroupBox {
            color: #1a1a1a;
            border: 1px solid #ccc;
            margin-top: 8px;
            padding-top: 16px;
        }
        QGroupBox::title { padding: 0 6px; }
        QScrollArea { border: none; }
    """,
    "Blaugrau": """
        QWidget {
            background-color: #1e2a38;
            color: #c8d6e5;
            font-size: 13px;
        }
        QTableWidget {
            background-color: #162230;
            alternate-background-color: #1e2a38;
            gridline-color: #2c3e50;
            selection-background-color: #2980b9;
        }
        QHeaderView::section {
            background-color: #243447;
            color: #c8d6e5;
            padding: 4px;
            border: 1px solid #2c3e50;
        }
        QTabBar::tab {
            background-color: #243447;
            color: #8fa7bf;
            padding: 8px 16px;
            border: 1px solid #2c3e50;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #2980b9;
            color: white;
        }
        QPushButton {
            background-color: #243447;
            color: #c8d6e5;
            border: 1px solid #2c3e50;
            padding: 6px 14px;
            border-radius: 3px;
        }
        QPushButton:hover { background-color: #2c3e50; }
        QPushButton:pressed { background-color: #2980b9; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #243447;
            color: #c8d6e5;
            border: 1px solid #2c3e50;
            padding: 4px;
            border-radius: 3px;
        }
        QGroupBox {
            color: #c8d6e5;
            border: 1px solid #2c3e50;
            margin-top: 8px;
            padding-top: 16px;
        }
        QGroupBox::title { padding: 0 6px; }
        QScrollArea { border: none; }
        QFrame { border-color: #2c3e50; }
    """,
    "Warm": """
        QWidget {
            background-color: #2c2420;
            color: #e8ddd3;
            font-size: 13px;
        }
        QTableWidget {
            background-color: #231e1a;
            alternate-background-color: #2c2420;
            gridline-color: #4a3f36;
            selection-background-color: #8b5e3c;
        }
        QHeaderView::section {
            background-color: #3a312a;
            color: #e8ddd3;
            padding: 4px;
            border: 1px solid #4a3f36;
        }
        QTabBar::tab {
            background-color: #3a312a;
            color: #b0a090;
            padding: 8px 16px;
            border: 1px solid #4a3f36;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #8b5e3c;
            color: white;
        }
        QPushButton {
            background-color: #3a312a;
            color: #e8ddd3;
            border: 1px solid #4a3f36;
            padding: 6px 14px;
            border-radius: 3px;
        }
        QPushButton:hover { background-color: #4a3f36; }
        QPushButton:pressed { background-color: #8b5e3c; }
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #3a312a;
            color: #e8ddd3;
            border: 1px solid #4a3f36;
            padding: 4px;
            border-radius: 3px;
        }
        QGroupBox {
            color: #e8ddd3;
            border: 1px solid #4a3f36;
            margin-top: 8px;
            padding-top: 16px;
        }
        QGroupBox::title { padding: 0 6px; }
        QScrollArea { border: none; }
        QFrame { border-color: #4a3f36; }
    """,
}


class EinstellungenTab(QWidget):
    def __init__(self, db=None):
        super().__init__()
        self.db = db
        self.settings = get_settings()

        from ui.i18n import t, LANGUAGES, current_language

        layout = QVBoxLayout(self)

        # --- Fenster ---
        fenster_group = QGroupBox(t("set.window"))
        fenster_layout = QVBoxLayout(fenster_group)
        self.remember_size_check = QCheckBox(t("set.remember_size"))
        self.remember_size_check.setChecked(
            self.settings.value("window/remember_geometry", True, type=bool))
        self.remember_size_check.toggled.connect(self._on_remember_changed)
        fenster_layout.addWidget(self.remember_size_check)
        layout.addWidget(fenster_group)

        # --- Aussehen ---
        aussehen_group = QGroupBox(t("set.appearance"))
        aussehen_layout = QFormLayout(aussehen_group)

        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(250)
        self.theme_combo.addItems(THEMES.keys())
        saved_theme = self.settings.value("appearance/theme", "Warm")
        idx = self.theme_combo.findText(saved_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        aussehen_layout.addRow(t("set.theme"), self.theme_combo)

        self.unit_combo = QComboBox()
        self.unit_combo.setMinimumWidth(250)
        self.unit_combo.addItems(["mm", "cm"])
        saved_unit = self.settings.value("appearance/unit", "mm")
        idx_u = self.unit_combo.findText(saved_unit)
        if idx_u >= 0:
            self.unit_combo.setCurrentIndex(idx_u)
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
        aussehen_layout.addRow(t("set.unit"), self.unit_combo)

        self.lang_combo = QComboBox()
        self.lang_combo.setMinimumWidth(250)
        for code, name in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        idx_l = self.lang_combo.findData(current_language())
        if idx_l >= 0:
            self.lang_combo.setCurrentIndex(idx_l)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        aussehen_layout.addRow(t("set.language"), self.lang_combo)

        layout.addWidget(aussehen_group)

        # --- Sägeblätter ---
        if db:
            from ui.tab_saegeblatt import SaegeblattDialog
            from core.models import Saegeblatt

            blade_group = QGroupBox(t("blade.title"))
            blade_layout = QVBoxLayout(blade_group)

            self.blade_table = QTableWidget()
            self.blade_table.setColumnCount(3)
            self.blade_table.setHorizontalHeaderLabels([
                t("blade.name").rstrip(":"), t("blade.kerf").rstrip(":"), "",
            ])
            self.blade_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch)
            self.blade_table.setSelectionBehavior(
                QTableWidget.SelectionBehavior.SelectRows)
            self.blade_table.setColumnHidden(2, True)
            self.blade_table.doubleClicked.connect(self._edit_blade)
            blade_layout.addWidget(self.blade_table)

            blade_btns = QHBoxLayout()
            btn_add_bl = QPushButton(t("blade.new"))
            btn_add_bl.clicked.connect(self._add_blade)
            btn_edit_bl = QPushButton(t("btn.edit"))
            btn_edit_bl.clicked.connect(self._edit_blade)
            btn_del_bl = QPushButton(t("btn.delete"))
            btn_del_bl.clicked.connect(self._delete_blade)
            blade_btns.addWidget(btn_add_bl)
            blade_btns.addWidget(btn_edit_bl)
            blade_btns.addWidget(btn_del_bl)
            blade_btns.addStretch()
            blade_layout.addLayout(blade_btns)

            layout.addWidget(blade_group)
            self._refresh_blades()

        # --- Backup ---
        backup_group = QGroupBox(t("set.backup"))
        backup_layout = QHBoxLayout(backup_group)
        btn_backup = QPushButton(t("set.backup_create"))
        btn_backup.clicked.connect(self._create_backup)
        btn_restore = QPushButton(t("set.backup_restore"))
        btn_restore.clicked.connect(self._restore_backup)
        backup_layout.addWidget(btn_backup)
        backup_layout.addWidget(btn_restore)
        backup_layout.addStretch()
        layout.addWidget(backup_group)

        # --- Info ---
        info_group = QGroupBox(t("set.storage"))
        info_layout = QVBoxLayout(info_group)
        from core.db import DEFAULT_DB
        info_layout.addWidget(QLabel(f"{t('set.db_path')} {DEFAULT_DB}"))
        info_layout.addWidget(QLabel(
            f"{t('set.settings_path')} {self.settings.fileName()}"))
        layout.addWidget(info_group)

        layout.addStretch()

    def refresh(self):
        if self.db:
            self._refresh_blades()

    def _refresh_blades(self):
        from ui.i18n import t
        blaetter = self.db.list_saegeblaetter()
        self.blade_table.setRowCount(len(blaetter))
        for i, s in enumerate(blaetter):
            self.blade_table.setItem(i, 0, QTableWidgetItem(s.name))
            self.blade_table.setItem(i, 1, QTableWidgetItem(
                f"{s.schnittbreite:.1f}"))
            self.blade_table.setItem(i, 2, QTableWidgetItem(str(s.id)))

    def _add_blade(self):
        from ui.tab_saegeblatt import SaegeblattDialog
        dlg = SaegeblattDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.db.save_saegeblatt(dlg.get_saegeblatt())
            self._refresh_blades()

    def _edit_blade(self):
        row = self.blade_table.currentRow()
        if row < 0:
            return
        sid = int(self.blade_table.item(row, 2).text())
        blaetter = self.db.list_saegeblaetter()
        sb = next((s for s in blaetter if s.id == sid), None)
        if not sb:
            return
        from ui.tab_saegeblatt import SaegeblattDialog
        dlg = SaegeblattDialog(self, sb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_saegeblatt()
            updated.id = sid
            self.db.save_saegeblatt(updated)
            self._refresh_blades()

    def _delete_blade(self):
        from ui.i18n import t
        row = self.blade_table.currentRow()
        if row < 0:
            return
        sid = int(self.blade_table.item(row, 2).text())
        reply = QMessageBox.question(
            self, t("dlg.delete_title"), t("dlg.delete_blade"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_saegeblatt(sid)
            self._refresh_blades()

    def _create_backup(self):
        from ui.i18n import t
        from core.db import DEFAULT_DB
        from core.settings import SETTINGS_FILE
        import zipfile
        from datetime import date

        path, _ = QFileDialog.getSaveFileName(
            self, t("set.backup_create"),
            f"cutstock_backup_{date.today().isoformat()}.zip",
            "ZIP (*.zip)",
        )
        if not path:
            return
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            if DEFAULT_DB.exists():
                zf.write(DEFAULT_DB, DEFAULT_DB.name)
            if SETTINGS_FILE.exists():
                zf.write(SETTINGS_FILE, SETTINGS_FILE.name)
        QMessageBox.information(self, t("set.backup"), t("set.backup_done"))

    def _restore_backup(self):
        from ui.i18n import t
        from core.db import DEFAULT_DB
        from core.settings import SETTINGS_FILE
        import zipfile

        path, _ = QFileDialog.getOpenFileName(
            self, t("set.backup_restore"), "", "ZIP (*.zip)",
        )
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                if DEFAULT_DB.name not in names:
                    QMessageBox.warning(
                        self, t("error"), t("set.backup_invalid"))
                    return
        except zipfile.BadZipFile:
            QMessageBox.warning(self, t("error"), t("set.backup_invalid"))
            return

        reply = QMessageBox.question(
            self, t("set.backup"),
            t("set.backup_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with zipfile.ZipFile(path, "r") as zf:
            dest = DEFAULT_DB.parent
            if DEFAULT_DB.name in zf.namelist():
                zf.extract(DEFAULT_DB.name, dest)
            if SETTINGS_FILE.name in zf.namelist():
                zf.extract(SETTINGS_FILE.name, dest)

        QMessageBox.information(
            self, t("set.backup"), t("set.backup_restored"))
        import sys, os
        from PySide6.QtWidgets import QApplication
        QApplication.instance().closeAllWindows()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _on_remember_changed(self, checked: bool):
        self.settings.setValue("window/remember_geometry", checked)

    def _on_unit_changed(self, unit: str):
        self.settings.setValue("appearance/unit", unit)
        self._ask_restart()

    def _on_lang_changed(self):
        from ui.i18n import set_language
        code = self.lang_combo.currentData()
        set_language(code)
        self._ask_restart()

    def _ask_restart(self):
        from ui.i18n import t
        reply = QMessageBox.question(
            self, t("app.title"),
            t("set.restart_now"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            import sys, os
            from PySide6.QtWidgets import QApplication
            QApplication.instance().closeAllWindows()
            os.execv(sys.executable, [sys.executable] + sys.argv)

    def _on_theme_changed(self, theme_name: str):
        self.settings.setValue("appearance/theme", theme_name)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(THEMES.get(theme_name, ""))
