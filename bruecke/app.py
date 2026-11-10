"""CutStock Druckbrücke – Symbol in der Menüleiste (macOS).

Zeigt, ob die Brücke läuft und der Drucker bereit ist; Einrichten (Adresse + Kopplungscode),
Pausieren, Beim Anmelden starten, Beenden. Die Arbeit macht bruecke.verbindung.Bruecke in
einem eigenen Thread; die Anzeige liest deren Lage einmal pro Sekunde.
"""

from __future__ import annotations

import fcntl
import locale
import os
import plistlib
import sys
import webbrowser
from pathlib import Path

import objc
from AppKit import (NSAlert, NSApplication, NSApplicationActivationPolicyAccessory,
                    NSImage, NSMakeRect, NSMenu, NSMenuItem, NSStatusBar, NSStackView,
                    NSTextField, NSUserInterfaceLayoutOrientationVertical,
                    NSVariableStatusItemLength)
from Foundation import NSObject, NSTimer

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bruecke.verbindung import (KONFIG_DIR, Bruecke, Konfig, adresse_normalisieren,  # noqa: E402
                                code_normalisieren)

AGENT = Path.home() / "Library" / "LaunchAgents" / "one.rohde.cutstock-druckbruecke.plist"


def _version() -> str:
    for basis in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent.parent):
        if basis and (Path(basis) / "VERSION").is_file():
            return (Path(basis) / "VERSION").read_text().strip()
    return ""


DE = (locale.getlocale()[0] or os.environ.get("LANG", "de")).lower().startswith("de")

TEXTE = {
    "titel": ("CutStock Druckbrücke", "CutStock print bridge"),
    "start": ("Startet …", "Starting …"),
    "nicht_eingerichtet": ("Noch nicht eingerichtet", "Not set up yet"),
    "bereit": ("Bereit – {modell}, {band}-mm-Band", "Ready – {modell}, {band} mm tape"),
    "druckt": ("Druckt …", "Printing …"),
    "pausiert": ("Pausiert", "Paused"),
    "kein_drucker": ("Kein Drucker gefunden (USB, eingeschaltet?)",
                     "No printer found (USB, switched on?)"),
    "druckerfehler": ("Drucker meldet: {code}", "Printer reports: {code}"),
    "offline": ("Keine Verbindung zu CutStock", "No connection to CutStock"),
    "code_ungueltig": ("Kopplungscode ungültig – neu einrichten",
                       "Pairing code rejected – set up again"),
    "verbunden": ("Instanz: {host}", "Instance: {host}"),
    "gedruckt": ("Seit dem Start gedruckt: {n} Etikett(en)", "Printed since start: {n} label(s)"),
    "pausieren": ("Pausieren", "Pause"),
    "fortsetzen": ("Fortsetzen", "Resume"),
    "oeffnen": ("CutStock öffnen", "Open CutStock"),
    "einrichten": ("Einrichten …", "Set up …"),
    "anmelden": ("Beim Anmelden starten", "Start at login"),
    "beenden": ("Druckbrücke beenden", "Quit print bridge"),
    "dlg_titel": ("Druckbrücke einrichten", "Set up print bridge"),
    "dlg_text": ("Adresse deiner CutStock-Instanz und den Kopplungscode aus CutStock "
                 "(Einstellungen → Etiketten & Drucker → Druckbrücke → Koppeln) eingeben.",
                 "Enter the address of your CutStock instance and the pairing code from "
                 "CutStock (Settings → Labels & printer → Print bridge → Pair)."),
    "dlg_adresse": ("Adresse, z. B. https://cutstock.example.com",
                    "Address, e.g. https://cutstock.example.com"),
    "dlg_code": ("Kopplungscode, z. B. ABCD-EFGH-JKLM-NPQR-STUV",
                 "Pairing code, e.g. ABCD-EFGH-JKLM-NPQR-STUV"),
    "ok": ("Speichern", "Save"),
    "abbrechen": ("Abbrechen", "Cancel"),
    "code_falsch": ("Der Kopplungscode stimmt nicht – er hat 20 Zeichen (Buchstaben und Ziffern "
                    "2–9), z. B. ABCD-EFGH-JKLM-NPQR-STUV. Am besten in CutStock kopieren und hier "
                    "einfügen (⌘V).",
                    "The pairing code is not valid – it has 20 characters (letters and digits "
                    "2–9), e.g. ABCD-EFGH-JKLM-NPQR-STUV. Best copy it in CutStock and paste it "
                    "here (⌘V)."),
    "adresse_fehlt": ("Bitte die Adresse der CutStock-Instanz eingeben.",
                      "Please enter the address of the CutStock instance."),
    "bearbeiten": ("Bearbeiten", "Edit"),
    "laeuft_schon": ("Die Druckbrücke läuft bereits.", "The print bridge is already running."),
}


