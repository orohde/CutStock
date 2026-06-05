"""Tab: Materialverwaltung."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox,
    QDoubleSpinBox, QHeaderView, QMessageBox, QLabel,
)
from PySide6.QtCore import Qt

from core.db import Database
from core.models import Material, MaterialTyp, Maserung
from ui.i18n import t


class MaterialTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            t("mat.name").rstrip(":"), t("mat.type").rstrip(":"),
            t("mat.dim"), t("mat.grain").rstrip(":"),
            t("mat.trim").rstrip(":"), t("mat.min_rest_l").rstrip(":"),
            t("mat.min_rest_w").rstrip(":"), "",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton(t("mat.new"))
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
        materialien = self.db.list_materials()
        self.table.setRowCount(len(materialien))
        for i, m in enumerate(materialien):
            self.table.setItem(i, 0, QTableWidgetItem(m.name))
            typ_display = t("mat.plate") if m.typ == MaterialTyp.PLATTE else t("mat.bar")
            self.table.setItem(i, 1, QTableWidgetItem(typ_display))
            if m.typ == MaterialTyp.PLATTE:
                dim = f"{m.dicke:.1f} mm Dicke"
            else:
                dim = f"{m.querschnitt_breite:.1f} × {m.querschnitt_tiefe:.1f} mm"
            self.table.setItem(i, 2, QTableWidgetItem(dim))
            self.table.setItem(i, 3, QTableWidgetItem(m.maserung.value))
            self.table.setItem(i, 4, QTableWidgetItem(
                f"{m.besaeumung:.1f}" if m.besaeumung > 0 else "–"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{m.rest_min_laenge:.1f}"))
            self.table.setItem(i, 6, QTableWidgetItem(f"{m.rest_min_breite:.1f}"))
            self.table.setItem(i, 7, QTableWidgetItem(str(m.id)))
        self.table.setColumnHidden(7, True)

    def _get_selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return int(self.table.item(row, 7).text())

    def _add(self):
        dlg = MaterialDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.db.save_material(dlg.get_material())
            self.refresh()

    def _edit(self):
        mid = self._get_selected_id()
        if mid is None:
            return
        mat = self.db.get_material(mid)
        if not mat:
            return
        dlg = MaterialDialog(self, mat)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_material()
            updated.id = mid
            self.db.save_material(updated)
            self.refresh()

    def _delete(self):
        mid = self._get_selected_id()
        if mid is None:
            return
        n_lager = len(self.db.list_lagerstuecke(mid))
        reply = QMessageBox.question(
            self, t("dlg.delete_title"),
            t("dlg.delete_material", n=n_lager),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_material(mid)
            self.refresh()


class MaterialDialog(QDialog):
    def __init__(self, parent, material: Material | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("mat.edit") if material else t("mat.new"))
        self.setMinimumWidth(500)

        from ui.units import length_row, to_display, to_mm

        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = QLineEdit()
        self.name_edit.setMinimumWidth(300)

        self.typ_combo = QComboBox()
        self.typ_combo.setMinimumWidth(250)
        self.typ_combo.addItem(t("mat.plate"), MaterialTyp.PLATTE.value)
        self.typ_combo.addItem(t("mat.bar"), MaterialTyp.STANGE.value)
        self.typ_combo.currentIndexChanged.connect(self._typ_changed)

        self.dicke_spin, self._dicke_row = length_row(999)
        self.dicke_label = QLabel(t("mat.thickness"))

        self.qs_breite_spin, self._qsb_row = length_row(999)
        self.qs_breite_label = QLabel(t("mat.cross_w"))
        self.qs_tiefe_spin, self._qst_row = length_row(999)
        self.qs_tiefe_label = QLabel(t("mat.cross_d"))

        self.maserung_combo = QComboBox()
        self.maserung_combo.setMinimumWidth(250)
        self.maserung_combo.addItem(t("mat.grain.none"), Maserung.KEINE.value)
        self.maserung_combo.addItem(t("mat.grain.long"), Maserung.LAENGS.value)
        self.maserung_combo.addItem(t("mat.grain.cross"), Maserung.QUER.value)
        self.maserung_label = QLabel(t("mat.grain"))

        self.besaeumung_spin, self._bes_row = length_row(200)

        self.rest_laenge_spin, self._rl_row = length_row()
        self.rest_breite_spin, self._rb_row = length_row()
        self.rest_breite_label = QLabel(t("mat.min_rest_w"))

        form.addRow(t("mat.name"), self.name_edit)
        form.addRow(t("mat.type"), self.typ_combo)
        form.addRow(self.dicke_label, self._dicke_row)
        form.addRow(self.qs_breite_label, self._qsb_row)
        form.addRow(self.qs_tiefe_label, self._qst_row)
        form.addRow(self.maserung_label, self.maserung_combo)
        form.addRow(t("mat.trim"), self._bes_row)
        form.addRow(t("mat.min_rest_l"), self._rl_row)
        form.addRow(self.rest_breite_label, self._rb_row)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton(t("btn.save"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)

        if material:
            self.name_edit.setText(material.name)
            idx_typ = self.typ_combo.findData(material.typ.value)
            if idx_typ >= 0:
                self.typ_combo.setCurrentIndex(idx_typ)
            self.dicke_spin.setValue(to_display(material.dicke))
            self.qs_breite_spin.setValue(to_display(material.querschnitt_breite))
            self.qs_tiefe_spin.setValue(to_display(material.querschnitt_tiefe))
            idx_m = self.maserung_combo.findData(material.maserung.value)
            if idx_m >= 0:
                self.maserung_combo.setCurrentIndex(idx_m)
            self.besaeumung_spin.setValue(to_display(material.besaeumung))
            self.rest_laenge_spin.setValue(to_display(material.rest_min_laenge))
            self.rest_breite_spin.setValue(to_display(material.rest_min_breite))

        self._typ_changed()

    def _typ_changed(self, _index=None):
        is_platte = self.typ_combo.currentData() == MaterialTyp.PLATTE.value
        self.dicke_label.setVisible(is_platte)
        self._dicke_row.setVisible(is_platte)
        self.maserung_label.setVisible(is_platte)
        self.maserung_combo.setVisible(is_platte)
        self.rest_breite_label.setVisible(is_platte)
        self._rb_row.setVisible(is_platte)
        self.qs_breite_label.setVisible(not is_platte)
        self._qsb_row.setVisible(not is_platte)
        self.qs_tiefe_label.setVisible(not is_platte)
        self._qst_row.setVisible(not is_platte)

    def get_material(self) -> Material:
        from ui.units import to_mm
        typ = MaterialTyp(self.typ_combo.currentData())
        return Material(
            name=self.name_edit.text(),
            typ=typ,
            dicke=to_mm(self.dicke_spin.value()) if typ == MaterialTyp.PLATTE else 0,
            querschnitt_breite=to_mm(self.qs_breite_spin.value()) if typ == MaterialTyp.STANGE else 0,
            querschnitt_tiefe=to_mm(self.qs_tiefe_spin.value()) if typ == MaterialTyp.STANGE else 0,
            maserung=Maserung(self.maserung_combo.currentData()) if typ == MaterialTyp.PLATTE else Maserung.KEINE,
            besaeumung=to_mm(self.besaeumung_spin.value()),
            rest_min_laenge=to_mm(self.rest_laenge_spin.value()),
            rest_min_breite=to_mm(self.rest_breite_spin.value()) if typ == MaterialTyp.PLATTE else 0,
        )
