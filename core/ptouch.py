"""Druckersprache der Brother P-touch PT-P710BT (gleiche Familie: PT-E550W, PT-P750W).

Selbst geschrieben nach Brothers „Raster Command Reference PT-E550W/P750W/P710BT“ (v1.02).
Rein: baut Druckaufträge aus Bildern und deutet die 32-Byte-Statusantwort – ohne Ein-/Ausgabe,
die macht core.drucker.

Begriffe: Der Druckkopf hat 128 Punkte quer zum Band (180 dpi). Eine Rasterzeile ist ein
Querschnitt durchs Band (16 Bytes), das Etikett wird Zeile für Zeile in Laufrichtung geschickt.
Ein Bild hat hier die Form (Länge × Höhe) in Druckpunkten, Höhe = Druckbereich des Bands.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KOPF_PUNKTE = 128
DPI = 180
ZEILE_BYTES = KOPF_PUNKTE // 8

# TZe-Band: Breite in mm → (Punkte im Druckbereich, Versatz am Kopf)
BAND = {4: (24, 52), 6: (32, 48), 9: (50, 39), 12: (70, 29), 18: (112, 8), 24: (128, 0)}

RAND_MIN = 14          # 2 mm Rand vorne/hinten (Minimum laut Handbuch)
LAENGE_MIN = 31        # 4,4 mm Etikettenlänge
LAENGE_MAX = 7086      # 1 m
VORLAUF_MM = 24.5      # Leerband vor jedem geschnittenen Stück: Abstand Druckkopf → Messer

MEDIEN = {0x00: "kein_band", 0x01: "laminiert", 0x03: "nicht_laminiert",
          0x11: "schrumpfschlauch", 0x17: "schrumpfschlauch", 0xFF: "inkompatibel"}

# Fehlerbits: (Byte im Status, Maske) → Fehlercode
FEHLER = {(8, 0x01): "kein_band", (8, 0x04): "messer_klemmt", (8, 0x08): "akku_schwach",
          (9, 0x01): "falsches_band", (9, 0x10): "deckel_offen", (9, 0x20): "ueberhitzt"}

STATUS_ART = {0x00: "antwort", 0x01: "fertig", 0x02: "fehler", 0x04: "aus",
              0x05: "meldung", 0x06: "phase"}


@dataclass
class Status:
    gueltig: bool = False
    modell: str = ""
    band_mm: int = 0          # eingelegte Bandbreite (3,5 mm meldet der Drucker als 4)
    medium: str = ""          # laminiert, nicht_laminiert, kein_band …
    art: str = ""             # antwort, fertig, fehler, phase …
    druckt: bool = False      # Phase „Drucken“
    fehler: list[str] = field(default_factory=list)
    bandfarbe: int = 0
    schriftfarbe: int = 0


def status_deuten(daten: bytes) -> Status:
    """32-Byte-Statusantwort des Druckers auswerten."""
    if len(daten) < 32 or daten[0] != 0x80 or daten[1] != 0x20:
        return Status()
    return Status(
        gueltig=True, modell=chr(daten[4]), band_mm=daten[10],
        medium=MEDIEN.get(daten[11], "inkompatibel"),
        art=STATUS_ART.get(daten[18], f"0x{daten[18]:02x}"),
        druckt=daten[19] == 0x01,
        fehler=[code for (i, maske), code in FEHLER.items() if daten[i] & maske],
        bandfarbe=daten[24], schriftfarbe=daten[25])


STATUS_ANFRAGE = b"\x00" * 100 + b"\x1b\x40" + b"\x1b\x69\x53"


def rasterzeilen(bild, band_mm: int) -> list[bytes]:
    """Bild (PIL, Modus "1", Länge × Druckbereich-Höhe; 1/weiß = drucken) → Rasterzeilen.

    Bildzeile oben liegt am höchsten Pin des Druckbereichs; Byte 0 der Zeile enthält die
    höchsten Pins, je Byte gehört das niederwertigste Bit zum niedrigeren Pin
    (am PT-P710BT so geprüft: Etikett richtig herum, nicht gespiegelt).
    """
    druck, versatz = BAND[band_mm]
    laenge, hoehe = bild.size
    if hoehe != druck:
        raise ValueError(f"Bildhöhe {hoehe} passt nicht zu {band_mm}-mm-Band ({druck} Punkte)")
    px = bild.load()
    zeilen = []
    for x in range(laenge):
        zeile = bytearray(ZEILE_BYTES)
        for y in range(hoehe):
            if px[x, y]:
                pin = versatz + (hoehe - 1 - y)
                zeile[ZEILE_BYTES - 1 - pin // 8] |= 1 << (pin % 8)
        zeilen.append(bytes(zeile))
    return zeilen


def packbits(daten: bytes) -> bytes:
    """TIFF-PackBits: Wiederholungen als (−(n−1), Byte), sonst (n−1, Bytes …)."""
    aus = bytearray()
    i, n = 0, len(daten)
    while i < n:
        lauf = 1
        while i + lauf < n and daten[i + lauf] == daten[i] and lauf < 128:
            lauf += 1
        if lauf > 1:
            aus += bytes([(257 - lauf) & 0xFF, daten[i]])
            i += lauf
            continue
        start = i
        while i < n and i - start < 128:
            if i + 1 < n and daten[i + 1] == daten[i]:
                break
            i += 1
        aus += bytes([i - start - 1]) + daten[start:i]
    return bytes(aus)


def bandlaenge_mm(laengen: list[int], rand: int = RAND_MIN) -> float:
    """Ungefährer Bandverbrauch: je geschnittenem Stück (Seite) der Vorlauf zwischen Kopf
    und Messer plus Länge und Ränder. Deshalb spart ein Streifen mit mehreren Etiketten
    je Etikett gut 2 cm. laengen in Druckpunkten."""
    rand_mm = 2 * max(RAND_MIN, rand) / DPI * 25.4
    return sum(VORLAUF_MM + n / DPI * 25.4 + rand_mm for n in laengen)


def auftrag(bilder: list, band_mm: int, **kw) -> bytes:
    """Der ganze Auftrag am Stück (für Tests und Dateien). Zum Drucker die Seiten einzeln
    schicken (seiten()) – der Puffer des Geräts fasst nicht beliebig viele Etiketten."""
    return b"".join(seiten(bilder, band_mm, **kw))


def seiten(bilder: list, band_mm: int, schneiden: bool = True, kette: bool = False,
           kompression: bool = True, rand: int = RAND_MIN,
           medium: int = 0x01) -> list[bytes]:
    """Druckdaten je Etikett (je ein Bild). Die erste Seite beginnt mit Zurücksetzen und
    Initialisieren; jede endet mit „Drucken“ bzw. die letzte mit „Drucken mit Vorschub“.
    Laut Handbuch nach jeder Seite auf „Druck fertig“ warten, bevor die nächste kommt.

    schneiden: Messer nach jedem Etikett. kette: nach dem letzten Etikett nicht vorschieben
    (spart beim nächsten Auftrag Band, das letzte Etikett bleibt bis dahin im Gerät).
    """
    if band_mm not in BAND:
        raise ValueError(f"{band_mm}-mm-Band wird nicht unterstützt")
    if not bilder:
        raise ValueError("Keine Etiketten")
    rand = max(RAND_MIN, min(int(rand), 900))
    teile = []
    for nr, bild in enumerate(bilder):
        job = bytearray(b"\x00" * 100 + b"\x1b\x40" if nr == 0 else b"")
        zeilen = rasterzeilen(bild, band_mm)
        if not LAENGE_MIN <= len(zeilen) <= LAENGE_MAX:
            raise ValueError(f"Etikett {nr + 1}: Länge {len(zeilen)} Punkte außerhalb "
                             f"{LAENGE_MIN}–{LAENGE_MAX}")
        job += b"\x1b\x69\x61\x01"                                   # Rastermodus
        # Druckinfo: gültig = Bandart, -breite, Wiederherstellung; Länge 0 (Endlosband)
        job += bytes([0x1B, 0x69, 0x7A, 0x86, medium, band_mm, 0x00])
        job += len(zeilen).to_bytes(4, "little") + bytes([0 if nr == 0 else 1, 0x00])
        job += bytes([0x1B, 0x69, 0x4D, 0x40 if schneiden else 0x00])  # Messer
        job += bytes([0x1B, 0x69, 0x4B, 0x00 if kette else 0x08])     # Kettendruck
        job += b"\x1b\x69\x64" + rand.to_bytes(2, "little")           # Rand vorne/hinten
        job += bytes([0x4D, 0x02 if kompression else 0x00])
        for z in zeilen:
            if not kompression:
                job += b"\x47" + ZEILE_BYTES.to_bytes(2, "little") + z
            elif not any(z):
                job += b"\x5a"                                       # Leerzeile
            else:
                p = packbits(z)
                if len(p) > ZEILE_BYTES:   # lohnt nicht: als 16 verschiedene Bytes schicken
                    p = bytes([ZEILE_BYTES - 1]) + z
                job += b"\x47" + len(p).to_bytes(2, "little") + p
        job += b"\x1a" if nr == len(bilder) - 1 else b"\x0c"
        teile.append(bytes(job))
    return teile
