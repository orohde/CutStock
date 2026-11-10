"""Etiketten als Druckbild für Etikettendrucker, die CutStock direkt ansteuert (P-touch).

Dasselbe Layout wie im PDF (core.labels.layout), gezeichnet mit Pillow in 1 Bit und genau in
Druckpunkten: Höhe = Druckbereich des Bands, Länge wie beim Endlos-Band aus dem Inhalt.
Der QR-Code liegt auf ganzen Punkten je Modul, damit er scharf bleibt; Text ist schwarz
(der Drucker kennt kein Grau).
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth

from core.labels import CHAIN_GAP_MM, CHAIN_MAX_MM, _endlos_breite, _endlos_gross, layout
from core.ptouch import BAND, DPI, LAENGE_MAX, LAENGE_MIN

PT_PX = DPI / 72.0   # Punkte (1/72") → Druckpunkte


def _schriftdateien() -> list[tuple[str, int, int]]:
    """(Datei, Index normal, Index fett) – Helvetica wie im PDF, sonst eine freie Schrift."""
    kandidaten = [("/System/Library/Fonts/Helvetica.ttc", 0, 1)]
    import reportlab
    rl = Path(reportlab.__file__).parent / "fonts"
    kandidaten.append((str(rl / "Vera.ttf"), 0, 0))
    if getattr(sys, "_MEIPASS", None):
        kandidaten.append((str(Path(sys._MEIPASS) / "reportlab" / "fonts" / "Vera.ttf"), 0, 0))
    return kandidaten


@lru_cache(maxsize=256)
def _schrift(fett: bool, px: int):
    from PIL import ImageFont
    for datei, normal, bold in _schriftdateien():
        if not Path(datei).is_file():
            continue
        if not fett:
            return ImageFont.truetype(datei, px, index=normal)
        fett_datei = datei.replace("Vera.ttf", "VeraBd.ttf")
        if Path(fett_datei).is_file() and fett_datei != datei:
            return ImageFont.truetype(fett_datei, px)
        return ImageFont.truetype(datei, px, index=bold)
    return ImageFont.load_default(px)


def druckbild(lab: dict, band_mm: int, stil: str = "normal"):
    """Ein Etikett für den P-touch (TZe-Band) als Bild (Modus "1", weiß = drucken),
    Länge × Druckbereich in Punkten."""
    return zeichnen(lab, BAND[band_mm][0], DPI, stil, laenge_min=LAENGE_MIN)


def druckbild_ql(lab: dict, medium, stil: str = "normal"):
    """Ein Etikett für den Brother QL (core.ql.Medium): Endlosrolle mit Länge aus dem Inhalt
    oder vorgestanzt mit festem Maß. Rot/Schwarz-Rolle: Paar (schwarz, rot)."""
    from core import ql
    return zeichnen(lab, medium.druckpunkte, ql.DPI, stil,
                    laenge_px=medium.zeilen_fest or None, laenge_min=ql.LAENGE_MIN,
                    zweifarbig=medium.zweifarbig)


def zeichnen(lab: dict, hoehe_px: int, dpi: int, stil: str = "normal",
             laenge_px: int | None = None, laenge_min: int = 1, zweifarbig: bool = False):
    """Etikett in Druckpunkten zeichnen: hoehe_px quer zum Band, Länge fest (laenge_px,
    vorgestanzte Etiketten) oder aus dem Inhalt (Endlosband). zweifarbig: die Titelzeile
    (fett, größte Schrift) kommt in ein zweites Bild für Rot – Rückgabe (schwarz, rot)."""
    from PIL import Image, ImageDraw
    pt_px = dpi / 72.0
    h_pt = hoehe_px / pt_px
    if laenge_px:
        w_pt, gross = laenge_px / pt_px, None
    else:
        w_pt, gross = _endlos_breite(lab, h_pt, stil), _endlos_gross(h_pt)
    items = layout(lab, w_pt, h_pt, gross, stil)
    laenge = laenge_px or max(laenge_min, round(w_pt * pt_px))
    schwarz = Image.new("1", (laenge, hoehe_px), 0)
    rot = Image.new("1", (laenge, hoehe_px), 0) if zweifarbig else None
    titel = None
    if zweifarbig:
        fette = [i for i in items if "text" in i and i["font"].endswith("Bold")]
        titel = max(fette, key=lambda i: i["size"], default=None)
    d_schwarz = ImageDraw.Draw(schwarz)
    d_rot = ImageDraw.Draw(rot) if rot is not None else None
    for i in items:
        if "qr" in i:
            _qr_zeichnen(d_schwarz, i, hoehe_px, pt_px)
            continue
        d = d_rot if i is titel else d_schwarz
        text = i["text"]
        fett = i["font"].endswith("Bold")
        soll = stringWidth(text, i["font"], i["size"]) * pt_px    # Breite wie im PDF
        px = max(6, round(i["size"] * pt_px))
        schrift = _schrift(fett, px)
        while px > 6 and schrift.getlength(text) > soll * 1.03:
            px -= 1
            schrift = _schrift(fett, px)
        x = i["x"] * pt_px
        y = hoehe_px - i["y"] * pt_px                           # Grundlinie von oben
        d.text((x, y), text, font=schrift, fill=1, anchor="rs" if i["rechts"] else "ls")
    return (schwarz, rot) if zweifarbig else schwarz


def _qr_zeichnen(d, item: dict, druck: int, pt_px: float = PT_PX):
    """QR-Code mit ganzen Punkten je Modul, mittig in seinem Feld aus dem Layout."""
    matrix = item["qr"]
    n = len(matrix)
    voll = n + 2 * item["quiet"]
    feld = item["size"] * pt_px
    modul = max(1, int(feld // voll))
    seite = modul * voll
    x0 = round(item["x"] * pt_px + (feld - seite) / 2) + item["quiet"] * modul
    oben = druck - (item["y"] + item["size"]) * pt_px
    y0 = round(oben + (feld - seite) / 2) + item["quiet"] * modul
    for r, zeile in enumerate(matrix):
        c = 0
        while c < n:
            if not zeile[c]:
                c += 1
                continue
            start = c
            while c < n and zeile[c]:
                c += 1
            d.rectangle([x0 + start * modul, y0 + r * modul,
                         x0 + c * modul - 1, y0 + (r + 1) * modul - 1], fill=1)


def streifen(bilder: list, max_mm: float = CHAIN_MAX_MM) -> list:
    """Etiketten hintereinander auf Streifen (je höchstens max_mm), dazwischen eine
    gestrichelte Schnittmarke. Spart Band: der Drucker schneidet nur je Streifen, das
    Leerband zwischen Kopf und Messer (~24,5 mm) fällt nur einmal an statt je Etikett."""
    from PIL import Image, ImageDraw
    if not bilder:
        return []
    luecke = round(CHAIN_GAP_MM / 25.4 * DPI)
    grenze = min(LAENGE_MAX, round(max_mm / 25.4 * DPI))
    gruppen: list[list] = [[]]
    laenge = 0
    for b in bilder:
        dazu = b.size[0] + (luecke if gruppen[-1] else 0)
        if gruppen[-1] and laenge + dazu > grenze:
            gruppen.append([])
            laenge, dazu = 0, b.size[0]
        gruppen[-1].append(b)
        laenge += dazu
    hoehe = bilder[0].size[1]
    aus = []
    for gruppe in gruppen:
        if len(gruppe) == 1:
            aus.append(gruppe[0])
            continue
        gesamt = sum(b.size[0] for b in gruppe) + luecke * (len(gruppe) - 1)
        bild = Image.new("1", (gesamt, hoehe), 0)
        d = ImageDraw.Draw(bild)
        x = 0
        for k, b in enumerate(gruppe):
            if k > 0:
                mitte = x - luecke // 2 - 1
                for y in range(0, hoehe, 8):            # Strich 4 Punkte, Lücke 4 Punkte
                    d.rectangle([mitte, y, mitte + 1, min(hoehe - 1, y + 3)], fill=1)
            bild.paste(b, (x, 0))
            x += b.size[0] + luecke
        aus.append(bild)
    return aus
