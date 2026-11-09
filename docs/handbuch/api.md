# REST-API

[← Handbuch](README.md)

Jede Funktion der Oberfläche ist auch per REST-API unter `/api/` erreichbar -- die Oberfläche selbst nutzt nichts anderes. Alle Endpoints akzeptieren und liefern JSON. Eine automatisch erzeugte, ausprobierbare Beschreibung aller Endpoints liefert CutStock unter `/docs`.

Für Programme, Scanner und Maschinen gilt:

- Materialien gehen über ID **oder Kürzel** (`AP40`), Stücke über ID **oder Code** (`AP40-07`, vom Etikett), Lagerorte über ID **oder Namen**.
- Fehler der Lager-Befehle haben einen festen Code: `{"detail": {"code": "stueck_reserviert", "message": "...", "projekt": "..."}}`.
- Jede Lagerbuchung landet im Lagerjournal, mit Quelle `api` oder `ui`.

## Authentifizierung

Wenn ein API-Key konfiguriert ist (Einstellungen-Seite), müssen externe Anfragen ihn als Bearer-Token mitschicken:

```bash
curl -H "Authorization: Bearer DEIN_API_KEY" http://cutstock:8420/api/materials
```

Anfragen von der eigenen Web-Oberfläche (Same-Origin) und von localhost sind immer ohne Key erlaubt.

