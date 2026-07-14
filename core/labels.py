"""Label PDFs (parts + remnants) via reportlab.

Two modes, selected by the format key from the app settings:
  - Sheet (A4): grid of labels, e.g. 3×8 = 70×36 mm (Avery 3475) or
    3×7 = 63.5×38.1 mm (Avery L7160). Plain-paper sheets get thin cut
    guide lines; pre-cut adhesive sheets do not.
  - Roll (label printer, e.g. Dymo/Brother): one label per PDF page,
    page size = label size – the printer driver handles the rest.

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
                   pitch_x=None, pitch_y=None, cut_lines=True),
    # Avery L7160 (pre-cut): 63.5×38.1, horizontal pitch 66.55 (2.05 mm gap)
    "a4_3x7": dict(cols=3, rows=7, label_w=63.5, label_h=38.1,
                   margin_x=7.25, margin_y=15.15,
                   pitch_x=66.55, pitch_y=38.1, cut_lines=False),
}

# Roll formats (width × height in mm), e.g. Dymo 99012 / Brother DK-11209
ROLL_FORMATS = {
    "roll_89x36": (89.0, 36.0),
    "roll_62x29": (62.0, 29.0),
}

DEFAULT_FORMAT = "a4_3x8"


def _fit(text: str, font: str, size: float, max_w: float) -> str:
    """Truncate text to max_w points (with ellipsis) so nothing overflows."""
    if not text:
        return ""
    if stringWidth(text, font, size) <= max_w:
        return text
    while text and stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


def _draw_label(c: canvas.Canvas, lab: dict, x: float, y: float,
                w: float, h: float):
    """Draw one label's content into the rectangle (x, y, w, h).

    All font sizes and vertical offsets are multiplied by a scale factor
    f derived from the label size relative to the 70×36 mm reference, so
    the same layout works from small Brother rolls up to custom sizes.
    """
    # Scale factor, clamped so extreme label sizes stay readable
    f = min(w / (70 * mm), h / (36 * mm))
    f = max(0.6, min(f, 1.5))
    pad = min(4 * mm, 0.09 * min(w, h) + 1 * mm)
    text_w = w - 2 * pad

    tx = x + pad
    # The three-line block spans ~40·f pt from the title's ascender to the
    # bottom line's descender; ty is the TITLE BASELINE placed so the whole
    # block sits vertically centered on the label.
    ty = y + h / 2 + 12 * f

    # ID top-right (e.g. the remnant number to write onto the wood)
    id_text = str(lab.get("id_text") or "")
    id_size = 9 * f
    id_w = stringWidth(id_text, "Helvetica-Bold", id_size) if id_text else 0
    if id_text:
        c.setFont("Helvetica-Bold", id_size)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawRightString(x + w - pad, ty, id_text)

    # Title (bold), keeping the ID's width free on the right
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10.5 * f)
    c.drawString(tx, ty, _fit(str(lab.get("title") or ""), "Helvetica-Bold",
                              10.5 * f, text_w - id_w - 2 * mm))

    # Dimensions line (large – the most important info on a sawn part)
    c.setFont("Helvetica", 11 * f)
    c.drawString(tx, ty - 16 * f, _fit(str(lab.get("line1") or ""),
                                       "Helvetica", 11 * f, text_w))

    # Context line (project/material), subdued
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Helvetica", 8.5 * f)
    c.drawString(tx, ty - 30 * f, _fit(str(lab.get("line2") or ""),
                                       "Helvetica", 8.5 * f, text_w))


def export_labels(labels: list[dict], path: str | Path,
                  title: str = "CutStock",
                  fmt: str = DEFAULT_FORMAT,
                  custom_w: float = 0.0, custom_h: float = 0.0):
    """labels: list of {title, line1, line2, id_text} – one entry per label.

    fmt: key from SHEET_FORMATS/ROLL_FORMATS or "custom" (then
    custom_w × custom_h in mm applies, one label per page). Unknown or
    implausible values fall back to the default A4 sheet.
    """
    if fmt == "custom" and custom_w >= 15 and custom_h >= 10:
        _export_roll(labels, path, title, custom_w, custom_h)
    elif fmt in ROLL_FORMATS:
        _export_roll(labels, path, title, *ROLL_FORMATS[fmt])
    else:
        _export_sheet(labels, path, title,
                      SHEET_FORMATS.get(fmt, SHEET_FORMATS[DEFAULT_FORMAT]))


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


def _export_sheet(labels: list[dict], path: str | Path, title: str, spec: dict):
    """A4 sheet with a label grid."""
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
    for i, lab in enumerate(labels):
        slot = i % per_page
        if i > 0 and slot == 0:
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
