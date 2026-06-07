"""Tab: Optimierungslauf starten, Ergebnis grafisch anzeigen, bestätigen."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QScrollArea, QGroupBox, QMessageBox, QFrame, QFileDialog,
    QGridLayout,
)
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtCore import Qt, QRectF, QSize, Signal

from core.db import Database
from core.models import MaterialTyp, drehung_fuer_teil
from ui.i18n import t
from core.optimize import (
    OptimierungsErgebnis, Schnittplan, StangenVorrat, PlattenVorrat,
    optimize_1d, optimize_2d, optimize_1d_ga, optimize_2d_ga,
    optimize_2d_nested,
)


FARBEN = [
    QColor("#4CAF50"), QColor("#2196F3"), QColor("#FF9800"),
    QColor("#9C27B0"), QColor("#F44336"), QColor("#00BCD4"),
    QColor("#8BC34A"), QColor("#FF5722"), QColor("#3F51B5"),
    QColor("#CDDC39"), QColor("#E91E63"), QColor("#009688"),
]


class SchnittplanWidget(QFrame):
    """Zeichnet einen einzelnen Schnittplan (Stange oder Platte).

    Teile können angeklickt werden um sie als gesägt zu markieren.
    """

    teil_clicked = Signal(str)  # Signal: teil_label wurde angeklickt

    def __init__(self, plan: Schnittplan, farb_map: dict[str, QColor],
                 is_1d: bool = False, plan_name: str = ""):
        super().__init__()
        self.plan = plan
        self.farb_map = farb_map
        self.is_1d = is_1d
        self.plan_name = plan_name
        self.marked: set[int] = set()  # Indices der als gesägt markierten Teile
        self._rects: list[QRectF] = []  # Klickbare Bereiche (wird in paintEvent befüllt)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_1d:
            self.setMinimumHeight(80)
            self.setMaximumHeight(80)
        else:
            self.setMinimumHeight(200)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for i, rect in enumerate(self._rects):
                if rect.contains(pos):
                    if i in self.marked:
                        self.marked.discard(i)
                    else:
                        self.marked.add(i)
                    self.update()
                    label = self.plan.platzierungen[i].teil_label
                    self.teil_clicked.emit(label)
                    break
        super().mousePressEvent(event)

    def hasHeightForWidth(self) -> bool:
        return not self.is_1d

    def heightForWidth(self, width: int) -> int:
        if self.is_1d or self.plan.lager_laenge <= 0:
            return 80
        padding = 20
        usable = width - padding
        ratio = self.plan.lager_breite / self.plan.lager_laenge
        return int(usable * ratio + padding)

    def sizeHint(self) -> QSize:
        if self.is_1d:
            return QSize(400, 80)
        w = max(self.width(), 400)
        return QSize(w, self.heightForWidth(w))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.is_1d:
            ideal_h = self.heightForWidth(self.width())
            if self.height() != ideal_h:
                self.setFixedHeight(ideal_h)

    def paintEvent(self, event):
        super().paintEvent(event)
        self._rects = []
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width() - 20
        h = self.height() - 20
        ox, oy = 10, 10

        if not self.is_1d and self.plan.lager_laenge > 0 and self.plan.lager_breite > 0:
            sx = w / self.plan.lager_laenge
            sy = h / self.plan.lager_breite
            scale = min(sx, sy)
            draw_w = self.plan.lager_laenge * scale
            draw_h = self.plan.lager_breite * scale
            ox = 10 + (w - draw_w) / 2
            oy = 10 + (h - draw_h) / 2
            painter.setPen(QPen(Qt.GlobalColor.black, 2))
            painter.drawRect(QRectF(ox, oy, draw_w, draw_h))
            self._draw_2d(painter, ox, oy, draw_w, draw_h)
        elif self.is_1d:
            painter.setPen(QPen(Qt.GlobalColor.black, 2))
            painter.drawRect(QRectF(ox, oy, w, h))
            self._draw_1d(painter, ox, oy, w, h)

        painter.end()

    def _draw_1d(self, painter: QPainter, ox, oy, w, h):
        scale = w / self.plan.lager_laenge if self.plan.lager_laenge > 0 else 1
        font_label = QFont()
        font_label.setPointSize(13)
        font_label.setBold(True)
        font_dim = QFont()
        font_dim.setPointSize(11)

        for i, p in enumerate(self.plan.platzierungen):
            x = ox + p.x * scale
            pw = p.laenge * scale
            rect = QRectF(x, oy + 2, pw, h - 4)
            self._rects.append(rect)
            is_marked = i in self.marked
            farbe = QColor("#888888") if is_marked else self.farb_map.get(p.teil_label, QColor("#CCCCCC"))
            painter.setBrush(farbe)
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(rect)
            painter.setPen(Qt.GlobalColor.black)
            label_text = f"✓ {p.teil_label}" if is_marked else p.teil_label
            label_rect = QRectF(x, oy + 2, pw, h / 2 - 2)
            dim_rect = QRectF(x, oy + h / 2, pw, h / 2 - 2)
            painter.setFont(font_label)
            painter.drawText(label_rect,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             label_text)
            painter.setFont(font_dim)
            painter.drawText(dim_rect,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             f"{p.laenge:.0f}")

    def _draw_2d(self, painter: QPainter, ox, oy, w, h):
        sx = w / self.plan.lager_laenge if self.plan.lager_laenge > 0 else 1
        sy = h / self.plan.lager_breite if self.plan.lager_breite > 0 else 1
        scale = min(sx, sy)

        base_size = max(14, min(26, int(h / 15)))
        font_label = QFont()
        font_label.setPointSize(base_size)
        font_label.setBold(True)
        font_dim = QFont()
        font_dim.setPointSize(max(11, base_size - 3))

        for i, p in enumerate(self.plan.platzierungen):
            x = ox + p.x * scale
            y = oy + p.y * scale
            pw = p.laenge * scale
            ph = p.breite * scale
            rect = QRectF(x, y, pw, ph)
            self._rects.append(rect)
            is_marked = i in self.marked
            farbe = QColor("#888888") if is_marked else self.farb_map.get(p.teil_label, QColor("#CCCCCC"))
            painter.setBrush(farbe)
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(rect)

            painter.setPen(Qt.GlobalColor.black)
            label_text = f"✓ {p.teil_label}" if is_marked else p.teil_label
            dim_text = f"{p.laenge:.0f} x {p.breite:.0f}"
            if p.gedreht:
                dim_text += " ↻"
            label_rect = QRectF(x, y, pw, ph / 2)
            dim_rect = QRectF(x, y + ph / 2, pw, ph / 2)
            painter.setFont(font_label)
            painter.drawText(label_rect,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             label_text)
            painter.setFont(font_dim)
            painter.drawText(dim_rect,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             dim_text)


class OptimierungTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.ergebnis: OptimierungsErgebnis | None = None
        self._lauf_material_id: int | None = None
        self._lauf_projekt_id: int | None = None
        self.is_1d_result: bool = False

        layout = QVBoxLayout(self)

        # Steuerungsbereich
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel(t("opt.project")))
        self.proj_combo = QComboBox()
        self.proj_combo.currentIndexChanged.connect(self._projekt_changed)
        ctrl.addWidget(self.proj_combo)
        ctrl.addWidget(QLabel(t("opt.material")))
        self.mat_combo = QComboBox()
        self.mat_combo.currentIndexChanged.connect(self._clear_result)
        ctrl.addWidget(self.mat_combo)
        ctrl.addWidget(QLabel(t("opt.blade")))
        self.blade_combo = QComboBox()
        ctrl.addWidget(self.blade_combo)
        self.algo_combo = QComboBox()
        self.algo_combo.setMinimumWidth(250)
        self.algo_combo.addItem(t("opt.algo_greedy"), "greedy")
        self.algo_combo.addItem(t("opt.algo_nested"), "nested")
        self.algo_combo.addItem(t("opt.algo_ga"), "ga")
        ctrl.addWidget(self.algo_combo)
        self.btn_run = QPushButton(t("opt.run"))
        self.btn_run.clicked.connect(self._run)
        ctrl.addWidget(self.btn_run)
        self.btn_confirm = QPushButton(t("opt.confirm"))
        self.btn_confirm.clicked.connect(self._confirm)
        self.btn_confirm.setEnabled(False)
        ctrl.addWidget(self.btn_confirm)
        self.btn_preview = QPushButton(t("opt.preview"))
        self.btn_preview.clicked.connect(self._preview_pdf)
        self.btn_preview.setEnabled(False)
        ctrl.addWidget(self.btn_preview)
        self.btn_pdf = QPushButton(t("opt.pdf"))
        self.btn_pdf.clicked.connect(self._export_pdf)
        self.btn_pdf.setEnabled(False)
        ctrl.addWidget(self.btn_pdf)
        layout.addLayout(ctrl)

        # Statistik-Panel
        self.stats_box = QGroupBox(t("stat.title"))
        self.stats_box.setVisible(False)
        stats_grid = QGridLayout(self.stats_box)
        stats_grid.setContentsMargins(8, 8, 8, 8)
        stats_grid.setHorizontalSpacing(16)
        stats_grid.setVerticalSpacing(4)

        self._stat_stock_used = QLabel("0")
        self._stat_parts_placed = QLabel("0")
        self._stat_parts_missing = QLabel("0")
        self._stat_total_waste = QLabel("0")
        self._stat_utilization = QLabel("0")
        self._stat_per_stock = QLabel("")
        self._stat_per_stock.setWordWrap(True)

        for lbl in (self._stat_stock_used, self._stat_parts_placed,
                    self._stat_parts_missing, self._stat_total_waste,
                    self._stat_utilization):
            lbl.setStyleSheet("font-weight: bold;")

        row = 0
        for label_key, value_widget in [
            ("stat.stock_used", self._stat_stock_used),
            ("stat.parts_placed", self._stat_parts_placed),
            ("stat.parts_missing", self._stat_parts_missing),
            ("stat.total_waste", self._stat_total_waste),
            ("stat.utilization", self._stat_utilization),
        ]:
            lbl = QLabel(t(label_key) + ":")
            stats_grid.addWidget(lbl, row, 0)
            stats_grid.addWidget(value_widget, row, 1)
            row += 1

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        stats_grid.addWidget(sep, row, 0, 1, 2)
        row += 1

        stats_grid.addWidget(QLabel(f"<b>{t('stat.per_stock')}:</b>"), row, 0, 1, 2)
        row += 1
        stats_grid.addWidget(self._stat_per_stock, row, 0, 1, 2)

        layout.addWidget(self.stats_box)

        # Scrollbereich für Schnittplan-Grafiken
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_container = QWidget()
        self.result_layout = QVBoxLayout(self.result_container)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.result_container)
        layout.addWidget(scroll)

        self.refresh()

    def refresh(self):
        """Combos aktualisieren – Ergebnis bleibt erhalten."""
        old_pid = self.proj_combo.currentData()
        old_mid = self.mat_combo.currentData()

        self.proj_combo.blockSignals(True)
        self.proj_combo.clear()
        for p in self.db.list_projekte():
            self.proj_combo.addItem(p.name, p.id)
        # Vorherige Auswahl wiederherstellen wenn möglich
        if old_pid is not None:
            idx = self.proj_combo.findData(old_pid)
            if idx >= 0:
                self.proj_combo.setCurrentIndex(idx)
        self.proj_combo.blockSignals(False)

        # Material aktualisieren ohne Ergebnis zu löschen
        self.mat_combo.blockSignals(True)
        self._update_mat_combo()
        if old_mid is not None:
            idx = self.mat_combo.findData(old_mid)
            if idx >= 0:
                self.mat_combo.setCurrentIndex(idx)
        self.mat_combo.blockSignals(False)

        self.blade_combo.clear()
        for s in self.db.list_saegeblaetter():
            self.blade_combo.addItem(f"{s.name} ({s.schnittbreite} mm)", s.id)

    def _projekt_changed(self):
        self._clear_result()
        self._update_mat_combo()

    def _update_mat_combo(self):
        self.mat_combo.clear()
        pid = self.proj_combo.currentData()
        if pid is None:
            return
        projekt = self.db.get_projekt(pid)
        if not projekt:
            return
        seen = set()
        for teil in projekt.teile:
            if teil.material_id not in seen:
                seen.add(teil.material_id)
                mat = self.db.get_material(teil.material_id)
                if mat:
                    typ_display = t("mat.plate") if mat.typ == MaterialTyp.PLATTE else t("mat.bar")
                    self.mat_combo.addItem(f"{mat.name} ({typ_display})", mat.id)

    def _run(self):
        pid = self.proj_combo.currentData()
        mid = self.mat_combo.currentData()
        sid = self.blade_combo.currentData()

        if not all([pid, mid, sid]):
            QMessageBox.warning(self, t("error"), t("dlg.select_all"))
            return

        mat = self.db.get_material(mid)
        if not mat:
            return

        blaetter = self.db.list_saegeblaetter()
        blade = next((s for s in blaetter if s.id == sid), None)
        if not blade:
            return

        projekt = self.db.get_projekt(pid)
        if not projekt:
            return

        teile = [teil for teil in projekt.teile
                 if teil.material_id == mid and teil.offen_anzahl > 0]

        if not teile:
            QMessageBox.information(self, t("hint"),
                                    t("opt.no_parts"))
            return

        lager = self.db.list_lagerstuecke(mid)
        if not lager:
            QMessageBox.warning(self, t("error"),
                                t("opt.no_stock"))
            return

        rand = mat.besaeumung
        algo = self.algo_combo.currentData()
        if mat.typ == MaterialTyp.STANGE:
            vorrat = [StangenVorrat(ls.id, ls.laenge - 2 * rand, ls.stueckzahl)
                      for ls in lager if ls.laenge - 2 * rand > 0]
            teil_list = [(teil.label, teil.laenge, teil.offen_anzahl) for teil in teile]
            opt_fn = optimize_1d_ga if algo == "ga" else optimize_1d
            self.ergebnis = opt_fn(teil_list, vorrat, blade.schnittbreite)
        else:
            vorrat = [PlattenVorrat(ls.id, ls.laenge - 2 * rand,
                                    ls.breite - 2 * rand, ls.stueckzahl)
                      for ls in lager
                      if ls.laenge - 2 * rand > 0 and ls.breite - 2 * rand > 0]
            teil_list = [(teil.label, teil.laenge, teil.breite, teil.offen_anzahl) for teil in teile]
            teil_dreh = {teil.label: drehung_fuer_teil(mat.maserung, teil.maserung)
                         for teil in teile}
            if algo == "ga":
                opt_fn = optimize_2d_ga
            elif algo == "nested":
                opt_fn = optimize_2d_nested
            else:
                opt_fn = optimize_2d
            self.ergebnis = opt_fn(
                teil_list, vorrat, blade.schnittbreite,
                teil_drehung=teil_dreh)

        self._lauf_material_id = mid
        self._lauf_projekt_id = pid
        self.is_1d_result = mat.typ == MaterialTyp.STANGE
        self._show_result(self.is_1d_result)

    def _clear_result(self):
        """Ergebnis zurücksetzen (bei Projekt/Material-Wechsel)."""
        self.ergebnis = None
        while self.result_layout.count():
            child = self.result_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.stats_box.setVisible(False)
        self.btn_confirm.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.btn_pdf.setEnabled(False)

    def _show_result(self, is_1d: bool):
        while self.result_layout.count():
            child = self.result_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        erg = self.ergebnis
        if not erg:
            return

        # Statistik-Panel befüllen
        n_plaene = len(erg.schnittplaene)
        n_teile = sum(len(p.platzierungen) for p in erg.schnittplaene)
        n_fehlend = len(erg.fehlende_teile)
        gesamt_verschnitt_abs = sum(p.verschnitt_mm for p in erg.schnittplaene)
        nutzung = 100.0 - erg.gesamt_verschnitt_prozent

        self._stat_stock_used.setText(str(n_plaene))
        self._stat_parts_placed.setText(str(n_teile))

        if n_fehlend > 0:
            self._stat_parts_missing.setText(
                f"{n_fehlend}  ({', '.join(erg.fehlende_teile)})")
            self._stat_parts_missing.setStyleSheet(
                "font-weight: bold; color: red;")
        else:
            self._stat_parts_missing.setText("0")
            self._stat_parts_missing.setStyleSheet("font-weight: bold;")

        einheit = "mm" if is_1d else "mm²"
        self._stat_total_waste.setText(
            f"{erg.gesamt_verschnitt_prozent:.1f}%  ({gesamt_verschnitt_abs:.0f} {einheit})")
        self._stat_utilization.setText(f"{nutzung:.1f}%")

        # Pro Lagerstück
        zeilen = []
        typ_label = t("mat.bar") if is_1d else t("mat.plate")
        for idx, plan in enumerate(erg.schnittplaene):
            buchstabe = chr(65 + idx) if idx < 26 else str(idx + 1)
            n_teile_plan = len(plan.platzierungen)
            if plan.lager_breite > 0:
                masse = f"{plan.lager_laenge:.0f} x {plan.lager_breite:.0f} mm"
            else:
                masse = f"{plan.lager_laenge:.0f} mm"
            zeilen.append(
                f"{typ_label} {buchstabe}  {masse}  –  "
                f"{100 - plan.verschnitt_prozent:.1f}% {t('stat.utilization').lower()}  "
                f"({plan.verschnitt_prozent:.1f}% {t('stat.total_waste').lower()})  –  "
                f"{n_teile_plan} {t('stat.parts_placed').lower()}"
            )
        self._stat_per_stock.setText("\n".join(zeilen))
        self.stats_box.setVisible(True)

        # Farb-Zuordnung
        labels = sorted({p.teil_label for sp in erg.schnittplaene
                         for p in sp.platzierungen})
        farb_map = {label: FARBEN[i % len(FARBEN)] for i, label in enumerate(labels)}

        typ_label = t("mat.bar") if is_1d else t("mat.plate")
        for i, plan in enumerate(erg.schnittplaene):
            buchstabe = chr(65 + i) if i < 26 else str(i + 1)
            plan_name = f"{typ_label} {buchstabe}"
            label = QLabel(
                f"<b>{plan_name}</b> – "
                f"{plan.lager_laenge:.0f}"
                f"{'×' + f'{plan.lager_breite:.0f}' if plan.lager_breite > 0 else ''} mm"
                f"  ({t('stat.total_waste')}: {plan.verschnitt_prozent:.1f}%)"
            )
            label.setStyleSheet("padding: 4px 0;")
            self.result_layout.addWidget(label)
            widget = SchnittplanWidget(plan, farb_map, is_1d,
                                       plan_name=plan_name)
            widget.teil_clicked.connect(self._on_teil_cut)
            self.result_layout.addWidget(widget)

        self.btn_confirm.setEnabled(bool(erg.schnittplaene))
        self.btn_preview.setEnabled(bool(erg.schnittplaene))
        self.btn_pdf.setEnabled(bool(erg.schnittplaene))

    def _on_teil_cut(self, label: str):
        """Wird aufgerufen wenn ein Teil in der Grafik angeklickt wird.

        1) gesaegt_anzahl im Projekt aktualisieren
        2) Lager live anpassen: Stange/Platte verbrauchen, tatsächlichen
           Rest berechnen und einbuchen. Bei Abwahl: rückgängig machen.
        """
        if not self._lauf_projekt_id:
            return
        projekt = self.db.get_projekt(self._lauf_projekt_id)
        if not projekt:
            return
        mat = self.db.get_material(self._lauf_material_id)
        if not mat:
            return

        # 1) gesaegt_anzahl aktualisieren
        marked_count = 0
        for i in range(self.result_layout.count()):
            w = self.result_layout.itemAt(i).widget()
            if isinstance(w, SchnittplanWidget):
                for j, p in enumerate(w.plan.platzierungen):
                    if p.teil_label == label and j in w.marked:
                        marked_count += 1

        for teil in projekt.teile:
            if teil.label == label and teil.material_id == self._lauf_material_id:
                teil.gesaegt_anzahl = min(marked_count, teil.stueckzahl)
                self.db.save_teil(teil)
                break

        # Kerf bestimmen
        sid = self.blade_combo.currentData()
        blaetter = self.db.list_saegeblaetter()
        blade = next((s for s in blaetter if s.id == sid), None)
        kerf = blade.schnittbreite if blade else 3.0

        # 2) Lager pro Schnittplan-Widget aktualisieren
        for i in range(self.result_layout.count()):
            w = self.result_layout.itemAt(i).widget()
            if not isinstance(w, SchnittplanWidget):
                continue

            has_marks = len(w.marked) > 0
            was_consumed = getattr(w, '_stock_consumed', False)
            old_rest_id = getattr(w, '_rest_id', None)

            if has_marks:
                # Tatsächlichen Rest berechnen aus markierten Teilen
                marked_parts = [w.plan.platzierungen[j] for j in w.marked]
                if self.is_1d_result:
                    used = sum(p.laenge for p in marked_parts)
                    cuts = len(marked_parts)
                    rest_val = w.plan.lager_laenge - used - kerf * cuts
                    rest_tuple = (max(0, rest_val),)
                else:
                    # 2D: Plan-Reste verwenden (Guillotine-Schnitte)
                    rest_tuple = None  # wird unten behandelt

                if not was_consumed:
                    # Erste Markierung: Stange/Platte verbrauchen
                    self.db.lager_verbrauchen(w.plan.lagerstueck_id)
                    w._stock_consumed = True

                # Alten Rest entfernen falls vorhanden
                if old_rest_id is not None:
                    self.db.delete_lagerstueck(old_rest_id)
                    w._rest_id = None

                # Neuen Rest einbuchen
                if self.is_1d_result and rest_tuple and rest_tuple[0] > 0:
                    r = self.db.rest_einbuchen(mat.id, rest_tuple[0])
                    if r:
                        w._rest_id = r.id
                elif not self.is_1d_result:
                    # 2D: nur wenn ALLE Teile markiert, Plan-Reste einbuchen
                    if len(w.marked) == len(w.plan.platzierungen):
                        for rest in w.plan.reste:
                            r = self.db.rest_einbuchen(mat.id, rest[0], rest[1])
                            # Nur letzten merken (vereinfacht)

            elif not has_marks and was_consumed:
                # Alle Markierungen entfernt: rückgängig machen
                if old_rest_id is not None:
                    self.db.delete_lagerstueck(old_rest_id)
                    w._rest_id = None
                # Stange/Platte zurückbuchen – bestehenden Eintrag suchen
                existing = [ls for ls in self.db.list_lagerstuecke(self._lauf_material_id)
                            if abs(ls.laenge - w.plan.lager_laenge) < 0.1
                            and abs(ls.breite - w.plan.lager_breite) < 0.1]
                if existing:
                    existing[0].stueckzahl += 1
                    self.db.save_lagerstueck(existing[0])
                else:
                    from core.models import Lagerstueck
                    ls = Lagerstueck(
                        material_id=self._lauf_material_id,
                        laenge=w.plan.lager_laenge,
                        breite=w.plan.lager_breite,
                        stueckzahl=1)
                    self.db.save_lagerstueck(ls)
                w._stock_consumed = False

    def _confirm(self):
        """Alle Teile auf einmal als gesägt markieren + Lager anpassen."""
        if not self.ergebnis or not self._lauf_projekt_id:
            return

        reply = QMessageBox.question(
            self, t("btn.confirm"),
            t("opt.confirm_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        mat = self.db.get_material(self._lauf_material_id)
        if not mat:
            return

        # Lagerstücke verbrauchen und Reste einbuchen
        for i_layout in range(self.result_layout.count()):
            w = self.result_layout.itemAt(i_layout).widget()
            if not isinstance(w, SchnittplanWidget):
                continue
            plan = w.plan

            # Alten Einzel-Rest entfernen falls vorhanden
            old_rest_id = getattr(w, '_rest_id', None)
            if old_rest_id is not None:
                self.db.delete_lagerstueck(old_rest_id)

            # Lagerstück verbrauchen falls noch nicht geschehen
            if not getattr(w, '_stock_consumed', False):
                self.db.lager_verbrauchen(plan.lagerstueck_id)

            # Plan-Reste einbuchen (die korrekten Reste nach ALLEN Teilen)
            for rest in plan.reste:
                if mat.typ == MaterialTyp.STANGE:
                    self.db.rest_einbuchen(mat.id, rest[0])
                else:
                    self.db.rest_einbuchen(mat.id, rest[0], rest[1])

        projekt = self.db.get_projekt(self._lauf_projekt_id)
        if projekt:
            for teil in projekt.teile:
                if teil.material_id == self._lauf_material_id:
                    teil.gesaegt_anzahl = teil.stueckzahl
                    self.db.save_teil(teil)

        QMessageBox.information(self, t("done"), t("opt.done"))
        self.btn_confirm.setEnabled(False)
        self.ergebnis = None

    def _preview_pdf(self):
        if not self.ergebnis:
            return

        import tempfile
        import subprocess
        import sys

        mat = self.db.get_material(self._lauf_material_id)
        mat_name = mat.name if mat else ""
        proj_name = self.proj_combo.currentText()
        blade_name = self.blade_combo.currentText()
        is_1d = mat.typ == MaterialTyp.STANGE if mat else False

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_path = tmp.name
        tmp.close()

        from core.pdf import export_pdf
        export_pdf(self.ergebnis, tmp_path, proj_name, mat_name, blade_name, is_1d)

        if sys.platform == "darwin":
            subprocess.run(["open", tmp_path])
        elif sys.platform == "win32":
            import os
            os.startfile(tmp_path)
        else:
            subprocess.run(["xdg-open", tmp_path])

    def _export_pdf(self):
        if not self.ergebnis:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "PDF speichern", "schnittplan.pdf", "PDF (*.pdf)")
        if not path:
            return

        mat = self.db.get_material(self._lauf_material_id)
        mat_name = mat.name if mat else ""
        proj_name = self.proj_combo.currentText()
        blade_name = self.blade_combo.currentText()
        is_1d = mat.typ == MaterialTyp.STANGE if mat else False

        from core.pdf import export_pdf
        export_pdf(self.ergebnis, path, proj_name, mat_name, blade_name, is_1d)
        QMessageBox.information(self, t("opt.pdf"),
                                f"PDF: {path}")
