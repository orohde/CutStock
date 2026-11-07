"""Maßeinheiten für die Anzeige – gespeichert wird immer in Millimetern.

Einheiten:
  mm       Millimeter            375.5 mm
  cm       Zentimeter            37.55 cm
  in       Zoll dezimal          24.25"
  in_frac  Zoll als Bruch        2' 1/4"   (auf 1/16" gerundet, ab 12" mit Fuß)

Die Oberfläche (web/static/app.js) rechnet genauso; beide Seiten müssen
gleich formatieren, damit PDF, Etiketten und Bildschirm übereinstimmen.
"""

from __future__ import annotations

import math

UNITS = ("mm", "cm", "in", "in_frac")
MM_PER_INCH = 25.4
FRACTION_DENOMINATOR = 16


def normalize_unit(unit: str | None) -> str:
    return unit if unit in UNITS else "mm"


def is_imperial(unit: str) -> bool:
    return unit in ("in", "in_frac")


def _plain(v: float, digits: int) -> str:
    """Zahl ohne überflüssige Nachkommastellen: 2000, 375.5."""
    txt = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if txt in ("", "-0") else txt


def inch_fraction(inches: float, feet: bool = True) -> str:
    """Zoll als Bruch mit Zollzeichen: 3/4", 30 1/2", ab 12" mit Fuß 2' 1/4"."""
    sixteenths = round(abs(inches) * FRACTION_DENOMINATOR)
    whole, rest = divmod(sixteenths, FRACTION_DENOMINATOR)
    fraction = ""
    if rest:
        g = math.gcd(rest, FRACTION_DENOMINATOR)
        fraction = f"{rest // g}/{FRACTION_DENOMINATOR // g}"
    ft = 0
    if feet and whole >= 12:
        ft, whole = divmod(whole, 12)
    if whole and fraction:
        zoll = f"{whole} {fraction}"
    else:
        zoll = fraction or str(whole)
    text = f"{ft}' {zoll}\"" if ft else f"{zoll}\""
    return ("-" if inches < 0 and sixteenths else "") + text


def number(mm: float, unit: str = "mm", feet: bool = True) -> str:
    """Maßzahl wie in Tabellen und Plänen: 375.5 / 37.55 / 24.25 / 2' 1/4"."""
    unit = normalize_unit(unit)
    if unit == "cm":
        return _plain(mm / 10, 2)
    if unit == "in":
        return _plain(mm / MM_PER_INCH, 3)
    if unit == "in_frac":
        return inch_fraction(mm / MM_PER_INCH, feet)
    return _plain(mm, 1)


def suffix(unit: str) -> str:
    """Was hinter einer Maßzahl steht (beim Bruch steckt das Zollzeichen schon drin)."""
    unit = normalize_unit(unit)
    return {"mm": " mm", "cm": " cm", "in": '"', "in_frac": ""}[unit]


def length(mm: float, unit: str = "mm", feet: bool = True) -> str:
    """Ein Maß mit Einheit: 375.5 mm, 24.25", 2' 1/4"."""
    return number(mm, unit, feet) + suffix(unit)


def dimensions(laenge: float, breite: float = 0.0, unit: str = "mm",
               feet: bool = True, sep: str = " × ") -> str:
    """800 × 600 mm, 31.5" × 23.625", 2' 7 1/2" × 23 5/8" – ohne Breite nur die Länge."""
    unit = normalize_unit(unit)
    if breite <= 0:
        return length(laenge, unit, feet)
    if is_imperial(unit):
        return f"{length(laenge, unit, feet)}{sep}{length(breite, unit, feet)}"
    return f"{number(laenge, unit)}{sep}{number(breite, unit)}{suffix(unit)}"
