# Reiter „Optimierung“

[← Handbuch](README.md)

Hier entstehen die Schnittpläne – und hier wird beim Sägen abgehakt.

![Optimierung Stangen](../screenshot_optimierung.png)

## Optimieren

Projekt, Material, Sägeblatt und Algorithmus wählen, dann **Optimieren**.

- Algorithmen: **Schnell** (Greedy), **Nested Guillotine** (intelligente Schnittrichtung),
  **Gründlich** (genetischer Algorithmus).
- **Reste zuerst**: erst nur Reste verplanen, dann ganze Stangen/Platten.
- **Max. je Stange**: höchstens so viele Teile auf eine Stange – lässt Platz für Füllteile.

Jede Berechnung wird als **Plan** gespeichert. Der Plan reserviert seine noch nicht angefangenen
Stücke, andere Projekte verplanen sie nicht (abschaltbar unter Einstellungen → Lager).
Hinweise erscheinen, wenn sich Teile oder Material seit der Berechnung geändert haben oder ein
eingeplantes Stück nicht mehr im Lager ist (mit Code, z. B. „Nicht mehr im Lager: AP40-07“).

## Der Plan

Jede Stange/Platte hat eine Kopfzeile: was man in die Hand nimmt („Nimm AP40-07 ·
Wandregal Alu“), wie viele Teile darauf liegen und **wohin jeder Abschnitt gehört**:

- **zurück ins Lager** – ab dem Mindest-Restmaß; der größte Rest behält den Code des Bretts,
  er liegt danach am Reste-Ort des Materials,
- **in die Abfallkiste** – kleiner, aber über der Untergrenze, wenn die Abfallkiste eingeschaltet ist
  (siehe [Lager](2-lager.md#abfallkiste)),
- **wegwerfen** – alles andere.

Ein Klick auf ein Teil im Plan hakt es als gesägt ab. Beim ersten Teil eines Bretts wird das
Stück aus dem Lager ausgetragen, Reste werden eingebucht, Abfall kommt in die Abfallkiste.
Zurücknehmen macht das wieder rückgängig.

Weitere Knöpfe: **Bestätigen (gesägt)** für alles, **PDF Export**, **Etiketten**,
**Werkstatt-Modus**, **Plan verwerfen** (gibt reservierte Stücke frei),
**Projekt neu starten** (Fortschritt auf 0, Lager bleibt).

Stangen sind im Plan **im gleichen Maßstab** gezeichnet: Die längste füllt die Breite, kürzere
sind entsprechend kürzer. Sehr kurze Stangen werden etwas breiter gezeichnet und dann gestrichelt
umrandet. Die Lupe und der Werkstatt-Modus zeigen jede Stange in voller Breite.

## Platten

2D-Guillotine-Packing: Alle Schnitte gehen von Kante zu Kante, so dass Reste Rechtecke bleiben.
Die nummerierte Schnittfolge unter jedem Plan sagt genau, wo gesägt wird – die Sägeblattbreite
ist eingerechnet.

![Optimierung Platten](../screenshot_platten.png)

## Füllteile

Bleibt am Ende einer Stange oder auf einer Platte Abfall, füllt CutStock ihn mit Teilen aus
anderen Projekten auf (**Füllteile …**). Es wird nie mehr Material verbraucht. Füllteile sind
schraffiert, tragen ihr Herkunftsprojekt und zählen gesägt direkt bei ihrem Projekt (Überzähliges kommt zu den Fertigteilen).

![Füllteile](../screenshot_fuellteile.png)

## Sammelplan

Wird dasselbe Material in mehreren Projekten gebraucht: „Optimieren nach: **Material
(Sammelplan)**“, Material wählen, Projekte anhaken. **Vergleichen** zeigt die Ersparnis gegenüber
getrennten Plänen. Jedes Projekt bekommt eine eigene Farbe; abgehakte Teile zählen in ihrem
Projekt. Anlegen, umbenennen, Mitglieder ändern und löschen geht auch im Reiter
[Projekte](3-projekte.md#sammelpläne), Kasten „Sammelpläne“.

![Sammelplan](../screenshot_sammelplan.png)

## Materialbedarf

Reicht der Bestand nicht, zeigt CutStock eine Einkaufsliste; per Klick lässt sie sich direkt
ins Lager übernehmen.

## Werkstatt-Modus

Vollbild fürs Tablet an der Säge: eine Stange/Platte pro Seite mit Stück-Code und Lagerort,
große Touch-Ziele, Fortschritt, „Als Nächstes“-Markierung. Entstandene Reste werden mit ihrem
Code angezeigt und können gleich als Etikett gedruckt werden.

![Werkstatt-Modus](../screenshot_werkstatt.png)

## PDF

Teileliste mit Anzahl, Materialbedarf mit Stück-Codes und Lagerort, gleiche Schnittmuster
zusammengefasst; bei jedem Muster steht, wohin die Abschnitte gehören.
