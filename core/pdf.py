"""PDF-Export der Schnittpläne mit reportlab.

Kompaktes Layout:
  - Seite 1: Teileliste (je Teil eine Zeile mit Anzahl) + Materialbedarf
  - Gleiche Schnittmuster werden zusammengefasst ("10 × Stange 2000 mm"),
    Stücke mit Defekt bleiben einzeln, weil es auf das konkrete Stück ankommt
  - Platten: so viele wie möglich pro Seite (proportional skaliert)
  - Stangen: volle Seitenbreite, darunter die Schnittliste des Musters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
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


@dataclass
class _Muster:
    """Ein Schnittmuster und wie oft es geschnitten wird."""
    plan: Schnittplan
    anzahl: int = 1
    folge: list[str] = field(default_factory=list)


def _fmt(v: float) -> str:
    """Maß ohne überflüssige Nachkommastelle: 2000, 375.5."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _latin1(txt: str) -> str:
    # Helvetica (Latin-1) has no "→" – substitute it, and defensively
    # replace any other non-Latin-1 char
    return txt.replace("→", "»").encode("latin-1", "replace").decode("latin-1")


def _fit_size(text: str, font: str, size: float, min_size: float,
              max_w: float) -> float | None:
    """Größte Schriftgröße ≤ size, bei der text in max_w passt (sonst None)."""
    while size >= min_size:
        if stringWidth(text, font, size) <= max_w:
            return size
        size -= 0.5
    return None


def _muster_bilden(plaene: list[Schnittplan], folgen: list[list[str]],
                   is_1d: bool) -> list[_Muster]:
    """Identische Schnittpläne zusammenfassen (Reihenfolge des ersten Auftretens)."""
    muster: list[_Muster] = []
    nach_key: dict[tuple, _Muster] = {}
    for i, plan in enumerate(plaene):
        folge = folgen[i] if i < len(folgen) else []
        if plan.defekte:
            # Stück mit Defekt ist nicht austauschbar – einzeln aufführen
            muster.append(_Muster(plan, 1, folge))
            continue
        if is_1d:
            teile = tuple(sorted((p.teil_label, round(p.laenge, 1))
                                 for p in plan.platzierungen))
        else:
            teile = tuple((p.teil_label, round(p.laenge, 1), round(p.breite, 1),
                           round(p.x, 1), round(p.y, 1), p.gedreht)
                          for p in plan.platzierungen)
        key = (round(plan.lager_laenge, 1), round(plan.lager_breite, 1),
               teile, tuple(folge))
        if key in nach_key:
            nach_key[key].anzahl += 1
        else:
            m = _Muster(plan, 1, folge)
            nach_key[key] = m
            muster.append(m)
    return muster


def _muster_titel(m: _Muster, art: str) -> str:
    plan = m.plan
    mass = _fmt(plan.lager_laenge)
    if plan.lager_breite > 0:
        mass += f" x {_fmt(plan.lager_breite)}"
    if plan.defekte:
        nr = f" #{plan.stueck_nr}" if plan.stueck_nr else ""
        return f"{art}{nr} – {mass} mm (mit Defekt)"
    return f"{m.anzahl} × {art} {mass} mm"


def export_pdf(
    ergebnis: OptimierungsErgebnis,
    path: str | Path,
    projekt_name: str = "",
    material_name: str = "",
    saegeblatt_name: str = "",
    is_1d: bool = False,
    schnittfolgen: list[list[str]] | None = None,
    schnittfolge_titel: str = "Schnittfolge",
):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    c.setTitle(f"CutStock – {projekt_name}")

    labels = sorted({p.teil_label for sp in ergebnis.schnittplaene
                     for p in sp.platzierungen})
    farb_map = {label: FARBEN[i % len(FARBEN)] for i, label in enumerate(labels)}

    cur = _PageCursor(c)
    _draw_header(c, cur, ergebnis, projekt_name, material_name, saegeblatt_name)
    _draw_stueckliste(c, cur, ergebnis, farb_map, is_1d)

    cur.advance(10)

    muster = _muster_bilden(ergebnis.schnittplaene, schnittfolgen or [], is_1d)
    if is_1d:
        _draw_1d_plans(c, cur, muster, farb_map)
    else:
        _draw_2d_plans(c, cur, muster, farb_map, schnittfolge_titel)

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
    cur.advance(14)


