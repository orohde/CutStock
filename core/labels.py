"""Label PDFs (parts + remnants) via reportlab.

Two modes, selected by the format key from the app settings:
  - Sheet (A4): grid of labels, e.g. 3×8 = 70×36 mm (Avery 3475) or
    3×7 = 63.5×38.1 mm (Avery L7160). Plain-paper sheets get thin cut
    guide lines; pre-cut adhesive sheets do not.
  - Roll (label printer, e.g. Dymo/Brother): one label per PDF page,
    page size = label size – the printer driver handles the rest.
  - Continuous tape: like a roll, the length follows the content.

Small labels get a compact layout: as many lines as stay readable, in order of
importance (ID/title, dimension, context), down to one line "short · dimension".

Content arrives pre-formatted from the caller: title, line1, line2,
id_text and optionally qr (text for a QR code, see qr_text). Font sizes scale
with the label size (reference: 70×36 mm).

QR codes (style): "normal" = QR on the left, text layout beside it; "mini" =
QR + code (and dimension if it fits); "qr" = QR with the code underneath;
"text" = no QR. Below QR_MIN_MM the label falls back to text only.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

# Sheet formats: grid on A4. margin/pitch in mm; None = centered grid resp.
# pitch = label size (no gaps). cut_lines only for plain paper (not pre-cut).
SHEET_FORMATS = {
    "a4_3x8": dict(cols=3, rows=8, label_w=70.0, label_h=36.0,
                   margin_x=None, margin_y=None,
                   pitch_x=None, pitch_y=None, cut_lines=True, ware="Avery 3475"),
    # Avery L7160 (pre-cut): 63.5×38.1, horizontal pitch 66.55 (2.05 mm gap)
    "a4_3x7": dict(cols=3, rows=7, label_w=63.5, label_h=38.1,
                   margin_x=7.25, margin_y=15.15,
                   pitch_x=66.55, pitch_y=38.1, cut_lines=False, ware="Avery L7160"),
    # Further pre-cut sheets: grid centered on the page (symmetric layouts)
    "a4_2x7": dict(cols=2, rows=7, label_w=99.1, label_h=38.1,
                   margin_x=None, margin_y=None,
                   pitch_x=101.6, pitch_y=38.1, cut_lines=False, ware="Avery L7163"),
    "a4_5x13": dict(cols=5, rows=13, label_w=38.1, label_h=21.2,
                    margin_x=None, margin_y=None,
                    pitch_x=40.6, pitch_y=21.2, cut_lines=False, ware="Avery L7651"),
    "a4_7x27": dict(cols=7, rows=27, label_w=25.4, label_h=10.0,
                    margin_x=None, margin_y=None,
                    pitch_x=27.94, pitch_y=10.0, cut_lines=False, ware="Avery L7658"),
}

# Roll formats (die-cut): width × height in mm as printed (text runs along the width)
ROLL_FORMATS = {
    "roll_62x29": (62.0, 29.0),
    "roll_90x38": (90.0, 38.0),
    "roll_100x62": (100.0, 62.0),
    "roll_89x36": (89.0, 36.0),
    "roll_90x29": (90.0, 29.0),
    "roll_54x17": (54.0, 17.0),
    "roll_23x23": (23.0, 23.0),
    "roll_51x19": (51.0, 19.0),
    "roll_25x13": (25.0, 13.0),
}
ROLL_WARE = {
    "roll_62x29": "Brother DK-11209", "roll_90x38": "Brother DK-11208",
    "roll_100x62": "Brother DK-11202", "roll_89x36": "Dymo 99012",
    "roll_90x29": "Brother DK-11201", "roll_54x17": "Brother DK-11204",
    "roll_23x23": "Brother DK-11221", "roll_51x19": "Dymo 11355", "roll_25x13": "Dymo 11353",
}

# Continuous tape: tape width = label height, length follows the content
ENDLESS_FORMATS = {
    "endless_12": (12.0, "Brother DK-22214"),
    "endless_29": (29.0, "Brother DK-22210"),
    "endless_62": (62.0, "Brother DK-22205"),
    # P-touch (TZe, laminated), e.g. PT-P710BT
    "tze_12": (12.0, "Brother TZe 12 mm (P-touch)"),
    "tze_18": (18.0, "Brother TZe 18 mm (P-touch)"),
    "tze_24": (24.0, "Brother TZe 24 mm (P-touch)"),
}
# Printable height on tapes where the print head does not cover the whole width
# (P-touch 180 dpi: 70 / 112 / 128 dots). Content stays inside, centered.
ENDLESS_PRINT_MM = {"tze_12": 9.9, "tze_18": 15.8, "tze_24": 18.1}

# Chain printing on continuous tape: labels side by side on one strip with cut
# marks (P-touch leaves ~2 cm of tape before each separate print job)
CHAIN_GAP_MM = 3.0
CHAIN_MAX_MM = 400.0

LABEL_STYLES = ("normal", "mini", "qr", "text")
QR_MIN_MM = 7.0       # smaller QR codes are unreliable with phone cameras
QR_QUIET = 2          # quiet zone in modules (standard: 4, phones manage with 2)

DEFAULT_FORMAT = "a4_3x8"

# Below this size the reference layout would have to shrink too far: compact layout
COMPACT_W, COMPACT_H = 50.0, 25.0
MIN_FONT = 5.5


def formats() -> list[dict]:
    """All formats for the settings: key, group, size in mm, product, labels per sheet."""
    erg = []
    for key, s in SHEET_FORMATS.items():
        erg.append(dict(key=key, gruppe="bogen_klein" if s["label_h"] < 25 else "bogen",
                        breite=s["label_w"], hoehe=s["label_h"], ware=s["ware"],
                        je_bogen=s["cols"] * s["rows"], endlos=False))
    for key, (w, h) in ROLL_FORMATS.items():
        erg.append(dict(key=key, gruppe="rolle_klein" if h < 25 else "rolle",
                        breite=w, hoehe=h, ware=ROLL_WARE[key], je_bogen=0, endlos=False))
    for key, (h, ware) in ENDLESS_FORMATS.items():
        erg.append(dict(key=key, gruppe="ptouch" if key.startswith("tze_") else "endlos",
                        breite=0.0, hoehe=h, ware=ware,
                        je_bogen=0, endlos=True))
    return erg


def qr_text(art: str, ref, base: str = "") -> str:
    """Content of a QR code. art "s" = stock piece (code), "o" = location (ID).

    With a server address: link to the piece/location view, e.g.
    "HTTPS://CUTSTOCK.EXAMPLE/S/AP40-07". Scheme and host in capitals (they are
    case-insensitive) keep the whole text in the compact alphanumeric QR mode.
    Without an address: just the code ("AP40-07", "O:3") for hand scanners.
    """
    art = art.lower()
    ref = str(ref).strip().upper()
    base = (base or "").strip().rstrip("/")
    if not base:
        return ref if art == "s" else f"O:{ref}"
    if "://" not in base:
        base = "https://" + base
    teile = urlsplit(base)
    return (f"{teile.scheme.upper()}://{teile.netloc.upper()}{teile.path}"
            f"/{art.upper()}/{quote(ref, safe='-')}")


def qr_matrix(text: str) -> list[list[bool]]:
    """QR modules (rows of dark=True), error correction M, smallest version."""
    from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel
    q = QRCode(None, QRErrorCorrectLevel.M)
    q.addData(text)
    q.make()
    n = q.getModuleCount()
    return [[bool(q.isDark(r, c)) for c in range(n)] for r in range(n)]


def _fit(text: str, font: str, size: float, max_w: float) -> str:
    """Truncate text to max_w points (with ellipsis) so nothing overflows."""
    if not text:
        return ""
    if stringWidth(text, font, size) <= max_w:
        return text
    while text and stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


def _item(text, font, size, x, y, color="#000000", rechts=False) -> dict:
    return dict(text=text, font=font, size=size, x=x, y=y, color=color, rechts=rechts)


def layout(lab: dict, w: float, h: float, gross: bool | None = None,
           stil: str = "normal") -> list[dict]:
    """Items for one label of w × h points (origin bottom left): text items and
    at most one QR item ({qr: matrix, x, y, size} – x/y bottom left, size in pt).

    Large labels: reference layout (title with ID on the right, dimension, context line),
    scaled to the label size. Small labels: as many lines as stay readable, in order of
    importance – ID/title, dimension, context; a single line is "short · dimension".
    gross: force the layout (continuous tape decides by its height only).
    stil: QR layout (see module docstring); without lab["qr"] always text only.
    """
    if lab.get("qr") and stil != "text":
        items = _layout_qr(lab, w, h, gross, stil)
        if items is not None:
            return items
    return _layout_text(lab, w, h, gross)


def _qr_rand(w: float, h: float) -> float:
    return min(1.5 * mm, 0.06 * min(w, h))


def _qr_lab(lab: dict, stil: str) -> dict:
    """Text part beside the QR code: mini = code (or title) + dimension only."""
    if stil != "mini" or lab.get("art") == "ort":
        return {k: v for k, v in lab.items() if k != "qr"}
    kopf = str(lab.get("id_text") or lab.get("kurz") or lab.get("title") or "")
    return {"id_text": kopf, "line1": str(lab.get("line1") or ""), "kurz": kopf}


def _qr_unten(lab: dict, w: float, h: float) -> tuple[str, float]:
    """Code underneath the QR ("qr" style): text and font size."""
    text = str(lab.get("id_text") or lab.get("kurz") or lab.get("title") or "")
    return text, max(MIN_FONT, min(9.0, h * 0.11))


def _layout_qr(lab: dict, w: float, h: float, gross: bool | None,
               stil: str) -> list[dict] | None:
    matrix = qr_matrix(str(lab["qr"]))
    module = len(matrix) + 2 * QR_QUIET
    rand = _qr_rand(w, h)
    if stil == "qr":
        text, fs = _qr_unten(lab, w, h)
        text_h = fs * 1.25 if text else 0.0
        side = min(w - 2 * rand, h - 2 * rand - text_h)
        if side < QR_MIN_MM * mm or side / module < 0.24 * mm:
            return _layout_qr(lab, w, h, gross, "mini")   # no room for the code underneath
        items = [dict(qr=matrix, x=(w - side) / 2, y=h - rand - side, size=side, quiet=QR_QUIET)]
        if text:
            text = _fit(text, "Helvetica-Bold", fs, w - 2 * rand)
            tw = stringWidth(text, "Helvetica-Bold", fs)
            items.append(_item(text, "Helvetica-Bold", fs, (w - tw) / 2, rand + fs * 0.2))
        return items
    # The QR takes at most ~40 % of the width, the text needs the rest
    side = min(h - 2 * rand, 30 * mm, w - 2 * rand - 12 * mm, max(0.38 * w, 12 * mm))
    if side < QR_MIN_MM * mm or side / module < 0.24 * mm:
        return None
    x0 = rand + side + 0.5 * mm
    text_gross = False if stil == "mini" else gross
    items = [dict(qr=matrix, x=rand, y=(h - side) / 2, size=side, quiet=QR_QUIET)]
    for i in _layout_text(_qr_lab(lab, stil), w - x0, h, text_gross):
        items.append(dict(i, x=i["x"] + x0))
    return items


def _layout_ort(lab: dict, w: float, h: float) -> list[dict]:
    """Location label: name as large as fits, the materials underneath (shortened)."""
    pad = min(3 * mm, 0.08 * min(w, h)) + 0.5 * mm
    text_w, avail = w - 2 * pad, h - 2 * pad
    name, mats = str(lab.get("title") or ""), str(lab.get("line1") or "")
    # The material line gets a fixed share first (~8 pt on 12 mm tape like the piece
    # labels – smaller is hard to read in thermal print), the name takes what is left
    ms = max(MIN_FONT, min(avail * 0.40, 10.0)) if mats else 0.0
    rest = avail - ms * 1.67 if mats else avail
    fs = min(rest / 0.72 if mats else avail * 0.8, avail * 0.55 if mats else 28.0, 28.0,
             text_w / max(stringWidth(name, "Helvetica-Bold", 1.0), 1.0))
    fs = max(fs, MIN_FONT)
    zwei = bool(mats) and ms >= MIN_FONT and avail >= fs * 0.95 + ms * 1.3
    block = fs * 0.72 + (ms * 1.45 if zwei else 0.0)   # cap heights + gap
    y = h / 2 + block / 2 - fs * 0.72
    items = [_item(_fit(name, "Helvetica-Bold", fs, text_w), "Helvetica-Bold", fs, pad, y)]
    if zwei:
        it = _item(_fit(mats, "Helvetica", ms, text_w), "Helvetica", ms, pad,
                   y - ms * 1.45, "#555555")
        it["max_w"] = 80 * mm   # continuous tape: the list must not make the label endless
        items.append(it)
    return items


def _layout_text(lab: dict, w: float, h: float, gross: bool | None = None) -> list[dict]:
    if lab.get("art") == "ort":
        return _layout_ort(lab, w, h)
    if gross is None:
        gross = w >= COMPACT_W * mm and h >= COMPACT_H * mm
    if gross:
        return _layout_gross(lab, w, h)
    return _layout_klein(lab, w, h)


def _layout_gross(lab: dict, w: float, h: float) -> list[dict]:
    # Scale factor relative to the 70×36 mm reference, clamped for extreme sizes
    f = min(w / (70 * mm), h / (36 * mm))
    f = max(0.6, min(f, 1.5))
    pad = min(4 * mm, 0.09 * min(w, h) + 1 * mm)
    text_w = w - 2 * pad
    # The three-line block spans ~40·f pt; ty is the TITLE BASELINE so the
    # whole block sits vertically centered on the label.
    ty = h / 2 + 12 * f
    items = []
    # ID top-right (e.g. the remnant number to write onto the wood)
    id_text = str(lab.get("id_text") or "")
    id_w = stringWidth(id_text, "Helvetica-Bold", 9 * f) if id_text else 0
    if id_text:
        items.append(_item(id_text, "Helvetica-Bold", 9 * f, w - pad, ty, "#555555", True))
    # Title (bold), keeping the ID's width free on the right
    items.append(_item(_fit(str(lab.get("title") or ""), "Helvetica-Bold", 10.5 * f,
                            text_w - id_w - 2 * mm), "Helvetica-Bold", 10.5 * f, pad, ty))
    # Dimensions line (large – the most important info on a sawn part)
    items.append(_item(_fit(str(lab.get("line1") or ""), "Helvetica", 11 * f, text_w),
                       "Helvetica", 11 * f, pad, ty - 16 * f))
    # Context line (project/material), subdued
    items.append(_item(_fit(str(lab.get("line2") or ""), "Helvetica", 8.5 * f, text_w),
                       "Helvetica", 8.5 * f, pad, ty - 30 * f, "#555555"))
    return [i for i in items if i["text"]]


def _zeilen_klein(lab: dict) -> list[tuple[str, str, str]]:
    """(text, font, color) in order of importance for small labels; the first line is
    ID + title (the title gets shortened, never the ID)."""
    kopf = " ".join(x for x in (str(lab.get("id_text") or ""), str(lab.get("title") or "")) if x)
    zeilen = [(kopf, "Helvetica-Bold", "#000000"),
              (str(lab.get("line1") or ""), "Helvetica", "#000000"),
              (str(lab.get("line2") or ""), "Helvetica", "#555555")]
    return [z for z in zeilen if z[0]]


def _kurz(lab: dict) -> str:
    """One-line text: short name (caller's „kurz“, else ID or title) and dimension."""
    kurz = str(lab.get("kurz") or lab.get("id_text") or lab.get("title") or "")
    return " · ".join(x for x in (kurz, str(lab.get("line1") or "")) if x)


def _layout_klein(lab: dict, w: float, h: float) -> list[dict]:
    pad = min(2 * mm, 0.08 * min(w, h)) + 0.5 * mm
    text_w, avail_h = w - 2 * pad, h - 2 * pad
    zeilen = _zeilen_klein(lab)
    # ID (stock code) and dimension must never be cut off: they limit the font size
    id_text = str(lab.get("id_text") or "")
    kurz = str(lab.get("kurz") or id_text or lab.get("title") or "")
    breit_max = text_w / max(stringWidth(id_text or kurz, "Helvetica-Bold", 1.0),
                             stringWidth(str(lab.get("line1") or ""), "Helvetica", 1.0), 1.0)
    for n in range(min(3, len(zeilen)), 1, -1):
        size = min(avail_h / (n * 1.2), 11.0, breit_max)
        if size >= 6.0:
            schrift = [size if i < 2 else size * 0.85 for i in range(n)]
            block = sum(s * 1.2 for s in schrift) - 0.2 * schrift[-1]
            y = h / 2 + block / 2 - schrift[0] * 0.8
            items = []
            for i, ((text, font, color), s) in enumerate(zip(zeilen[:n], schrift)):
                if i == 0 and id_text and text.startswith(id_text + " "):
                    rest_w = text_w - stringWidth(id_text + " ", font, s)
                    titel = _fit(text[len(id_text) + 1:], font, s, rest_w)
                    text = f"{id_text} {titel}" if len(titel) > 2 else id_text
                else:
                    text = _fit(text, font, s, text_w)
                items.append(_item(text, font, s, pad, y, color))
                y -= s * 1.2
            return items
    # Only one line fits: "AP40-07 · 1200 mm"
    size = max(MIN_FONT, min(avail_h / 1.2, 12.0, breit_max))
    return [_item(_fit(_kurz(lab), "Helvetica-Bold", size, text_w), "Helvetica-Bold", size,
                  pad, h / 2 - size * 0.35)]


def _endlos_gross(h: float) -> bool:
    return h >= COMPACT_H * mm


def _items_breite(items: list[dict]) -> float:
    """Widest text line of a text layout (title and right-aligned ID share a line)."""
    breit = 0.0
    for i in items:
        breit = max(breit, min(stringWidth(i["text"], i["font"], i["size"]),
                               i.get("max_w", float("inf"))))
    ids = [i for i in items if i["rechts"]]
    if ids:   # title and ID share the first line
        titel = next((i for i in items if i["y"] == ids[0]["y"] and not i["rechts"]), None)
        breit = max(breit, (stringWidth(titel["text"], titel["font"], titel["size"]) if titel else 0)
                    + stringWidth(ids[0]["text"], ids[0]["font"], ids[0]["size"]) + 2 * mm)
    return breit


def _endlos_breite(lab: dict, h: float, stil: str = "normal") -> float:
    """Length of a continuous-tape label (points) so the content fits."""
    if lab.get("qr") and stil != "text":
        breite = _endlos_breite_qr(lab, h, stil)
        if breite:
            return breite
    pad = min(4 * mm, 0.09 * h + 1 * mm)
    breit = _items_breite(_layout_text(lab, 1000 * mm, h, _endlos_gross(h)))
    if lab.get("art") == "ort":
        return min(breit + 2 * pad + 1 * mm, 150 * mm)
    # Large layout scales with the length: at least the reference proportion
    mindest = 70 * mm * min(h / (36 * mm), 1.5) if _endlos_gross(h) else max(25 * mm, h)
    return min(max(breit + 2 * pad + 1 * mm, mindest), 150 * mm)


def _endlos_breite_qr(lab: dict, h: float, stil: str) -> float:
    """Tape length with a QR code, 0 if the QR does not fit the tape height."""
    module = len(qr_matrix(str(lab["qr"]))) + 2 * QR_QUIET
    rand = min(1.5 * mm, 0.06 * h)
    if stil == "qr":
        text, fs = _qr_unten(lab, 1000 * mm, h)
        side = h - 2 * rand - (fs * 1.25 if text else 0.0)
        if side < QR_MIN_MM * mm or side / module < 0.24 * mm:
            return _endlos_breite_qr(lab, h, "mini")
        tw = stringWidth(text, "Helvetica-Bold", fs) if text else 0.0
        return max(side, tw) + 2 * rand
    side = min(h - 2 * rand, 30 * mm)
    if side < QR_MIN_MM * mm or side / module < 0.24 * mm:
        return 0.0
    text_lab = _qr_lab(lab, stil)
    gross = stil == "normal" and _endlos_gross(h)
    pad = (min(3 * mm, 0.08 * h) + 0.5 * mm if lab.get("art") == "ort"
           else min(4 * mm, 0.09 * h + 1 * mm) if gross else min(2 * mm, 0.08 * h) + 0.5 * mm)
    text_w = max(_items_breite(_layout_text(text_lab, 1000 * mm, h, gross)) + 2 * pad + 1 * mm,
                 12 * mm + 2 * rand)
    return min(rand + side + 0.5 * mm + text_w, 150 * mm)


def _draw_items(c: canvas.Canvas, items: list[dict], x: float, y: float):
    """Draw layout items with their origin at (x, y)."""
    for i in items:
        if "qr" in i:
            _draw_qr(c, i, x, y)
            continue
        c.setFillColor(colors.HexColor(i["color"]))
        c.setFont(i["font"], i["size"])
        if i["rechts"]:
            c.drawRightString(x + i["x"], y + i["y"], i["text"])
        else:
            c.drawString(x + i["x"], y + i["y"], i["text"])


def _draw_qr(c: canvas.Canvas, item: dict, x: float, y: float):
    """QR modules as black rectangles (runs per row), quiet zone included in size."""
    matrix = item["qr"]
    n = len(matrix)
    m = item["size"] / (n + 2 * item["quiet"])
    x0 = x + item["x"] + item["quiet"] * m
    top = y + item["y"] + item["size"] - item["quiet"] * m
    c.setFillColor(colors.black)
    for r, zeile in enumerate(matrix):
        col = 0
        while col < n:
            if not zeile[col]:
                col += 1
                continue
            start = col
            while col < n and zeile[col]:
                col += 1
            # minimal overlap so no hairlines show between modules
            c.rect(x0 + start * m, top - (r + 1) * m, (col - start) * m + 0.01,
                   m + 0.01, stroke=0, fill=1)


def _draw_label(c: canvas.Canvas, lab: dict, x: float, y: float,
                w: float, h: float, gross: bool | None = None, stil: str = "normal"):
    """Draw one label's content into the rectangle (x, y, w, h)."""
    _draw_items(c, layout(lab, w, h, gross, stil), x, y)


def label_size(fmt: str, lab: dict, custom_w: float = 0.0, custom_h: float = 0.0,
               stil: str = "normal") -> tuple[float, float]:
    """Size of one label in mm for the format (continuous tape: length from the content)."""
    if fmt == "custom" and custom_w >= 15 and custom_h >= 10:
        return custom_w, custom_h
    if fmt in ROLL_FORMATS:
        return ROLL_FORMATS[fmt]
    if fmt in ENDLESS_FORMATS:
        return _endlos_breite(lab, _druckhoehe(fmt) * mm, stil) / mm, ENDLESS_FORMATS[fmt][0]
    spec = SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT])
    return spec["label_w"], spec["label_h"]


