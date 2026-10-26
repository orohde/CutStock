# CutStock

**Verschnitt minimieren. Jedes Brett, jede Stange, jede Platte optimal nutzen.**

CutStock ist ein Werkzeug zur Verschnittoptimierung, das Holzwerkern, Makern und kleinen Werkstaetten hilft, das Maximum aus ihrem Material herauszuholen. Ob Plattenteile fuer ein Regal oder Stangenprofile fuer einen Rahmen -- CutStock berechnet den optimalen Schnittplan, verwaltet den Lagerbestand und exportiert druckfertige Schnittplaene als PDF.

CutStock gibt es in zwei Varianten, die denselben Optimierungskern teilen:

- **Desktop-App** (macOS, Windows) -- Doppelklick, laeuft offline, Daten bleiben lokal (oeffnet die Web-UI im Standard-Browser)
- **Web-App** (Docker) -- selbst gehostet, erreichbar von jedem Browser oder Tablet im Netzwerk

![CutStock Plattenoptimierung](docs/screenshot_platten.png)

> **[English version](README.md)**

## Funktionen

- **1D + 2D Optimierung** -- Stangen (1D Bin-Packing) und Platten (2D Guillotine-Packing) mit Saegeblatt-Schnittbreite (Kerf)
- **Drei Algorithmen** -- Schnell (Greedy), Nested Guillotine (intelligente Schnittrichtung), Gruendlich (Genetischer Algorithmus, ~95% Ausnutzung)
- **Maserungsrichtung** -- beruecksichtigt Holzmaserung pro Material und Teil (laengs, quer oder egal)
- **Besaeumung** -- konfigurierbarer Rand fuer beschaedigte Plattenkanten
- **Defekte markieren** -- Defektstellen (Astloecher, Risse, Verfaerbungen) pro Einzelstueck erfassen; der Optimierer umgeht sie automatisch
- **Einzelstueck-Nummerierung** -- bei mehreren gleichen Brettern gezielt angeben, welches Brett welchen Defekt hat; aufklappbare Stueckliste im Lagerbestand
- **Lagerverwaltung** -- Bestand verfolgen, verbrauchte Stuecke automatisch austragen, verwertbare Reste automatisch einbuchen
- **Projektverwaltung** -- Teile nach Projekten organisieren, Import/Export als JSON, Teilelisten-Import aus CSV
- **Visuelle Schnittplaene** -- farbkodierte Zuschnittschemata mit Labels und Massen
- **Schnittfolge** -- nummerierte, massgenaue Schrittliste pro Schnittplan (Kerf eingerechnet, auch im PDF)
- **Werkstatt-Modus** -- Vollbild-Touch-Ansicht fuers Tablet an der Saege: grosse Ziele, Fortschritt, Teile beim Saegen abhaken
- **Etiketten** -- druckbare Etiketten fuer Teile und Reste (A4-Boegen wie Avery 3475/L7160 oder Dymo/Brother-Etikettendrucker, freie Masse)
- **PDF-Export** -- kompaktes mehrseitiges Layout (2-spaltig fuer Stangen, proportional fuer Platten)
- **Statistik** -- detaillierte Verschnittanalyse pro Lagerstueck und Gesamtwerte
- **Backup/Restore** -- komplette Datenbank + Einstellungen als ZIP (Desktop)
- **Mehrsprachig** -- Deutsch, English, Francais, Italiano
- **SAP Horizon Design** -- identischer Fiori-Look in Desktop und Web, helles und dunkles Farbschema
- **Tastenkuerzel** -- komplett per Tastatur bedienbar, in der Web-App frei belegbar
- **Plattformuebergreifend** -- macOS (.app), Windows (.exe), Docker
- **Materialbedarf** -- wenn der Lagerbestand nicht reicht, wird eine Einkaufsliste angezeigt; per Klick direkt ins Lager uebernehmen
- **REST-API** -- vollstaendige API fuer externen Zugriff (Automatisierung, Skripte, Integrationen); optional per API-Key (Bearer-Token) geschuetzt
- **iCloud-Sync** -- Desktop-Datenbank und Einstellungen synchronisieren automatisch zwischen Macs

## Web-App (Docker)

Die Web-App stellt denselben Optimierungskern ueber ein FastAPI-Backend mit
SAP-Fiori-Oberflaeche (Horizon) bereit. Alle Assets sind gebuendelt -- zur
Laufzeit ist keine Internetverbindung noetig.

### Schnellstart mit Docker Compose

