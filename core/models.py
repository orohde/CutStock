"""Datenklassen für CutStock – vergleichbar mit Java-Records / POJOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MaterialTyp(Enum):
    PLATTE = "Platte"
    STANGE = "Stange"


class Maserung(Enum):
    """Maserungsrichtung – bestimmt ob/wie Teile gedreht werden dürfen.

    Für Material (Platte):
      KEINE  = kein sichtbares Muster (z.B. MDF) – Drehung frei
      LAENGS = Maserung folgt der langen Kante des Lagerstücks
      QUER   = Maserung folgt der kurzen Kante des Lagerstücks

    Für Teile:
      LAENGS = Maserung soll parallel zur Teillänge verlaufen
      QUER   = Maserung soll parallel zur Teilbreite verlaufen
      EGAL   = keine Vorgabe – Drehung erlaubt
    """
    KEINE = "keine"
    LAENGS = "längs"
    QUER = "quer"
    EGAL = "egal"


class TeilStatus(Enum):
    OFFEN = "offen"
    GESAEGT = "gesägt"


@dataclass
class Material:
    id: int | None = None
    name: str = ""
    typ: MaterialTyp = MaterialTyp.PLATTE
    # Platte: Dicke in mm
    dicke: float = 0.0
    # Stange: Querschnitt Breite x Tiefe in mm
    querschnitt_breite: float = 0.0
    querschnitt_tiefe: float = 0.0
    # Nur für Platten: Maserungsrichtung
    maserung: Maserung = Maserung.KEINE
    # Legacy-Feld (wird aus maserung abgeleitet, für Abwärtskompatibilität)
    drehung_erlaubt: bool = True
    # Besäumung: Rand in mm der vor dem Zuschnitt abgeschnitten wird
    besaeumung: float = 0.0
    # Rest-Schwellen (Reste kleiner als diese Werte = Abfall)
    rest_min_laenge: float = 0.0
    rest_min_breite: float = 0.0
    bild: bytes = b""
    # Kürzel für Stück-Codes (z.B. "AP4040" → Stück "AP4040-07"), eindeutig
    kuerzel: str = ""
    # Standard-Lagerort der Stücke bzw. neu entstehender Reste (Freitext)
    lagerort: str = ""
    lagerort_reste: str = ""

    def stueck_code(self, nr: int) -> str:
        return stueck_code(self.kuerzel, nr)


@dataclass
class Lagerstueck:
    id: int | None = None
    material_id: int = 0
    laenge: float = 0.0
    breite: float = 0.0
    stueckzahl: int = 1
    ist_rest: bool = False   # Reststück (für "Reste zuerst aufbrauchen")


@dataclass
class Saegeblatt:
    id: int | None = None
    name: str = ""
    schnittbreite: float = 3.0


@dataclass
class Projekt:
    id: int | None = None
    name: str = ""
    anzahl: int = 1        # Exemplare: das Projekt wird so oft gebaut
    teile: list[Teil] = field(default_factory=list)
    art: str = ""          # "sammel" = Sammelplan mehrerer Projekte (ohne eigene Teile)


@dataclass
class Teil:
    id: int | None = None
    projekt_id: int = 0
    label: str = ""
    typ: MaterialTyp = MaterialTyp.PLATTE
    material_id: int = 0
    laenge: float = 0.0
    breite: float = 0.0
    stueckzahl: int = 1
    gesaegt_anzahl: int = 0
    maserung: Maserung = Maserung.EGAL
    status: TeilStatus = TeilStatus.OFFEN
    # Exemplare des Projekts (nicht in der Teil-Tabelle, kommt vom Projekt).
    # stueckzahl gilt pro Exemplar, gesaegt_anzahl zählt über alle Exemplare.
    exemplare: int = 1
    # Fertig gesägte Teile auf Vorrat ("Regal"), z.B. als Füllteil eines anderen
    # Projekts entstanden. Wird nur über eigene Methoden geändert, nicht per save_teil.
    vorrat: int = 0

    @property
    def gesamt_anzahl(self) -> int:
        return self.stueckzahl * max(1, self.exemplare)

    @property
    def offen_anzahl(self) -> int:
        return max(0, self.gesamt_anzahl - self.gesaegt_anzahl)

    @property
    def ist_komplett(self) -> bool:
        return self.gesaegt_anzahl >= self.gesamt_anzahl


@dataclass
class Einzelstueck:
    id: int | None = None
    lagerstueck_id: int = 0
    nr: int = 1           # eindeutig je Material, frei gewordene Nummern werden wieder vergeben
    notiz: str = ""
    lagerort: str = ""    # leer = Lagerort des Materials


@dataclass
class Defekt:
    id: int | None = None
    einzelstueck_id: int = 0
    position: float = 0.0
    position_y: float = 0.0
    laenge: float = 0.0
    breite: float = 0.0


@dataclass
class PlanStueck:
    """Ein platziertes Teil in einem gespeicherten Schnittplan."""
    id: int | None = None
    brett_id: int = 0
    teil_id: int | None = None
    teil_label: str = ""
    laenge: float = 0.0
    breite: float = 0.0
    x: float = 0.0
    y: float = 0.0
    gedreht: bool = False
    gesaegt: bool = False
    ist_fuellteil: bool = False   # Teil eines anderen Projekts, gesägt geht in dessen Vorrat


@dataclass
class PlanBrett:
    """Eine Platte/Stange in einem gespeicherten Schnittplan inkl. Lagerzustand."""
    id: int | None = None
    schnittplan_id: int = 0
    pos: int = 0
    lagerstueck_id: int = 0
    stueck_nr: int = 0
    lager_laenge: float = 0.0
    lager_breite: float = 0.0
    reste: list = field(default_factory=list)
    defekte: list = field(default_factory=list)       # [{position, position_y, laenge, breite}]
    verschnitt_mm: float = 0.0
    verschnitt_prozent: float = 0.0
    verbraucht: bool = False                         # Lagerstück schon ausgetragen
    rest_ids: list = field(default_factory=list)     # eingebuchte Reste [[lagerstück_id, nr]]
    verbrauchtes_stueck: dict | None = None          # Schnappschuss fürs Zurückbuchen
    stuecke: list[PlanStueck] = field(default_factory=list)


@dataclass
class GespeicherterPlan:
    """Optimierungsergebnis eines Projekts für ein Material (ein Plan je Paar)."""
    id: int | None = None
    projekt_id: int = 0
    material_id: int = 0
    saegeblatt_id: int | None = None
    kerf: float = 0.0
    algorithmus: str = ""
    eingabe_hash: str = ""
    fehlende_teile: list = field(default_factory=list)
    materialbedarf: list = field(default_factory=list)
    erstellt: float = 0.0
    geaendert: float = 0.0
    version: int = 1
    bretter: list[PlanBrett] = field(default_factory=list)
    # Füllteile aus anderen Projekten: [{"teil_id", "modus": "auffuellen"|"fest", "menge"}]
    fuellteile: list = field(default_factory=list)
    fuell_alle_reste: bool = False   # auch verwertbare Reste auffüllen (sonst nur Abfall)


def stueck_code(kuerzel: str, nr: int) -> str:
    """Aufschrift eines Einzelstücks, z.B. "AP4040-07"."""
    if not nr:
        return ""
    return f"{kuerzel}-{nr:02d}" if kuerzel else f"#{nr}"


def kuerzel_vorschlag(name: str, vergeben: set[str]) -> str:
    """Kürzel aus dem Materialnamen ableiten, z.B. "Alu Profil 40x80 Nut 8" → "AP4080".

    Abkürzungen in Großbuchstaben bleiben ganz ("MDF 19 mm" → "MDF19"),
    sonst je Wort der Anfangsbuchstabe. Dazu die Maße (erstes "AxB" bzw. erste Zahl).
    Bei Kollision wird ein Buchstabe angehängt (B, C, ...).
    """
    import re
    fuellwoerter = {"mm", "cm", "m", "x", "nut", "mit", "und", "für", "fuer", "der", "die", "das"}
    worte = [w for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", name) if w.lower() not in fuellwoerter]
    buchst = "".join(w if (w.isupper() and len(w) <= 4) else w[0] for w in worte)
    buchst = (buchst.upper()
              .replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE").replace("ß", "SS"))[:4]
    mass = re.search(r"(\d+)\s*[x×]\s*(\d+)", name)
    zahl = mass.group(1) + mass.group(2) if mass else (re.findall(r"\d+", name) or [""])[0]
    basis = ((buchst or "M") + zahl)[:10]
    kandidat, i = basis, 1
    while kandidat in vergeben:
        kandidat = basis + chr(ord("A") + i)
        i += 1
    return kandidat


def drehung_fuer_teil(mat_maserung: Maserung, teil_maserung: Maserung
                      ) -> tuple[bool, bool]:
    """Berechnet welche Orientierungen für ein Teil erlaubt sind.

    Returns:
        (normal_erlaubt, gedreht_erlaubt)
        normal = Teillänge ∥ Plattenlänge
        gedreht = Teillänge ∥ Plattenbreite (90° Drehung)
    """
    if mat_maserung == Maserung.KEINE or teil_maserung == Maserung.EGAL:
        return True, True

    # Material hat Maserung, Teil hat Vorgabe
    if mat_maserung == Maserung.LAENGS:
        # Maserung ∥ Plattenlänge
        # Normal: Teillänge ∥ Plattenlänge → Maserung ∥ Teillänge
        # Gedreht: Teillänge ∥ Plattenbreite → Maserung ∥ Teilbreite
        if teil_maserung == Maserung.LAENGS:
            return True, False
        else:  # QUER
            return False, True
    else:  # mat QUER
        # Maserung ∥ Plattenbreite
        # Normal: Teillänge ∥ Plattenlänge → Maserung ∥ Teilbreite
        # Gedreht: Teillänge ∥ Plattenbreite → Maserung ∥ Teillänge
        if teil_maserung == Maserung.LAENGS:
            return False, True
        else:  # QUER
            return True, False
