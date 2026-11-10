"""Brother QL im Netzwerk: Status über IPP lesen, Druckdaten (core.ql) per IPP schicken und auf
„fertig“ warten. Über den rohen Port 9100 meldet der QL nichts zurück (Handbuch 5.9) – IPP schon.
"""

from __future__ import annotations

import re
import time

from core import ipp, ql

ATTRIBUTE = ["printer-state", "printer-state-reasons", "media-ready", "printer-make-and-model",
             "color-supported", "marker-colors", "document-format-supported"]

# printer-state-reasons (ohne -error/-warning/-report) → Fehlercode wie beim P-touch
GRUENDE = {"media-empty": "kein_band", "media-needed": "kein_band", "media-low": "",
           "cover-open": "deckel_offen", "door-open": "deckel_offen",
           "media-jam": "papierstau", "cutter-error": "messer_klemmt",
           "offline": "drucker_nicht_erreichbar", "shutdown": "drucker_nicht_erreichbar",
           "paused": "drucker_pausiert"}


def medium_aus(media_ready: list[str], zweifarbig: bool = False) -> ql.Medium | None:
    """„roll_current_29x0mm“ → 29 mm endlos; „…_62x29mm“ → vorgestanzt 62 × 29."""
    for m in media_ready:
        treffer = re.search(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)mm", str(m))
        if not treffer:
            continue
        b, l = float(treffer.group(1)), float(treffer.group(2))
        breite = round(b)
        if l < 1:
            return ql.Medium(breite, 0, zweifarbig)
        # vorgestanzt: nächstes bekanntes Maß (Rollen melden z. B. 90,3 statt 90)
        passend = [(abs(lb - l), lb) for (bb, lb) in ql.GESTANZT if bb == breite]
        if passend:
            abstand, laenge = min(passend)
            if abstand <= 2:
                return ql.Medium(breite, laenge, zweifarbig)
        return ql.Medium(breite, round(l), zweifarbig)
    return None


def _fehler_aus(zustand: int, gruende: list[str]) -> list[str]:
    fehler = []
    for g in gruende:
        g = str(g)
        if g in ("none", "") or g.endswith("-report"):
            continue
        kern = re.sub(r"-(error|warning)$", "", g)
        code = GRUENDE.get(kern, "drucker_fehler" if g.endswith("-error") else "")
        if code and code not in fehler:
            fehler.append(code)
    if zustand == 5 and not fehler:          # gestoppt ohne bekannten Grund
        fehler.append("drucker_fehler")
    return fehler


def status(adresse: str) -> dict:
    """Wie core.drucker.status(): {gefunden, modell, band_mm, laenge_mm, zweifarbig, medium,
    fehler, code}. band_mm = Rollenbreite, laenge_mm 0 = Endlosrolle."""
    try:
        a = ipp.Drucker(adresse, timeout=5).attribute(ATTRIBUTE)
    except ipp.IppFehler as e:
        return {"gefunden": False, "code": "drucker_nicht_erreichbar", "text": e.text}
    modell = str((a.get("printer-make-and-model") or [""])[0])
    farben = [str(f).lower() for f in a.get("marker-colors", [])]
    zweifarbig = bool((a.get("color-supported") or [False])[0]) or any(
        f not in ("#000000", "none", "") for f in farben)
    medium = medium_aus([str(x) for x in a.get("media-ready", [])], zweifarbig)
    fehler = _fehler_aus(int((a.get("printer-state") or [3])[0]),
                         [str(x) for x in a.get("printer-state-reasons", [])])
    if medium is None and "kein_band" not in fehler:
        fehler.append("kein_band")
    elif medium is not None and not medium.bekannt:
        fehler.append("rolle_unbekannt")
    out = {"gefunden": True, "modell": modell.removeprefix("Brother ").strip() or "Brother QL",
           "band_mm": medium.breite_mm if medium else 0,
           "laenge_mm": medium.laenge_mm if medium else 0,
           "zweifarbig": bool(medium and medium.zweifarbig),
           "medium": (medium.name() if medium else ""), "fehler": fehler,
           "code": fehler[0] if fehler else ""}
    return out


def medium_von(st: dict) -> ql.Medium:
    return ql.Medium(int(st["band_mm"]), int(st.get("laenge_mm") or 0),
                     bool(st.get("zweifarbig")))


def drucken(adresse: str, daten: bytes, etiketten: int, warten_s: float | None = None) -> dict:
    """Fertige QL-Druckdaten schicken und warten, bis der Drucker den Auftrag als fertig meldet.
    Fehler als ipp.IppFehler mit Code (kein_band, deckel_offen, drucker_fehler …)."""
    d = ipp.Drucker(adresse, timeout=15)
    job = d.drucken(daten, name="CutStock Etiketten")
    ende = time.monotonic() + (warten_s if warten_s is not None else 20 + 3 * etiketten)
    while time.monotonic() < ende:
        zustand, gruende = d.auftrag(job)
        if zustand == "fertig":
            return {"gedruckt": etiketten, "bestaetigt": True, "auftrag": job}
        if zustand in ("abgebrochen", "gestoppt"):
            st = status(adresse)
            code = st.get("code") or "drucker_fehler"
            raise ipp.IppFehler(code, ", ".join(gruende) or code)
        time.sleep(0.7)
    raise ipp.IppFehler("drucker_antwortet_nicht", "Printer did not report the job as finished")
