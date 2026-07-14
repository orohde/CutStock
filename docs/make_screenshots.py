"""Generate the documentation screenshots against a local dev server.

Creates a rich demo dataset via the REST API (materials, stock, blades,
two projects) and then drives the web UI with Playwright to capture the
screenshots used in README / website (light Horizon theme, German UI).

Usage:
    # 1) start a dev server with a THROWAWAY database:
    CUTSTOCK_DB=/tmp/cutstock-shots.db python -m uvicorn web.app:app --port 8010
    # 2) run this script (needs: pip install playwright && playwright install chromium):
    python docs/make_screenshots.py http://localhost:8010

Output: docs/screenshot_*.png (viewport 1280px @2x = 2560px wide).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
OUT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

def api(method: str, path: str, body: dict | None = None) -> dict | list | None:
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(req, data) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def seed_demo_data() -> dict:
    """Create the demo dataset; returns ids needed for the UI flow."""
    if api("GET", "/api/materials"):
        raise SystemExit("Database is not empty – use a fresh throwaway DB!")

    span = api("POST", "/api/materials", {
        "name": "Spanplatte weiß 19mm", "typ": "Platte", "dicke": 19.0,
        "maserung": "keine", "besaeumung": 10.0,
        "rest_min_laenge": 300.0, "rest_min_breite": 200.0})
    eiche = api("POST", "/api/materials", {
        "name": "Eiche Leimholz 18mm", "typ": "Platte", "dicke": 18.0,
        "maserung": "längs", "besaeumung": 5.0,
        "rest_min_laenge": 200.0, "rest_min_breite": 150.0})
    leiste = api("POST", "/api/materials", {
        "name": "Buchenleiste 20x40", "typ": "Stange",
        "querschnitt_breite": 20.0, "querschnitt_tiefe": 40.0,
        "rest_min_laenge": 150.0})

    for stock in [
        {"material_id": span["id"], "laenge": 2800, "breite": 2070, "stueckzahl": 8},
        # Remnant in stock (visible in the material tab) but deliberately too
        # small for any part, so the cut plans show full-size panels
        {"material_id": span["id"], "laenge": 350, "breite": 250, "stueckzahl": 1},
        {"material_id": eiche["id"], "laenge": 2500, "breite": 1250, "stueckzahl": 3},
        {"material_id": leiste["id"], "laenge": 2400, "breite": 0, "stueckzahl": 12},
        {"material_id": leiste["id"], "laenge": 1000, "breite": 0, "stueckzahl": 2},
    ]:
        api("POST", "/api/stock", stock)

    api("POST", "/api/blades", {"name": "Standard 3,0 mm", "schnittbreite": 3.0})
    api("POST", "/api/blades", {"name": "Feinschnitt 2,4 mm", "schnittbreite": 2.4})

    schrank = api("POST", "/api/projects", {"name": "Kleiderschrank Schlafzimmer"})
    P, S = "Platte", "Stange"
    for label, typ, mat, l, b, n, grain in [
        ("Seitenwand",       P, span, 2000, 600, 2, "längs"),
        ("Boden",            P, span, 1000, 600, 1, "egal"),
        ("Deckel",           P, span, 1000, 600, 1, "egal"),
        ("Mittelwand",       P, span, 1926, 580, 1, "längs"),
        ("Tür",              P, span,  996, 1985, 2, "längs"),
        ("Einlegeboden",     P, span,  481, 550, 6, "egal"),
        ("Schubladenfront",  P, span,  480, 200, 3, "längs"),
        ("Schubladenseite",  P, span,  500, 150, 6, "egal"),
        ("Schubladenboden",  P, span,  450, 480, 3, "egal"),
        ("Sockelblende",     P, span, 1000, 100, 1, "egal"),
        ("Kleiderstange",    S, leiste, 950, 0, 2, "egal"),
        ("Rahmenleiste",     S, leiste, 580, 0, 8, "egal"),
        ("Sockelleiste",     S, leiste, 960, 0, 2, "egal"),
    ]:
        api("POST", f"/api/projects/{schrank['id']}/parts", {
            "label": label, "typ": typ, "material_id": mat["id"],
            "laenge": l, "breite": b, "stueckzahl": n,
            "gesaegt_anzahl": 0, "maserung": grain})

    bank = api("POST", "/api/projects", {"name": "Gartenbank Eiche"})
    for label, l, b, n, grain in [
        ("Sitzlatte", 1500, 90, 6, "längs"),
        ("Lehnenlatte", 1500, 70, 3, "längs"),
        ("Seitenteil", 850, 600, 2, "längs"),
        ("Querstrebe", 1360, 80, 2, "egal"),
    ]:
        api("POST", f"/api/projects/{bank['id']}/parts", {
            "label": label, "typ": P, "material_id": eiche["id"],
            "laenge": l, "breite": b, "stueckzahl": n,
            "gesaegt_anzahl": 0, "maserung": grain})

    # Light theme + German UI + mm for consistent screenshots
    api("PUT", "/api/settings", {"language": "de", "theme": "light", "unit": "mm"})

    return {"span": span["id"], "leiste": leiste["id"], "schrank": schrank["id"]}


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

def shoot(ids: dict):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 860},
                                device_scale_factor=2)
        page.goto(BASE)
        page.wait_for_selector("#material-table tbody tr")

        # 1) Material & Lager (Spanplatte ausgewählt → Lagerbestand rechts)
        page.click('#material-table tbody tr:has-text("Spanplatte")')
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "screenshot_material.png"))

        # 2) Projekte (Kleiderschrank ausgewählt → Teileliste)
        page.click('.tab-btn[data-tab="projects"]')
        page.wait_for_selector("#project-list tbody tr")
        page.click('#project-list tbody tr:has-text("Kleiderschrank")')
        page.wait_for_selector('#parts-table tbody tr:has-text("Seitenwand")')
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "screenshot_projekte.png"))

        # 3) Optimierung 2D (Platten) inkl. aufgeklappter Schnittfolge.
        # Größerer Viewport + Scroll auf die Statistik, damit Kacheln,
        # erster Plan und Schnittfolge gemeinsam ins Bild passen.
        page.click('.tab-btn[data-tab="optimization"]')
        page.select_option("#opt-project", str(ids["schrank"]))
        page.select_option("#opt-material", str(ids["span"]))
        page.select_option("#opt-algorithm", "nested")
        page.click("#btn-optimize")
        page.wait_for_selector(".cut-plan-canvas", timeout=30000)
        # Erst Viewport setzen und den Resize-Rerender (250 ms Debounce)
        # abwarten – der baut die Karten neu und würde ein zuvor geöffnetes
        # <details> wieder schließen. Dann Schnittfolge öffnen.
        page.set_viewport_size({"width": 1280, "height": 1060})
        page.wait_for_timeout(800)
        page.eval_on_selector(".cut-seq", "d => d.open = true")
        page.evaluate("document.getElementById('opt-stats').scrollIntoView(); window.scrollBy(0, -12)")
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUT / "screenshot_platten.png"))
        page.set_viewport_size({"width": 1280, "height": 860})
        page.wait_for_timeout(600)

        # 4) Werkstatt-Modus: zwei Teile abhaken, damit Fortschritt,
        # Häkchen und "Als Nächstes"-Markierung sichtbar sind
        page.click("#btn-saw-mode")
        page.wait_for_selector(".saw-piece")
        page.click(".saw-piece >> nth=0")
        page.wait_for_timeout(500)
        page.click(".saw-piece >> nth=1")
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "screenshot_werkstatt.png"))
        page.click("#saw-close")

        # 5) Optimierung 1D (Stangen)
        page.select_option("#opt-material", str(ids["leiste"]))
        page.click("#btn-optimize")
        page.wait_for_selector(".cut-plan-canvas", timeout=30000)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "screenshot_optimierung.png"))

        # 6) Einstellungen (ganze Seite inkl. Etiketten + Tastenkürzel)
        page.click('.tab-btn[data-tab="settings"]')
        page.wait_for_selector("#settings-label-format")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "screenshot_einstellungen.png"), full_page=True)

        browser.close()


if __name__ == "__main__":
    ids = seed_demo_data()
    shoot(ids)
    print("Screenshots geschrieben nach", OUT)
