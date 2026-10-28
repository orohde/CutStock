"""Generate the documentation screenshots against a local dev server.

Creates a rich demo dataset via the REST API (materials with images, stock
with a marked defect, blades, three projects – panels and bars) and then
drives the web UI with Playwright to capture the screenshots used in
README / website (light Horizon theme, German or English UI).

Usage:
    # 1) start a dev server with a THROWAWAY database:
    CUTSTOCK_DB=/tmp/cutstock-shots.db python -m uvicorn web.app:app --port 8010
    # 2) run this script (needs: pip install playwright && playwright install chromium):
    python docs/make_screenshots.py http://localhost:8010
    # English UI + English demo data (website EN pages), needs its own fresh DB:
    python docs/make_screenshots.py http://localhost:8010 en

Output: docs/screenshot_*.png, docs/screenshot_*_en.png for English
(viewport 1280px @2x = 2560px wide).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
LANG = sys.argv[2] if len(sys.argv) > 2 else "de"
OUT = Path(__file__).resolve().parent
IMAGES = OUT / "demo_images"


# English demo data for the EN website pages (German strings are the keys)
EN = {
    "Spanplatte weiß 19mm": "White chipboard 19mm",
    "Eiche Leimholz 18mm": "Oak panel 18mm",
    "Buchenleiste 20x40": "Beech batten 20x40",
    "Kiefer Kantholz 44x44": "Pine timber 44x44",
    "Eiche": "Oak",
    "Astloch": "Knot hole",
    "Standard 3,0 mm": "Standard 3.0 mm",
    "Feinschnitt 2,4 mm": "Fine cut 2.4 mm",
    "Kleiderschrank Schlafzimmer": "Bedroom wardrobe",
    "Kleiderschrank": "wardrobe",
    "Seitenwand": "Side panel",
    "Boden": "Bottom",
    "Deckel": "Top",
    "Mittelwand": "Divider",
    "Tür": "Door",
    "Einlegeboden": "Shelf",
    "Schubladenfront": "Drawer front",
    "Schubladenseite": "Drawer side",
    "Schubladenboden": "Drawer bottom",
    "Sockelblende": "Plinth",
    "Kleiderstange": "Clothes rail",
    "Rahmenleiste": "Frame batten",
    "Sockelleiste": "Skirting",
    "Gartenbank Eiche": "Oak garden bench",
    "Sitzlatte": "Seat slat",
    "Lehnenlatte": "Backrest slat",
    "Seitenteil": "Side frame",
    "Querstrebe": "Cross brace",
    "Werkstattregal Kiefer": "Pine workshop shelf",
    "Pfosten": "Post",
    "Querriegel": "Rail",
    "Tiefenriegel": "Depth rail",
    "Diagonalstrebe": "Diagonal brace",
    "Fußleiste": "Foot rail",
    "Konsole": "Bracket",
}


def tr(text: str) -> str:
    return EN.get(text, text) if LANG == "en" else text


def shot(name: str) -> str:
    suffix = "" if LANG == "de" else f"_{LANG}"
    return str(OUT / f"screenshot_{name}{suffix}.png")


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


def upload_image(material_id: int, filename: str) -> None:
    """Multipart upload of a demo texture as material image."""
    boundary = "cutstock-demo-boundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
    body += (IMAGES / filename).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/materials/{material_id}/image",
                                 data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    urllib.request.urlopen(req).read()


def seed_demo_data() -> dict:
    """Create the demo dataset; returns ids needed for the UI flow."""
    if api("GET", "/api/materials"):
        raise SystemExit("Database is not empty – use a fresh throwaway DB!")

    span = api("POST", "/api/materials", {
        "name": tr("Spanplatte weiß 19mm"), "typ": "Platte", "dicke": 19.0,
        "maserung": "keine", "besaeumung": 10.0,
        "rest_min_laenge": 300.0, "rest_min_breite": 200.0})
    eiche = api("POST", "/api/materials", {
        "name": tr("Eiche Leimholz 18mm"), "typ": "Platte", "dicke": 18.0,
        "maserung": "längs", "besaeumung": 5.0,
        "rest_min_laenge": 200.0, "rest_min_breite": 150.0})
    leiste = api("POST", "/api/materials", {
        "name": tr("Buchenleiste 20x40"), "typ": "Stange",
        "querschnitt_breite": 20.0, "querschnitt_tiefe": 40.0,
        "rest_min_laenge": 150.0})
    kiefer = api("POST", "/api/materials", {
        "name": tr("Kiefer Kantholz 44x44"), "typ": "Stange",
        "querschnitt_breite": 44.0, "querschnitt_tiefe": 44.0,
        "rest_min_laenge": 200.0})

    for mat, img in [(span, "spanplatte.jpg"), (eiche, "eiche.jpg"),
                     (leiste, "buche.jpg"), (kiefer, "kiefer.jpg")]:
        upload_image(mat["id"], img)

    for stock in [
        {"material_id": span["id"], "laenge": 2800, "breite": 2070, "stueckzahl": 8},
        # Remnant in stock (visible in the material tab) but deliberately too
        # small for any part, so the cut plans show full-size panels
        {"material_id": span["id"], "laenge": 350, "breite": 250, "stueckzahl": 1},
        {"material_id": eiche["id"], "laenge": 2500, "breite": 1250, "stueckzahl": 3},
        {"material_id": leiste["id"], "laenge": 2400, "breite": 0, "stueckzahl": 12},
        {"material_id": leiste["id"], "laenge": 1000, "breite": 0, "stueckzahl": 2},
        {"material_id": kiefer["id"], "laenge": 3000, "breite": 0, "stueckzahl": 10},
    ]:
        created = api("POST", "/api/stock", stock)
        if stock["material_id"] == eiche["id"]:
            eiche_stock = created
        elif stock["material_id"] == span["id"] and stock["laenge"] == 2800:
            span_stock = created

    # Knot hole on oak board #1 – shows the badge, the piece list and the
    # hatched defect area in the cut plan
    piece1 = api("GET", f"/api/stock/{eiche_stock['id']}/pieces")[0]
    api("POST", f"/api/pieces/{piece1['id']}/defects",
        {"position": 900, "position_y": 420, "laenge": 80, "breite": 60})
    api("PUT", f"/api/pieces/{piece1['id']}", {"notiz": tr("Astloch")})

    api("POST", "/api/blades", {"name": tr("Standard 3,0 mm"), "schnittbreite": 3.0})
    api("POST", "/api/blades", {"name": tr("Feinschnitt 2,4 mm"), "schnittbreite": 2.4})

    schrank = api("POST", "/api/projects", {"name": tr("Kleiderschrank Schlafzimmer")})
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
            "label": tr(label), "typ": typ, "material_id": mat["id"],
            "laenge": l, "breite": b, "stueckzahl": n,
            "gesaegt_anzahl": 0, "maserung": grain})

    bank = api("POST", "/api/projects", {"name": tr("Gartenbank Eiche")})
    for label, l, b, n, grain in [
        ("Sitzlatte", 1500, 90, 6, "längs"),
        ("Lehnenlatte", 1500, 70, 3, "längs"),
        ("Seitenteil", 850, 600, 2, "längs"),
        ("Querstrebe", 1360, 80, 2, "egal"),
    ]:
        api("POST", f"/api/projects/{bank['id']}/parts", {
            "label": tr(label), "typ": P, "material_id": eiche["id"],
            "laenge": l, "breite": b, "stueckzahl": n,
            "gesaegt_anzahl": 0, "maserung": grain})

    # Bars with mixed lengths → varied, colourful 1D plan with remnants
    regal = api("POST", "/api/projects", {"name": tr("Werkstattregal Kiefer")})
    for label, l, n in [
        ("Pfosten", 1800, 4),
        ("Querriegel", 1150, 6),
        ("Tiefenriegel", 500, 6),
        ("Diagonalstrebe", 780, 2),
        ("Fußleiste", 1150, 2),
        ("Konsole", 320, 4),
    ]:
        api("POST", f"/api/projects/{regal['id']}/parts", {
            "label": tr(label), "typ": S, "material_id": kiefer["id"],
            "laenge": l, "breite": 0, "stueckzahl": n,
            "gesaegt_anzahl": 0, "maserung": "egal"})

    # Light theme + UI language + mm for consistent screenshots
    api("PUT", "/api/settings", {"language": LANG, "theme": "light", "unit": "mm"})

    return {"span": span["id"], "eiche": eiche["id"], "kiefer": kiefer["id"],
            "schrank": schrank["id"], "bank": bank["id"], "regal": regal["id"],
            "span_stock": span_stock}


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

def shoot(ids: dict):
    from playwright.sync_api import sync_playwright

    def optimize(page, project: int, material: int, algorithm: str = "nested"):
        page.select_option("#opt-project", str(project))
        page.select_option("#opt-material", str(material))
        page.select_option("#opt-algorithm", algorithm)
        page.click("#btn-optimize")
        page.wait_for_selector(".cut-plan-canvas", timeout=30000)
        page.wait_for_timeout(600)

    def hide_toasts(page):
        page.evaluate("document.querySelectorAll('[class*=toast]').forEach(e => e.remove())")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 860},
                                device_scale_factor=2)
        page.goto(BASE)
        page.wait_for_selector("#material-table tbody tr")

        # 1) Material & Lager: Eiche ausgewählt, Einzelstücke aufgeklappt
        # (Defekt-Badge + Notiz), Materialbilder als Thumbnails
        page.set_viewport_size({"width": 1280, "height": 440})
        page.click(f'#material-table tbody tr:has-text("{tr("Eiche")}")')
        page.wait_for_selector("#stock-table tbody tr .expand-toggle")
        page.wait_for_timeout(500)  # Lager-Rerender nach Materialwahl abwarten
        page.click("#stock-table tbody tr .expand-toggle")
        page.wait_for_selector("#stock-table td.expand-toggle.expanded")
        page.wait_for_timeout(500)
        page.mouse.move(1270, 430)
        page.wait_for_timeout(300)
        page.screenshot(path=shot("material"))
        page.set_viewport_size({"width": 1280, "height": 860})

        # 2) Projekte (Kleiderschrank ausgewählt → Teileliste)
        page.click('.tab-btn[data-tab="projects"]')
        page.wait_for_selector("#project-list tbody tr")
        page.click(f'#project-list tbody tr:has-text("{tr("Kleiderschrank")}")')
        page.wait_for_selector(f'#parts-table tbody tr:has-text("{tr("Seitenwand")}")')
        page.wait_for_timeout(300)
        page.screenshot(path=shot("projekte"))

        # 3) Optimierung 2D (Platten) inkl. aufgeklappter Schnittfolge.
        # Größerer Viewport + Scroll auf die Statistik, damit Kacheln,
        # erster Plan und Schnittfolge gemeinsam ins Bild passen.
        page.click('.tab-btn[data-tab="optimization"]')
        optimize(page, ids["schrank"], ids["span"])
        # Erst Viewport setzen und den Resize-Rerender (250 ms Debounce)
        # abwarten – der baut die Karten neu und würde ein zuvor geöffnetes
        # <details> wieder schließen. Dann Schnittfolge öffnen.
        page.set_viewport_size({"width": 1280, "height": 1060})
        page.wait_for_timeout(800)
        page.eval_on_selector(".cut-seq", "d => d.open = true")
        page.evaluate("document.getElementById('opt-stats').scrollIntoView(); window.scrollBy(0, -12)")
        page.wait_for_timeout(200)
        page.screenshot(path=shot("platten"))
        page.set_viewport_size({"width": 1280, "height": 860})
        page.wait_for_timeout(600)

        # 4) Materialbedarf: Lager absichtlich zu knapp (vor dem Werkstatt-Modus,
        # der sonst schon eine Platte verbraucht) → Kacheln
        # "Fehlende Teile" + "Materialbedarf" mit Button "Ins Lager"
        api("PUT", f"/api/stock/{ids['span_stock']['id']}", {
            "material_id": ids["span"], "laenge": 2800, "breite": 2070, "stueckzahl": 2})
        page.select_option("#opt-project", str(ids["bank"]))  # reset view
        optimize(page, ids["schrank"], ids["span"])
        hide_toasts(page)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        box = page.locator("#opt-stats").bounding_box()
        page.screenshot(path=shot("materialbedarf"),
                        clip={"x": 0, "y": 0, "width": 1280,
                              "height": box["y"] + box["height"] + 16})
        api("PUT", f"/api/stock/{ids['span_stock']['id']}", {
            "material_id": ids["span"], "laenge": 2800, "breite": 2070, "stueckzahl": 8})

        optimize(page, ids["schrank"], ids["span"])
        hide_toasts(page)

        # 5) Werkstatt-Modus: zwei Teile abhaken, damit Fortschritt,
        # Häkchen und "Als Nächstes"-Markierung sichtbar sind
        page.click("#btn-saw-mode")
        page.wait_for_selector(".saw-piece")
        page.click(".saw-piece >> nth=0")
        page.wait_for_timeout(500)
        page.click(".saw-piece >> nth=1")
        page.wait_for_timeout(500)
        page.screenshot(path=shot("werkstatt"))
        page.click("#saw-close")

        # 6) Optimierung 1D (Stangen): Werkstattregal mit gemischten Längen
        page.set_viewport_size({"width": 1280, "height": 1000})
        optimize(page, ids["regal"], ids["kiefer"])
        hide_toasts(page)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        page.screenshot(path=shot("optimierung"))

        # 7) Defekt im Schnittplan: Gartenbank auf Eiche mit Astloch (#1)
        optimize(page, ids["bank"], ids["eiche"])
        hide_toasts(page)
        page.locator(".cut-plan-card").first.screenshot(
            path=shot("defekt"))

        # 8) Einstellungen (ganze Seite inkl. Etiketten + Tastenkürzel)
        page.click('.tab-btn[data-tab="settings"]')
        page.wait_for_selector("#settings-label-format")
        page.wait_for_timeout(400)
        page.screenshot(path=shot("einstellungen"), full_page=True)

        browser.close()


if __name__ == "__main__":
    ids = seed_demo_data()
    shoot(ids)
    print("Screenshots geschrieben nach", OUT)