def tx(key: str, **kw) -> str:
    de, en = TEXTE[key]
    return (de if DE else en).format(**kw)


def anmeldeobjekt_an() -> bool:
    return AGENT.is_file()


def anmeldeobjekt_setzen(an: bool):
    """Als LaunchAgent eintragen: startet bei der Anmeldung (wirkt ab der nächsten)."""
    if not an:
        AGENT.unlink(missing_ok=True)
        return
    programm = sys.executable if getattr(sys, "frozen", False) else None
    if programm is None:
        return    # nur in der gebauten App sinnvoll
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(plistlib.dumps({
        "Label": "one.rohde.cutstock-druckbruecke",
        "ProgramArguments": [programm],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }))


class Steuerung(NSObject):
    def initMitBruecke_(self, bruecke):
        self = objc.super(Steuerung, self).init()
        if self is None:
            return None
        self.bruecke = bruecke
        self.symbol = None
        self.letzte = None
        self.codefeld = None
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        self.menue = NSMenu.alloc().init()
        self.menue.setAutoenablesItems_(False)
        self.item.setMenu_(self.menue)
        self.zeile_status = self._eintrag("", None)
        self.zeile_instanz = self._eintrag("", None)
        self.zeile_zaehler = self._eintrag("", None)
        self.menue.addItem_(NSMenuItem.separatorItem())
        self.punkt_pause = self._eintrag(tx("pausieren"), "pause:")
        self.punkt_oeffnen = self._eintrag(tx("oeffnen"), "oeffnen:")
        self._eintrag(tx("einrichten"), "einrichten:")
        self.punkt_anmelden = self._eintrag(tx("anmelden"), "anmelden:")
        self.menue.addItem_(NSMenuItem.separatorItem())
        v = self._eintrag(f"{tx('titel')} {bruecke.version}", None)
        v.setEnabled_(False)
        self._eintrag(tx("beenden"), "beenden:")
        for z in (self.zeile_status, self.zeile_instanz, self.zeile_zaehler):
            z.setEnabled_(False)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "aktualisieren:", None, True)
        self.aktualisieren_(None)
        return self

    @objc.python_method
    def _eintrag(self, titel, aktion):
        m = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(titel, aktion, "")
        if aktion:
            m.setTarget_(self)
        self.menue.addItem_(m)
        return m

    @objc.python_method
    def _symbol_setzen(self, name: str):
        if name == self.symbol:
            return
        self.symbol = name
        bild = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, tx("titel"))
        bild.setTemplate_(True)
        self.item.button().setImage_(bild)
        self.item.button().setToolTip_(tx("titel"))

    def aktualisieren_(self, _timer):
        b, lage = self.bruecke, self.bruecke.lage
        d = lage.drucker or {}
        z = lage.zustand
        if z == "bereit":
            text = tx("bereit", modell=d.get("modell", ""), band=d.get("band_mm", 0))
        elif z == "druckerfehler":
            text = tx("druckerfehler", code=d.get("code", ""))
        else:
            text = tx(z)
        self.zeile_status.setTitle_(text)
        if z == "code_ungueltig" and self.letzte != "code_ungueltig":
            self.performSelector_withObject_afterDelay_("einrichten:", None, 0.3)
        self.letzte = z
        host = b.konfig.adresse.split("://")[-1] if b.konfig.adresse else "–"
        self.zeile_instanz.setTitle_(tx("verbunden", host=host))
        self.zeile_zaehler.setTitle_(tx("gedruckt", n=lage.gedruckt))
        self.punkt_pause.setTitle_(tx("fortsetzen" if b.konfig.pausiert else "pausieren"))
        self.punkt_pause.setEnabled_(b.konfig.eingerichtet)
        self.punkt_oeffnen.setEnabled_(bool(b.konfig.adresse))
        self.punkt_anmelden.setState_(1 if anmeldeobjekt_an() else 0)
        self.punkt_anmelden.setEnabled_(bool(getattr(sys, "frozen", False)))
        self._symbol_setzen({"bereit": "printer", "druckt": "printer.fill",
                             "pausiert": "pause.circle"}.get(z, "exclamationmark.triangle"))

    def controlTextDidChange_(self, notiz):
        """Kopplungscode beim Tippen in Großbuchstaben – ohne Umschalttaste."""
        feld = notiz.object()
        if feld is not getattr(self, "codefeld", None):
            return
        text = str(feld.stringValue())
        if text != text.upper():
            editor = feld.currentEditor()
            auswahl = editor.selectedRange() if editor else None
            feld.setStringValue_(text.upper())
            if editor and auswahl is not None:
                editor.setSelectedRange_(auswahl)

    # --- Menüpunkte ------------------------------------------------------------

    def pause_(self, _):
        k = self.bruecke.konfig
        k.pausiert = not k.pausiert
        k.speichern()
        self.bruecke.neu_verbinden()
        self.aktualisieren_(None)

    def oeffnen_(self, _):
        if self.bruecke.konfig.adresse:
            webbrowser.open(self.bruecke.konfig.adresse)

    def anmelden_(self, _):
        anmeldeobjekt_setzen(not anmeldeobjekt_an())
        self.aktualisieren_(None)

    def beenden_(self, _):
        self.bruecke.anhalten()
        NSApplication.sharedApplication().terminate_(None)

    def einrichten_(self, _):
        k = self.bruecke.konfig
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_(tx("dlg_titel"))
        alert.setInformativeText_(tx("dlg_text"))
        alert.addButtonWithTitle_(tx("ok"))
        alert.addButtonWithTitle_(tx("abbrechen"))
        adresse = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 24))
        adresse.setPlaceholderString_(tx("dlg_adresse"))
        adresse.setStringValue_(k.adresse)
        code = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 24))
        code.setPlaceholderString_(tx("dlg_code"))
        code.setStringValue_(k.code)
        code.setDelegate_(self)          # beim Tippen gleich in Großbuchstaben
        self.codefeld = code
        stapel = NSStackView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 56))
        stapel.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stapel.setSpacing_(8)
        stapel.addView_inGravity_(adresse, 1)
        stapel.addView_inGravity_(code, 1)
        alert.setAccessoryView_(stapel)
        alert.window().setInitialFirstResponder_(adresse)
        while True:
            if alert.runModal() != 1000:      # erster Knopf = Speichern
                return
            neue_adresse = adresse_normalisieren(str(adresse.stringValue()))
            neuer_code = code_normalisieren(str(code.stringValue()))
            if not neue_adresse:
                alert.setInformativeText_(tx("adresse_fehlt"))
                alert.window().setInitialFirstResponder_(adresse)
            elif neuer_code is None:
                alert.setInformativeText_(tx("code_falsch"))
                alert.window().setInitialFirstResponder_(code)
            else:
                break
        k.adresse, k.code = neue_adresse, neuer_code
        k.speichern()
        if not anmeldeobjekt_an():
            anmeldeobjekt_setzen(True)    # beim ersten Einrichten gleich mit eintragen
        self.bruecke.neu_verbinden()
        self.aktualisieren_(None)


