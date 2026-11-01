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
id_text. Font sizes scale with the label size (reference: 70×36 mm).
"""

from __future__ import annotations

from pathlib import Path

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
}

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
        erg.append(dict(key=key, gruppe="endlos", breite=0.0, hoehe=h, ware=ware,
                        je_bogen=0, endlos=True))
    return erg


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


def layout(lab: dict, w: float, h: float, gross: bool | None = None) -> list[dict]:
    """Text items for one label of w × h points (origin bottom left).

    Large labels: reference layout (title with ID on the right, dimension, context line),
    scaled to the label size. Small labels: as many lines as stay readable, in order of
    importance – ID/title, dimension, context; a single line is "short · dimension".
    gross: force the layout (continuous tape decides by its height only).
    """
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


def _endlos_breite(lab: dict, h: float) -> float:
    """Length of a continuous-tape label (points) so the content fits."""
    items = layout(lab, 1000 * mm, h, _endlos_gross(h))
    pad = min(4 * mm, 0.09 * h + 1 * mm)
    breit = 0.0
    for i in items:
        breit = max(breit, stringWidth(i["text"], i["font"], i["size"]))
    ids = [i for i in items if i["rechts"]]
    if ids:   # title and ID share the first line
        titel = next((i for i in items if i["y"] == ids[0]["y"] and not i["rechts"]), None)
        breit = max(breit, (stringWidth(titel["text"], titel["font"], titel["size"]) if titel else 0)
                    + stringWidth(ids[0]["text"], ids[0]["font"], ids[0]["size"]) + 2 * mm)
    # Large layout scales with the length: at least the reference proportion
    mindest = 70 * mm * min(h / (36 * mm), 1.5) if _endlos_gross(h) else max(25 * mm, h)
    return min(max(breit + 2 * pad + 1 * mm, mindest), 150 * mm)


def _draw_label(c: canvas.Canvas, lab: dict, x: float, y: float,
                w: float, h: float, gross: bool | None = None):
    """Draw one label's content into the rectangle (x, y, w, h)."""
    for i in layout(lab, w, h, gross):
        c.setFillColor(colors.HexColor(i["color"]))
        c.setFont(i["font"], i["size"])
        if i["rechts"]:
            c.drawRightString(x + i["x"], y + i["y"], i["text"])
        else:
            c.drawString(x + i["x"], y + i["y"], i["text"])


def label_size(fmt: str, lab: dict, custom_w: float = 0.0, custom_h: float = 0.0
               ) -> tuple[float, float]:
    """Size of one label in mm for the format (continuous tape: length from the content)."""
    if fmt == "custom" and custom_w >= 15 and custom_h >= 10:
        return custom_w, custom_h
    if fmt in ROLL_FORMATS:
        return ROLL_FORMATS[fmt]
    if fmt in ENDLESS_FORMATS:
        h = ENDLESS_FORMATS[fmt][0] * mm
        return _endlos_breite(lab, h) / mm, h / mm
    spec = SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT])
    return spec["label_w"], spec["label_h"]


def export_labels(labels: list[dict], path: str | Path,
                  title: str = "CutStock",
                  fmt: str = DEFAULT_FORMAT,
                  custom_w: float = 0.0, custom_h: float = 0.0,
                  start: int = 1):
    """labels: list of {title, line1, line2, id_text} – one entry per label.

    fmt: key from SHEET_FORMATS/ROLL_FORMATS or "custom" (then
    custom_w × custom_h in mm applies, one label per page). Unknown or
    implausible values fall back to the default A4 sheet.
    start: first field on the sheet (1 = top left, row by row) so a partly
    used sheet can be reused. Ignored for rolls.
    """
    if fmt == "custom" and custom_w >= 15 and custom_h >= 10:
        _export_roll(labels, path, title, custom_w, custom_h)
    elif fmt in ROLL_FORMATS:
        _export_roll(labels, path, title, *ROLL_FORMATS[fmt])
    elif fmt in ENDLESS_FORMATS:
        _export_endless(labels, path, title, ENDLESS_FORMATS[fmt][0])
    else:
        _export_sheet(labels, path, title,
                      SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT]), start)


def _export_roll(labels: list[dict], path: str | Path, title: str,
                 label_w_mm: float, label_h_mm: float):
    """Label printer: one page per label, page size = label size."""
    page = (label_w_mm * mm, label_h_mm * mm)
    c = canvas.Canvas(str(path), pagesize=page)
    c.setTitle(f"CutStock – {title}")
    for i, lab in enumerate(labels):
        if i > 0:
            c.showPage()
            c.setPageSize(page)
        _draw_label(c, lab, 0, 0, page[0], page[1])
    c.save()


def _export_endless(labels: list[dict], path: str | Path, title: str, tape_mm: float):
    """Continuous tape: one page per label, length from the content."""
    c = canvas.Canvas(str(path))
    c.setTitle(f"CutStock – {title}")
    for i, lab in enumerate(labels):
        if i > 0:
            c.showPage()
        w = _endlos_breite(lab, tape_mm * mm)
        c.setPageSize((w, tape_mm * mm))
        _draw_label(c, lab, 0, 0, w, tape_mm * mm, _endlos_gross(tape_mm * mm))
    c.save()


def sheet_fields(fmt: str) -> int:
    """Labels per A4 sheet, 0 for roll formats."""
    if fmt == "custom" or fmt in ROLL_FORMATS or fmt in ENDLESS_FORMATS:
        return 0
    spec = SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT])
    return spec["cols"] * spec["rows"]


def _export_sheet(labels: list[dict], path: str | Path, title: str, spec: dict,
                  start: int = 1):
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

        _draw_label(c, lab, x, y, lw, lh)

    c.save()
