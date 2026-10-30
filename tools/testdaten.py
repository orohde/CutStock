#!/usr/bin/env python3
"""Umfangreiche Testdaten in eine CutStock-Instanz einspielen (über die REST-API).

Gedacht für die Test-Instanz, NICHT für echte Daten:

    python3 tools/testdaten.py http://10.10.20.20:8422 --leeren

--leeren löscht vorher ALLE Projekte, Materialien (inkl. Lager) und Sägeblätter
der Zielinstanz. Zum Schutz verweigert das Skript Ziele, die nach der
Live-Instanz aussehen (Port 8420, cutstock.rohde.one).

Inhalt: Alu-Profile, Holzbalken/Latten (Stangen) und Holzplatten mit vollen
Längen/Formaten, Reststücken und einzelnen Defekten, vier Sägeblätter und
mehrere Projekte, auch mit Teilen aus verschiedenen Materialien. Materialien
haben Kürzel und Lagerorte, Reste liegen in eigenen Restekisten.
Nur Standardbibliothek – läuft ohne venv.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

LIVE_MERKMALE = (":8420", "cutstock.rohde.one")

# ---------------------------------------------------------------------------
# Materialien: name → (typ, Felder, Lager [(länge, breite, anzahl)], Defekte)
# Defekte: [(lager_index, stück_nr, position, position_y, länge, breite)]
# ---------------------------------------------------------------------------

STANGE, PLATTE = "Stange", "Platte"

MATERIALIEN = {
    # ---- Alu-Profile (Systemprofile Nut 8 / Nut 6, Rohre, Flach, Winkel) ----
    "Alu Profil 30x30 Nut 8": (STANGE, dict(querschnitt_breite=30, querschnitt_tiefe=30,
                                            besaeumung=2, rest_min_laenge=150),
                               [(2000, 0, 10), (1000, 0, 2), (1180, 0, 3), (640, 0, 5), (310, 0, 6)], []),
    "Alu Profil 40x40 Nut 8": (STANGE, dict(querschnitt_breite=40, querschnitt_tiefe=40,
                                            besaeumung=2, rest_min_laenge=150),
                               [(2000, 0, 14), (1000, 0, 2), (1520, 0, 2), (870, 0, 4), (420, 0, 3)], []),
    "Alu Profil 40x80 Nut 8": (STANGE, dict(querschnitt_breite=40, querschnitt_tiefe=80,
                                            besaeumung=2, rest_min_laenge=200),
                               [(2000, 0, 8), (1000, 0, 2), (960, 0, 2)], []),
    "Alu Profil 20x20 Nut 6": (STANGE, dict(querschnitt_breite=20, querschnitt_tiefe=20,
                                            besaeumung=1, rest_min_laenge=100),
                               [(2000, 0, 10), (1000, 0, 4), (450, 0, 6), (180, 0, 10)], []),
    "Alu Rechteckrohr 40x20x2": (STANGE, dict(querschnitt_breite=40, querschnitt_tiefe=20,
                                              besaeumung=1, rest_min_laenge=150),
                                 [(2000, 0, 8), (1000, 0, 2), (1350, 0, 2), (500, 0, 3)], []),
    "Alu Flachstange 30x5": (STANGE, dict(querschnitt_breite=30, querschnitt_tiefe=5,
                                          rest_min_laenge=100),
                             [(2000, 0, 6), (1000, 0, 2), (740, 0, 3)], []),
    "Alu Winkel 30x30x3": (STANGE, dict(querschnitt_breite=30, querschnitt_tiefe=30,
                                        rest_min_laenge=100),
                           [(2000, 0, 5), (1200, 0, 2), (260, 0, 8)], []),

    # ---- Holzbalken / Latten ----
    "KVH Fichte 60x120": (STANGE, dict(querschnitt_breite=60, querschnitt_tiefe=120,
                                       besaeumung=5, rest_min_laenge=300),
                          [(5000, 0, 6), (4000, 0, 4), (1800, 0, 2), (950, 0, 3)],
                          [(0, 2, 1200, 0, 60, 0), (0, 5, 3300, 0, 40, 0)]),
    "KVH Fichte 80x80": (STANGE, dict(querschnitt_breite=80, querschnitt_tiefe=80,
                                      besaeumung=5, rest_min_laenge=300),
                         [(5000, 0, 4), (2500, 0, 3), (700, 0, 4)], [(0, 1, 2400, 0, 50, 0)]),
    "Kantholz Douglasie 100x100": (STANGE, dict(querschnitt_breite=100, querschnitt_tiefe=100,
                                                besaeumung=5, rest_min_laenge=300),
                                   [(4000, 0, 4), (2000, 0, 2), (600, 0, 3)], []),
    "Dachlatte 24x48": (STANGE, dict(querschnitt_breite=24, querschnitt_tiefe=48,
                                     besaeumung=3, rest_min_laenge=250),
                        [(4000, 0, 20), (2000, 0, 6), (800, 0, 9)], [(0, 7, 1900, 0, 30, 0)]),
    "Rahmenholz 44x68 gehobelt": (STANGE, dict(querschnitt_breite=44, querschnitt_tiefe=68,
                                               besaeumung=3, rest_min_laenge=200),
                                  [(3000, 0, 12), (1500, 0, 4), (650, 0, 6)], []),
    "Leimholz Fichte Kantel 40x60": (STANGE, dict(querschnitt_breite=40, querschnitt_tiefe=60,
                                                  besaeumung=2, rest_min_laenge=200),
                                     [(2500, 0, 8), (1100, 0, 3), (480, 0, 5)], []),
    "Eiche Kantholz 50x50": (STANGE, dict(querschnitt_breite=50, querschnitt_tiefe=50,
                                          besaeumung=5, rest_min_laenge=200),
                             [(2400, 0, 6), (900, 0, 2)], [(0, 3, 600, 0, 25, 0)]),

    # ---- Holzplatten ----
    "MDF 19 mm": (PLATTE, dict(dicke=19, maserung="keine", besaeumung=10,
                               rest_min_laenge=300, rest_min_breite=200),
                  [(2800, 2070, 4), (1400, 2070, 2), (900, 600, 3), (650, 420, 4)], []),
    "MDF 8 mm (Rückwände)": (PLATTE, dict(dicke=8, maserung="keine", besaeumung=10,
                                          rest_min_laenge=300, rest_min_breite=200),
                             [(2800, 2070, 3), (1200, 800, 2)], []),
    "Spanplatte Melamin weiß 19 mm": (PLATTE, dict(dicke=19, maserung="keine", besaeumung=10,
                                                   rest_min_laenge=300, rest_min_breite=200),
                                      [(2800, 2070, 5), (1750, 900, 2), (800, 560, 3)], []),
    "Multiplex Birke 18 mm": (PLATTE, dict(dicke=18, maserung="längs", besaeumung=10,
                                           rest_min_laenge=300, rest_min_breite=150),
                              [(2500, 1250, 6), (1250, 1250, 2), (1100, 450, 3), (700, 300, 4)],
                              [(0, 2, 800, 400, 120, 80)]),
    "OSB/3 18 mm": (PLATTE, dict(dicke=18, maserung="keine", besaeumung=5,
                                 rest_min_laenge=400, rest_min_breite=300),
                    [(2500, 1250, 8), (1250, 625, 3)], []),
    "Siebdruckplatte 21 mm": (PLATTE, dict(dicke=21, maserung="längs", besaeumung=10,
                                           rest_min_laenge=300, rest_min_breite=200),
                              [(2500, 1250, 3), (1250, 600, 2)], []),
    "Leimholz Eiche 26 mm": (PLATTE, dict(dicke=26, maserung="längs", besaeumung=15,
                                          rest_min_laenge=250, rest_min_breite=120),
                             [(2000, 600, 6), (1200, 400, 3), (800, 300, 4)],
                             [(0, 1, 450, 280, 40, 40), (0, 4, 1500, 100, 60, 35)]),
    "Sperrholz Pappel 10 mm": (PLATTE, dict(dicke=10, maserung="längs", besaeumung=5,
                                            rest_min_laenge=200, rest_min_breite=150),
                               [(2500, 1220, 4), (900, 600, 2)], []),
}

SAEGEBLAETTER = [
    ("Formatkreissäge Holz 3,2 mm", 3.2),
    ("Plattensäge 4,4 mm", 4.4),
    ("Alu-Kappsäge 2,8 mm", 2.8),
    ("Handkreissäge 2,4 mm", 2.4),
]

# Projekte: name → [(label, material, länge, breite, stückzahl, maserung)]
PROJEKTE = {
    "Werkbank mit Alu-Gestell": [
        ("Bein", "Alu Profil 40x80 Nut 8", 860, 0, 4, "egal"),
        ("Längsriegel", "Alu Profil 40x40 Nut 8", 1920, 0, 4, "egal"),
        ("Querriegel", "Alu Profil 40x40 Nut 8", 720, 0, 4, "egal"),
        ("Fachbodenauflage", "Alu Profil 30x30 Nut 8", 720, 0, 2, "egal"),
        ("Arbeitsplatte", "Multiplex Birke 18 mm", 2000, 800, 1, "längs"),
        ("Fachboden", "OSB/3 18 mm", 1920, 720, 1, "egal"),
    ],
    "CNC-Fräse Rahmen": [
        ("Seitenträger", "Alu Profil 40x80 Nut 8", 1200, 0, 2, "egal"),
        ("Portalträger", "Alu Profil 40x80 Nut 8", 900, 0, 1, "egal"),
        ("Portalstütze", "Alu Profil 40x40 Nut 8", 300, 0, 2, "egal"),
        ("Querverbinder", "Alu Profil 40x40 Nut 8", 820, 0, 3, "egal"),
        ("Opferplatte", "MDF 19 mm", 1180, 860, 1, "egal"),
        ("Kabelkanal-Halter", "Alu Winkel 30x30x3", 60, 0, 12, "egal"),
    ],
    "Gartenhaus Unterkonstruktion": [
        ("Schwelle lang", "KVH Fichte 60x120", 3000, 0, 2, "egal"),
        ("Schwelle kurz", "KVH Fichte 60x120", 2380, 0, 2, "egal"),
        ("Bodenbalken", "KVH Fichte 60x120", 2380, 0, 5, "egal"),
        ("Eckpfosten", "Kantholz Douglasie 100x100", 2100, 0, 4, "egal"),
        ("Rähm", "KVH Fichte 80x80", 3000, 0, 2, "egal"),
        ("Dachlatte", "Dachlatte 24x48", 1600, 0, 14, "egal"),
        ("Bodenplatte", "OSB/3 18 mm", 1250, 1000, 6, "egal"),
    ],
    "Küchenunterschrank 60 cm": [
        ("Seite", "Spanplatte Melamin weiß 19 mm", 720, 560, 2, "egal"),
        ("Boden", "Spanplatte Melamin weiß 19 mm", 562, 560, 1, "egal"),
        ("Einlegeboden", "Spanplatte Melamin weiß 19 mm", 560, 520, 1, "egal"),
        ("Traverse", "Spanplatte Melamin weiß 19 mm", 562, 100, 2, "egal"),
        ("Rückwand", "MDF 8 mm (Rückwände)", 715, 595, 1, "egal"),
        ("Front", "MDF 19 mm", 716, 596, 1, "egal"),
    ],
    "Bücherregal Eiche": [
        ("Seitenwand", "Leimholz Eiche 26 mm", 1900, 300, 2, "längs"),
        ("Fachboden", "Leimholz Eiche 26 mm", 762, 280, 5, "längs"),
        ("Deckel", "Leimholz Eiche 26 mm", 814, 300, 1, "längs"),
        ("Sockelblende", "Leimholz Eiche 26 mm", 762, 80, 1, "längs"),
        ("Rückwand", "Sperrholz Pappel 10 mm", 1880, 800, 1, "längs"),
    ],
    "Hochbeet 200x100": [
        ("Eckpfosten", "Eiche Kantholz 50x50", 800, 0, 4, "egal"),
        ("Mittelpfosten", "Eiche Kantholz 50x50", 800, 0, 2, "egal"),
        ("Seitenbrett lang", "Siebdruckplatte 21 mm", 2000, 200, 4, "längs"),
        ("Seitenbrett kurz", "Siebdruckplatte 21 mm", 958, 200, 4, "längs"),
    ],
    "Schreibtisch höhenverstellbar": [
        ("Tischplatte", "Multiplex Birke 18 mm", 1600, 800, 1, "längs"),
        ("Kabelwanne Boden", "Multiplex Birke 18 mm", 1200, 150, 1, "längs"),
        ("Traverse", "Alu Rechteckrohr 40x20x2", 1100, 0, 2, "egal"),
        ("Fußausleger", "Alu Rechteckrohr 40x20x2", 700, 0, 2, "egal"),
        ("Leiste Kabelkanal", "Alu Flachstange 30x5", 1200, 0, 2, "egal"),
    ],
    "Werkstattwand Lochblech-Rahmen": [
        ("Rahmen senkrecht", "Rahmenholz 44x68 gehobelt", 1950, 0, 6, "egal"),
        ("Rahmen waagrecht", "Rahmenholz 44x68 gehobelt", 1100, 0, 9, "egal"),
        ("Halteleiste", "Leimholz Fichte Kantel 40x60", 1000, 0, 6, "egal"),
        ("Halter klein", "Alu Profil 20x20 Nut 6", 150, 0, 24, "egal"),
        ("Halter lang", "Alu Profil 20x20 Nut 6", 420, 0, 8, "egal"),
    ],
}


class Api:
    def __init__(self, base: str, key: str | None):
        self.base = base.rstrip("/")
        self.key = key

    def call(self, method: str, path: str, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.key:
            req.add_header("Authorization", f"Bearer {self.key}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} → HTTP {e.code}: {e.read().decode(errors='replace')}")


def leeren(api: Api):
    for p in api.call("GET", "/api/projects"):
        api.call("DELETE", f"/api/projects/{p['id']}")
    for m in api.call("GET", "/api/materials"):
        api.call("DELETE", f"/api/materials/{m['id']}")
    for b in api.call("GET", "/api/blades"):
        api.call("DELETE", f"/api/blades/{b['id']}")


# Kürzel und Lagerorte (Lagerort, Lagerort für Reste)
KUERZEL = {
    "Alu Profil 30x30 Nut 8": "AP30", "Alu Profil 40x40 Nut 8": "AP40",
    "Alu Profil 40x80 Nut 8": "AP4080", "Alu Profil 20x20 Nut 6": "AP20",
    "Alu Rechteckrohr 40x20x2": "AR4020", "Alu Flachstange 30x5": "AF30",
    "Alu Winkel 30x30x3": "AW30", "KVH Fichte 60x120": "KVH12",
    "KVH Fichte 80x80": "KVH8", "Kantholz Douglasie 100x100": "DG10",
    "Dachlatte 24x48": "DL", "Rahmenholz 44x68 gehobelt": "RH68",
    "Leimholz Fichte Kantel 40x60": "LF60", "Eiche Kantholz 50x50": "EK50",
    "MDF 19 mm": "MDF19", "MDF 8 mm (Rückwände)": "MDF8",
    "Spanplatte Melamin weiß 19 mm": "SPW19", "Multiplex Birke 18 mm": "MPX18",
    "OSB/3 18 mm": "OSB18", "Siebdruckplatte 21 mm": "SD21",
    "Leimholz Eiche 26 mm": "LHE26", "Sperrholz Pappel 10 mm": "SPP10",
}


def lagerorte(name: str, typ: str) -> tuple[str, str]:
    if name.startswith("Alu"):
        return "Wandregal Alu", "Restekiste Alu"
    if typ == STANGE:
        return "Holzregal Balken", "Restekiste Holz"
    return "Plattenständer", "Plattenwagen Reste"


def einspielen(api: Api):
    mat_ids: dict[str, int] = {}
    n_lager = n_defekte = 0
    for name, (typ, felder, lager, defekte) in MATERIALIEN.items():
        ort, ort_reste = lagerorte(name, typ)
        mid = api.call("POST", "/api/materials", {
            "name": name, "typ": typ, "kuerzel": KUERZEL.get(name, ""),
            "lagerort": ort, "lagerort_reste": ort_reste, **felder})["id"]
        mat_ids[name] = mid
        stock_ids = []
        for i, (laenge, breite, anzahl) in enumerate(lager):
            sid = api.call("POST", "/api/stock", {
                "material_id": mid, "laenge": laenge, "breite": breite,
                "stueckzahl": anzahl, "ist_rest": i >= 2})["id"]
            stock_ids.append(sid)
            n_lager += anzahl
            if i >= 2:   # kleinere Bestände sind Reste → liegen in der Restekiste
                for p in api.call("GET", f"/api/stock/{sid}/pieces"):
                    api.call("PUT", f"/api/pieces/{p['id']}", {"notiz": p["notiz"],
                                                               "lagerort": ort_reste})
        for idx, nr, pos, pos_y, laenge, breite in defekte:
            stueck = {s["nr"]: s for s in api.call("GET", f"/api/stock/{stock_ids[idx]}/pieces")}
            api.call("POST", f"/api/pieces/{stueck[nr]['id']}/defects", {
                "position": pos, "position_y": pos_y, "laenge": laenge, "breite": breite})
            n_defekte += 1

    for name, kerf in SAEGEBLAETTER:
        api.call("POST", "/api/blades", {"name": name, "schnittbreite": kerf})

    n_teile = 0
    for pname, teile in PROJEKTE.items():
        pid = api.call("POST", "/api/projects", {"name": pname})["id"]
        for label, mat, laenge, breite, anzahl, maserung in teile:
            api.call("POST", f"/api/projects/{pid}/parts", {
                "label": label, "typ": MATERIALIEN[mat][0], "material_id": mat_ids[mat],
                "laenge": laenge, "breite": breite, "stueckzahl": anzahl,
                "maserung": maserung})
            n_teile += anzahl

    print(f"{len(MATERIALIEN)} Materialien, {n_lager} Lagerstücke, {n_defekte} Defekte, "
          f"{len(SAEGEBLAETTER)} Sägeblätter, {len(PROJEKTE)} Projekte, {n_teile} Teile")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", help="z.B. http://10.10.20.20:8422")
    ap.add_argument("--leeren", action="store_true",
                    help="vorher alle Projekte, Materialien und Sägeblätter löschen")
    ap.add_argument("--key", help="API-Key, falls in der Instanz gesetzt")
    ap.add_argument("--sprache", default="de", choices=["de", "en", "fr", "it"],
                    help="Oberflächensprache der Instanz (Standard: de)")
    args = ap.parse_args()

    if any(m in args.url for m in LIVE_MERKMALE):
        sys.exit(f"Abbruch: {args.url} sieht nach der Live-Instanz aus.")
    api = Api(args.url, args.key)
    api.call("PUT", "/api/settings", {"language": args.sprache})
    if args.leeren:
        leeren(api)
    elif api.call("GET", "/api/materials"):
        sys.exit("Abbruch: Instanz enthält schon Materialien – mit --leeren neu befüllen.")
    einspielen(api)


if __name__ == "__main__":
    main()
