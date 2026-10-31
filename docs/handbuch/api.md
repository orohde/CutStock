# REST-API

[← Handbuch](README.md)

Jede Funktion der Oberflaeche ist auch per REST-API unter `/api/` erreichbar -- die Oberflaeche selbst nutzt nichts anderes. Alle Endpoints akzeptieren und liefern JSON. Eine automatisch erzeugte, ausprobierbare Beschreibung aller Endpoints liefert CutStock unter `/docs`.

Fuer Programme, Scanner und Maschinen gilt:

- Materialien gehen ueber ID **oder Kuerzel** (`AP40`), Stuecke ueber ID **oder Code** (`AP40-07`, vom Etikett), Lagerorte ueber ID **oder Namen**.
- Fehler der Lager-Befehle haben einen festen Code: `{"detail": {"code": "stueck_reserviert", "message": "...", "projekt": "..."}}`.
- Jede Lagerbuchung landet im Lagerjournal, mit Quelle `api` oder `ui`.

## Authentifizierung

Wenn ein API-Key konfiguriert ist (Einstellungen-Seite), muessen externe Anfragen ihn als Bearer-Token mitschicken:

```bash
curl -H "Authorization: Bearer DEIN_API_KEY" http://cutstock:8420/api/materials
```

Anfragen von der eigenen Web-Oberflaeche (Same-Origin) und von localhost sind immer ohne Key erlaubt.

## Endpoints

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
| GET | `/api/stock/{id}/pieces` | Einzelstuecke auflisten (Code, Lagerort, reserviert fuer) |
| GET | `/api/pieces/{id oder Code}` | Stueck suchen: Material, Mass, Lagerort, Reservierung |
| PUT | `/api/pieces/{id oder Code}` | Notiz eines Stuecks aendern |
| GET/POST/DELETE | `/api/materials/{id}/image` | Materialbild lesen, hochladen, entfernen |
| **Lager** (siehe unten) | | |
| GET | `/api/locations` | Lagerorte mit Anzahl Materialien und Stuecke |
| POST | `/api/locations` | Lagerort anlegen `{"name": "Regal 3"}` |
| PUT | `/api/locations/{id oder Name}` | Lagerort umbenennen |
| DELETE | `/api/locations/{id oder Name}?ziel=…` | Lagerort loeschen; genutzt → `ziel` noetig |
| GET | `/api/locations/{id oder Name}/contents` | Was dort liegt: Materialien mit Stuecken |
| PUT | `/api/materials/{id oder Kuerzel}/location` | Material einem Lagerort zuweisen |
| POST | `/api/stock/receive` | Zugang: Stuecke einbuchen, liefert die neuen Codes |
| POST | `/api/pieces/{id oder Code}/take` | Stueck entnehmen (mit Grund) |
| GET | `/api/waste` | Inhalt der Abfallkiste |
| POST | `/api/waste` | Abschnitte in die Abfallkiste legen |
| POST | `/api/waste/take` | Abschnitte aus der Abfallkiste nehmen |
| DELETE | `/api/waste?material=…` | Abfallkiste leeren (ganz oder je Material) |
| GET | `/api/journal?material=…&seit=…` | Lagerjournal, neueste Buchung zuerst |
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
| PUT | `/api/projects/{id}` | Projekt aktualisieren (Name, Anzahl Exemplare) |
| DELETE | `/api/projects/{id}` | Projekt loeschen |
| POST | `/api/projects/{id}/clone` | Projekt kopieren |
| POST | `/api/projects/{id}/copy-parts` | Teile in ein Projekt kopieren |
| POST | `/api/projects/{id}/restart` | Projekt neu starten (Fortschritt 0, Plaene weg, Lager bleibt) |
| **Teile** | | |
| GET | `/api/projects/{id}/parts` | Teile eines Projekts auflisten |
| POST | `/api/projects/{id}/parts` | Teil hinzufuegen |
| PUT | `/api/parts/{id}` | Teil aktualisieren (optional `vorrat`: Regal-Bestand setzen) |
| DELETE | `/api/parts/{id}` | Teil loeschen |
| **Optimierung und Plaene** | | |
| POST | `/api/optimize` | Optimieren und als Plan des Projekts fuer das Material speichern |
| GET | `/api/projects/{id}/plans/{material_id}` | Gespeicherten Plan abrufen (`null`, wenn keiner existiert) |
| POST | `/api/plan-pieces/{id}` | Stueck als gesaegt markieren/zuruecknehmen (`{"gesaegt": true}`), aktualisiert Fortschritt und Lager |
| POST | `/api/plans/{id}/confirm-all` | Alle offenen Stuecke des Plans als gesaegt markieren |
| DELETE | `/api/plans/{id}` | Plan verwerfen (gibt reservierte Stuecke frei) |
| GET | `/api/projects/{id}/fill-candidates/{material_id}` | Moegliche Fuellteile aus anderen Projekten |
| GET | `/api/sammel/{material_id}` | Sammelplan-Status und moegliche Projekte |
| POST | `/api/sammel/optimize` | Sammelplan anlegen/ersetzen und berechnen |
| GET | `/api/parts` | Teile aller Projekte (Reiter "Teile") |
| POST | `/api/cut-lists` | Schnittliste aus einzelnen Teilen anlegen |
| POST | `/api/sammel/compare` | Vergleich getrennt/gemeinsam (ohne Speichern) |
| POST | `/api/projects/{id}/take-stock/{material_id}` | Teile-Vorrat ("Regal") als gesaegt uebernehmen |
| **Export** | | |
| POST | `/api/pdf` | PDF-Schnittplan erzeugen |
| POST | `/api/labels` | Etiketten-PDF erzeugen |
| **System** | | |
| GET | `/api/version` | App-Version und Links |
| GET | `/api/license` | Lizenzstatus |
| GET | `/api/settings` | Einstellungen lesen |
| PUT | `/api/settings` | Einstellungen aendern |
| GET | `/api/backup` | Datenbank-Backup herunterladen (ZIP) |
| POST | `/api/restore` | Aus Backup wiederherstellen (ZIP) |
| GET | `/api/i18n/{lang}` | Uebersetzungen fuer eine Sprache |