```yaml
services:
  cutstock:
    image: ghcr.io/orohde/cutstock:latest
    container_name: cutstock
    restart: unless-stopped
    ports:
      - "8420:8000"
    volumes:
      - ./data:/data
    environment:
      - CUTSTOCK_DB=/data/cutstock.db
```

```bash
docker compose up -d
```

Danach `http://localhost:8420` im Browser oeffnen.

### Schnellstart mit docker run

```bash
docker run -d --name cutstock \
  -p 8420:8000 \
  -v "$(pwd)/data:/data" \
  ghcr.io/orohde/cutstock:latest
```

### Image selbst bauen

```bash
git clone https://github.com/orohde/CutStock.git
cd CutStock
docker build -t cutstock .
docker run -d -p 8420:8000 -v "$(pwd)/data:/data" cutstock
```

### Hinweise

| Thema | Detail |
|-------|--------|
| Port | Container lauscht auf `8000`; Host-Port frei waehlbar (`8420` in den Beispielen) |
| Daten | SQLite-Datenbank + `settings.json` liegen im `/data`-Volume |
| Unraid | Als Volume-Mapping `/mnt/user/appdata/cutstock:/data` verwenden |
| API-Key | Optional; unter Einstellungen setzen, um die REST-API vor externem Zugriff zu schuetzen. Die Web-Oberflaeche funktioniert ohne. |
| Reverse Proxy | Reines HTTP-Backend, laeuft hinter nginx, Traefik, Zoraxy, Caddy, ... |
| Benutzer | Bewusst Single-User -- keine eingebaute Anmeldung; bei Veroeffentlichung Reverse Proxy/SSO vorschalten |

Die Web-Oberflaeche umfasst Materialien, Lager, Projekte, Teile, Optimierung
mit visuellen Schnittplaenen, PDF-Export und Einstellungen. Die Tastenkuerzel
stehen auf der Einstellungen-Seite und lassen sich dort umbelegen (Taste
anklicken, neue Taste druecken).

## Screenshots

### Material & Lager

Materialien (Platten, Stangen) mit Dicke, Querschnitt, Maserungsrichtung, Besaeumung und Rest-Schwellen verwalten. Der Lagerbestand zeigt die Stuecke des gewaehlten Materials -- bei mehreren gleichen Brettern aufklappbar mit Einzelstueck-Nummerierung und Defekt-Badges.

![Material & Lager](docs/screenshot_material.png)

### Projekte

Teile nach Projekten organisieren. Jedes Teil hat ein Label, Typ, Material, Masse, Stueckzahl und Maserungsrichtung. Projekte als JSON importieren/exportieren.

![Projekte](docs/screenshot_projekte.png)

### Optimierung -- Stangen

Projekt, Material, Saegeblatt und Algorithmus waehlen. Der Optimierer berechnet den besten Schnittplan und zeigt farbkodierte Zuschnittschemata mit Statistik.

![Optimierung Stangen](docs/screenshot_optimierung.png)

### Optimierung -- Platten

2D Guillotine-Packing fuer Plattenwerkstoffe. Alle Schnitte gehen von Kante zu Kante, so dass alle Reste Rechtecke bleiben und wiederverwendbar sind. Die nummerierte Schnittfolge unter jedem Plan sagt exakt, wo gesaegt wird -- die Saegeblattbreite ist bereits eingerechnet.

![Optimierung Platten](docs/screenshot_platten.png)

### Werkstatt-Modus

Vollbild-Ansicht fuers Tablet neben der Saege: eine Platte pro Seite, grosse Touch-Ziele, Gesamtfortschritt und "Als Naechstes"-Markierung. Abhaken aktualisiert Teile-Fortschritt und Lager live.

![Werkstatt-Modus](docs/screenshot_werkstatt.png)

### Einstellungen

Sprache, Farbschema (Horizon hell/dunkel), Masseinheit (mm/cm), Etiketten-Papierformat (A4-Boegen oder Etikettendrucker), Saegeblaetter, Tastenkuerzel und Backup/Restore konfigurieren.

![Einstellungen](docs/screenshot_einstellungen.png)

## Algorithmen

