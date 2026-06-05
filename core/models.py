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


@dataclass
class Lagerstueck:
    id: int | None = None
    material_id: int = 0
    laenge: float = 0.0
    breite: float = 0.0
    stueckzahl: int = 1


@dataclass
class Saegeblatt:
    id: int | None = None
    name: str = ""
    schnittbreite: float = 3.0


@dataclass
class Projekt:
    id: int | None = None
    name: str = ""
    teile: list[Teil] = field(default_factory=list)


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
    # Gewünschte Maserungsrichtung (nur Platte)
    maserung: Maserung = Maserung.EGAL
    status: TeilStatus = TeilStatus.OFFEN


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
