"""Tab: Projektverwaltung mit Teileliste."""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QDialog, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QHeaderView, QMessageBox, QSplitter,
    QLabel, QGroupBox, QFileDialog,
)
from PySide6.QtCore import Qt

from core.db import Database
from core.models import Projekt, Teil, MaterialTyp, TeilStatus, Maserung
from ui.i18n import t


class ProjektTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Linke Seite: Projektliste
        left = QGroupBox(t("proj.title"))
        left_layout = QVBoxLayout(left)
        self.proj_table = QTableWidget()
        self.proj_table.setColumnCount(3)
        self.proj_table.setHorizontalHeaderLabels([
            t("proj.name").rstrip(":"), t("proj.progress"), ""])
        self.proj_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.proj_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.proj_table.setColumnHidden(2, True)
        self.proj_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.proj_table.currentCellChanged.connect(self._projekt_selected)
        left_layout.addWidget(self.proj_table)

        proj_btns = QHBoxLayout()
        btn_add_proj = QPushButton(t("btn.new"))
        btn_add_proj.clicked.connect(self._add_projekt)
        btn_del_proj = QPushButton(t("btn.delete"))
        btn_del_proj.clicked.connect(self._delete_projekt)
        btn_export = QPushButton(t("proj.export"))
        btn_export.clicked.connect(self._export_projekt)
        btn_import = QPushButton(t("proj.import"))
        btn_import.clicked.connect(self._import_projekt)
        proj_btns.addWidget(btn_add_proj)
        proj_btns.addWidget(btn_del_proj)
        proj_btns.addWidget(btn_export)
        proj_btns.addWidget(btn_import)
        left_layout.addLayout(proj_btns)

        # Rechte Seite: Teileliste
        right = QGroupBox(t("proj.parts"))
        right_layout = QVBoxLayout(right)
        self.teil_table = QTableWidget()
        self.teil_table.setColumnCount(8)
        self.teil_table.setHorizontalHeaderLabels([
            t("part.label").rstrip(":"), t("mat.type").rstrip(":"),
            t("opt.material").rstrip(":"), t("stock.length").rstrip(":"),
            t("stock.width").rstrip(":"), t("proj.progress"),
            "Status", "",
        ])
        self.teil_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.teil_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.teil_table.setColumnHidden(7, True)
        self.teil_table.doubleClicked.connect(self._edit_teil)
        right_layout.addWidget(self.teil_table)

        teil_btns = QHBoxLayout()
        btn_add_teil = QPushButton(t("part.add"))
        btn_add_teil.clicked.connect(self._add_teil)
        btn_edit_teil = QPushButton(t("btn.edit"))
        btn_edit_teil.clicked.connect(self._edit_teil)
        btn_del_teil = QPushButton(t("btn.remove"))
        btn_del_teil.clicked.connect(self._delete_teil)
        btn_cut_plus = QPushButton(t("part.cut_plus"))
        btn_cut_plus.clicked.connect(self._cut_plus)
        btn_cut_minus = QPushButton(t("part.cut_minus"))
        btn_cut_minus.clicked.connect(self._cut_minus)
        teil_btns.addWidget(btn_add_teil)
        teil_btns.addWidget(btn_edit_teil)
        teil_btns.addWidget(btn_del_teil)
        teil_btns.addStretch()
        teil_btns.addWidget(btn_cut_plus)
        teil_btns.addWidget(btn_cut_minus)
        right_layout.addLayout(teil_btns)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        self.refresh()

    def refresh(self):
        self._refresh_projekte()

    def _refresh_projekte(self):
        self.proj_table.blockSignals(True)
        self.teil_table.setRowCount(0)
        self.proj_table.setCurrentCell(-1, -1)
        projekte = self.db.list_projekte()
        self.proj_table.setRowCount(len(projekte))
        for i, p in enumerate(projekte):
            self.proj_table.setItem(i, 0, QTableWidgetItem(p.name))
            total = sum(teil.stueckzahl for teil in p.teile)
            done = sum(teil.gesaegt_anzahl for teil in p.teile)
            progress = QTableWidgetItem(f"{done} / {total}")
            progress.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.proj_table.setItem(i, 1, progress)
            self.proj_table.setItem(i, 2, QTableWidgetItem(str(p.id)))
        self.proj_table.blockSignals(False)
        if projekte:
            self.proj_table.selectRow(0)
        self._projekt_selected()

    def _get_selected_projekt_id(self) -> int | None:
        row = self.proj_table.currentRow()
        if row < 0:
            return None
        return int(self.proj_table.item(row, 2).text())

    def _projekt_selected(self):
        pid = self._get_selected_projekt_id()
        if pid is None:
            self.teil_table.setRowCount(0)
            return
        self._refresh_teile(pid)

    def _refresh_teile(self, projekt_id: int):
        teile = self.db.list_teile(projekt_id)
        self.teil_table.setRowCount(len(teile))
        for i, teil in enumerate(teile):
            mat = self.db.get_material(teil.material_id)
            mat_name = mat.name if mat else "?"
            typ_display = t("mat.plate") if teil.typ == MaterialTyp.PLATTE else t("mat.bar")
            status_key = "status.open" if teil.status == TeilStatus.OFFEN else "status.cut"
            self.teil_table.setItem(i, 0, QTableWidgetItem(teil.label))
            self.teil_table.setItem(i, 1, QTableWidgetItem(typ_display))
            self.teil_table.setItem(i, 2, QTableWidgetItem(mat_name))
            self.teil_table.setItem(i, 3, QTableWidgetItem(f"{teil.laenge:.1f}"))
            self.teil_table.setItem(i, 4, QTableWidgetItem(
                f"{teil.breite:.1f}" if teil.breite > 0 else "–"))
            fortschritt = f"{teil.gesaegt_anzahl} / {teil.stueckzahl}"
            progress_item = QTableWidgetItem(fortschritt)
            progress_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.teil_table.setItem(i, 5, progress_item)
            self.teil_table.setItem(i, 6, QTableWidgetItem(t(status_key)))
            self.teil_table.setItem(i, 7, QTableWidgetItem(str(teil.id)))

    def _add_projekt(self):
        dlg = ProjektDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.db.save_projekt(Projekt(name=dlg.name_edit.text()))
            self._refresh_projekte()

    def _delete_projekt(self):
        pid = self._get_selected_projekt_id()
        if pid is None:
            return
        reply = QMessageBox.question(
            self, t("dlg.delete_title"), t("dlg.delete_project"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_projekt(pid)
            self._refresh_projekte()

    def _add_teil(self):
        pid = self._get_selected_projekt_id()
        if pid is None:
            QMessageBox.information(self, t("hint"), t("dlg.select_project"))
            return
        dlg = TeilDialog(self, self.db, projekt_id=pid)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            teil = dlg.get_teil()
            teil.projekt_id = pid
            self.db.save_teil(teil)
            self._refresh_teile(pid)

    def _edit_teil(self):
        pid = self._get_selected_projekt_id()
        row = self.teil_table.currentRow()
        if pid is None or row < 0:
            return
        tid = int(self.teil_table.item(row, 7).text())
        teile = self.db.list_teile(pid)
        teil = next((t for t in teile if t.id == tid), None)
        if not teil:
            return
        dlg = TeilDialog(self, self.db, teil)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_teil()
            updated.id = tid
            updated.projekt_id = pid
            self.db.save_teil(updated)
            self._refresh_teile(pid)

    def _delete_teil(self):
        pid = self._get_selected_projekt_id()
        row = self.teil_table.currentRow()
        if pid is None or row < 0:
            return
        tid = int(self.teil_table.item(row, 7).text())
        reply = QMessageBox.question(
            self, t("dlg.delete_title"), t("dlg.delete_part"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_teil(tid)
            self._refresh_teile(pid)

    def _cut_plus(self):
        pid = self._get_selected_projekt_id()
        row = self.teil_table.currentRow()
        if pid is None or row < 0:
            return
        tid = int(self.teil_table.item(row, 7).text())
        teile = self.db.list_teile(pid)
        teil = next((t_item for t_item in teile if t_item.id == tid), None)
        if not teil:
            return
        if teil.gesaegt_anzahl < teil.stueckzahl:
            teil.gesaegt_anzahl += 1
            self.db.save_teil(teil)
            self._refresh_teile(pid)
            self._refresh_projekte_progress()

    def _cut_minus(self):
        pid = self._get_selected_projekt_id()
        row = self.teil_table.currentRow()
        if pid is None or row < 0:
            return
        tid = int(self.teil_table.item(row, 7).text())
        teile = self.db.list_teile(pid)
        teil = next((t_item for t_item in teile if t_item.id == tid), None)
        if not teil:
            return
        if teil.gesaegt_anzahl > 0:
            teil.gesaegt_anzahl -= 1
            self.db.save_teil(teil)
            self._refresh_teile(pid)
            self._refresh_projekte_progress()

    def _refresh_projekte_progress(self):
        """Nur den Fortschritt in der Projektliste aktualisieren."""
        for i in range(self.proj_table.rowCount()):
            pid_item = self.proj_table.item(i, 2)
            if not pid_item:
                continue
            pid = int(pid_item.text())
            projekt = self.db.get_projekt(pid)
            if projekt:
                total = sum(t_item.stueckzahl for t_item in projekt.teile)
                done = sum(t_item.gesaegt_anzahl for t_item in projekt.teile)
                progress = QTableWidgetItem(f"{done} / {total}")
                progress.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.proj_table.setItem(i, 1, progress)

    def _export_projekt(self):
        pid = self._get_selected_projekt_id()
        if pid is None:
            QMessageBox.information(self, t("hint"), t("dlg.select_project"))
            return
        projekt = self.db.get_projekt(pid)
        if not projekt:
            return

        parts = []
        for teil in projekt.teile:
            mat = self.db.get_material(teil.material_id)
            mat_name = mat.name if mat else ""
            entry = {
                "label": teil.label,
                "type": teil.typ.value,
                "material": mat_name,
                "length": teil.laenge,
                "quantity": teil.stueckzahl,
                "grain": teil.maserung.value,
            }
            if teil.typ == MaterialTyp.PLATTE:
                entry["width"] = teil.breite
            parts.append(entry)

        data = {"project": projekt.name, "parts": parts}

        path, _ = QFileDialog.getSaveFileName(
            self, t("proj.export"), f"{projekt.name}.json",
            "JSON (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, t("done"), t("proj.export_done"))

    def _import_projekt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("proj.import"), "", "JSON (*.json)")
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Material-Name → ID Lookup aufbauen
        materials = self.db.list_materials()
        mat_by_name = {m.name: m for m in materials}

        # Projekt anlegen
        projekt = self.db.save_projekt(Projekt(name=data.get("project", "Import")))

        imported = 0
        missing_materials = set()

        for p in data.get("parts", []):
            mat_name = p.get("material", "")
            mat = mat_by_name.get(mat_name)
            if mat is None:
                missing_materials.add(mat_name)
                continue

            typ = MaterialTyp(p.get("type", "Platte"))
            maserung = Maserung(p.get("grain", "egal"))
            teil = Teil(
                projekt_id=projekt.id,
                label=p.get("label", ""),
                typ=typ,
                material_id=mat.id,
                laenge=p.get("length", 0.0),
                breite=p.get("width", 0.0) if typ == MaterialTyp.PLATTE else 0.0,
                stueckzahl=p.get("quantity", 1),
                maserung=maserung,
            )
            self.db.save_teil(teil)
            imported += 1

        self._refresh_projekte()

        msg = t("proj.import_done", n=imported)
        if missing_materials:
            msg += "\n\n" + t("proj.import_missing",
                              materials="\n".join(f"- {m}" for m in sorted(missing_materials)))
            QMessageBox.warning(self, t("hint"), msg)
        else:
            QMessageBox.information(self, t("done"), msg)


class ProjektDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("proj.new"))
        self.setMinimumWidth(400)
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.name_edit = QLineEdit()
        self.name_edit.setMinimumWidth(300)
        self.name_edit.setPlaceholderText(t("proj.name_hint"))
        form.addRow(t("proj.name"), self.name_edit)
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton(t("btn.create"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)


class TeilDialog(QDialog):
    def __init__(self, parent, db: Database, teil: Teil | None = None,
                 projekt_id: int | None = None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(t("part.edit") if teil else t("part.new"))
        self.setMinimumWidth(500)

        from ui.units import length_row, to_display

        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.label_edit = QLineEdit()
        self.label_edit.setMinimumWidth(300)
        self.label_edit.setPlaceholderText(t("part.label_hint"))

        self.typ_combo = QComboBox()
        self.typ_combo.setMinimumWidth(250)
        self.typ_combo.addItem(t("mat.plate"), MaterialTyp.PLATTE.value)
        self.typ_combo.addItem(t("mat.bar"), MaterialTyp.STANGE.value)
        self.typ_combo.currentIndexChanged.connect(self._typ_changed)

        self.mat_combo = QComboBox()
        self.mat_combo.setMinimumWidth(250)
        self._materialien = db.list_materials()

        self.laenge_spin, self._laenge_row = length_row()
        self.breite_spin, self._breite_row = length_row()
        self.breite_label = QLabel(t("stock.width"))
        self.stueck_spin = QSpinBox()
        self.stueck_spin.setRange(1, 9999)
        self.stueck_spin.setValue(1)

        self.maserung_combo = QComboBox()
        self.maserung_combo.setMinimumWidth(250)
        self.maserung_combo.addItem(t("part.grain.any"), Maserung.EGAL.value)
        self.maserung_combo.addItem(t("part.grain.long"), Maserung.LAENGS.value)
        self.maserung_combo.addItem(t("part.grain.cross"), Maserung.QUER.value)
        self.maserung_label = QLabel(t("mat.grain"))

        form.addRow(t("part.label"), self.label_edit)
        form.addRow(t("mat.type"), self.typ_combo)
        form.addRow(t("opt.material"), self.mat_combo)
        form.addRow(t("stock.length"), self._laenge_row)
        form.addRow(self.breite_label, self._breite_row)
        form.addRow(self.maserung_label, self.maserung_combo)
        form.addRow(t("stock.qty"), self.stueck_spin)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton(t("btn.save"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)

        self._update_materials()

        if teil:
            self.label_edit.setText(teil.label)
            idx_typ = self.typ_combo.findData(teil.typ.value)
            if idx_typ >= 0:
                self.typ_combo.setCurrentIndex(idx_typ)
            self.laenge_spin.setValue(to_display(teil.laenge))
            self.breite_spin.setValue(to_display(teil.breite))
            self.stueck_spin.setValue(teil.stueckzahl)
            idx_mas = self.maserung_combo.findData(teil.maserung.value)
            if idx_mas >= 0:
                self.maserung_combo.setCurrentIndex(idx_mas)
            idx = self.mat_combo.findData(teil.material_id)
            if idx >= 0:
                self.mat_combo.setCurrentIndex(idx)
        elif projekt_id is not None:
            existing = db.list_teile(projekt_id)
            nr = len(existing) + 1
            self.label_edit.setText(f"Teil {nr}")

        self._typ_changed()

    def _typ_changed(self, _index=None):
        is_platte = self.typ_combo.currentData() == MaterialTyp.PLATTE.value
        self._breite_row.setVisible(is_platte)
        self.breite_label.setVisible(is_platte)
        self.maserung_label.setVisible(is_platte)
        self.maserung_combo.setVisible(is_platte)
        self._update_materials()

    def _update_materials(self):
        typ = MaterialTyp(self.typ_combo.currentData())
        self.mat_combo.clear()
        for m in self._materialien:
            if m.typ == typ:
                self.mat_combo.addItem(m.name, m.id)

    def get_teil(self) -> Teil:
        from ui.units import to_mm
        typ = MaterialTyp(self.typ_combo.currentData())
        return Teil(
            label=self.label_edit.text(),
            typ=typ,
            material_id=self.mat_combo.currentData(),
            laenge=to_mm(self.laenge_spin.value()),
            breite=to_mm(self.breite_spin.value()) if typ == MaterialTyp.PLATTE else 0,
            maserung=Maserung(self.maserung_combo.currentData()) if typ == MaterialTyp.PLATTE else Maserung.EGAL,
            stueckzahl=self.stueck_spin.value(),
        )