CutStock loest das klassische [Cutting-Stock-Problem](https://de.wikipedia.org/wiki/Verschnittproblem) mit drei Ansaetzen:

### Warum Guillotine-Schnitte?

Alle CutStock-Algorithmen verwenden **Guillotine-Schnitte** -- jeder Schnitt geht vollstaendig von Kante zu Kante. Das ist eine bewusste Entscheidung:

| Ansatz | Materialausnutzung | Reste | Benoetigte Werkzeuge |
|--------|-------------------|-------|---------------------|
| **Guillotine** (CutStock) | ~85-95% | Immer rechteckig | Tischkreissaege, Handkreissaege |
| **Freischnitt** | ~93-98% | L-foermig, T-foermig | CNC-Fraese noetig |

Guillotine-Schnitte lassen sich mit jeder normalen Saege ausfuehren. Die Reste sind immer saubere Rechtecke, die gelagert und wiederverwendet werden koennen. Die 5-10% bessere Ausnutzung von Freischnitt-Algorithmen erfordert eine CNC-Fraese und erzeugt unregelmaessige Reste, die kaum wiederverwendbar sind -- fuer die meisten Werkstaetten unpraktisch.

### 1D -- Stangen / Profile

- **Schnell (Greedy FFD):** First-Fit-Decreasing -- sortiert Teile nach Laenge, platziert jedes auf der ersten Stange, auf die es passt. Sofortiges Ergebnis.
- **Gruendlich (GA):** Genetischer Algorithmus -- entwickelt 80 Permutationen ueber 200 Generationen, um bessere Kombinationen zu finden.

### 2D -- Platten

- **Schnell (Greedy):** Best-Area-Fit Guillotine-Packing. Teilt immer zuerst horizontal (rechts + unterhalb).
- **Nested Guillotine:** Wie Greedy, testet aber an jedem Schnitt **beide Teilungsrichtungen** (horizontal und vertikal) und waehlt die, die den groessten nutzbaren Rest erzeugt. Bessere Ergebnisse bei komplexen Layouts mit asymmetrischen Teilen.
- **Gruendlich (GA):** Genetischer Algorithmus -- optimiert Platzierungsreihenfolge und Rotationsentscheidungen ueber 200 Generationen. Beste Ergebnisse, braucht aber 2-5 Sekunden.

### Alle Algorithmen beruecksichtigen:

- **Saegeblatt-Schnittbreite** -- wird bei jedem Schnitt abgezogen
- **Besaeumung** -- beschaedigte Kanten werden vor dem Zuschnitt entfernt
- **Maserungsrichtung** -- Teile werden nur in Orientierungen platziert, die zur Holzmaserung passen
- **Endlicher Bestand** -- verwendet kleinste/Rest-Stuecke zuerst, meldet Teile, die nicht passen
- **Materialbedarf** -- wenn Teile nicht passen, wird geschaetzt, wie viele zusaetzliche Bretter/Stangen benoetigt werden

## REST-API

Die Web-App stellt eine vollstaendige REST-API unter `/api/` bereit. Alle Endpoints akzeptieren und liefern JSON.

### Authentifizierung

Wenn ein API-Key konfiguriert ist (Einstellungen-Seite), muessen externe Anfragen ihn als Bearer-Token mitschicken:

```bash
curl -H "Authorization: Bearer DEIN_API_KEY" http://cutstock:8420/api/materials
```

Anfragen von der eigenen Web-Oberflaeche (Same-Origin) und von localhost sind immer ohne Key erlaubt.

### Endpoints

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| **Materialien** | | |
| GET | `/api/materials` | Alle Materialien auflisten |
| POST | `/api/materials` | Material anlegen |
| PUT | `/api/materials/{id}` | Material aktualisieren |
| DELETE | `/api/materials/{id}` | Material loeschen |
| **Lagerbestand** | | |
| GET | `/api/stock?material_id=N` | Lagerbestand auflisten (optionaler Filter) |
| POST | `/api/stock` | Lagereintrag anlegen |
| PUT | `/api/stock/{id}` | Lagereintrag aktualisieren |
| DELETE | `/api/stock/{id}` | Lagereintrag loeschen |
| GET | `/api/stock/{id}/pieces` | Einzelstuecke auflisten |
| PUT | `/api/pieces/{id}` | Einzelstueck aktualisieren |
| **Defekte** | | |
| GET | `/api/stock/{id}/defects` | Defekte eines Lagerstuecks |
| GET | `/api/pieces/{id}/defects` | Defekte eines Einzelstuecks |
| POST | `/api/pieces/{id}/defects` | Defekt hinzufuegen |
| PUT | `/api/defects/{id}` | Defekt aktualisieren |
| DELETE | `/api/defects/{id}` | Defekt loeschen |
| **Saegeblaetter** | | |
| GET | `/api/blades` | Saegeblaetter auflisten |
| POST | `/api/blades` | Saegeblatt anlegen |
| PUT | `/api/blades/{id}` | Saegeblatt aktualisieren |
| DELETE | `/api/blades/{id}` | Saegeblatt loeschen |
| **Projekte** | | |
| GET | `/api/projects` | Projekte auflisten |
| GET | `/api/projects/{id}` | Projekt abrufen |
| POST | `/api/projects` | Projekt anlegen |
| PUT | `/api/projects/{id}` | Projekt aktualisieren |
| DELETE | `/api/projects/{id}` | Projekt loeschen |
| **Teile** | | |
| GET | `/api/projects/{id}/parts` | Teile eines Projekts auflisten |
| POST | `/api/projects/{id}/parts` | Teil hinzufuegen |
| PUT | `/api/parts/{id}` | Teil aktualisieren |
| DELETE | `/api/parts/{id}` | Teil loeschen |
| **Optimierung** | | |
| POST | `/api/optimize` | Optimierung ausfuehren |
| POST | `/api/optimize/confirm` | Schnittplaene bestaetigen (Lager aktualisieren) |
| POST | `/api/optimize/mark-plan` | Einzelnen Plan als gesaegt markieren |
| **Export** | | |
| POST | `/api/pdf` | PDF-Schnittplan erzeugen |
| POST | `/api/labels` | Etiketten-PDF erzeugen |
| **System** | | |
| GET | `/api/version` | App-Version und Links |
| GET | `/api/settings` | Einstellungen lesen |
| PUT | `/api/settings` | Einstellungen aendern |
| GET | `/api/backup` | Datenbank-Backup herunterladen (ZIP) |
| POST | `/api/restore` | Aus Backup wiederherstellen (ZIP) |
| GET | `/api/i18n/{lang}` | Uebersetzungen fuer eine Sprache |

### Optimierungsanfrage

```json
POST /api/optimize
{
  "project_id": 1,
  "material_id": 3,
  "blade_id": 1,
  "algorithm": "nested"
}
```

Algorithmus-Optionen: `greedy`, `nested`, `ga`

Die Antwort enthaelt `schnittplaene` (Schnittplaene), `fehlende_teile` (nicht platzierte Teile), `gesamt_verschnitt_prozent` (Gesamtverschnitt in %) und `materialbedarf` (zusaetzlich benoetigtes Material -- leer wenn alles passt).

## Download (Desktop)

Fertige Binaries fuer macOS und Windows gibt es auf der [Releases-Seite](https://github.com/orohde/CutStock/releases).

> **Wichtig: Unsignierte Builds**
>
> Die Releases sind **nicht code-signiert** (kein kostenpflichtiges Apple/Microsoft-Entwicklerzertifikat).
> Das Betriebssystem zeigt beim ersten Start eine Sicherheitswarnung:
>
> - **macOS**: Rechtsklick auf die App, "Oeffnen" waehlen, dann nochmal "Oeffnen" klicken (Gatekeeper)
> - **Windows**: "Weitere Informationen" klicken, dann "Trotzdem ausfuehren" (SmartScreen)
>
> Das ist bei Open-Source-Software normal. Der Quellcode ist vollstaendig einsehbar.
>
> Die Desktop-App oeffnet den Standard-Browser -- keine zusaetzlichen Laufzeitumgebungen noetig.

## Installation (aus dem Quellcode)

### Desktop

Voraussetzungen: Python 3.12+, macOS/Windows

```bash
git clone https://github.com/orohde/CutStock.git
cd CutStock
./setup.sh        # Erstellt venv, installiert Abhaengigkeiten
./run.sh          # Starten (Entwicklung)
```

Standalone-App bauen:

```bash
./build.sh          # macOS: erstellt dist/CutStock.app
build_windows.bat   # Windows: erstellt dist\CutStock\CutStock.exe
```

### Web (ohne Docker)

```bash
git clone https://github.com/orohde/CutStock.git
cd CutStock
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-web.txt
CUTSTOCK_DB=./data/cutstock.db uvicorn web.app:app --host 0.0.0.0 --port 8000
```

## Datenspeicherung

| Variante | Datenbank | Einstellungen |
|----------|-----------|---------------|
| macOS | `iCloud Drive/CutStock/cutstock.db` | `iCloud Drive/CutStock/settings.json` |
| Windows | `%APPDATA%\CutStock\cutstock.db` | `%APPDATA%\CutStock\settings.json` |
| Docker | `/data/cutstock.db` (Volume) | `/data/settings.json` (Volume) |

Auf macOS synchronisieren Desktop-Datenbank und Einstellungen automatisch ueber iCloud Drive zwischen Macs. Ein Heartbeat-basierter Lock-Mechanismus verhindert gleichzeitigen Zugriff.

Desktop-App und Web-App teilen sich exakt dieselbe Oberflaeche: Der Desktop-Build
startet dasselbe FastAPI-Backend lokal und oeffnet es im Standard-Browser.
Es gibt kein separates "App-Fenster" -- was man auf macOS, Windows und Docker
sieht, ist dieselbe Web-UI. Eine Codebasis, ueberall identisch.

> **So funktioniert es**
>
> Beim Start von CutStock wird ein lokaler Webserver im Hintergrund gestartet
> und der Browser oeffnet sich automatisch unter `http://127.0.0.1:<Port>/`.
> Die App laeuft, bis man sie beendet:
>
> - **macOS**: CutStock ueber das Dock beenden (Rechtsklick -> Beenden) oder Cmd+Q
> - **Windows**: CutStock ueber den Task-Manager oder das System-Tray beenden
>
> Das Schliessen des Browser-Tabs stoppt den Server **nicht** -- man kann den
> Tab jederzeit wieder oeffnen oder die URL erneut aufrufen. Um CutStock
> vollstaendig zu stoppen, muss die App selbst beendet werden.
>
> Keine zusaetzlichen Laufzeitumgebungen oder Browser-Plugins erforderlich.

## Tech-Stack

- **Python 3.12+** -- Anwendungslogik
- **FastAPI + Uvicorn** -- Backend (Desktop lokal, Docker als Server)
- **SAP Fundamental Styles / Horizon Theme** -- Designsystem der UI (gebuendelt, Apache-2.0)
- **SQLite** -- lokale Datenbank (kein Server noetig)
- **reportlab** -- PDF-Erzeugung
- **PyInstaller** -- Standalone-App-Packaging
- **Docker** -- Container-Image fuer die Web-App

## Projektstruktur

```
CutStock/
  core/                    -- gemeinsam, GUI-unabhaengig
    db.py                  -- SQLite-Schema + Repository-Pattern
    models.py              -- Dataclasses (Material, Lager, Projekt, Teil, ...)
    optimize.py            -- 1D/2D-Optimierungsalgorithmen (Greedy + GA)
    pdf.py                 -- PDF-Export mit Schnittplan-Zeichnungen
    lock.py                -- iCloud-sicherer Heartbeat-Lock
    settings.py            -- JSON-basierte Einstellungen
  web/                     -- Anwendung (Backend + UI)
    app.py                 -- FastAPI-Backend (REST-API + statische Dateien)
    static/                -- Frontend (Vanilla JS/HTML/CSS)
      vendor/              -- gebuendelte Fundamental Styles + Horizon-Themes + Fonts
  ui/
    i18n.py                -- Uebersetzungen (DE/EN/FR/IT), auch vom Backend genutzt
  tests/
    test_optimize.py       -- Algorithmus-Tests
  desktop.py               -- Desktop-Einstiegspunkt (lokales FastAPI + Browser)
  desktop.spec             -- PyInstaller-Spec (macOS)
  desktop_win.spec         -- PyInstaller-Spec (Windows)
  Dockerfile               -- Container-Image der Web-App
  compose.yml              -- Docker-Compose-Beispiel
```

## Lizenz

**CC BY-NC-SA 4.0** -- frei fuer den persoenlichen, nicht-kommerziellen Gebrauch; Namensnennung erforderlich.

**Kommerzielle Nutzung:** Wer CutStock im Betrieb einsetzen moechte -- etwa in einer Schreinerei, Tischlerei oder einem anderen Gewerbe -- kann eine separate kommerzielle Lizenz erwerben. Anfragen gern ueber [worldgate.de/cutstock](https://worldgate.de/cutstock/).

Details siehe [LICENSE](LICENSE).

Die gebuendelten SAP Fundamental Styles und Horizon-Theme-Assets (`web/static/vendor/`) stehen unter Apache-2.0-Lizenz von SAP SE.

## Mitmachen

Beitraege willkommen! Bitte zuerst ein Issue eroeffnen, um die geplante Aenderung zu besprechen.

Fuer eine neue Sprache siehe `ui/i18n.py` -- einfach den Sprachcode zu `LANGUAGES` hinzufuegen und jede Zeile in `TRANSLATIONS` uebersetzen.
