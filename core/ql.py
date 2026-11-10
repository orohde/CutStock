"""Druckersprache der Brother QL-800/810W/820NWB (Etikettendrucker mit DK-Rollen).

Selbst geschrieben nach Brothers „Raster Command Reference QL-800/810W/820NWB“ (v1.01).
Rein: baut Druckaufträge aus Bildern – ohne Ein-/Ausgabe (die macht core.ipp übers Netz).

Begriffe wie in core.ptouch: Der Kopf hat 720 Punkte quer zur Rolle (300 dpi), eine Rasterzeile
ist ein Querschnitt (90 Bytes). Ein Bild hat die Form (Länge × Höhe) in Druckpunkten, Höhe =
Druckbereich der Rolle. Rot/Schwarz-Rollen (DK-22251) bekommen zwei Bilder je Etikett.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.ptouch import packbits

DPI = 300
KOPF_PUNKTE = 720
ZEILE_BYTES = KOPF_PUNKTE // 8
RAND = 35                 # 3 mm Vorschub vorne/hinten bei Endlosrollen (Minimum laut Handbuch)
LAENGE_MIN = 150          # 12,7 mm
LAENGE_MAX = 11811        # 1 m

# Endlosrollen: Breite mm → (Punkte linker Rand, Druckbereich, rechter Rand)
ENDLOS = {12: (585, 106, 29), 29: (408, 306, 6), 38: (295, 413, 12), 50: (154, 554, 12),
          54: (130, 590, 0), 62: (12, 696, 12)}

# Vorgestanzte Etiketten: (Breite, Länge) mm → (linker Rand, Druckbereich, Rasterzeilen)
GESTANZT = {(17, 54): (555, 165, 566), (17, 87): (555, 165, 956), (23, 23): (442, 236, 202),
            (29, 42): (408, 306, 425), (29, 90): (408, 306, 991), (38, 90): (295, 413, 991),
            (39, 48): (289, 425, 495), (52, 29): (142, 578, 271), (54, 29): (59, 602, 271),
            (60, 86): (24, 672, 954), (62, 29): (12, 696, 271), (62, 60): (12, 696, 645),
            (62, 75): (12, 696, 820), (62, 100): (12, 696, 1109)}


@dataclass(frozen=True)
class Medium:
    """Eingelegte Rolle: Endlos (laenge_mm 0) oder vorgestanzt; zweifarbig = Rot/Schwarz."""
    breite_mm: int
    laenge_mm: int = 0
    zweifarbig: bool = False

    @property
    def endlos(self) -> bool:
        return self.laenge_mm == 0

    @property
    def bekannt(self) -> bool:
        return (self.breite_mm in ENDLOS) if self.endlos else \
            (self.breite_mm, self.laenge_mm) in GESTANZT

    @property
    def rand_links(self) -> int:
        return ENDLOS[self.breite_mm][0] if self.endlos else \
            GESTANZT[(self.breite_mm, self.laenge_mm)][0]

    @property
    def druckpunkte(self) -> int:
        """Punkte quer zur Rolle (= Bildhöhe)."""
        return ENDLOS[self.breite_mm][1] if self.endlos else \
            GESTANZT[(self.breite_mm, self.laenge_mm)][1]

    @property
    def zeilen_fest(self) -> int:
        """Rasterzeilen eines vorgestanzten Etiketts (= Bildlänge), 0 bei Endlosrollen."""
        return 0 if self.endlos else GESTANZT[(self.breite_mm, self.laenge_mm)][2]

    def name(self) -> str:
        art = f"{self.breite_mm} mm endlos" if self.endlos else \
            f"{self.breite_mm} × {self.laenge_mm} mm"
        return art + (" Rot/Schwarz" if self.zweifarbig else "")


def rasterzeilen(bild, medium: Medium) -> list[bytes]:
    """Bild (PIL "1", Länge × Druckbereich; 1 = drucken) → Rasterzeilen à 90 Bytes.

    Byte 0 der Zeile enthält die höchsten Pins (Seite des rechten Rands), je Byte gehört das
    niederwertigste Bit zum niedrigeren Pin; die Bildzeile oben liegt am höchsten Pin des
    Druckbereichs – wie beim P-touch (core.ptouch).
    """
    laenge, hoehe = bild.size
    if hoehe != medium.druckpunkte:
        raise ValueError(f"Bildhöhe {hoehe} passt nicht zu {medium.name()} "
                         f"({medium.druckpunkte} Punkte)")
    links = medium.rand_links
    px = bild.load()
    zeilen = []
    for x in range(laenge):
        zeile = bytearray(ZEILE_BYTES)
        for y in range(hoehe):
            if px[x, y]:
                pin = links + (hoehe - 1 - y)
                zeile[ZEILE_BYTES - 1 - pin // 8] |= 1 << (pin % 8)
        zeilen.append(bytes(zeile))
    return zeilen


def auftrag(bilder: list, medium: Medium, schneiden: bool = True,
            kompression: bool = True) -> bytes:
    """Ganzer Druckauftrag (alle Etiketten). Ein Bild je Etikett; bei Rot/Schwarz ein Paar
    (schwarz, rot) je Etikett. schneiden: Messer nach jedem Etikett, sonst nur am Ende."""
    if not medium.bekannt:
        raise ValueError(f"Rolle {medium.name()} wird nicht unterstützt")
    if not bilder:
        raise ValueError("Keine Etiketten")
    zwei = medium.zweifarbig
    kompression = kompression and not zwei      # Kompression gilt nur für „g“-Zeilen
    job = bytearray(b"\x00" * 400 + b"\x1b\x40")  # Zurücksetzen, Initialisieren
    for nr, bild in enumerate(bilder):
        schwarz, rot = bild if zwei else (bild, None)
        zeilen = rasterzeilen(schwarz, medium)
        rote = rasterzeilen(rot, medium) if zwei else []
        if zwei and len(rote) != len(zeilen):
            raise ValueError(f"Etikett {nr + 1}: rotes und schwarzes Bild verschieden lang")
        if medium.endlos and not LAENGE_MIN <= len(zeilen) <= LAENGE_MAX:
            raise ValueError(f"Etikett {nr + 1}: Länge {len(zeilen)} Punkte außerhalb "
                             f"{LAENGE_MIN}–{LAENGE_MAX}")
        if not medium.endlos and len(zeilen) != medium.zeilen_fest:
            raise ValueError(f"Etikett {nr + 1}: {len(zeilen)} Zeilen, Etikett hat "
                             f"{medium.zeilen_fest}")
        job += b"\x1b\x69\x61\x01"                      # Rastermodus
        job += b"\x1b\x69\x21\x00"                      # automatische Statusmeldung an
        gueltig = 0x02 | 0x04 | 0x80 | (0x08 if not medium.endlos else 0) \
            | (0x40 if not zwei else 0)                  # Qualität vor Tempo (nicht bei 2 Farben)
        job += bytes([0x1B, 0x69, 0x7A, gueltig, 0x0A if medium.endlos else 0x0B,
                      medium.breite_mm, medium.laenge_mm])
        job += len(zeilen).to_bytes(4, "little") + bytes([0 if nr == 0 else 1, 0x00])
        job += bytes([0x1B, 0x69, 0x4D, 0x40 if schneiden else 0x00])   # Messer
        if schneiden:
            job += b"\x1b\x69\x41\x01"                  # nach jedem Etikett
        job += bytes([0x1B, 0x69, 0x4B, 0x08 | (0x01 if zwei else 0x00)])  # Schnitt am Ende
        rand = RAND if medium.endlos else 0
        job += b"\x1b\x69\x64" + rand.to_bytes(2, "little")
        job += bytes([0x4D, 0x02 if kompression else 0x00])
        for i, z in enumerate(zeilen):
            if zwei:
                job += b"\x77\x01" + bytes([ZEILE_BYTES]) + z
                job += b"\x77\x02" + bytes([ZEILE_BYTES]) + rote[i]
            elif not kompression:
                job += b"\x67\x00" + bytes([ZEILE_BYTES]) + z
            elif not any(z):
                job += b"\x5a"                          # Leerzeile
            else:
                p = packbits(z)
                if len(p) > ZEILE_BYTES:                # lohnt nicht: 91 Bytes laut Handbuch
                    p = bytes([ZEILE_BYTES - 1]) + z
                job += b"\x67\x00" + bytes([len(p)]) + p
        job += b"\x1a" if nr == len(bilder) - 1 else b"\x0c"
    return bytes(job)


def bandlaenge_mm(laengen: list[int], medium: Medium) -> float:
    """Ungefährer Verbrauch: Endlos = Länge + 2 × 3 mm je Etikett; vorgestanzt = Etiketten."""
    if not medium.endlos:
        return float(len(laengen) * medium.laenge_mm)
    return sum(n / DPI * 25.4 + 2 * RAND / DPI * 25.4 for n in laengen)