## Endpoints

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| **Materialien** | | |
| GET | `/api/materials` | Alle Materialien auflisten |
| POST | `/api/materials` | Material anlegen |
| PUT | `/api/materials/{id}` | Material aktualisieren (`saegeblatt_id`: Standard-Sägeblatt der Optimierung, 0 = erstes, weglassen = unverändert) |
| DELETE | `/api/materials/{id}` | Material löschen |
| **Lagerbestand** | | |
| GET | `/api/stock?material_id=N` | Lagerbestand auflisten (optionaler Filter) |
| POST | `/api/stock` | Lagereintrag anlegen |
| PUT | `/api/stock/{id}` | Lagereintrag aktualisieren |
| GET | `/api/stock/reorder` | Nachbestellliste: leere Normalmaße und Materialien ohne Bestand |
| DELETE | `/api/stock/{id}` | Lagereintrag löschen |
| GET | `/api/stock/{id}/pieces` | Einzelstücke auflisten (Code, Lagerort, reserviert für) |
| GET | `/api/pieces/{id oder Code}` | Stück suchen: Material, Mass, Lagerort, Reservierung |
| PUT | `/api/pieces/{id oder Code}` | Notiz eines Stücks ändern |
| GET/POST/DELETE | `/api/materials/{id}/image` | Materialbild lesen, hochladen, entfernen |
| **Lager** (siehe unten) | | |
| GET | `/api/locations` | Lagerorte mit Anzahl Materialien und Stücke |
| POST | `/api/locations` | Lagerort anlegen `{"name": "Regal 3"}` |
| PUT | `/api/locations/{id oder Name}` | Lagerort umbenennen |
| DELETE | `/api/locations/{id oder Name}?ziel=…` | Lagerort löschen; genutzt → `ziel` nötig |
| GET | `/api/locations/{id oder Name}/contents` | Was dort liegt: Materialien mit Stücken |
| PUT | `/api/materials/{id oder Kuerzel}/location` | Material einem Lagerort zuweisen |
| POST | `/api/stock/receive` | Zugang: Stücke einbuchen, liefert die neuen Codes |
| POST | `/api/pieces/{id oder Code}/take` | Stück entnehmen (mit Grund) |
| GET | `/api/waste` | Inhalt der Abfallkiste |
| POST | `/api/waste` | Abschnitte in die Abfallkiste legen |
| POST | `/api/waste/take` | Abschnitte aus der Abfallkiste nehmen |
| DELETE | `/api/waste?material=…` | Abfallkiste leeren (ganz oder je Material) |
| GET | `/api/journal?material=…&seit=…` | Lagerjournal, neueste Buchung zuerst |
| **Defekte** | | |
| GET | `/api/stock/{id}/defects` | Defekte eines Lagerstücks |
| GET | `/api/pieces/{id}/defects` | Defekte eines Einzelstücks |
| POST | `/api/pieces/{id}/defects` | Defekt hinzufügen |
| PUT | `/api/defects/{id}` | Defekt aktualisieren |
| DELETE | `/api/defects/{id}` | Defekt löschen |
| **Sägeblätter** | | |
| GET | `/api/blades` | Sägeblätter auflisten |
| POST | `/api/blades` | Sägeblatt anlegen |
| PUT | `/api/blades/{id}` | Sägeblatt aktualisieren |
| DELETE | `/api/blades/{id}` | Sägeblatt löschen |
| **Projekte** | | |
| GET | `/api/projects?art=` | Projekte auflisten; ohne `art` Projekte und Sägeaufträge, `art=projekt` nur Projekte, `art=liste` nur Sägeaufträge, `art=sammel` nur Sammelpläne, `art=vorlage` nur Vorlagen, `art=alle` alles außer Vorlagen |
| GET | `/api/projects/{id}` | Projekt abrufen |
| POST | `/api/projects` | Projekt anlegen |
| PUT | `/api/projects/{id}` | Projekt aktualisieren (Name, Anzahl Exemplare) |
| DELETE | `/api/projects/{id}` | Projekt oder Sammelplan löschen (Gesägtes bleibt in den Projekten) |
| POST | `/api/projects/{id}/clone` | Projekt kopieren |
| POST | `/api/projects/{id}/copy-parts` | Teile in ein Projekt kopieren |
| POST | `/api/projects/{id}/restart` | Projekt neu starten (Fortschritt 0, Pläne weg, Lager bleibt) |
| POST | `/api/projects/{id}/as-template` | Projekt, Sägeauftrag oder Vorlage als neue Vorlage speichern (`name` optional) |
| **Vorlagen** | | |
| POST | `/api/templates` | Leere Vorlage anlegen `{"name": "Regal A"}` (Teile über `/api/projects/{id}/parts`) |
| POST | `/api/templates/{id}/run` | Durchgang: Sägeauftrag aus der Vorlage anlegen `{"saetze": 3, "name": ""}` |
| GET | `/api/templates/{id}/runs` | Verlauf der Durchgänge (neueste zuerst) |
| **Teile** | | |
| GET | `/api/projects/{id}/parts` | Teile eines Projekts auflisten |
| POST | `/api/projects/{id}/parts` | Teil hinzufügen |
| PUT | `/api/parts/{id}` | Teil aktualisieren (optional `vorrat`: Fertigteile setzen) |
| DELETE | `/api/parts/{id}` | Teil löschen |
| **Optimierung und Pläne** | | |
| GET | `/api/worklist?fertige=` | Arbeitsliste der Optimierung: Sammelpläne, Sägeaufträge, Projekte je Material mit Status und Fortschritt |
| POST | `/api/optimize` | Optimieren und als Plan des Projekts für das Material speichern |
| POST | `/api/plans/{id}/fill-choice` | Füllung einer Gruppe gleicher Stangenreste wählen (`wahl: null` = Automatik) |
| GET | `/api/projects/{id}/plans/{material_id}` | Gespeicherten Plan abrufen (`null`, wenn keiner existiert) |
| POST | `/api/plan-pieces/{id}` | Stück als gesägt markieren/zurücknehmen (`{"gesaegt": true}`), aktualisiert Fortschritt und Lager |
| POST | `/api/plans/{id}/confirm-all` | Alle offenen Stücke des Plans als gesägt markieren |
| DELETE | `/api/plans/{id}` | Plan verwerfen (gibt reservierte Stücke frei) |
| GET | `/api/projects/{id}/fill-candidates/{material_id}` | Mögliche Füllteile aus anderen Projekten |
| GET | `/api/sammel/{material_id}` | Sammelplan-Status und mögliche Projekte |
| POST | `/api/sammel` | Sammelplan anlegen (Material und Projekte, noch ohne Schnittplan) |
| PUT | `/api/sammel/{id oder Kuerzel}/members` | Mitglieder des Sammelplans eines Materials ersetzen |
| POST | `/api/sammel/optimize` | Sammelplan anlegen/ersetzen und berechnen |
| GET | `/api/parts` | Teile aller Projekte mit Verplanung: `beauftragt`, `auftraege`, `verplant`, `sammelplan`, `verfuegbar` (Reiter "Teile") |
| GET | `/api/parts/materials` | Verfügbare Teile je Material mit grober Lager-Schätzung (`bedarf`, `lager`, `reicht`, `fehlt_stueck`) |
| POST | `/api/parts/{id}/take-stock` | Fertigteile eines Teils als gesägt übernehmen `{"anzahl": 0}` (0 = so viele wie möglich) |
| POST | `/api/cut-lists` | Sägeauftrag aus einzelnen Teilen anlegen (`name` optional) |
| POST | `/api/sammel/compare` | Vergleich getrennt/gemeinsam (ohne Speichern) |
| POST | `/api/projects/{id}/take-stock/{material_id}` | Fertigteile eines Projekts (eines Materials) als gesägt übernehmen |
| **Export** | | |
| POST | `/api/pdf` | PDF-Schnittplan erzeugen |
| POST | `/api/labels` | Etiketten-PDF aus fertigen Texten erzeugen |
| GET | `/api/labels/formats` | Alle Etikettenformate (Gruppe, Maße, Ware, Etiketten je Bogen) |
| GET | `/api/labels/preview?format=` | Musteretikett: Größe und Textpositionen wie im PDF |
| POST | `/api/labels/pieces` | Etiketten für Lagerstücke (Auswahl per Code, Lagerort, Material, Filter) |
| **System** | | |
| GET | `/api/version` | App-Version und Links |
| GET | `/api/license` | Lizenzstatus |
| GET | `/api/settings` | Einstellungen lesen |
| PUT | `/api/settings` | Einstellungen ändern (`unit`: `mm`, `cm`, `in`, `in_frac`; `unit_feet`: Fuß ab 12") |
| GET | `/api/backup` | Datenbank-Backup herunterladen (ZIP) |
| POST | `/api/restore` | Aus Backup wiederherstellen (ZIP) |
| GET | `/api/i18n/{lang}` | Übersetzungen für eine Sprache |
| POST | `/api/seed` | Beispieldaten anlegen (nur in einer leeren Datenbank) |
| GET | `/api/is-desktop` | Läuft CutStock als Desktop-App? |
| POST | `/api/shutdown` | Desktop-App beenden (nur in der Desktop-App) |

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

Algorithmus-Optionen: `greedy`, `nested`, `ga`. `reste_zuerst`, `fuellteile` und `fuell_alle_reste` sind optional (Füllteil-Modus `auffuellen` oder `fest`; ohne `fuellteile` bleibt die Auswahl des gespeicherten Plans).

Die Antwort ist der gespeicherte Plan: `plan_id`, `schnittplaene` (je Brett u. a. `stueck_code`, `lagerort`, `platzierungen` mit `id` und `gesaegt`), `fehlende_teile`, `gesamt_verschnitt_prozent`, `materialbedarf` (zusätzlich benötigtes Material -- leer wenn alles passt), `zu_lang` (fehlende Teile, die größer als jedes Stück im Lager sind -- nicht im Materialbedarf) sowie Hinweise `veraltet` (mit `veraltet_grund`: `teile` = Teile/Material geändert, `anderswo` = Teile inzwischen anderswo gesägt) und `lager_fehlt`.

Das verwendete Sägeblatt wird zum Standard-Sägeblatt des Materials (`saegeblatt_id` in `/api/materials`); dasselbe gilt für `/api/sammel/optimize`.

## Arbeitsliste

`GET /api/worklist` liefert alles, was gesägt werden kann -- Sammelpläne zuerst, dann Sägeaufträge, dann Projekte. Je Eintrag `art` (`sammel`, `liste`, `projekt`), `projekt_id`, `name`, `status` und je Material eine Zeile:

```json
{"art": "projekt", "projekt_id": 5, "name": "Werkbank", "status": "bereit",
 "materialien": [{"material_id": 2, "material": "Alu Profil 40x40", "typ": "Stange",
   "teile": 2, "offen": 6, "status": "bereit", "veraltet_grund": "", "plan_id": 17,
   "gesamt": 6, "gesaegt": 0, "sammelplan_id": 0, "sammelplan": "",
   "auch_in": [{"projekt_id": 8, "name": "CNC-Fräse"}]}]}
```

`status`: `kein_plan`, `bereit`, `in_arbeit`, `veraltet`, `fertig`, `sammel` (Material wird im Sammelplan `sammelplan_id` gesägt) oder `verplant` (alles Offene steckt in Sägeaufträgen oder anderen Plänen). Bei `verplant` nennt `auftraege` die Sägeaufträge (`projekt_id`, `name`), in denen die offenen Teile stecken. `auch_in` nennt andere Projekte mit offenen Teilen in diesem Material, solange es noch keinen Sammelplan gibt (Vorschlag „zusammen sägen?“ → `POST /api/sammel`). Fertige Zeilen und Einträge fehlen, außer mit `?fertige=true`.

## Lager-Befehle

Zugang -- liefert die Codes fürs Beschriften:

```json
POST /api/stock/receive
{"material": "AP40", "laenge": 6000, "anzahl": 4}

→ {"stock_id": 12, "codes": ["AP40-21", "AP40-22", "AP40-23", "AP40-24"], "lagerort": "Wandregal Alu"}
```

`breite` nur bei Platten, `ist_rest: true` für Reststücke (liegen dann am Reste-Ort).

Stück entnehmen:

```json
POST /api/pieces/AP40-07/take
{"grund": "verbraucht", "notiz": "Musterbau"}
```

`grund`: `verbraucht`, `verkauft`, `defekt` oder `abfall` (= in die Abfallkiste, wenn eingeschaltet).
Ist das Stück von einem gespeicherten Plan reserviert, kommt `409` mit `code: "stueck_reserviert"` und dem Projekt; mit `"trotzdem": true` wird es dennoch entnommen. Der Plan zeigt danach `lager_fehlt` und `fehlende_stuecke`.

Etiketten für Lagerstücke -- z. B. alle noch nicht beschrifteten Stücke eines Regals:

```json
POST /api/labels/pieces
{"lagerort": "Wandregal Alu", "nur_ungedruckt": true, "startfeld": 5}
```

Auswahl über `codes` (Liste von Codes oder IDs) **oder** `lagerort` und/oder `material`; eingrenzen mit `nur_reste`, `nur_ganze`, `nur_ungedruckt`. `startfeld` überspringt auf A4-Bögen die schon benutzten Felder. Antwort ist das PDF (Kopfzeile `X-Label-Count` = Anzahl); die Stücke gelten danach als gedruckt (`etikett_gedruckt` am Stück = Unix-Zeit, `0` = nie), außer mit `"markieren": false`. Ohne Auswahl `400 auswahl_fehlt`, passt nichts `404 keine_stuecke`.

Material einem Lagerort zuweisen:

```json
PUT /api/materials/AP40/location
{"lagerort": "Wandregal Alu", "lagerort_reste": "Restekiste Alu"}
```

`lagerort_reste: ""` = Reste liegen beim Material. Beim Anlegen/Ändern eines Materials über `/api/materials` wird ein unbekannter Lagerort-Name automatisch angelegt.

Lagerort löschen, der noch genutzt wird:

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

## Sägeaufträge

Ein Sägeauftrag ist ein Projekt mit `art: "liste"`, dessen Teile Kopien mit
`herkunft_teil_id` sind. Gesägt zählt jedes Stück beim Herkunftsteil (`gesaegt_anzahl`), solange
dort etwas offen ist; erst der Überschuss geht zu dessen Fertigteilen (`vorrat`). Zurücknehmen
bucht genau das zurück. Dieselbe Regel gilt für Füllteile. Beauftragte Mengen sind ab dem Anlegen
gesperrt: Der Plan des Herkunftsprojekts verplant sie nicht noch einmal, und `GET /api/parts`
zieht sie von `verfuegbar` ab.

```json
POST /api/cut-lists
{"eintraege": [{"teil_id": 12, "menge": 4}]}      → 201, Projekt "Sägeauftrag 01.11.2026"
POST /api/parts/12/take-stock {"anzahl": 0}       → Teil mit vorrat −n, gesaegt_anzahl +n
```

## Sammelpläne

Ein Sammelplan ist ein Projekt mit `art: "sammel"`, `sammel_material_id` und `mitglieder`
(Projekt-IDs); eigene Teile hat er nicht. `GET /api/projects` liefert ihn nur mit `?art=sammel`
oder `?art=alle`, Mitglieds-Projekte nennen ihn unter `sammel` (`{material_id: Name}`).

```json
POST /api/sammel
{"material": "AP40", "projekte": ["Werkbank", "12"]}

→ 201 {"id": 31, "name": "Sammelplan Alu Profil 40x40", "art": "sammel", "sammel_material_id": 2, "mitglieder": [5, 12], ...}
```

Material per ID oder Kürzel, Projekte per ID oder Namen, `name` optional. Gibt es für das
Material schon einen, kommt `409 sammel_vorhanden` mit `sammel_id`; unbekannt sind
`404 material_unbekannt` bzw. `projekt_unbekannt`. Berechnet wird mit `POST /api/sammel/optimize`.

Mitglieder ändern (ein berechneter Plan gilt danach als `veraltet`):

```json
PUT /api/sammel/AP40/members
{"projekte": ["Werkbank"]}
```

Umbenennen mit `PUT /api/projects/{id}` (die Anzahl bleibt 1), löschen mit
`DELETE /api/projects/{id}`: Gesägtes zählt schon in den Mitglieds-Projekten (`gesaegt_anzahl`),
der Rest wird wieder offen, reservierte Lagerstücke werden frei. Teile anlegen, kopieren oder
duplizieren geht bei einem Sammelplan nicht (`400 sammel_ohne_teile`).

## Vorlagen

Eine Vorlage ist ein Projekt mit `art: "vorlage"` – eine feste Stückliste, die nie selbst
optimiert oder gesägt wird (`anzahl` immer 1, `gesaegt_anzahl` und `vorrat` ihrer Teile immer 0).
Teile werden wie bei Projekten über `/api/projects/{id}/parts` und `/api/parts/{id}` gepflegt,
umbenannt wird mit `PUT /api/projects/{id}`, gelöscht mit `DELETE /api/projects/{id}`.
`GET /api/projects` liefert Vorlagen nur mit `?art=vorlage`; sie fehlen auch in `GET /api/parts`,
in der Arbeitsliste und bei Sammelplänen.

```json
POST /api/templates                     {"name": "Regal A"}
POST /api/projects/14/as-template       {"name": ""}              → Name des Sägeauftrags/Projekts
POST /api/templates/31/run              {"saetze": 3}

→ 201 {"id": 40, "name": "Regal A – 09.11.2026", "art": "liste", "anzahl": 3,
       "vorlage_id": 31, "vorlage_name": "Regal A", "teile": [...], ...}
```

Ein **Durchgang** ist ein Sägeauftrag (`art: "liste"`) mit `anzahl` = Sätze und eigenen Teilen
ohne `herkunft_teil_id`: Gesägt zählt nur beim Durchgang selbst. Optimiert wird er wie jeder
Sägeauftrag mit `POST /api/optimize`, also gegen das aktuelle Lager. Änderungen an der Vorlage
wirken erst beim nächsten Durchgang.

An der Vorlage stehen `durchgaenge` (Anzahl), `zuletzt` (Unix-Zeit des letzten Durchgangs) und
`laufend` (noch nicht fertige Durchgänge). `GET /api/templates/{id}/runs` liefert je Durchgang
`auftrag_id` (0 = Sägeauftrag gelöscht), `name`, `saetze`, `gesaegt`, `gesamt`, `angelegt` und
`fertig` (Unix-Zeit, 0 = offen; wird beim Zurücknehmen wieder 0). Nach dem Löschen des Sägeauftrags
bleibt der Eintrag mit dem letzten Stand.

`as-template` übernimmt die Stückzahl je Exemplar; bei Sägeaufträgen fällt der Zusatz
„(Projekt)“ am Teilenamen weg, solange die Namen eindeutig bleiben. Fehler:
`404 vorlage_unbekannt`, `400 vorlage_leer` (Durchgang ohne Teile), `400 vorlage_nicht_saegbar`
(`/api/optimize`, `restart` oder `take-stock` mit einer Vorlage), `400 name_leer`.