def _druckhoehe(fmt: str) -> float:
    """Printable height of a continuous tape in mm."""
    return ENDLESS_PRINT_MM.get(fmt, ENDLESS_FORMATS[fmt][0])


def label_items(fmt: str, lab: dict, custom_w: float = 0.0, custom_h: float = 0.0,
                stil: str = "normal") -> tuple[float, float, list[dict]]:
    """One label as it is printed: size in mm and items in page coordinates (points,
    origin bottom left) – the settings preview uses this."""
    w, h = label_size(fmt, lab, custom_w, custom_h, stil)
    if fmt in ENDLESS_FORMATS:
        druck = _druckhoehe(fmt) * mm
        dy = (h * mm - druck) / 2
        items = layout(lab, w * mm, druck, _endlos_gross(druck), stil)
        return w, h, [dict(i, y=i["y"] + dy) for i in items]
    return w, h, layout(lab, w * mm, h * mm, None, stil)


def export_labels(labels: list[dict], path: str | Path,
                  title: str = "CutStock",
                  fmt: str = DEFAULT_FORMAT,
                  custom_w: float = 0.0, custom_h: float = 0.0,
                  start: int = 1, stil: str = "normal", kette: bool = False):
    """labels: list of {title, line1, line2, id_text, kurz, qr} – one entry per label.

    fmt: key from SHEET_FORMATS/ROLL_FORMATS or "custom" (then
    custom_w × custom_h in mm applies, one label per page). Unknown or
    implausible values fall back to the default A4 sheet.
    start: first field on the sheet (1 = top left, row by row) so a partly
    used sheet can be reused. Ignored for rolls.
    stil: QR layout (LABEL_STYLES). kette: continuous tape – all labels on one
    strip with cut marks instead of one page each.
    """
    stil = stil if stil in LABEL_STYLES else "normal"
    if fmt == "custom" and custom_w >= 15 and custom_h >= 10:
        _export_roll(labels, path, title, custom_w, custom_h, stil)
    elif fmt in ROLL_FORMATS:
        _export_roll(labels, path, title, *ROLL_FORMATS[fmt], stil=stil)
    elif fmt in ENDLESS_FORMATS:
        _export_endless(labels, path, title, fmt, stil, kette)
    else:
        _export_sheet(labels, path, title,
                      SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT]), start, stil)


