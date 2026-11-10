"""Druckbrücke ohne Oberfläche: meldet den Druckerstatus an eine CutStock-Instanz, holt
Druckaufträge ab und gibt sie per USB an den P-touch.

Die Verbindung geht immer von hier aus (langes Warten auf Aufträge, „Long-Poll“) – die
Instanz muss diesen Rechner nicht erreichen können. Gedruckt wird nur, was CutStock fertig
geschickt hat; Layouts kennt die Brücke nicht.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from core import drucker

WARTEN_S = 25          # so lange wartet die Instanz mit der Antwort, wenn nichts ansteht
PAUSE_S = 5            # Abstand der Meldungen ohne Drucker / pausiert / nach Fehlern

KONFIG_DIR = Path.home() / "Library" / "Application Support" / "CutStock Druckbruecke"


def rechnername() -> str:
    try:
        name = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
        if name:
            return name
    except (OSError, subprocess.SubprocessError):
        pass
    return socket.gethostname().removesuffix(".local")


CODE_ZEICHEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # wie in CutStock (ohne 0/O, 1/I)


def code_normalisieren(code: str) -> str | None:
    """Kopplungscode in die Form ABCD-EFGH-JKLM-NPQR-STUV bringen; None bei Tippfehlern.
    Leerzeichen, Kleinbuchstaben und fehlende Bindestriche sind egal."""
    roh = "".join(c for c in code.upper() if c not in " -\t\n")
    if len(roh) != 20 or any(c not in CODE_ZEICHEN for c in roh):
        return None
    return "-".join(roh[i:i + 4] for i in range(0, 20, 4))


def adresse_normalisieren(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    return url


@dataclass
class Konfig:
    adresse: str = ""
    code: str = ""
    pausiert: bool = False

    @classmethod
    def laden(cls, pfad: Path | None = None) -> "Konfig":
        pfad = pfad or KONFIG_DIR / "config.json"
        try:
            d = json.loads(pfad.read_text())
        except (OSError, ValueError):
            return cls()
        return cls(adresse=str(d.get("adresse", "")), code=str(d.get("code", "")),
                   pausiert=bool(d.get("pausiert", False)))

    def speichern(self, pfad: Path | None = None):
        pfad = pfad or KONFIG_DIR / "config.json"
        pfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = pfad.with_suffix(".tmp")
        tmp.write_text(json.dumps({"adresse": self.adresse, "code": self.code,
                                   "pausiert": self.pausiert}, indent=2))
        os.chmod(tmp, 0o600)          # der Kopplungscode ist ein Zugangsschlüssel
        tmp.replace(pfad)

    @property
    def eingerichtet(self) -> bool:
        return bool(self.adresse and self.code)


@dataclass
class Lage:
    """Was die Menüleiste anzeigt."""
    zustand: str = "start"     # start, nicht_eingerichtet, bereit, druckt, pausiert,
                               # kein_drucker, druckerfehler, offline, code_ungueltig
    drucker: dict = field(default_factory=dict)
    meldung: str = ""          # z. B. letzter Fehler oder „3 Etiketten gedruckt“
    gedruckt: int = 0          # Etiketten seit dem Start


def _ssl_kontext():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class Bruecke:
    def __init__(self, konfig: Konfig, version: str = "", status=None, drucken=None,
                 senden=None):
        self.konfig = konfig
        self.version = version
        self.lage = Lage()
        self.name = rechnername()
        self._status = status or drucker.status
        self._drucken = drucken or drucker.drucken_daten
        self._senden = senden or self._http
        self._stopp = threading.Event()
        self._wecken = threading.Event()
        self._ssl = _ssl_kontext()

    # --- Steuerung von außen (Menüleiste) ---------------------------------------

    def starten(self) -> threading.Thread:
        t = threading.Thread(target=self.laufen, name="druckbruecke", daemon=True)
        t.start()
        return t

    def anhalten(self):
        self._stopp.set()
        self._wecken.set()

    def neu_verbinden(self):
        """Nach Einrichten / Pause: sofort melden statt den Abstand abzuwarten."""
        self._wecken.set()

    # --- Schleife ------------------------------------------------------------

    def laufen(self):
        while not self._stopp.is_set():
            warten = self.einmal()
            self._wecken.wait(warten)
            self._wecken.clear()

    def einmal(self) -> float:
        """Ein Durchgang: Status melden, ggf. Auftrag drucken. Liefert die Pause danach."""
        k = self.konfig
        if not k.eingerichtet:
            self.lage.zustand = "nicht_eingerichtet"
            return PAUSE_S
        st = self._status()
        self.lage.drucker = st
        hallo = {"name": self.name, "version": self.version, "pausiert": k.pausiert,
                 "gefunden": bool(st.get("gefunden")), "modell": st.get("modell", ""),
                 "band_mm": int(st.get("band_mm") or 0), "medium": st.get("medium", ""),
                 "fehler": list(st.get("fehler") or []), "code": st.get("code", "")}
        bereit = hallo["gefunden"] and not hallo["code"] and not k.pausiert
        try:
            antwort = self._senden("POST", f"/api/printer/bridge/poll?wait={WARTEN_S if bereit else 0}",
                                   hallo)
        except PermissionError:
            self.lage.zustand = "code_ungueltig"
            return PAUSE_S * 2
        except OSError as e:
            self.lage.zustand, self.lage.meldung = "offline", str(e)[:120]
            return PAUSE_S
        if k.pausiert:
            self.lage.zustand = "pausiert"
        elif not hallo["gefunden"]:
            self.lage.zustand = "kein_drucker"
        elif hallo["code"]:
            self.lage.zustand = "druckerfehler"
        else:
            self.lage.zustand = "bereit"
        auftrag = (antwort or {}).get("auftrag")
        if not auftrag:
            return 0.0 if bereit else PAUSE_S
        self._auftrag_drucken(auftrag)
        return 0.0

    def _auftrag_drucken(self, a: dict):
        self.lage.zustand = "druckt"
        ergebnis = {"gedruckt": 0, "code": "", "text": ""}
        try:
            seiten = [base64.b64decode(x) for x in a["seiten"]]
            erg = self._drucken(seiten, list(a["laengen"]), int(a["band_mm"]),
                                medium=a.get("medium"))
            ergebnis["gedruckt"] = int(erg.get("gedruckt", 0))
            self.lage.gedruckt += int(a.get("etiketten") or 0)
            self.lage.meldung = f"ok:{a.get('etiketten', 0)}"
        except drucker.DruckerFehler as e:
            ergebnis.update(gedruckt=int(e.extra.get("gedruckt", 0)), code=e.code, text=e.text)
            self.lage.meldung = f"fehler:{e.code}"
        except Exception as e:  # noqa: BLE001 – Ergebnis immer melden
            ergebnis.update(code="drucker_fehler", text=str(e)[:200])
            self.lage.meldung = "fehler:drucker_fehler"
        self.lage.zustand = "bereit"
        for _ in range(3):   # Ergebnis nicht verlieren, wenn das Netz kurz hakt
            try:
                self._senden("POST", f"/api/printer/bridge/jobs/{a['id']}/result", ergebnis)
                return
            except PermissionError:
                return
            except OSError:
                time.sleep(2)

    # --- HTTP ----------------------------------------------------------------

    def _http(self, methode: str, pfad: str, daten: dict) -> dict:
        req = urllib.request.Request(
            self.konfig.adresse + pfad, method=methode, data=json.dumps(daten).encode(),
            headers={"Content-Type": "application/json", "X-CutStock-Bridge": self.konfig.code,
                     "User-Agent": f"CutStock-Druckbruecke/{self.version}"})
        try:
            with urllib.request.urlopen(req, timeout=WARTEN_S + 20, context=self._ssl) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PermissionError("pairing code rejected") from e
            raise OSError(f"HTTP {e.code}") from e
