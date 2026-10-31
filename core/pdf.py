"""PDF-Export der Schnittpläne mit reportlab.

Kompaktes Layout:
  - Seite 1: Teileliste (je Teil eine Zeile mit Anzahl) + Materialbedarf
    (Stück-Codes wie auf den Etiketten, Lagerort, Materialname und -bild)
  - Gleiche Schnittmuster werden zusammengefasst ("10 × Stange 2000 mm"),
    Stücke mit Defekt bleiben einzeln, weil es auf das konkrete Stück ankommt
  - Platten: so viele wie möglich pro Seite (proportional skaliert)
  - Stangen: volle Seitenbreite, darunter die Schnittliste des Musters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
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
    codes: list[str] = field(default_factory=list)   # Stück-Codes aller Exemplare


def _fmt(v: float) -> str:
    """Maß ohne überflüssige Nachkommastelle: 2000, 375.5."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _latin1(txt: str) -> str:
    # Helvetica (Latin-1) has no "→" – substitute it, and defensively
    # replace any other non-Latin-1 char
    return txt.replace("→", "»").encode("latin-1", "replace").decode("latin-1")


def _schraffur(c: canvas.Canvas, x: float, y: float, w: float, h: float):
    """Füllteile schraffiert, wie in der App."""
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.saveState()
    c.clipPath(p, stroke=0, fill=0)
    c.setStrokeColor(colors.Color(1, 1, 1, alpha=0.6))
    c.setLineWidth(0.6)
    i = -h
    while i < w:
        c.line(x + i, y, x + i + h, y + h)
        i += 5
    c.restoreState()


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
            muster.append(_Muster(plan, 1, folge, [plan.stueck_code] if plan.stueck_code else []))
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
            if plan.stueck_code:
                nach_key[key].codes.append(plan.stueck_code)
        else:
            m = _Muster(plan, 1, folge, [plan.stueck_code] if plan.stueck_code else [])
            nach_key[key] = m
            muster.append(m)
    return muster


def _muster_titel(m: _Muster, art: str) -> str:
    plan = m.plan
    mass = _fmt(plan.lager_laenge)
    if plan.lager_breite > 0:
        mass += f" x {_fmt(plan.lager_breite)}"
    codes = _codes_text(m.codes)
    if plan.defekte:
        nr = f" {codes}" if codes else ""
        return f"{art}{nr} – {mass} mm (mit Defekt)"
    return f"{m.anzahl} × {art} {mass} mm" + (f" – {codes}" if codes else "")


def _codes_text(codes: list[str], max_n: int = 8) -> str:
    """Stück-Codes kompakt: "AP4040-01, -02, -05" (gleiches Kürzel nur einmal)."""
    if not codes:
        return ""
    teile, letztes = [], None
    for code in codes[:max_n]:
        kuerzel, _, nr = code.rpartition("-")
        teile.append(f"-{nr}" if kuerzel and kuerzel == letztes else code)
        letztes = kuerzel or None
    return ", ".join(teile) + (f" (+{len(codes) - max_n})" if len(codes) > max_n else "")


def export_pdf(
    ergebnis: OptimierungsErgebnis,
    path: str | Path,
    projekt_name: str = "",
    material_name: str = "",
    saegeblatt_name: str = "",
    is_1d: bool = False,
    schnittfolgen: list[list[str]] | None = None,
    schnittfolge_titel: str = "Schnittfolge",
    material_bild: bytes = b"",
    nach_projekt: bool = False,
):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    c.setTitle(f"CutStock – {projekt_name}")

    labels = sorted({p.teil_label for sp in ergebnis.schnittplaene
                     for p in sp.platzierungen})
    if nach_projekt:
        # Sammelplan: eine Farbe je Projekt, damit die Teile im richtigen Stapel landen
        projekte = sorted({_projekt_von(label) for label in labels})
        projekt_farbe = {pr: FARBEN[i % len(FARBEN)] for i, pr in enumerate(projekte)}
        farb_map = {label: projekt_farbe[_projekt_von(label)] for label in labels}
    else:
        farb_map = {label: FARBEN[i % len(FARBEN)] for i, label in enumerate(labels)}

    cur = _PageCursor(c)
    _draw_header(c, cur, ergebnis, projekt_name, material_name, saegeblatt_name)
    _draw_stueckliste(c, cur, ergebnis, farb_map, is_1d, projekt_name)
    _draw_materialbedarf(c, cur, ergebnis, material_name, material_bild)

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


