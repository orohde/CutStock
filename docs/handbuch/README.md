# CutStock – Handbuch

Das Handbuch ist nach den Reitern der Oberfläche aufgeteilt. Jede Seite beschreibt einen Reiter:
was man dort sieht, was man dort tut und welche Begriffe dazugehören.

| Taste | Reiter | Wofür |
|-------|--------|-------|
| 1 | [Material](1-material.md) | Materialien anlegen, Lagerbestand je Material, Defekte, Etiketten |
| 2 | [Lager](2-lager.md) | Lagerorte verwalten, sehen was wo liegt, Stücke entnehmen, Abfallkiste |
| 3 | [Projekte](3-projekte.md) | Projekte und ihre Teile |
| 4 | [Teile](4-teile.md) | Offene Teile aller Projekte, Sägeaufträge, Vorlagen, Fertigteile |
| 5 | [Optimierung](5-optimierung.md) | Schnittpläne berechnen, sägen, abhaken, PDF, Werkstatt-Modus |
| 6 | [Einstellungen](6-einstellungen.md) | Sprache, Einheiten, Etiketten, Lager, REST-API, Backup, Sägeblätter |

Für Programme, Scanner und Maschinen: [REST-API](api.md).

## Desktop-App: im Browser, aber lokal

Die Desktop-App (macOS, Windows) öffnet sich in deinem Standard-Browser. Das ist kein
Online-Dienst: CutStock läuft komplett auf deinem eigenen Rechner, der Browser zeigt nur die
Oberfläche an. Es wird keine Internetverbindung gebraucht, und die Daten bleiben auf deinem
Rechner (auf dem Mac auf Wunsch per iCloud zwischen deinen Macs abgeglichen). Zum Beenden gibt
es oben rechts den Knopf „Beenden“.

## Begriffe

- **Material** – ein Werkstoff, z. B. „Alu Profil 40x40“ (Stange) oder „MDF 19 mm“ (Platte).
- **Kürzel** – kurzer Name des Materials für Stück-Codes, z. B. `AP40`.
- **Stück** – ein einzelnes Brett, eine Stange oder Platte im Lager, mit Code wie `AP40-07`.
  Der Code steht auf dem Etikett bzw. wird aufs Material geschrieben.
- **Rest** – ein Stück, das beim Sägen übrig blieb und mindestens das Mindest-Restmaß des Materials hat.
  Reste kommen zurück ins Lager und behalten den Code ihres Bretts.
- **Abschnitt / Abfall** – was kleiner als das Mindest-Restmaß ist. Er wird weggeworfen oder,
  wenn eingeschaltet, ohne Code in der **Abfallkiste** geführt.
- **Lagerort** – wo ein Material liegt (Regal, Wagen, Kiste). Jedes Material hat genau einen,
  dazu optional einen eigenen Ort für seine Reste.
- **Plan** – das gespeicherte Ergebnis einer Optimierung für ein Projekt und ein Material.
  Ein Plan reserviert die Stücke, die er verwenden will.
- **Vorlage** – eine feste Stückliste zum Wiederholen. „Sägen ×N“ legt daraus jedes Mal einen
  neuen Sägeauftrag an.
