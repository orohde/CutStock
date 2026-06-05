"""Kombinierter Tab: Material oben, Lager unten (Master-Detail)."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox,
    QDoubleSpinBox, QSpinBox, QHeaderView, QMessageBox, QLabel,
    QSplitter, QGroupBox,
)
from PySide6.QtCore import Qt

from core.db import Database
from core.models import Material, MaterialTyp, Lagerstueck

from ui.i18n import t
from ui.tab_material import MaterialDialog


class MaterialLagerTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ---- Obere Hälfte: Materialien ----
        mat_group = QGroupBox(t("mat.title"))
        mat_layout = QVBoxLayout(mat_group)

        self.mat_table = QTableWidget()
        self.mat_table.setColumnCount(8)
        self.mat_table.setHorizontalHeaderLabels([
            t("mat.name").rstrip(":"), t("mat.type").rstrip(":"),
            t("mat.dim"), t("mat.grain").rstrip(":"),
            t("mat.trim").rstrip(":"), t("mat.min_rest_l").rstrip(":"),
            t("mat.min_rest_w").rstrip(":"), "",
        ])
        self.mat_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.mat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mat_table.setColumnHidden(7, True)
        self.mat_table.currentCellChanged.connect(self._material_selected)
        self.mat_table.doubleClicked.connect(self._edit_material)
        mat_layout.addWidget(self.mat_table)

        mat_btns = QHBoxLayout()
        btn_add_mat = QPushButton(t("mat.new"))
        btn_add_mat.clicked.connect(self._add_material)
        btn_edit_mat = QPushButton(t("btn.edit"))
        btn_edit_mat.clicked.connect(self._edit_material)
        btn_del_mat = QPushButton(t("btn.delete"))
        btn_del_mat.clicked.connect(self._delete_material)
        mat_btns.addWidget(btn_add_mat)
        mat_btns.addWidget(btn_edit_mat)
        mat_btns.addWidget(btn_del_mat)
        mat_btns.addStretch()
        mat_layout.addLayout(mat_btns)

        # ---- Untere Hälfte: Lager für das gewählte Material ----
        lager_group = QGroupBox(t("stock.title"))
        lager_layout = QVBoxLayout(lager_group)

        self.lager_table = QTableWidget()
        self.lager_table.setColumnCount(4)
        self.lager_table.setHorizontalHeaderLabels([
            t("stock.length").rstrip(":"), t("stock.width").rstrip(":"),
            t("stock.qty").rstrip(":"), "",
        ])
        self.lager_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.lager_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.lager_table.setColumnHidden(3, True)
        self.lager_table.doubleClicked.connect(self._edit_lager)
        lager_layout.addWidget(self.lager_table)

        lager_btns = QHBoxLayout()
        btn_add_ls = QPushButton(t("stock.new"))
        btn_add_ls.clicked.connect(self._add_lager)
        btn_edit_ls = QPushButton(t("btn.edit"))
        btn_edit_ls.clicked.connect(self._edit_lager)
        btn_del_ls = QPushButton(t("btn.delete"))
        btn_del_ls.clicked.connect(self._delete_lager)
        lager_btns.addWidget(btn_add_ls)
        lager_btns.addWidget(btn_edit_ls)
        lager_btns.addWidget(btn_del_ls)
        lager_btns.addStretch()
        lager_layout.addLayout(lager_btns)

        splitter.addWidget(mat_group)
        splitter.addWidget(lager_group)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self.refresh()

    def refresh(self):
        self._refresh_materials()

    def _refresh_materials(self):
        self.mat_table.blockSignals(True)
        materialien = self.db.list_materials()
        self.mat_table.setRowCount(len(materialien))
        for i, m in enumerate(materialien):
            self.mat_table.setItem(i, 0, QTableWidgetItem(m.name))
            typ_display = t("mat.plate") if m.typ == MaterialTyp.PLATTE else t("mat.bar")
            self.mat_table.setItem(i, 1, QTableWidgetItem(typ_display))
            if m.typ == MaterialTyp.PLATTE:
                dim = f"{m.dicke:.1f} mm Dicke"
            else:
                dim = f"{m.querschnitt_breite:.1f} × {m.querschnitt_tiefe:.1f} mm"
            self.mat_table.setItem(i, 2, QTableWidgetItem(dim))
            self.mat_table.setItem(i, 3, QTableWidgetItem(m.maserung.value))
            self.mat_table.setItem(i, 4, QTableWidgetItem(
                f"{m.besaeumung:.1f}" if m.besaeumung > 0 else "–"))
            self.mat_table.setItem(i, 5, QTableWidgetItem(f"{m.rest_min_laenge:.1f}"))
            self.mat_table.setItem(i, 6, QTableWidgetItem(f"{m.rest_min_breite:.1f}"))
            self.mat_table.setItem(i, 7, QTableWidgetItem(str(m.id)))
        self.mat_table.blockSignals(False)
        if materialien:
            self.mat_table.selectRow(0)
        self._material_selected()

    def _get_selected_material_id(self) -> int | None:
        row = self.mat_table.currentRow()
        if row < 0:
            return None
        item = self.mat_table.item(row, 7)
        return int(item.text()) if item else None

    def _material_selected(self):
        mid = self._get_selected_material_id()
        if mid is None:
            self.lager_table.setRowCount(0)
            return
        self._refresh_lager(mid)

    def _refresh_lager(self, material_id: int):
        mat = self.db.get_material(material_id)
        stuecke = self.db.list_lagerstuecke(material_id)
        is_platte = mat.typ == MaterialTyp.PLATTE if mat else True

        self.lager_table.setRowCount(len(stuecke))
        for i, ls in enumerate(stuecke):
            self.lager_table.setItem(i, 0, QTableWidgetItem(f"{ls.laenge:.1f}"))
            self.lager_table.setItem(i, 1, QTableWidgetItem(
                f"{ls.breite:.1f}" if ls.breite > 0 else "–"))
            self.lager_table.setItem(i, 2, QTableWidgetItem(str(ls.stueckzahl)))
            self.lager_table.setItem(i, 3, QTableWidgetItem(str(ls.id)))

    # ---- Material CRUD ----

    def _add_material(self):
        dlg = MaterialDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.db.save_material(dlg.get_material())
            self._refresh_materials()

    def _edit_material(self):
        mid = self._get_selected_material_id()
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
            self._refresh_materials()

    def _delete_material(self):
        mid = self._get_selected_material_id()
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
            self._refresh_materials()

    # ---- Lager CRUD (vorgefiltert auf gewähltes Material) ----

    def _add_lager(self):
        mid = self._get_selected_material_id()
        if mid is None:
            QMessageBox.information(self, t("hint"),
                                    t("dlg.select_material"))
            return
        mat = self.db.get_material(mid)
        if not mat:
            return

        from ui.units import length_row, to_display, to_mm
        dlg = _LagerQuickDialog(self, mat)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ls = dlg.get_lagerstueck(mid, mat.typ == MaterialTyp.PLATTE)
            self.db.save_lagerstueck(ls)
            self._refresh_lager(mid)

    def _edit_lager(self):
        mid = self._get_selected_material_id()
        row = self.lager_table.currentRow()
        if mid is None or row < 0:
            return
        lid = int(self.lager_table.item(row, 3).text())
        ls = self.db.get_lagerstueck(lid)
        if not ls:
            return
        mat = self.db.get_material(mid)
        if not mat:
            return
        dlg = _LagerQuickDialog(self, mat, ls)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_lagerstueck(mid, mat.typ == MaterialTyp.PLATTE)
            updated.id = lid
            self.db.save_lagerstueck(updated)
            self._refresh_lager(mid)

    def _delete_lager(self):
        mid = self._get_selected_material_id()
        row = self.lager_table.currentRow()
        if mid is None or row < 0:
            return
        lid = int(self.lager_table.item(row, 3).text())
        reply = QMessageBox.question(
            self, t("dlg.delete_title"), t("dlg.delete_stock"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_lagerstueck(lid)
            self._refresh_lager(mid)


class _LagerQuickDialog(QDialog):
    """Kompakter Lager-Dialog ohne Material-Auswahl (Material steht schon fest)."""

    def __init__(self, parent, mat: Material, ls: Lagerstueck | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("stock.edit") if ls else t("stock.new"))
        self.setMinimumWidth(450)

        from ui.units import length_row, to_display

        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        typ_display = t("mat.plate") if mat.typ == MaterialTyp.PLATTE else t("mat.bar")
        mat_label = QLabel(f"{mat.name} ({typ_display})")
        mat_label.setStyleSheet("font-weight: bold;")
        form.addRow(t("opt.material"), mat_label)

        self.laenge_spin, self._laenge_row = length_row()
        form.addRow(t("stock.length"), self._laenge_row)

        self.breite_spin, self._breite_row = length_row()
        self.breite_label = QLabel(t("stock.width"))
        is_platte = mat.typ == MaterialTyp.PLATTE
        self.breite_label.setVisible(is_platte)
        self._breite_row.setVisible(is_platte)
        form.addRow(self.breite_label, self._breite_row)

        self.stueck_spin = QSpinBox()
        self.stueck_spin.setRange(1, 9999)
        form.addRow(t("stock.qty"), self.stueck_spin)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton(t("btn.save"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)

        if ls:
            self.laenge_spin.setValue(to_display(ls.laenge))
            self.breite_spin.setValue(to_display(ls.breite))
            self.stueck_spin.setValue(ls.stueckzahl)

    def get_lagerstueck(self, material_id: int, is_platte: bool) -> Lagerstueck:
        from ui.units import to_mm
        return Lagerstueck(
            material_id=material_id,
            laenge=to_mm(self.laenge_spin.value()),
            breite=to_mm(self.breite_spin.value()) if is_platte else 0,
            stueckzahl=self.stueck_spin.value(),
        )