def _projekt_von(label: str) -> str:
    """Projekt aus „Label → Projekt“ (Sammelplan, Füllteile), sonst ''."""
    return label.split(" → ", 1)[1] if " → " in label else ""


def _teil_von(label: str) -> str:
    return label.split(" → ", 1)[0]


def _draw_stueckliste(c: canvas.Canvas, cur: _PageCursor,
                      erg: OptimierungsErgebnis, farb_map: dict, is_1d: bool,
                      projekt_name: str = ""):
    # Je Teil (Label + Maß) eine Zeile mit der Anzahl; Füllteile in eigenem Abschnitt
    teile: dict[tuple[str, float, float], int] = {}
    fuell: dict[tuple[str, float, float], int] = {}
    for plan in erg.schnittplaene:
        for p in plan.platzierungen:
            ziel = fuell if p.ist_fuellteil else teile
            key = (p.teil_label, round(p.laenge, 1), round(p.breite, 1))
            ziel[key] = ziel.get(key, 0) + 1
    _draw_teile_tabelle(c, cur, teile, farb_map, is_1d, projekt_name)
    if fuell:
        cur.advance(4)
        cur.need(40)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGIN, cur.y,
                     f"Füllteile ({sum(fuell.values())}) – kommen ins Regal ihres Projekts")
        cur.advance(14)
        _draw_teile_tabelle(c, cur, fuell, farb_map, is_1d, projekt_name)


