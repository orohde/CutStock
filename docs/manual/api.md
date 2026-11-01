# REST API

[← Manual](README.md)

Every function of the user interface is also available via the REST API under `/api/` -- the interface itself uses nothing else. All endpoints accept and return JSON. CutStock serves an automatically generated, interactive description of all endpoints at `/docs`.

For programs, scanners and machines:

- Materials can be addressed by ID **or short code** (`AP40`), pieces by ID **or code** (`AP40-07`, from the label), locations by ID **or name**.
- Errors of the stock commands carry a fixed code: `{"detail": {"code": "stueck_reserviert", "message": "...", "projekt": "..."}}`.
- Every stock booking is written to the stock journal, with source `api` or `ui`.

## Authentication

When an API key is configured (Settings page), external requests must include it as a Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" http://cutstock:8420/api/materials
```

Requests from the web UI (same-origin) and from localhost are always allowed without a key.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| **Materials** | | |
| GET | `/api/materials` | List all materials |
| POST | `/api/materials` | Create a material |
| PUT | `/api/materials/{id}` | Update a material (`saegeblatt_id`: default saw blade for optimization, 0 = first, omitted = unchanged) |
| DELETE | `/api/materials/{id}` | Delete a material |
| **Stock** | | |
| GET | `/api/stock?material_id=N` | List stock (optional filter) |
| POST | `/api/stock` | Create stock entry |
| PUT | `/api/stock/{id}` | Update stock entry |
| DELETE | `/api/stock/{id}` | Delete stock entry |
| GET | `/api/stock/{id}/pieces` | List individual pieces (code, location, reserved for) |
| GET | `/api/pieces/{id or code}` | Look up a piece: material, size, location, reservation |
| PUT | `/api/pieces/{id or code}` | Change a piece's note |
| GET/POST/DELETE | `/api/materials/{id}/image` | Read, upload, remove material image |
| **Stock locations** (see below) | | |
| GET | `/api/locations` | Locations with number of materials and pieces |
| POST | `/api/locations` | Create a location `{"name": "Rack 3"}` |
| PUT | `/api/locations/{id or name}` | Rename a location |
| DELETE | `/api/locations/{id or name}?ziel=…` | Delete a location; if in use, `ziel` (target) is required |
| GET | `/api/locations/{id or name}/contents` | What is stored there: materials with pieces |
| PUT | `/api/materials/{id or short code}/location` | Assign a material to a location |
| POST | `/api/stock/receive` | Receive stock: add pieces, returns the new codes |
| POST | `/api/pieces/{id or code}/take` | Take a piece out (with reason) |
| GET | `/api/waste` | Contents of the offcut bin |
| POST | `/api/waste` | Put offcuts into the bin |
| POST | `/api/waste/take` | Take offcuts out of the bin |
| DELETE | `/api/waste?material=…` | Empty the bin (all or per material) |
| GET | `/api/journal?material=…&seit=…` | Stock journal, newest first |
| **Defects** | | |
| GET | `/api/stock/{id}/defects` | Defects on a stock entry |
| GET | `/api/pieces/{id}/defects` | Defects on a piece |
| POST | `/api/pieces/{id}/defects` | Add a defect |
| PUT | `/api/defects/{id}` | Update a defect |
| DELETE | `/api/defects/{id}` | Delete a defect |
| **Saw Blades** | | |
| GET | `/api/blades` | List saw blades |
| POST | `/api/blades` | Create a blade |
| PUT | `/api/blades/{id}` | Update a blade |
| DELETE | `/api/blades/{id}` | Delete a blade |
| **Projects** | | |
| GET | `/api/projects?art=` | List projects; without `art` projects and cut jobs, `art=projekt` projects only, `art=liste` cut jobs only, `art=sammel` combined plans only, `art=alle` everything |
| GET | `/api/projects/{id}` | Get a project |
| POST | `/api/projects` | Create a project |
| PUT | `/api/projects/{id}` | Update a project (name, number of copies) |
| DELETE | `/api/projects/{id}` | Delete a project or combined plan (cut parts stay in the projects) |
| POST | `/api/projects/{id}/clone` | Duplicate a project |
| POST | `/api/projects/{id}/copy-parts` | Copy parts into a project |
| POST | `/api/projects/{id}/restart` | Restart project (progress 0, plans removed, stock unchanged) |
| **Parts** | | |
| GET | `/api/projects/{id}/parts` | List parts of a project |
| POST | `/api/projects/{id}/parts` | Add a part |
| PUT | `/api/parts/{id}` | Update a part (optional `vorrat`: set finished parts) |
| DELETE | `/api/parts/{id}` | Delete a part |
| **Optimization and Plans** | | |
| GET | `/api/worklist?fertige=` | Optimization work list: combined plans, cut jobs, projects per material with status and progress |
| POST | `/api/optimize` | Optimize and save as the project's plan for the material |
| POST | `/api/plans/{id}/fill-choice` | Choose the filling of a group of equal bar offcuts (`wahl: null` = automatic) |
| GET | `/api/projects/{id}/plans/{material_id}` | Get the saved plan (`null` if there is none) |
| POST | `/api/plan-pieces/{id}` | Mark a piece as cut / undo (`{"gesaegt": true}`), updates progress and stock |
| POST | `/api/plans/{id}/confirm-all` | Mark all open pieces of the plan as cut |
| DELETE | `/api/plans/{id}` | Discard plan (releases reserved pieces) |
| GET | `/api/projects/{id}/fill-candidates/{material_id}` | Possible filler parts from other projects |
| GET | `/api/sammel/{material_id}` | Combined plan status and eligible projects |
| POST | `/api/sammel` | Create a combined plan (material and projects, no cutting plan yet) |
| PUT | `/api/sammel/{id or code}/members` | Replace the members of a material's combined plan |
| POST | `/api/sammel/optimize` | Create/replace and compute the combined plan |
| GET | `/api/parts` | Parts of all projects with planning state: `beauftragt` (in cut jobs), `auftraege`, `verplant`, `sammelplan`, `verfuegbar` ("Parts" tab) |
| GET | `/api/parts/materials` | Available parts per material with a rough stock estimate (`bedarf`, `lager`, `reicht`, `fehlt_stueck`) |
| POST | `/api/parts/{id}/take-stock` | Count a part's finished parts as cut `{"anzahl": 0}` (0 = as many as possible) |
| POST | `/api/cut-lists` | Create a cut job from individual parts (`name` optional) |
| POST | `/api/sammel/compare` | Compare separate vs. combined (not saved) |
| POST | `/api/projects/{id}/take-stock/{material_id}` | Count a project's finished parts (one material) as cut |
| **Export** | | |
| POST | `/api/pdf` | Generate PDF cut plan |
| POST | `/api/labels` | Generate label PDF from ready-made texts |
| POST | `/api/labels/pieces` | Labels for stock pieces (select by code, location, material, filters) |
| **System** | | |
| GET | `/api/version` | App version and links |
| GET | `/api/license` | License status |
| GET | `/api/settings` | Read settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/backup` | Download database backup (ZIP) |
| POST | `/api/restore` | Restore from backup (ZIP) |
| GET | `/api/i18n/{lang}` | Translations for a language |
| POST | `/api/seed` | Create sample data (empty database only) |
| GET | `/api/is-desktop` | Is CutStock running as the desktop app? |
| POST | `/api/shutdown` | Quit the desktop app (desktop app only) |

