"""PDF-Export der Schnittpläne mit reportlab.

Kompaktes Layout:
  - Seite 1: Stückliste + ggf. erste Schnittplane
  - Platten: so viele wie möglich pro Seite (proportional skaliert)
  - Stangen: 2 Spalten, ~5 pro Spalte = ~10 pro Seite
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.optimize import OptimierungsErgebnis, Schnittplan

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 15 * mm
USABLE_W = PAGE_W - 2 * MARGIN
USABLE_H = PAGE_H - 2 * MARGIN

FARBEN = [
    colors.HexColor("#4CAF50"), colors.HexColor("#2196F3"),
    colors.HexColor("#FF9800"), colors.HexColor("#9C27B0"),
    colors.HexColor("#F44336"), colors.HexColor("#00BCD4"),
    colors.HexColor("#8BC34A"), colors.HexColor("#FF5722"),
    colors.HexColor("#3F51B5"), colors.HexColor("#CDDC39"),
    colors.HexColor("#E91E63"), colors.HexColor("#009688"),
]


class _PageCursor:
    """Verwaltet die aktuelle Y-Position und Seitenumbrüche."""

    def __init__(self, c: canvas.Canvas):
        self.c = c
        self.y = PAGE_H - MARGIN

    def need(self, height: float):
        if self.y - height < MARGIN:
            self.c.showPage()
            self.y = PAGE_H - MARGIN

    def advance(self, height: float):
        self.y -= height


def export_pdf(
    ergebnis: OptimierungsErgebnis,
    path: str | Path,
    projekt_name: str = "",
    material_name: str = "",
    saegeblatt_name: str = "",
    is_1d: bool = False,
):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    c.setTitle(f"CutStock – {projekt_name}")

    labels = sorted({p.teil_label for sp in ergebnis.schnittplaene
                     for p in sp.platzierungen})
    farb_map = {label: FARBEN[i % len(FARBEN)] for i, label in enumerate(labels)}

    cur = _PageCursor(c)
    _draw_header(c, cur, ergebnis, projekt_name, material_name, saegeblatt_name)
    _draw_stueckliste(c, cur, ergebnis, farb_map)

    cur.advance(10)

    if is_1d:
        _draw_1d_plans(c, cur, ergebnis.schnittplaene, farb_map)
    else:
        _draw_2d_plans(c, cur, ergebnis.schnittplaene, farb_map)

    c.save()


def _draw_header(c: canvas.Canvas, cur: _PageCursor,
                 erg: OptimierungsErgebnis,
                 projekt: str, material: str, blade: str):
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, cur.y, "CutStock – Schnittplan")
    cur.advance(20)

    c.setFont("Helvetica", 10)
    info = (f"Projekt: {projekt}   |   Material: {material}   |   "
            f"Sägeblatt: {blade}   |   "
            f"Lagerstücke: {len(erg.schnittplaene)}   |   "
            f"Verschnitt: {erg.gesamt_verschnitt_prozent:.1f}%")
    c.drawString(MARGIN, cur.y, info)
    cur.advance(14)

    if erg.fehlende_teile:
        c.setFillColor(colors.red)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGIN, cur.y, f"FEHLEND: {', '.join(erg.fehlende_teile)}")
        c.setFillColor(colors.black)
        cur.advance(14)

    c.setStrokeColor(colors.grey)
    c.line(MARGIN, cur.y, PAGE_W - MARGIN, cur.y)
    cur.advance(8)


def _draw_stueckliste(c: canvas.Canvas, cur: _PageCursor,
                      erg: OptimierungsErgebnis, farb_map: dict):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN, cur.y, "#")
    c.drawString(MARGIN + 20, cur.y, "Label")
    c.drawString(MARGIN + 160, cur.y, "Länge")
    c.drawString(MARGIN + 220, cur.y, "Breite")
    c.drawString(MARGIN + 280, cur.y, "Lager")
    cur.advance(12)

    c.setFont("Helvetica", 9)
    nr = 1
    for plan in erg.schnittplaene:
        for p in plan.platzierungen:
            cur.need(14)
            farbe = farb_map.get(p.teil_label, colors.grey)
            c.setFillColor(farbe)
            c.rect(MARGIN, cur.y - 2, 10, 10, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.drawString(MARGIN + 13, cur.y, str(nr))
            c.drawString(MARGIN + 20, cur.y, p.teil_label)
            c.drawString(MARGIN + 160, cur.y, f"{p.laenge:.1f}")
            if p.breite > 0:
                c.drawString(MARGIN + 220, cur.y, f"{p.breite:.1f}")
            c.drawString(MARGIN + 280, cur.y, f"#{plan.lagerstueck_id}")
            cur.advance(13)
            nr += 1


# =====================================================================
# 2D Platten – so viele wie möglich pro Seite
# =====================================================================

def _draw_2d_plans(c: canvas.Canvas, cur: _PageCursor,
                   plaene: list[Schnittplan], farb_map: dict):
    gap = 8
    for plan in plaene:
        ratio = plan.lager_breite / plan.lager_laenge if plan.lager_laenge > 0 else 0.5
        draw_w = USABLE_W
        draw_h = draw_w * ratio
        # Wenn zu hoch, auf verfügbare Höhe begrenzen
        max_h = USABLE_H * 0.45
        if draw_h > max_h:
            draw_h = max_h
            draw_w = draw_h / ratio

        total_h = draw_h + 18  # 18 für Titel
        cur.need(total_h + gap)

        # Titel
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, cur.y,
                     f"Lagerstück #{plan.lagerstueck_id} – "
                     f"{plan.lager_laenge:.0f} x {plan.lager_breite:.0f} mm  "
                     f"(Verschnitt: {plan.verschnitt_prozent:.1f}%)")
        cur.advance(14)

        _draw_2d_rect(c, plan, farb_map, MARGIN, cur.y - draw_h, draw_w, draw_h)
        cur.advance(draw_h + gap)


def _draw_2d_rect(c: canvas.Canvas, plan: Schnittplan, farb_map: dict,
                  ox: float, oy: float, w: float, h: float):
    sx = w / plan.lager_laenge if plan.lager_laenge > 0 else 1
    sy = h / plan.lager_breite if plan.lager_breite > 0 else 1
    scale = min(sx, sy)

    pw = plan.lager_laenge * scale
    ph = plan.lager_breite * scale

    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.rect(ox, oy, pw, ph, fill=0)

    font_size = max(6, min(10, int(ph / 20)))

    for p in plan.platzierungen:
        x = ox + p.x * scale
        y = oy + ph - (p.y + p.breite) * scale
        rw = p.laenge * scale
        rh = p.breite * scale

        farbe = farb_map.get(p.teil_label, colors.grey)
        c.setFillColor(farbe)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.3)
        c.rect(x, y, rw, rh, fill=1, stroke=1)

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", font_size)
        c.drawCentredString(x + rw / 2, y + rh / 2 + font_size * 0.3,
                            p.teil_label)
        c.setFont("Helvetica", max(5, font_size - 2))
        dim = f"{p.laenge:.0f}x{p.breite:.0f}"
        if p.gedreht:
            dim += " ↻"
        c.drawCentredString(x + rw / 2, y + rh / 2 - font_size * 0.7, dim)


# =====================================================================
# 1D Stangen – 2 Spalten, ~5 pro Spalte
# =====================================================================

def _draw_1d_plans(c: canvas.Canvas, cur: _PageCursor,
                   plaene: list[Schnittplan], farb_map: dict):
    col_w = (USABLE_W - 10) / 2  # 10 = gap zwischen Spalten
    bar_h = 30
    row_h = bar_h + 20  # Platz für Titel + Balken
    col = 0  # 0 = links, 1 = rechts
    row_start_y = cur.y

    for plan in plaene:
        if col == 0:
            cur.need(row_h)
            row_start_y = cur.y

        ox = MARGIN + col * (col_w + 10)
        top_y = row_start_y

        # Titel
        c.setFont("Helvetica-Bold", 8)
        c.drawString(ox, top_y,
                     f"#{plan.lagerstueck_id} – {plan.lager_laenge:.0f} mm  "
                     f"({plan.verschnitt_prozent:.1f}%)")

        bar_y = top_y - 14 - bar_h
        scale = col_w / plan.lager_laenge if plan.lager_laenge > 0 else 1

        c.setStrokeColor(colors.black)
        c.setLineWidth(0.8)
        c.rect(ox, bar_y, plan.lager_laenge * scale, bar_h, fill=0)

        c.setFont("Helvetica", 7)
        for p in plan.platzierungen:
            x = ox + p.x * scale
            w = p.laenge * scale
            farbe = farb_map.get(p.teil_label, colors.grey)
            c.setFillColor(farbe)
            c.setStrokeColor(colors.black)
            c.setLineWidth(0.3)
            c.rect(x, bar_y + 1, w, bar_h - 2, fill=1, stroke=1)

            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(x + w / 2, bar_y + bar_h / 2 + 2, p.teil_label)
            c.setFont("Helvetica", 6)
            c.drawCentredString(x + w / 2, bar_y + bar_h / 2 - 8,
                                f"{p.laenge:.0f}")

        if col == 1:
            cur.y = row_start_y
            cur.advance(row_h)
            col = 0
        else:
            col = 1

    if col == 1:
        cur.y = row_start_y
        cur.advance(row_h)
