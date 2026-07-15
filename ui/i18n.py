"""Internationalisierung – einfaches Dictionary-basiertes System.

Sprachen: Deutsch (de), Englisch (en), Französisch (fr), Italienisch (it).
Standard: Englisch. Gespeichert in settings.json neben der DB.
"""

TRANSLATIONS = {
    # ---- App / Fenster ----
    "app.title": {
        "de": "CutStock – Verschnittoptimierung",
        "en": "CutStock – Cut Optimization",
        "fr": "CutStock – Optimisation de coupe",
        "it": "CutStock – Ottimizzazione del taglio",
    },
    # ---- Tabs ----
    "tab.material_stock": {
        "de": "Material && Lager",
        "en": "Material && Stock",
        "fr": "Matériau && Stock",
        "it": "Materiale && Magazzino",
    },
    "tab.projects": {
        "de": "Projekte", "en": "Projects", "fr": "Projets", "it": "Progetti",
    },
    "tab.optimization": {
        "de": "Optimierung", "en": "Optimization", "fr": "Optimisation",
        "it": "Ottimizzazione",
    },
    "tab.settings": {
        "de": "Einstellungen", "en": "Settings", "fr": "Paramètres",
        "it": "Impostazioni",
    },
    # ---- Material & Lager ----
    "mat.title": {
        "de": "Materialien", "en": "Materials", "fr": "Matériaux",
        "it": "Materiali",
    },
    "mat.new": {
        "de": "Neues Material", "en": "New Material", "fr": "Nouveau matériau",
        "it": "Nuovo materiale",
    },
    "mat.edit": {
        "de": "Material bearbeiten", "en": "Edit Material", "fr": "Modifier matériau",
        "it": "Modifica materiale",
    },
    "mat.name": {"de": "Name:", "en": "Name:", "fr": "Nom:", "it": "Nome:"},
    "mat.type": {"de": "Typ:", "en": "Type:", "fr": "Type:", "it": "Tipo:"},
    "mat.plate": {"de": "Platte", "en": "Panel", "fr": "Panneau", "it": "Pannello"},
    "mat.bar": {"de": "Stange", "en": "Bar", "fr": "Barre", "it": "Barra"},
    "mat.thickness": {
        "de": "Dicke:", "en": "Thickness:", "fr": "Épaisseur:",
        "it": "Spessore:",
    },
    "mat.cross_w": {
        "de": "Querschnitt Breite:", "en": "Cross-section Width:",
        "fr": "Largeur section:", "it": "Larghezza sezione:",
    },
    "mat.cross_d": {
        "de": "Querschnitt Tiefe:", "en": "Cross-section Depth:",
        "fr": "Profondeur section:", "it": "Profondità sezione:",
    },
    "mat.grain": {
        "de": "Maserung:", "en": "Grain:", "fr": "Veinage:",
        "it": "Venatura:",
    },
    "mat.grain.none": {
        "de": "Keine (frei drehbar)", "en": "None (freely rotatable)",
        "fr": "Aucun (rotation libre)", "it": "Nessuna (rotazione libera)",
    },
    "mat.grain.long": {
        "de": "Längs (lange Kante)", "en": "Lengthwise (long edge)",
        "fr": "Longitudinal (long côté)", "it": "Longitudinale (lato lungo)",
    },
    "mat.grain.cross": {
        "de": "Quer (kurze Kante)", "en": "Crosswise (short edge)",
        "fr": "Transversal (court côté)", "it": "Trasversale (lato corto)",
    },
    "mat.trim": {
        "de": "Besäumung (Rand):", "en": "Edge trim:", "fr": "Délignage:",
        "it": "Rifilatura (bordo):",
    },
    "mat.min_rest_l": {
        "de": "Min-Restlänge:", "en": "Min rest length:", "fr": "Longueur min reste:",
        "it": "Lunghezza min resto:",
    },
    "mat.min_rest_w": {
        "de": "Min-Restbreite:", "en": "Min rest width:", "fr": "Largeur min reste:",
        "it": "Larghezza min resto:",
    },
    "mat.dim": {
        "de": "Dicke/Querschnitt", "en": "Thickness/Section",
        "fr": "Épaisseur/Section", "it": "Spessore/Sezione",
    },
    # ---- Lager / Stock ----
    "stock.title": {
        "de": "Lagerbestand", "en": "Stock", "fr": "Stock",
        "it": "Magazzino",
    },
    "stock.new": {
        "de": "Lagerstück hinzufügen", "en": "Add Stock Piece",
        "fr": "Ajouter pièce de stock", "it": "Aggiungi pezzo a magazzino",
    },
    "stock.edit": {
        "de": "Lagerstück bearbeiten", "en": "Edit Stock Piece",
        "fr": "Modifier pièce de stock", "it": "Modifica pezzo a magazzino",
    },
    "stock.length": {
        "de": "Länge:", "en": "Length:", "fr": "Longueur:", "it": "Lunghezza:",
    },
    "stock.width": {
        "de": "Breite:", "en": "Width:", "fr": "Largeur:", "it": "Larghezza:",
    },
    "stock.qty": {
        "de": "Stückzahl:", "en": "Quantity:", "fr": "Quantité:", "it": "Quantità:",
    },
    # ---- Projekte ----
    "proj.title": {
        "de": "Projekte", "en": "Projects", "fr": "Projets", "it": "Progetti",
    },
    "proj.new": {
        "de": "Neues Projekt", "en": "New Project", "fr": "Nouveau projet",
        "it": "Nuovo progetto",
    },
    "proj.name": {
        "de": "Projektname:", "en": "Project name:", "fr": "Nom du projet:",
        "it": "Nome progetto:",
    },
    "proj.name_hint": {
        "de": "z.B. Regal Wohnzimmer", "en": "e.g. Living room shelf",
        "fr": "p.ex. Étagère salon", "it": "es. Scaffale soggiorno",
    },
    "proj.parts": {
        "de": "Teile", "en": "Parts", "fr": "Pièces", "it": "Pezzi",
    },
    # ---- Teile / Parts ----
    "part.new": {
        "de": "Neues Teil", "en": "New Part", "fr": "Nouvelle pièce",
        "it": "Nuovo pezzo",
    },
    "part.edit": {
        "de": "Teil bearbeiten", "en": "Edit Part", "fr": "Modifier pièce",
        "it": "Modifica pezzo",
    },
    "part.add": {
        "de": "Teil hinzufügen", "en": "Add Part", "fr": "Ajouter pièce",
        "it": "Aggiungi pezzo",
    },
    "part.label": {"de": "Label:", "en": "Label:", "fr": "Label:", "it": "Etichetta:"},
    "part.label_hint": {
        "de": "z.B. Seitenwand links", "en": "e.g. Left side panel",
        "fr": "p.ex. Panneau latéral gauche", "it": "es. Pannello laterale sinistro",
    },
    "part.grain.any": {
        "de": "Egal (frei drehbar)", "en": "Any (freely rotatable)",
        "fr": "Indifférent (rotation libre)", "it": "Indifferente (rotazione libera)",
    },
    "part.grain.long": {
        "de": "Längs (∥ Teillänge)", "en": "Lengthwise (∥ part length)",
        "fr": "Longitudinal (∥ longueur pièce)",
        "it": "Longitudinale (∥ lunghezza pezzo)",
    },
    "part.grain.cross": {
        "de": "Quer (∥ Teilbreite)", "en": "Crosswise (∥ part width)",
        "fr": "Transversal (∥ largeur pièce)",
        "it": "Trasversale (∥ larghezza pezzo)",
    },
    # ---- Sägeblätter / Saw Blades ----
    "blade.title": {
        "de": "Sägeblätter", "en": "Saw Blades", "fr": "Lames de scie",
        "it": "Lame da sega",
    },
    "blade.new": {
        "de": "Neues Sägeblatt", "en": "New Saw Blade",
        "fr": "Nouvelle lame de scie", "it": "Nuova lama da sega",
    },
    "blade.edit": {
        "de": "Sägeblatt bearbeiten", "en": "Edit Saw Blade",
        "fr": "Modifier lame de scie", "it": "Modifica lama da sega",
    },
    "blade.name": {"de": "Name:", "en": "Name:", "fr": "Nom:", "it": "Nome:"},
    "blade.kerf": {
        "de": "Schnittbreite:", "en": "Kerf width:", "fr": "Largeur de trait:",
        "it": "Larghezza di taglio:",
    },
    # ---- Optimierung ----
    "opt.project": {
        "de": "Projekt:", "en": "Project:", "fr": "Projet:", "it": "Progetto:",
    },
    "opt.material": {
        "de": "Material:", "en": "Material:", "fr": "Matériau:", "it": "Materiale:",
    },
    "opt.blade": {
        "de": "Sägeblatt:", "en": "Saw blade:", "fr": "Lame:", "it": "Lama:",
    },
    "opt.run": {
        "de": "Optimieren", "en": "Optimize", "fr": "Optimiser", "it": "Ottimizza",
    },
    "opt.confirm": {
        "de": "Bestätigen (gesägt)", "en": "Confirm (cut)",
        "fr": "Confirmer (découpé)", "it": "Conferma (tagliato)",
    },
    "opt.pdf": {
        "de": "PDF Export", "en": "PDF Export", "fr": "Export PDF",
        "it": "Esporta PDF",
    },
    "opt.result": {
        "de": "Ergebnis: {n_plans} Lagerstück(e) verwendet, {n_parts} Teile platziert, Verschnitt: {waste}%",
        "en": "Result: {n_plans} stock piece(s) used, {n_parts} parts placed, Waste: {waste}%",
        "fr": "Résultat: {n_plans} pièce(s) de stock, {n_parts} pièces placées, Chute: {waste}%",
        "it": "Risultato: {n_plans} pezzo/i a magazzino, {n_parts} pezzi piazzati, Sfrido: {waste}%",
    },
    "opt.missing": {
        "de": "FEHLEND", "en": "MISSING", "fr": "MANQUANT", "it": "MANCANTE",
    },
    "opt.no_parts": {
        "de": "Keine offenen Teile für dieses Material.",
        "en": "No open parts for this material.",
        "fr": "Aucune pièce ouverte pour ce matériau.",
        "it": "Nessun pezzo aperto per questo materiale.",
    },
    "opt.no_stock": {
        "de": "Kein Lagerstück für dieses Material vorhanden.",
        "en": "No stock piece available for this material.",
        "fr": "Aucune pièce de stock disponible pour ce matériau.",
        "it": "Nessun pezzo a magazzino disponibile per questo materiale.",
    },
    "opt.confirm_msg": {
        "de": "Schnittplan übernehmen?\n- Verbrauchte Lagerstücke werden ausgetragen\n- Verwertbare Reste werden eingebucht\n- Teile werden als gesägt markiert",
        "en": "Apply cutting plan?\n- Used stock pieces will be removed\n- Usable remnants will be added to stock\n- Parts will be marked as cut",
        "fr": "Appliquer le plan de coupe?\n- Les pièces de stock utilisées seront retirées\n- Les chutes utilisables seront ajoutées au stock\n- Les pièces seront marquées comme coupées",
        "it": "Applicare il piano di taglio?\n- I pezzi a magazzino utilizzati verranno rimossi\n- Gli sfridi riutilizzabili verranno aggiunti al magazzino\n- I pezzi verranno contrassegnati come tagliati",
    },
    "opt.done": {
        "de": "Schnittplan bestätigt. Lager aktualisiert.",
        "en": "Cutting plan confirmed. Stock updated.",
        "fr": "Plan de coupe confirmé. Stock mis à jour.",
        "it": "Piano di taglio confermato. Magazzino aggiornato.",
    },
    # ---- Einstellungen ----
    "set.window": {
        "de": "Fenster", "en": "Window", "fr": "Fenêtre", "it": "Finestra",
    },
    "set.remember_size": {
        "de": "Fenstergröße und -position merken",
        "en": "Remember window size and position",
        "fr": "Mémoriser taille et position de la fenêtre",
        "it": "Ricorda dimensione e posizione della finestra",
    },
    "set.appearance": {
        "de": "Aussehen", "en": "Appearance", "fr": "Apparence", "it": "Aspetto",
    },
    "set.theme": {
        "de": "Farbschema:", "en": "Color theme:", "fr": "Thème:",
        "it": "Tema colori:",
    },
    "set.unit": {
        "de": "Maßeinheit:", "en": "Unit:", "fr": "Unité:",
        "it": "Unità di misura:",
    },
    "set.language": {
        "de": "Sprache:", "en": "Language:", "fr": "Langue:", "it": "Lingua:",
    },
    "set.restart_now": {
        "de": "Die Änderung wird nach einem Neustart wirksam.\nJetzt neu starten?",
        "en": "The change takes effect after a restart.\nRestart now?",
        "fr": "Le changement prend effet après un redémarrage.\nRedémarrer maintenant?",
        "it": "La modifica avrà effetto dopo un riavvio.\nRiavviare ora?",
    },
    "set.storage": {
        "de": "Speicherorte", "en": "Storage", "fr": "Stockage",
        "it": "Archiviazione",
    },
    "set.db_path": {
        "de": "Datenbank:", "en": "Database:", "fr": "Base de données:",
        "it": "Database:",
    },
    "set.settings_path": {
        "de": "Einstellungen:", "en": "Settings:", "fr": "Paramètres:",
        "it": "Impostazioni:",
    },
    # ---- Allgemein ----
    "btn.save": {
        "de": "Speichern", "en": "Save", "fr": "Enregistrer", "it": "Salva",
    },
    "btn.cancel": {
        "de": "Abbrechen", "en": "Cancel", "fr": "Annuler", "it": "Annulla",
    },
    "btn.edit": {
        "de": "Bearbeiten", "en": "Edit", "fr": "Modifier", "it": "Modifica",
    },
    "btn.delete": {
        "de": "Löschen", "en": "Delete", "fr": "Supprimer", "it": "Elimina",
    },
    "btn.remove": {
        "de": "Entfernen", "en": "Remove", "fr": "Retirer", "it": "Rimuovi",
    },
    "btn.new": {
        "de": "Neu", "en": "New", "fr": "Nouveau", "it": "Nuovo",
    },
    "btn.create": {
        "de": "Anlegen", "en": "Create", "fr": "Créer", "it": "Crea",
    },
    "btn.confirm": {
        "de": "Bestätigen", "en": "Confirm", "fr": "Confirmer", "it": "Conferma",
    },
    "dlg.delete_title": {
        "de": "Löschen", "en": "Delete", "fr": "Supprimer", "it": "Elimina",
    },
    "dlg.delete_material": {
        "de": "Material und alle zugehörigen Daten löschen?\n\n- {n} Lagerstück(e) werden entfernt\n- Teile mit diesem Material werden aus Projekten entfernt",
        "en": "Delete material and all related data?\n\n- {n} stock piece(s) will be removed\n- Parts using this material will be removed from projects",
        "fr": "Supprimer le matériau et toutes les données liées?\n\n- {n} pièce(s) de stock seront retirées\n- Les pièces utilisant ce matériau seront retirées des projets",
        "it": "Eliminare il materiale e tutti i dati associati?\n\n- {n} pezzo/i a magazzino verranno rimossi\n- I pezzi che utilizzano questo materiale verranno rimossi dai progetti",
    },
    "dlg.delete_stock": {
        "de": "Lagerstück wirklich löschen?",
        "en": "Really delete stock piece?",
        "fr": "Vraiment supprimer la pièce de stock?",
        "it": "Eliminare davvero il pezzo a magazzino?",
    },
    "dlg.delete_project": {
        "de": "Projekt und alle Teile löschen?",
        "en": "Delete project and all parts?",
        "fr": "Supprimer le projet et toutes les pièces?",
        "it": "Eliminare il progetto e tutti i pezzi?",
    },
    "dlg.delete_part": {
        "de": "Teil wirklich entfernen?",
        "en": "Really remove part?",
        "fr": "Vraiment retirer la pièce?",
        "it": "Rimuovere davvero il pezzo?",
    },
    "dlg.delete_blade": {
        "de": "Sägeblatt wirklich löschen?",
        "en": "Really delete saw blade?",
        "fr": "Vraiment supprimer la lame de scie?",
        "it": "Eliminare davvero la lama da sega?",
    },
    "dlg.select_project": {
        "de": "Bitte zuerst ein Projekt wählen.",
        "en": "Please select a project first.",
        "fr": "Veuillez d'abord sélectionner un projet.",
        "it": "Selezionare prima un progetto.",
    },
    "dlg.select_material": {
        "de": "Bitte zuerst ein Material wählen.",
        "en": "Please select a material first.",
        "fr": "Veuillez d'abord sélectionner un matériau.",
        "it": "Selezionare prima un materiale.",
    },
    "dlg.select_all": {
        "de": "Bitte Projekt, Material und Sägeblatt wählen.",
        "en": "Please select project, material and saw blade.",
        "fr": "Veuillez sélectionner projet, matériau et lame.",
        "it": "Selezionare progetto, materiale e lama.",
    },
    "status.open": {
        "de": "offen", "en": "open", "fr": "ouvert", "it": "aperto",
    },
    "status.cut": {
        "de": "gesägt", "en": "cut", "fr": "coupé", "it": "tagliato",
    },
    "hint": {"de": "Hinweis", "en": "Note", "fr": "Note", "it": "Nota"},
    "error": {"de": "Fehler", "en": "Error", "fr": "Erreur", "it": "Errore"},
    "done": {"de": "Erledigt", "en": "Done", "fr": "Terminé", "it": "Fatto"},
    # ---- Import / Export ----
    "proj.export": {
        "de": "Export", "en": "Export", "fr": "Exporter", "it": "Esporta",
    },
    "proj.import": {
        "de": "Import", "en": "Import", "fr": "Importer", "it": "Importa",
    },
    "proj.export_done": {
        "de": "Projekt erfolgreich exportiert.",
        "en": "Project exported successfully.",
        "fr": "Projet exporté avec succès.",
        "it": "Progetto esportato con successo.",
    },
    "proj.import_done": {
        "de": "{n} Teil(e) erfolgreich importiert.",
        "en": "{n} part(s) imported successfully.",
        "fr": "{n} pièce(s) importée(s) avec succès.",
        "it": "{n} pezzo/i importato/i con successo.",
    },
    "proj.import_missing": {
        "de": "Folgende Materialien wurden nicht gefunden, betroffene Teile übersprungen:\n{materials}",
        "en": "The following materials were not found, affected parts skipped:\n{materials}",
        "fr": "Les matériaux suivants n'ont pas été trouvés, pièces concernées ignorées:\n{materials}",
        "it": "I seguenti materiali non sono stati trovati, pezzi interessati saltati:\n{materials}",
    },
    # ---- Backup / Restore ----
    "set.backup": {
        "de": "Backup", "en": "Backup", "fr": "Sauvegarde", "it": "Backup",
    },
    "set.backup_create": {
        "de": "Backup erstellen", "en": "Create Backup",
        "fr": "Créer une sauvegarde", "it": "Crea backup",
    },
    "set.backup_restore": {
        "de": "Backup wiederherstellen", "en": "Restore Backup",
        "fr": "Restaurer sauvegarde", "it": "Ripristina backup",
    },
    "set.backup_done": {
        "de": "Backup erfolgreich erstellt.", "en": "Backup created successfully.",
        "fr": "Sauvegarde créée avec succès.", "it": "Backup creato con successo.",
    },
    "set.backup_confirm": {
        "de": "Alle aktuellen Daten werden überschrieben. Fortfahren?",
        "en": "All current data will be overwritten. Continue?",
        "fr": "Toutes les données actuelles seront écrasées. Continuer?",
        "it": "Tutti i dati attuali verranno sovrascritti. Continuare?",
    },
    "set.backup_invalid": {
        "de": "Ungültiges Backup: Die ZIP-Datei enthält keine gültige Datenbank.",
        "en": "Invalid backup: The ZIP file does not contain a valid database.",
        "fr": "Sauvegarde invalide: le fichier ZIP ne contient pas de base de données valide.",
        "it": "Backup non valido: il file ZIP non contiene un database valido.",
    },
    "set.backup_restored": {
        "de": "Backup erfolgreich wiederhergestellt. Die App wird neu gestartet.",
        "en": "Backup restored successfully. The app will restart.",
        "fr": "Sauvegarde restaurée avec succès. L'application va redémarrer.",
        "it": "Backup ripristinato con successo. L'app verrà riavviata.",
    },
    # ---- Statistik ----
    "stat.title": {
        "de": "Statistik", "en": "Statistics", "fr": "Statistiques",
        "it": "Statistiche",
    },
    "stat.stock_used": {
        "de": "Lagerstücke verwendet", "en": "Stock pieces used",
        "fr": "Pièces de stock utilisées", "it": "Pezzi a magazzino utilizzati",
    },
    "stat.parts_placed": {
        "de": "Teile platziert", "en": "Parts placed",
        "fr": "Pièces placées", "it": "Pezzi piazzati",
    },
    "stat.parts_missing": {
        "de": "Fehlende Teile", "en": "Missing parts",
        "fr": "Pièces manquantes", "it": "Pezzi mancanti",
    },
    "stat.total_waste": {
        "de": "Gesamtverschnitt", "en": "Total waste",
        "fr": "Chute totale", "it": "Sfrido totale",
    },
    "stat.utilization": {
        "de": "Materialausnutzung", "en": "Material utilization",
        "fr": "Utilisation du matériau", "it": "Utilizzo del materiale",
    },
    "stat.per_stock": {
        "de": "Pro Lagerstück", "en": "Per stock piece",
        "fr": "Par pièce de stock", "it": "Per pezzo a magazzino",
    },
    "opt.preview": {
        "de": "Vorschau", "en": "Preview", "fr": "Aperçu", "it": "Anteprima",
    },
    "opt.algo_greedy": {
        "de": "Schnell (Greedy)", "en": "Fast (Greedy)",
        "fr": "Rapide (Greedy)", "it": "Veloce (Greedy)",
    },
    "opt.algo_nested": {
        "de": "Nested Guillotine (Platten)", "en": "Nested Guillotine (Panels)",
        "fr": "Guillotine imbriquée (Panneaux)", "it": "Ghigliottina nidificata (Pannelli)",
    },
    "opt.algo_ga": {
        "de": "Gründlich (GA)", "en": "Thorough (GA)",
        "fr": "Approfondi (GA)", "it": "Approfondito (GA)",
    },
    "proj.progress": {
        "de": "Fortschritt", "en": "Progress", "fr": "Progression", "it": "Progresso",
    },
    "part.cut_plus": {
        "de": "Gesägt +1", "en": "Cut +1", "fr": "Coupé +1", "it": "Tagliato +1",
    },
    "part.cut_minus": {
        "de": "Gesägt -1", "en": "Cut -1", "fr": "Coupé -1", "it": "Tagliato -1",
    },
    # ----- Tastenkürzel (Web) -----
    "hotkey.title": {
        "de": "Tastenkürzel", "en": "Keyboard Shortcuts",
        "fr": "Raccourcis clavier", "it": "Scorciatoie da tastiera",
    },
    "hotkey.key": {
        "de": "Taste", "en": "Key", "fr": "Touche", "it": "Tasto",
    },
    "hotkey.action": {
        "de": "Aktion", "en": "Action", "fr": "Action", "it": "Azione",
    },
    "hotkey.tabs": {
        "de": "Tab wechseln", "en": "Switch tab",
        "fr": "Changer d'onglet", "it": "Cambiare scheda",
    },
    "hotkey.new": {
        "de": "Neues Element (Material / Projekt / Bauteil / Sägeblatt)",
        "en": "New item (material / project / part / saw blade)",
        "fr": "Nouvel élément (matériau / projet / pièce / lame)",
        "it": "Nuovo elemento (materiale / progetto / pezzo / lama)",
    },
    "hotkey.edit": {
        "de": "Ausgewähltes Element bearbeiten", "en": "Edit selected item",
        "fr": "Modifier l'élément sélectionné", "it": "Modifica elemento selezionato",
    },
    "hotkey.delete": {
        "de": "Ausgewähltes Element löschen", "en": "Delete selected item",
        "fr": "Supprimer l'élément sélectionné", "it": "Elimina elemento selezionato",
    },
    "hotkey.del_key": {
        "de": "Entf", "en": "Del", "fr": "Suppr", "it": "Canc",
    },
    "hotkey.stock": {
        "de": "Neuer Lagerbestand (Material-Tab)", "en": "New stock item (material tab)",
        "fr": "Nouveau stock (onglet matériaux)", "it": "Nuova giacenza (scheda materiali)",
    },
    "hotkey.optimize": {
        "de": "Optimierung starten", "en": "Run optimization",
        "fr": "Lancer l'optimisation", "it": "Avvia ottimizzazione",
    },
    "hotkey.save": {
        "de": "Dialog speichern", "en": "Save dialog",
        "fr": "Enregistrer le dialogue", "it": "Salva finestra",
    },
    "hotkey.close": {
        "de": "Dialog schließen", "en": "Close dialog",
        "fr": "Fermer le dialogue", "it": "Chiudi finestra",
    },
    "hotkey.hint": {
        "de": "Auf eine Taste klicken, um sie zu ändern. Esc bricht ab.",
        "en": "Click a key to change it. Esc cancels.",
        "fr": "Cliquez sur une touche pour la modifier. Échap annule.",
        "it": "Clicca su un tasto per modificarlo. Esc annulla.",
    },
    "hotkey.press": {
        "de": "Taste drücken …", "en": "Press a key …",
        "fr": "Appuyez sur une touche …", "it": "Premi un tasto …",
    },
    "hotkey.conflict": {
        "de": "Taste {key} ist bereits belegt.",
        "en": "Key {key} is already in use.",
        "fr": "La touche {key} est déjà utilisée.",
        "it": "Il tasto {key} è già in uso.",
    },
    "part.sawn_count": {
        "de": "Gesägt (Stück):", "en": "Sawn (pieces):",
        "fr": "Scié (pièces) :", "it": "Tagliato (pezzi):",
    },
    "set.about": {
        "de": "Über / Links", "en": "About / Links",
        "fr": "À propos / Liens", "it": "Info / Link",
    },
    "set.version": {
        "de": "Version:", "en": "Version:", "fr": "Version :", "it": "Versione:",
    },
    "set.website": {
        "de": "Projektseite (WorldGate)", "en": "Project page (WorldGate)",
        "fr": "Page du projet (WorldGate)", "it": "Pagina del progetto (WorldGate)",
    },
    "set.github": {
        "de": "Quellcode auf GitHub", "en": "Source code on GitHub",
        "fr": "Code source sur GitHub", "it": "Codice sorgente su GitHub",
    },
    "set.check_update": {
        "de": "Nach Updates suchen", "en": "Check for updates",
        "fr": "Rechercher des mises à jour", "it": "Controlla aggiornamenti",
    },
    "set.checking_update": {
        "de": "Suche nach Updates …", "en": "Checking for updates …",
        "fr": "Recherche de mises à jour …", "it": "Ricerca aggiornamenti …",
    },
    "set.update_available": {
        "de": "Update verfügbar: {version}", "en": "Update available: {version}",
        "fr": "Mise à jour disponible : {version}", "it": "Aggiornamento disponibile: {version}",
    },
    "set.up_to_date": {
        "de": "CutStock ist aktuell ({version}).", "en": "CutStock is up to date ({version}).",
        "fr": "CutStock est à jour ({version}).", "it": "CutStock è aggiornato ({version}).",
    },
    "set.update_failed": {
        "de": "Update-Prüfung fehlgeschlagen (keine Verbindung?).",
        "en": "Update check failed (no connection?).",
        "fr": "Échec de la vérification (pas de connexion ?).",
        "it": "Controllo aggiornamenti fallito (nessuna connessione?).",
    },
    "stat.usable_remnant": {
        "de": "Nutzbares Restmaterial", "en": "Usable remnant",
        "fr": "Chutes réutilisables", "it": "Sfrido riutilizzabile",
    },
    "stat.real_waste": {
        "de": "echter Verschnitt", "en": "real waste",
        "fr": "chute réelle", "it": "scarto reale",
    },
    "opt.algorithm": {
        "de": "Algorithmus", "en": "Algorithm",
        "fr": "Algorithme", "it": "Algoritmo",
    },
    "opt.zoom": {
        "de": "Vergrößern", "en": "Zoom", "fr": "Agrandir", "it": "Ingrandisci",
    },
    "opt.saw_hint": {
        "de": "Tipp: Auf ein Stück im Schnittplan klicken, um es als gesägt zu markieren.",
        "en": "Tip: click a piece in the cut plan to mark it as sawn.",
        "fr": "Astuce : cliquez sur une pièce du plan de coupe pour la marquer comme sciée.",
        "it": "Suggerimento: clicca su un pezzo nel piano di taglio per segnarlo come tagliato.",
    },
    # ---- Schnittfolge ----
    "seq.title": {
        "de": "Schnittfolge", "en": "Cutting sequence",
        "fr": "Séquence de coupe", "it": "Sequenza di taglio",
    },
    "seq.cut_v": {
        "de": "bei {pos} von links", "en": "at {pos} from left",
        "fr": "à {pos} depuis la gauche", "it": "a {pos} da sinistra",
    },
    "seq.cut_h": {
        "de": "bei {pos} von oben", "en": "at {pos} from top",
        "fr": "à {pos} depuis le haut", "it": "a {pos} dall'alto",
    },
    "seq.cut_1d": {
        "de": "{label}: {len} ablängen", "en": "{label}: cut {len} to length",
        "fr": "{label} : couper à {len}", "it": "{label}: tagliare a {len}",
    },
    # ---- Werkstatt-Modus ----
    "saw.mode": {
        "de": "Werkstatt-Modus", "en": "Workshop mode",
        "fr": "Mode atelier", "it": "Modalità officina",
    },
    "saw.next_piece": {
        "de": "Als Nächstes", "en": "Up next",
        "fr": "À suivre", "it": "Prossimo",
    },
    "saw.done": {
        "de": "Alle Teile gesägt", "en": "All pieces sawn",
        "fr": "Toutes les pièces sciées", "it": "Tutti i pezzi tagliati",
    },
    # ---- Etiketten ----
    "labels.button": {
        "de": "Etiketten", "en": "Labels",
        "fr": "Étiquettes", "it": "Etichette",
    },
    "labels.stock": {
        "de": "Lager/Rest", "en": "Stock/Remnant",
        "fr": "Stock/Chute", "it": "Magazzino/Sfrido",
    },
    "labels.format": {
        "de": "Papierformat:", "en": "Paper format:",
        "fr": "Format du papier:", "it": "Formato carta:",
    },
    "labels.fmt_a4_3x8": {
        "de": "A4-Bogen 3×8 (70×36 mm, Avery 3475)",
        "en": "A4 sheet 3×8 (70×36 mm, Avery 3475)",
        "fr": "Feuille A4 3×8 (70×36 mm, Avery 3475)",
        "it": "Foglio A4 3×8 (70×36 mm, Avery 3475)",
    },
    "labels.fmt_a4_3x7": {
        "de": "A4-Bogen 3×7 (63,5×38,1 mm, Avery L7160)",
        "en": "A4 sheet 3×7 (63.5×38.1 mm, Avery L7160)",
        "fr": "Feuille A4 3×7 (63,5×38,1 mm, Avery L7160)",
        "it": "Foglio A4 3×7 (63,5×38,1 mm, Avery L7160)",
    },
    "labels.fmt_roll_89x36": {
        "de": "Etikettendrucker 89×36 mm (z.B. Dymo 99012)",
        "en": "Label printer 89×36 mm (e.g. Dymo 99012)",
        "fr": "Imprimante d'étiquettes 89×36 mm (p.ex. Dymo 99012)",
        "it": "Stampante di etichette 89×36 mm (es. Dymo 99012)",
    },
    "labels.fmt_roll_62x29": {
        "de": "Etikettendrucker 62×29 mm (z.B. Brother DK-11209)",
        "en": "Label printer 62×29 mm (e.g. Brother DK-11209)",
        "fr": "Imprimante d'étiquettes 62×29 mm (p.ex. Brother DK-11209)",
        "it": "Stampante di etichette 62×29 mm (es. Brother DK-11209)",
    },
    "labels.fmt_custom": {
        "de": "Benutzerdefiniert (1 Etikett pro Seite)",
        "en": "Custom (1 label per page)",
        "fr": "Personnalisé (1 étiquette par page)",
        "it": "Personalizzato (1 etichetta per pagina)",
    },
    "labels.custom_w": {
        "de": "Etikett Breite (mm):", "en": "Label width (mm):",
        "fr": "Largeur étiquette (mm):", "it": "Larghezza etichetta (mm):",
    },
    "labels.custom_h": {
        "de": "Etikett Höhe (mm):", "en": "Label height (mm):",
        "fr": "Hauteur étiquette (mm):", "it": "Altezza etichetta (mm):",
    },
    # ---- CSV-Import ----
    "csv.import": {
        "de": "CSV-Import", "en": "CSV import",
        "fr": "Import CSV", "it": "Import CSV",
    },
    "csv.confirm": {
        "de": "{n} Teile erkannt (Maße in {unit}). Spalten: Label, Länge, Breite, Anzahl, Maserung, Material.",
        "en": "{n} parts detected (dimensions in {unit}). Columns: label, length, width, quantity, grain, material.",
        "fr": "{n} pièces détectées (dimensions en {unit}). Colonnes : label, longueur, largeur, quantité, veinage, matériau.",
        "it": "{n} pezzi rilevati (dimensioni in {unit}). Colonne: label, lunghezza, larghezza, quantità, venatura, materiale.",
    },
    "csv.default_material": {
        "de": "Material (falls Spalte fehlt):", "en": "Material (if column missing):",
        "fr": "Matériau (si colonne absente):", "it": "Materiale (se manca la colonna):",
    },
    "set.license_note": {
        "de": "CC BY-NC-SA 4.0 — kostenlos für den privaten, nicht-kommerziellen Einsatz. Für den Einsatz im Betrieb ist eine kommerzielle Lizenz auf Anfrage erhältlich (Kontakt über die Projektseite).",
        "en": "CC BY-NC-SA 4.0 — free for private, non-commercial use. For business use, a commercial license is available on request (contact via the project page).",
        "fr": "CC BY-NC-SA 4.0 — gratuit pour un usage privé et non commercial. Pour un usage professionnel, une licence commerciale est disponible sur demande (contact via la page du projet).",
        "it": "CC BY-NC-SA 4.0 — gratuito per uso privato e non commerciale. Per l'uso in azienda è disponibile una licenza commerciale su richiesta (contatto tramite la pagina del progetto).",
    },
    "csv.invalid": {
        "de": "CSV konnte nicht gelesen werden.", "en": "Could not read the CSV file.",
        "fr": "Impossible de lire le fichier CSV.", "it": "Impossibile leggere il file CSV.",
    },
}

LANGUAGES = {"en": "English", "de": "Deutsch", "fr": "Français", "it": "Italiano"}

_current_lang = None


def current_language() -> str:
    global _current_lang
    if _current_lang is None:
        from core.settings import get_settings
        _current_lang = get_settings().value("appearance/language", "en")
    return _current_lang


def set_language(lang: str):
    global _current_lang
    _current_lang = lang
    from core.settings import get_settings
    get_settings().setValue("appearance/language", lang)


def t(key: str, **kwargs) -> str:
    """Übersetzung holen. Fehlende Keys geben den Key selbst zurück."""
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    text = entry.get(current_language(), entry.get("en", key))
    if kwargs:
        text = text.format(**kwargs)
    return text