def _export_roll(labels: list[dict], path: str | Path, title: str,
                 label_w_mm: float, label_h_mm: float, stil: str = "normal"):
    """Label printer: one page per label, page size = label size."""
    page = (label_w_mm * mm, label_h_mm * mm)
    c = canvas.Canvas(str(path), pagesize=page)
    c.setTitle(f"CutStock – {title}")
    for i, lab in enumerate(labels):
        if i > 0:
            c.showPage()
            c.setPageSize(page)
        _draw_label(c, lab, 0, 0, page[0], page[1], stil=stil)
    c.save()


def _export_endless(labels: list[dict], path: str | Path, title: str, fmt: str,
                    stil: str = "normal", kette: bool = False):
    """Continuous tape: one page per label, length from the content. kette: labels
    side by side on strips of at most CHAIN_MAX_MM with dashed cut marks."""
    c = canvas.Canvas(str(path))
    c.setTitle(f"CutStock – {title}")
    tape = ENDLESS_FORMATS[fmt][0] * mm
    teile = [label_items(fmt, lab, stil=stil) for lab in labels]
    if not kette:
        for n, (w, _, items) in enumerate(teile):
            if n > 0:
                c.showPage()
            c.setPageSize((w * mm, tape))
            _draw_items(c, items, 0, 0)
        c.save()
        return
    gap = CHAIN_GAP_MM * mm
    streifen: list[list[tuple[float, list[dict]]]] = [[]]
    laenge = 0.0
    for w, _, items in teile:
        if streifen[-1] and laenge + gap + w * mm > CHAIN_MAX_MM * mm:
            streifen.append([])
            laenge = 0.0
        laenge += (gap if streifen[-1] else 0.0) + w * mm
        streifen[-1].append((w * mm, items))
    for n, teil in enumerate(streifen):
        if n > 0:
            c.showPage()
        c.setPageSize((sum(w for w, _ in teil) + gap * (len(teil) - 1), tape))
        x = 0.0
        for k, (w, items) in enumerate(teil):
            if k > 0:   # cut mark in the middle of the gap
                c.setStrokeColor(colors.HexColor("#999999"))
                c.setLineWidth(0.3)
                c.setDash(1.5, 1.5)
                c.line(x - gap / 2, 0, x - gap / 2, tape)
                c.setDash()
            _draw_items(c, items, x, 0)
            x += w + gap
    c.save()


