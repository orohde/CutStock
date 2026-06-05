"""Tab: Sägeblattverwaltung."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QDialog, QFormLayout, QLineEdit, QDoubleSpinBox,
    QHeaderView, QMessageBox,
)

from core.db import Database
from core.models import Saegeblatt
from ui.i18n import t


class SaegeblattTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([t("blade.name").rstrip(":"), t("blade.kerf").rstrip(":"), ""])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton(t("blade.new"))
        btn_add.clicked.connect(self._add)
        btn_edit = QPushButton(t("btn.edit"))
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton(t("btn.delete"))
        btn_del.clicked.connect(self._delete)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_del)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.refresh()

    def refresh(self):
        blaetter = self.db.list_saegeblaetter()
        self.table.setRowCount(len(blaetter))
        for i, s in enumerate(blaetter):
            self.table.setItem(i, 0, QTableWidgetItem(s.name))
            self.table.setItem(i, 1, QTableWidgetItem(f"{s.schnittbreite:.1f}"))
            self.table.setItem(i, 2, QTableWidgetItem(str(s.id)))
        self.table.setColumnHidden(2, True)

    def _get_selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return int(self.table.item(row, 2).text())

    def _add(self):
        dlg = SaegeblattDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.db.save_saegeblatt(dlg.get_saegeblatt())
            self.refresh()

    def _edit(self):
        sid = self._get_selected_id()
        if sid is None:
            return
        sb = next((s for s in self.db.list_saegeblaetter() if s.id == sid), None)
        if not sb:
            return
        dlg = SaegeblattDialog(self, sb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_saegeblatt()
            updated.id = sid
            self.db.save_saegeblatt(updated)
            self.refresh()

    def _delete(self):
        sid = self._get_selected_id()
        if sid is None:
            return
        reply = QMessageBox.question(
            self, t("dlg.delete_title"), t("dlg.delete_blade"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_saegeblatt(sid)
            self.refresh()


class SaegeblattDialog(QDialog):
    def __init__(self, parent, sb: Saegeblatt | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("blade.edit") if sb else t("blade.new"))
        self.setMinimumWidth(450)

        from ui.units import length_row, to_display

        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = QLineEdit()
        self.name_edit.setMinimumWidth(250)
        self.kerf_spin, self._kerf_row = length_row(20)
        self.kerf_spin.setValue(to_display(3.0))

        form.addRow(t("blade.name"), self.name_edit)
        form.addRow(t("blade.kerf"), self._kerf_row)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton(t("btn.save"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)

        if sb:
            self.name_edit.setText(sb.name)
            self.kerf_spin.setValue(to_display(sb.schnittbreite))

    def get_saegeblatt(self) -> Saegeblatt:
        from ui.units import to_mm
        return Saegeblatt(
            name=self.name_edit.text(),
            schnittbreite=to_mm(self.kerf_spin.value()),
        )
