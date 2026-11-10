"""Warteschlange für die Druckbrücke: Aufträge, die ein Hilfsprogramm beim Drucker abholt.

Die Brücke meldet sich regelmäßig (Status des Druckers) und fragt dabei nach Arbeit. Ein Auftrag
enthält fertige Druckdaten je Seite. Bandschutz:
- Ein Auftrag, der nicht innerhalb von ABHOLEN_S abgeholt wird, verfällt – kein Druck Stunden
  später, wenn der Rechner wieder angeht.
- Ein abgeholter Auftrag wird nie ein zweites Mal ausgegeben. Kommt kein Ergebnis, heißt er
  „unbekannt“ – lieber einmal zu wenig als doppelt drucken.

Alles im Speicher: Aufträge leben Sekunden bis Minuten, ein Neustart verwirft sie.
"""

from __future__ import annotations

import secrets
import threading
import time

ABHOLEN_S = 60        # so lange wartet ein Auftrag auf die Brücke
ERGEBNIS_S = 300      # so lange darf der Druck eines abgeholten Auftrags dauern
ONLINE_S = 15         # Brücke gilt als erreichbar, wenn sie sich so kürzlich gemeldet hat
AUFHEBEN_S = 3600     # erledigte Aufträge so lange abfragbar

ZUSTAENDE = ("wartet", "uebernommen", "fertig", "fehler", "verfallen", "unbekannt")


class Warteschlange:
    def __init__(self, uhr=time.monotonic):
        self._uhr = uhr
        self._cv = threading.Condition()
        self._auftraege: dict[str, dict] = {}
        self._status: dict | None = None
        self._gemeldet = 0.0

    # --- Brücke ---------------------------------------------------------------

    def melden(self, status: dict):
        """Statusmeldung der Brücke (Drucker, Band, Name, Version, pausiert)."""
        with self._cv:
            self._status = dict(status)
            self._gemeldet = self._uhr()

    def bruecke(self) -> dict | None:
        """Letzter Status der Brücke mit alter_s und online – None, wenn sie sich nie meldete."""
        with self._cv:
            if self._status is None:
                return None
            alter = self._uhr() - self._gemeldet
            return dict(self._status, alter_s=round(alter), online=alter <= ONLINE_S)

    def abholen(self, warten: float = 0.0) -> dict | None:
        """Ältesten wartenden Auftrag übernehmen; bis `warten` Sekunden auf einen warten."""
        ende = self._uhr() + max(0.0, min(warten, 60.0))
        with self._cv:
            while True:
                if self._status is not None:   # wartende Brücke ist erreichbar
                    self._gemeldet = self._uhr()
                self._aufraeumen()
                offen = [a for a in self._auftraege.values() if a["zustand"] == "wartet"]
                if offen:
                    a = min(offen, key=lambda x: x["angelegt"])
                    a["zustand"], a["uebernommen"] = "uebernommen", self._uhr()
                    return a
                rest = ende - self._uhr()
                if rest <= 0:
                    return None
                self._cv.wait(min(rest, 1.0))

    def ergebnis(self, auftrag_id: str, gedruckt: int, code: str = "", text: str = "") -> bool:
        """Ergebnis der Brücke für einen übernommenen Auftrag. False = unbekannter Auftrag."""
        with self._cv:
            a = self._auftraege.get(auftrag_id)
            if a is None or a["zustand"] not in ("uebernommen", "unbekannt"):
                return False
            a.update(zustand="fehler" if code else "fertig", gedruckt=max(0, int(gedruckt)),
                     code=code, text=text, erledigt=self._uhr())
            self._cv.notify_all()
            return True

    # --- CutStock ---------------------------------------------------------------

    def anlegen(self, seiten: list[bytes], laengen: list[int], band_mm: int, medium: int,
                info: dict) -> dict:
        with self._cv:
            self._aufraeumen()
            a = {"id": secrets.token_hex(8), "angelegt": self._uhr(), "zustand": "wartet",
                 "seiten": seiten, "laengen": laengen, "band_mm": band_mm, "medium": medium,
                 "gedruckt": 0, "code": "", "text": "", **info}
            self._auftraege[a["id"]] = a
            self._cv.notify_all()
            return a

    def auftrag(self, auftrag_id: str) -> dict | None:
        with self._cv:
            self._aufraeumen()
            return self._auftraege.get(auftrag_id)

    def leeren(self):
        """Brücke getrennt: Status vergessen, wartende Aufträge verfallen lassen."""
        with self._cv:
            self._status = None
            for a in self._auftraege.values():
                if a["zustand"] == "wartet":
                    a.update(zustand="verfallen", erledigt=self._uhr())

    def _aufraeumen(self):
        jetzt = self._uhr()
        for k, a in list(self._auftraege.items()):
            if a["zustand"] == "wartet" and jetzt - a["angelegt"] > ABHOLEN_S:
                a.update(zustand="verfallen", erledigt=jetzt)
            elif a["zustand"] == "uebernommen" and jetzt - a["uebernommen"] > ERGEBNIS_S:
                a.update(zustand="unbekannt", erledigt=jetzt)
            if a.get("erledigt") and jetzt - a["erledigt"] > AUFHEBEN_S:
                del self._auftraege[k]