def sheet_fields(fmt: str) -> int:
    """Labels per A4 sheet, 0 for roll formats."""
    if fmt == "custom" or fmt in ROLL_FORMATS or fmt in ENDLESS_FORMATS:
        return 0
    spec = SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT])
    return spec["cols"] * spec["rows"]


def _export_sheet(labels: list[dict], path: str | Path, title: str, spec: dict,
                  start: int = 1, stil: str = "normal"):
    """A4 sheet with a label grid, starting at field `start` on the first sheet."""
    page_w, page_h = A4
    cols, rows = spec["cols"], spec["rows"]
    lw, lh = spec["label_w"] * mm, spec["label_h"] * mm
    pitch_x = (spec["pitch_x"] or spec["label_w"]) * mm
    pitch_y = (spec["pitch_y"] or spec["label_h"]) * mm
    grid_w = (cols - 1) * pitch_x + lw
    grid_h = (rows - 1) * pitch_y + lh
    off_x = spec["margin_x"] * mm if spec["margin_x"] is not None else (page_w - grid_w) / 2
    off_y = spec["margin_y"] * mm if spec["margin_y"] is not None else (page_h - grid_h) / 2

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"CutStock – {title}")

    per_page = cols * rows
    skip = min(max(int(start or 1), 1), per_page) - 1
    for i, lab in enumerate(labels, start=skip):
        slot = i % per_page
        if i > skip and slot == 0:
            c.showPage()

        col = slot % cols
        row = slot // cols
        x = off_x + col * pitch_x
        y = page_h - off_y - row * pitch_y - lh

        if spec["cut_lines"]:
            c.setStrokeColor(colors.HexColor("#c8c8c8"))
            c.setLineWidth(0.3)
            c.rect(x, y, lw, lh, fill=0)

        _draw_label(c, lab, x, y, lw, lh, stil=stil)

    c.save()