## Optimization request

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

Algorithm choices: `greedy`, `nested`, `ga`. `reste_zuerst` (remnants first), `fuellteile` (filler parts) and `fuell_alle_reste` are optional (filler mode `auffuellen` = fill or `fest` = fixed quantity; without `fuellteile` the saved plan's selection is kept).

The response is the saved plan: `plan_id`, `schnittplaene` (per board e.g. `stueck_code`, `lagerort`, `platzierungen` with `id` and `gesaegt`), `fehlende_teile` (parts that didn't fit), `gesamt_verschnitt_prozent` (total waste %), `materialbedarf` (additional material needed -- empty when everything fits) and the hints `veraltet` (outdated, with `veraltet_grund`: `teile` = parts/material changed, `anderswo` = parts cut elsewhere meanwhile) and `lager_fehlt` (stock missing).

The saw blade used becomes the material's default saw blade (`saegeblatt_id` in `/api/materials`); the same applies to `/api/sammel/optimize`.

## Work list

`GET /api/worklist` returns everything that can be cut -- combined plans first, then cut jobs, then projects. Per entry `art` (`sammel` = combined plan, `liste` = cut job, `projekt`), `projekt_id`, `name`, `status` and one line per material:

```json
{"art": "projekt", "projekt_id": 5, "name": "Workbench", "status": "bereit",
 "materialien": [{"material_id": 2, "material": "Alu profile 40x40", "typ": "Stange",
   "teile": 2, "offen": 6, "status": "bereit", "veraltet_grund": "", "plan_id": 17,
   "gesamt": 6, "gesaegt": 0, "sammelplan_id": 0, "sammelplan": "",
   "auch_in": [{"projekt_id": 8, "name": "CNC router"}]}]}
```

`status`: `kein_plan` (no plan yet), `bereit` (ready), `in_arbeit` (in progress), `veraltet` (outdated), `fertig` (finished), `sammel` (material is cut in combined plan `sammelplan_id`) or `verplant` (everything open is in cut jobs or other plans). With `verplant`, `auftraege` names the cut jobs (`projekt_id`, `name`) holding the open parts. `auch_in` lists other projects with open parts in this material as long as there is no combined plan (the "cut together?" suggestion → `POST /api/sammel`). Finished lines and entries are left out unless `?fertige=true`.

## Stock commands

Receive stock -- returns the codes for labelling:

```json
POST /api/stock/receive
{"material": "AP40", "laenge": 6000, "anzahl": 4}

→ {"stock_id": 12, "codes": ["AP40-21", "AP40-22", "AP40-23", "AP40-24"], "lagerort": "Rack Alu"}
```

`breite` (width) only for panels, `ist_rest: true` for offcuts (stored at the offcut location).

Take a piece out:

```json
POST /api/pieces/AP40-07/take
{"grund": "verbraucht", "notiz": "prototype"}
```

`grund` (reason): `verbraucht` (used), `verkauft` (sold), `defekt` (defective) or `abfall` (into the offcut bin, if switched on).
If a saved plan reserves the piece, the answer is `409` with `code: "stueck_reserviert"` and the project; with `"trotzdem": true` it is taken out anyway. The plan then reports `lager_fehlt` and `fehlende_stuecke`.

Labels for stock pieces -- e.g. all pieces on a rack that have no label yet:

```json
POST /api/labels/pieces
{"lagerort": "Wandregal Alu", "nur_ungedruckt": true, "startfeld": 5}
```

Select with `codes` (list of codes or IDs) **or** `lagerort` (location) and/or `material`; narrow down with `nur_reste` (offcuts only), `nur_ganze` (whole pieces only), `nur_ungedruckt` (not printed yet). `startfeld` skips fields already used on an A4 sheet. The answer is the PDF (header `X-Label-Count` = number of labels); the pieces then count as printed (`etikett_gedruckt` on the piece = Unix time, `0` = never), unless `"markieren": false`. No selection gives `400 auswahl_fehlt`, nothing matching `404 keine_stuecke`.

Assign a material to a location:

```json
PUT /api/materials/AP40/location
{"lagerort": "Rack Alu", "lagerort_reste": "Offcut box Alu"}
```

`lagerort_reste: ""` = offcuts stay with the material. When creating/updating a material via `/api/materials`, an unknown location name is created automatically.

Delete a location that is still in use:

```
DELETE /api/locations/Rack%203              → 409 {"code": "lagerort_in_benutzung", "materialien": [...]}
DELETE /api/locations/Rack%203?ziel=Stock   → 204, the materials are now at "Stock"
```

Offcut bin (no codes, only material + size + quantity):

```json
POST /api/waste        {"material": "AP40", "laenge": 180, "anzahl": 2}
POST /api/waste/take   {"material": "AP40", "laenge": 180}
DELETE /api/waste?material=AP40
```

Stock journal: `GET /api/journal?material=AP40&seit=1767225600&limit=100` -- each entry has `zeit` (Unix time), `art` (`zugang`, `korrektur_ab`, `entnahme`, `plan_verbrauch`, `plan_zurueck`, `rest_ein`, `rest_zurueck`, `abfall_ein`, `abfall_zurueck`, `abfall_ab`, `abfall_leer`, `material_lagerort`, `lagerort_neu`, `lagerort_umbenannt`, `lagerort_geloescht`), `code`, sizes, `anzahl`, `quelle` (`ui`/`api`), `notiz`.

## Cut jobs

A cut job is a project with `art: "liste"` whose parts are copies with `herkunft_teil_id`. Each
cut piece counts for the original part (`gesaegt_anzahl`) as long as it has open pieces; only the
surplus goes to its finished parts (`vorrat`). Undoing reverses exactly that. Filler parts follow
the same rule. Quantities in a cut job are blocked as soon as it is created: the original
project's plan won't plan them again, and `GET /api/parts` subtracts them from `verfuegbar`.

```json
POST /api/cut-lists
{"eintraege": [{"teil_id": 12, "menge": 4}]}      → 201, project "Cut job 2026-11-01"
POST /api/parts/12/take-stock {"anzahl": 0}       → part with vorrat −n, gesaegt_anzahl +n
```

## Combined plans

A combined plan is a project with `art: "sammel"`, `sammel_material_id` and `mitglieder`
(member project IDs); it has no parts of its own. `GET /api/projects` only lists it with
`?art=sammel` or `?art=alle`; member projects name it under `sammel` (`{material_id: name}`).

```json
POST /api/sammel
{"material": "AP40", "projekte": ["Workbench", "12"]}

→ 201 {"id": 31, "name": "Sammelplan Alu Profil 40x40", "art": "sammel", "sammel_material_id": 2, "mitglieder": [5, 12], ...}
```

Material by ID or code, projects by ID or name, `name` optional. If the material already has
one, you get `409 sammel_vorhanden` with `sammel_id`; unknown references give
`404 material_unbekannt` or `projekt_unbekannt`. The plan is calculated with
`POST /api/sammel/optimize`.

Change members (a calculated plan is then `veraltet`, i.e. outdated):

```json
PUT /api/sammel/AP40/members
{"projekte": ["Workbench"]}
```

Rename with `PUT /api/projects/{id}` (the number of copies stays 1), delete with
`DELETE /api/projects/{id}`: what has been cut already counts in the member projects
(`gesaegt_anzahl`), the rest becomes open again and reserved stock pieces are released. Adding,
copying or duplicating parts is not possible for a combined plan (`400 sammel_ohne_teile`).