## Optimierungsanfrage

```json
POST /api/optimize
{
  "project_id": 1,
  "material_id": 3,
  "blade_id": 1,
  "algorithm": "nested",
  "reste_zuerst": false,
  "fuellteile": [{"teil_id": 42, "modus": "auffuellen", "menge": 0}],
  "fuell_alle_reste": false
}
```

Algorithmus-Optionen: `greedy`, `nested`, `ga`. `reste_zuerst`, `fuellteile` und `fuell_alle_reste` sind optional (Fuellteil-Modus `auffuellen` oder `fest`; ohne `fuellteile` bleibt die Auswahl des gespeicherten Plans).

Die Antwort ist der gespeicherte Plan: `plan_id`, `schnittplaene` (je Brett u. a. `stueck_code`, `lagerort`, `platzierungen` mit `id` und `gesaegt`), `fehlende_teile`, `gesamt_verschnitt_prozent`, `materialbedarf` (zusaetzlich benoetigtes Material -- leer wenn alles passt) sowie Hinweise `veraltet` und `lager_fehlt`.

## Lager-Befehle

Zugang -- liefert die Codes fuers Beschriften:

```json
POST /api/stock/receive
{"material": "AP40", "laenge": 6000, "anzahl": 4}

→ {"stock_id": 12, "codes": ["AP40-21", "AP40-22", "AP40-23", "AP40-24"], "lagerort": "Wandregal Alu"}
```

`breite` nur bei Platten, `ist_rest: true` fuer Reststuecke (liegen dann am Reste-Ort).

Stueck entnehmen:

```json
POST /api/pieces/AP40-07/take
{"grund": "verbraucht", "notiz": "Musterbau"}
```

`grund`: `verbraucht`, `verkauft`, `defekt` oder `abfall` (= in die Abfallkiste, wenn eingeschaltet).
Ist das Stueck von einem gespeicherten Plan reserviert, kommt `409` mit `code: "stueck_reserviert"` und dem Projekt; mit `"trotzdem": true` wird es dennoch entnommen. Der Plan zeigt danach `lager_fehlt` und `fehlende_stuecke`.

Material einem Lagerort zuweisen:

```json
PUT /api/materials/AP40/location
{"lagerort": "Wandregal Alu", "lagerort_reste": "Restekiste Alu"}
```

`lagerort_reste: ""` = Reste liegen beim Material. Beim Anlegen/Aendern eines Materials ueber `/api/materials` wird ein unbekannter Lagerort-Name automatisch angelegt.

Lagerort loeschen, der noch genutzt wird:

```
DELETE /api/locations/Regal%203            → 409 {"code": "lagerort_in_benutzung", "materialien": [...]}
DELETE /api/locations/Regal%203?ziel=Lager → 204, die Materialien liegen jetzt in "Lager"
```

Abfallkiste (ohne Codes, nur Material + Mass + Anzahl):

```json
POST /api/waste        {"material": "AP40", "laenge": 180, "anzahl": 2}
POST /api/waste/take   {"material": "AP40", "laenge": 180}
DELETE /api/waste?material=AP40
```

Lagerjournal: `GET /api/journal?material=AP40&seit=1767225600&limit=100` -- je Eintrag `zeit` (Unix-Zeit), `art` (`zugang`, `korrektur_ab`, `entnahme`, `plan_verbrauch`, `plan_zurueck`, `rest_ein`, `rest_zurueck`, `abfall_ein`, `abfall_zurueck`, `abfall_ab`, `abfall_leer`, `material_lagerort`, `lagerort_neu`, `lagerort_umbenannt`, `lagerort_geloescht`), `code`, Masse, `anzahl`, `quelle` (`ui`/`api`), `notiz`.