def _bearbeiten_menue(app):
    """⌘X/⌘C/⌘V/⌘A/⌘Z kommen unter macOS über das Menü „Bearbeiten“ – auch eine App nur in der
    Menüleiste braucht es, sonst kann man im Einrichten-Dialog nichts einfügen."""
    haupt = NSMenu.alloc().init()
    app_punkt = NSMenuItem.alloc().init()
    haupt.addItem_(app_punkt)
    app_menue = NSMenu.alloc().init()
    app_menue.addItemWithTitle_action_keyEquivalent_(tx("beenden"), "terminate:", "q")
    app_punkt.setSubmenu_(app_menue)
    punkt = NSMenuItem.alloc().init()
    haupt.addItem_(punkt)
    menue = NSMenu.alloc().initWithTitle_(tx("bearbeiten"))
    for titel, aktion, taste in (("Undo", "undo:", "z"), ("Redo", "redo:", "Z"),
                                 ("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                                 ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")):
        menue.addItemWithTitle_action_keyEquivalent_(titel, aktion, taste)
    punkt.setSubmenu_(menue)
    app.setMainMenu_(haupt)


def _nur_einmal():
    """Zweiter Start (z. B. Doppelklick, obwohl sie schon läuft) beendet sich gleich."""
    KONFIG_DIR.mkdir(parents=True, exist_ok=True)
    f = open(KONFIG_DIR / "laeuft.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


def main():
    sperre = _nur_einmal()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # kein Dock-Symbol
    _bearbeiten_menue(app)
    if sperre is None:
        a = NSAlert.alloc().init()
        a.setMessageText_(tx("laeuft_schon"))
        app.activateIgnoringOtherApps_(True)
        a.runModal()
        return
    bruecke = Bruecke(Konfig.laden(), version=_version())
    steuerung = Steuerung.alloc().initMitBruecke_(bruecke)
    bruecke.starten()
    if not bruecke.konfig.eingerichtet:
        steuerung.performSelector_withObject_afterDelay_("einrichten:", None, 0.5)
    app.run()


if __name__ == "__main__":
    main()