def _draw_stueckliste(c: canvas.Canvas, cur: _PageCursor,
                      erg: OptimierungsErgebnis, farb_map: dict, is_1d: bool):
    # Je Teil (Label + Maß) eine Zeile mit der Anzahl
    teile: dict[tuple[str, float, float], int] = {}
    for plan in erg.schnittplaene:
        for p in plan.platzierungen:
            key = (p.teil_label, round(p.laenge, 1), round(p.breite, 1))
            teile[key] = teile.get(key, 0) + 1

    # Spaltenbreiten nach dem längsten Label, Zahlen rechtsbündig
    label_w = max([stringWidth("Teil", "Helvetica-Bold", 9)]
                  + [stringWidth(k[0], "Helvetica", 9) for k in teile])
    x_label = MARGIN + 14
    x_laenge = x_label + label_w + 50
    x_breite = x_laenge + 60
    x_anzahl = (x_laenge if is_1d else x_breite) + 60

    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_label, cur.y, "Teil")
    c.drawRightString(x_laenge, cur.y, "Länge")
    if not is_1d:
        c.drawRightString(x_breite, cur.y, "Breite")
    c.drawRightString(x_anzahl, cur.y, "Anzahl")
    cur.advance(13)

    c.setFont("Helvetica", 9)
    for (label, laenge, breite), anzahl in sorted(teile.items()):
        cur.need(13)
        c.setFillColor(farb_map.get(label, colors.grey))
        c.rect(MARGIN, cur.y - 2, 10, 10, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.drawString(x_label, cur.y, label)
        c.drawRightString(x_laenge, cur.y, _fmt(laenge))
        if not is_1d:
            c.drawRightString(x_breite, cur.y, _fmt(breite))
        c.drawRightString(x_anzahl, cur.y, str(anzahl))
        cur.advance(13)

    # Materialbedarf: Lagerstücke nach Maß zusammengefasst
    bedarf: dict[tuple[float, float], int] = {}
    for plan in erg.schnittplaene:
        key = (plan.lager_laenge, plan.lager_breite)
        bedarf[key] = bedarf.get(key, 0) + 1
    teile_txt = ",   ".join(
        f"{n} × {_fmt(l)}{' x ' + _fmt(b) if b > 0 else ''} mm"
        for (l, b), n in sorted(bedarf.items(), reverse=True))
    cur.advance(4)
    cur.need(13)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN, cur.y, "Materialbedarf:")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN + stringWidth("Materialbedarf: ", "Helvetica-Bold", 9),
                 cur.y, teile_txt)
    cur.advance(13)


# =====================================================================
# 2D Platten – so viele wie möglich pro Seite
# =====================================================================

def _draw_2d_plans(c: canvas.Canvas, cur: _PageCursor,
                   muster: list[_Muster], farb_map: dict,
                   schnittfolge_titel: str = "Schnittfolge"):
    gap = 8
    for m in muster:
        plan = m.plan
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
        titel = _muster_titel(m, "Platte")
        c.drawString(MARGIN, cur.y, titel)
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN + stringWidth(titel + "   ", "Helvetica-Bold", 9),
                     cur.y, f"Verschnitt: {plan.verschnitt_prozent:.1f}%")
        cur.advance(14)

        _draw_2d_rect(c, plan, farb_map, MARGIN, cur.y - draw_h, draw_w, draw_h)
        cur.advance(draw_h + gap)

        # Cutting sequence (numbered steps) in 2 columns below the plan;
        # steps come pre-formatted from the frontend so PDF and web UI
        # always show the identical decomposition
        steps = m.folge
        if steps:
            cur.need(12)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(MARGIN, cur.y, schnittfolge_titel + ":")
            cur.advance(11)
            c.setFont("Helvetica", 7.5)
            col_w = USABLE_W / 2
            half = (len(steps) + 1) // 2
            rows = half
            for r in range(rows):
                cur.need(10)
                for col in range(2):
                    i = r + col * half
                    if i < len(steps):
                        c.drawString(MARGIN + col * col_w, cur.y,
                                     f"{i + 1}. {_latin1(steps[i])}")
                cur.advance(9.5)
            cur.advance(gap)


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

        # Beschriftung nur, wenn sie ins Teil passt (sonst schrumpfen/weglassen)
        c.setFillColor(colors.black)
        dim = f"{p.laenge:.0f}x{p.breite:.0f}"
        if p.gedreht:
            dim += " ↻"
        lbl_size = _fit_size(p.teil_label, "Helvetica-Bold", font_size, 5, rw - 2)
        dim_size = _fit_size(dim, "Helvetica", max(5, font_size - 2), 5, rw - 2)
        if lbl_size and dim_size and rh >= lbl_size + dim_size + 2:
            c.setFont("Helvetica-Bold", lbl_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 + lbl_size * 0.3,
                                p.teil_label)
            c.setFont("Helvetica", dim_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 - lbl_size * 0.7, dim)
        elif lbl_size and rh >= lbl_size + 1:
            c.setFont("Helvetica-Bold", lbl_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 - lbl_size * 0.35,
                                p.teil_label)
        elif dim_size and rh >= dim_size + 1:
            c.setFont("Helvetica", dim_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 - dim_size * 0.35, dim)