def _draw_teile_tabelle(c: canvas.Canvas, cur: _PageCursor,
                        teile: dict[tuple[str, float, float], int], farb_map: dict,
                        is_1d: bool, projekt_name: str):
    if not teile:
        return

    # Teile aus anderen Projekten (Sammelplan, Füllteile) nach Projekt gruppieren;
    # das Projekt steht dann als Zwischenüberschrift statt hinter jedem Label
    gruppiert = any(_projekt_von(k[0]) for k in teile)
    def anzeige(label: str) -> str:
        return _latin1(_teil_von(label) if gruppiert else label)

    # Spaltenbreiten nach dem längsten Label, Zahlen rechtsbündig
    label_w = max([stringWidth("Teil", "Helvetica-Bold", 9)]
                  + [stringWidth(anzeige(k[0]), "Helvetica", 9) for k in teile])
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

    def projekt(key) -> str:
        return _projekt_von(key[0]) or projekt_name

    c.setFont("Helvetica", 9)
    gruppe = None
    for key, anzahl in sorted(teile.items(), key=lambda kv: (projekt(kv[0]), kv[0])):
        label, laenge, breite = key
        if gruppiert and projekt(key) != gruppe:
            gruppe = projekt(key)
            summe = sum(n for k, n in teile.items() if projekt(k) == gruppe)
            cur.need(28)
            cur.advance(3)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(MARGIN, cur.y, _latin1(f"{gruppe or '–'}  ({summe})"))
            c.setFont("Helvetica", 9)
            cur.advance(13)
        cur.need(13)
        c.setFillColor(farb_map.get(label, colors.grey))
        c.rect(MARGIN, cur.y - 2, 10, 10, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.drawString(x_label, cur.y, anzeige(label))
        c.drawRightString(x_laenge, cur.y, _fmt(laenge))
        if not is_1d:
            c.drawRightString(x_breite, cur.y, _fmt(breite))
        c.drawRightString(x_anzahl, cur.y, str(anzahl))
        cur.advance(13)


def _draw_materialbedarf(c: canvas.Canvas, cur: _PageCursor,
                         erg: OptimierungsErgebnis, material: str, bild: bytes):
    # Je Format die benötigte Anzahl, dazu die Stück-Codes (wie auf den Etiketten)
    # und wo sie liegen
    bedarf: dict[tuple[float, float], list[Schnittplan]] = {}
    for plan in erg.schnittplaene:
        bedarf.setdefault((plan.lager_laenge, plan.lager_breite), []).append(plan)

    img, img_w, img_h = None, 0.0, 0.0
    if bild:
        try:
            img = ImageReader(BytesIO(bild))
            iw, ih = img.getSize()
            f = min(30 * mm / iw, 22 * mm / ih)
            img_w, img_h = iw * f, ih * f
        except Exception:
            img = None  # unlesbares Bild: ohne Bild weiter

    text_h = 12 * (len(bedarf) + (1 if material else 0))
    cur.advance(8)
    cur.need(13 + max(img_h, text_h))
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN, cur.y, "Materialbedarf")
    cur.advance(14)

    oben = cur.y + 8  # Oberkante der ersten Textzeile
    x = MARGIN
    if img:
        c.drawImage(img, MARGIN, oben - img_h, img_w, img_h, mask="auto")
        x += img_w + 8

    if material:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, cur.y, material)
        cur.advance(12)
    c.setFont("Helvetica", 9)
    for (laenge, breite), plaene in sorted(bedarf.items(), reverse=True):
        mass = _fmt(laenge) + (f" x {_fmt(breite)}" if breite > 0 else "")
        c.drawRightString(x + 20, cur.y, f"{len(plaene)} ×")
        c.drawString(x + 24, cur.y, f"{mass} mm")
        orte = sorted({p.lagerort for p in plaene if p.lagerort})
        info = _codes_text([p.stueck_code for p in plaene if p.stueck_code])
        if orte:
            info += (" · " if info else "") + ", ".join(orte)
        c.drawString(x + 110, cur.y, info)
        cur.advance(12)
    cur.y = min(cur.y, oben - img_h - 4)


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
        if p.ist_fuellteil:
            _schraffur(c, x, y, rw, rh)

        # Beschriftung nur, wenn sie ins Teil passt (sonst schrumpfen/weglassen)
        c.setFillColor(colors.black)
        dim = f"{p.laenge:.0f}x{p.breite:.0f}"
        if p.gedreht:
            dim += " ↻"
        lbl = _latin1(p.teil_label)
        lbl_size = _fit_size(lbl, "Helvetica-Bold", font_size, 5, rw - 2)
        dim_size = _fit_size(dim, "Helvetica", max(5, font_size - 2), 5, rw - 2)
        if lbl_size and dim_size and rh >= lbl_size + dim_size + 2:
            c.setFont("Helvetica-Bold", lbl_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 + lbl_size * 0.3, lbl)
            c.setFont("Helvetica", dim_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 - lbl_size * 0.7, dim)
        elif lbl_size and rh >= lbl_size + 1:
            c.setFont("Helvetica-Bold", lbl_size)
            c.drawCentredString(x + rw / 2, y + rh / 2 - lbl_size * 0.35, lbl)
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
    teile = [f"{n} × {_latin1(label)} ({_fmt(laenge)} mm)"
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
            if p.ist_fuellteil:
                _schraffur(c, x, bar_y + 1, w, bar_h - 2)

            # Label + Länge, wenn sie ins Teil passen; sonst nur die Länge
            c.setFillColor(colors.black)
            mitte = bar_y + bar_h / 2
            laenge_txt = _fmt(p.laenge)
            lbl = _latin1(p.teil_label)
            lbl_size = _fit_size(lbl, "Helvetica-Bold", 7.5, 5, w - 3)
            len_size = _fit_size(laenge_txt, "Helvetica", 7, 5, w - 2)
            if lbl_size and len_size:
                c.setFont("Helvetica-Bold", lbl_size)
                c.drawCentredString(x + w / 2, mitte + 2, lbl)
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