# =====================================================================
# 1D Stangen – volle Breite, ein Block je Schnittmuster
# =====================================================================

def _schnittliste_zeilen(plan: Schnittplan, max_w: float) -> list[str]:
    """'2 × Label (375.5 mm)   ·   …   ·   Rest 19 mm', auf max_w umbrochen."""
    anzahl: dict[tuple[str, float], int] = {}
    for p in plan.platzierungen:
        key = (p.teil_label, round(p.laenge, 1))
        anzahl[key] = anzahl.get(key, 0) + 1
    teile = [f"{n} × {label} ({_fmt(laenge)} mm)"
             for (label, laenge), n in anzahl.items()]
    rest = sum(r[0] for r in plan.reste if r)
    if rest > 0:
        teile.append(f"Rest {_fmt(rest)} mm")

    sep = "   ·   "
    zeilen: list[str] = []
    zeile = ""
    for t in teile:
        kandidat = zeile + sep + t if zeile else t
        if zeile and stringWidth(kandidat, "Helvetica", 8) > max_w:
            zeilen.append(zeile)
            zeile = t
        else:
            zeile = kandidat
    if zeile:
        zeilen.append(zeile)
    return zeilen


def _draw_1d_plans(c: canvas.Canvas, cur: _PageCursor,
                   muster: list[_Muster], farb_map: dict):
    bar_w = USABLE_W
    bar_h = 26
    zeile_h = 10
    gap = 14

    for m in muster:
        plan = m.plan
        zeilen = _schnittliste_zeilen(plan, bar_w)
        cur.need(6 + bar_h + 4 + len(zeilen) * zeile_h)

        # Titel: "10 × Stange 2000 mm   Verschnitt: 1.0%"
        titel = _muster_titel(m, "Stange")
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, cur.y, titel)
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN + stringWidth(titel + "   ", "Helvetica-Bold", 9),
                     cur.y, f"Verschnitt: {plan.verschnitt_prozent:.1f}%")

        ox = MARGIN
        bar_y = cur.y - 6 - bar_h
        scale = bar_w / plan.lager_laenge if plan.lager_laenge > 0 else 1

        c.setStrokeColor(colors.black)
        c.setLineWidth(0.8)
        c.rect(ox, bar_y, plan.lager_laenge * scale, bar_h, fill=0)

        for p in plan.platzierungen:
            x = ox + p.x * scale
            w = p.laenge * scale
            farbe = farb_map.get(p.teil_label, colors.grey)
            c.setFillColor(farbe)
            c.setStrokeColor(colors.black)
            c.setLineWidth(0.3)
            c.rect(x, bar_y + 1, w, bar_h - 2, fill=1, stroke=1)

            # Label + Länge, wenn sie ins Teil passen; sonst nur die Länge
            c.setFillColor(colors.black)
            mitte = bar_y + bar_h / 2
            laenge_txt = _fmt(p.laenge)
            lbl_size = _fit_size(p.teil_label, "Helvetica-Bold", 7.5, 5, w - 3)
            len_size = _fit_size(laenge_txt, "Helvetica", 7, 5, w - 2)
            if lbl_size and len_size:
                c.setFont("Helvetica-Bold", lbl_size)
                c.drawCentredString(x + w / 2, mitte + 2, p.teil_label)
                c.setFont("Helvetica", len_size)
                c.drawCentredString(x + w / 2, mitte - 8, laenge_txt)
            elif len_size:
                c.setFont("Helvetica", len_size)
                c.drawCentredString(x + w / 2, mitte - len_size * 0.35, laenge_txt)

        # Defekte rot schraffiert (werden als Abfall herausgeschnitten)
        for d in plan.defekte:
            x = ox + d.position * scale
            w = d.laenge * scale
            c.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.2))
            c.setStrokeColor(colors.Color(0.8, 0.1, 0.1))
            c.setLineWidth(0.5)
            c.rect(x, bar_y, w, bar_h, fill=1, stroke=1)
            p_clip = c.beginPath()
            p_clip.rect(x, bar_y, w, bar_h)
            c.saveState()
            c.clipPath(p_clip, stroke=0, fill=0)
            step = 4
            i = -bar_h
            while i < w:
                c.line(x + i, bar_y, x + i + bar_h, bar_y + bar_h)
                i += step
            c.restoreState()

        # Schnittliste unter dem Balken
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 8)
        cur.y = bar_y - 4 - 8
        for z in zeilen:
            c.drawString(MARGIN, cur.y, z)
            cur.advance(zeile_h)
        cur.advance(gap)
