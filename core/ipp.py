"""Kleiner IPP-Client (Internet Printing Protocol) für Netzwerkdrucker – nur Standardbibliothek.

Selbst geschrieben nach RFC 8010 (Kodierung) und RFC 8011 (Operationen). Kann genau das, was
CutStock braucht: Druckerzustand lesen (Get-Printer-Attributes), Auftrag prüfen ohne zu drucken
(Validate-Job), Auftrag schicken (Print-Job) und dessen Stand abfragen (Get-Job-Attributes).
"""

from __future__ import annotations

import struct
import urllib.error
import urllib.request

# Operationen
PRINT_JOB, VALIDATE_JOB, GET_JOB_ATTRIBUTES, GET_PRINTER_ATTRIBUTES = 0x0002, 0x0004, 0x0009, 0x000B

# Gruppen- und Werte-Tags
OPERATION, JOB, END, PRINTER, UNSUPPORTED = 0x01, 0x02, 0x03, 0x04, 0x05
INTEGER, BOOLEAN, ENUM = 0x21, 0x22, 0x23
TEXT, NAME, KEYWORD, URI, CHARSET, LANGUAGE, MIME = 0x41, 0x42, 0x44, 0x45, 0x47, 0x48, 0x49

JOB_ZUSTAND = {3: "wartet", 4: "angehalten", 5: "druckt", 6: "gestoppt", 7: "abgebrochen",
               8: "abgebrochen", 9: "fertig"}


class IppFehler(Exception):
    def __init__(self, code: str, text: str = ""):
        super().__init__(text or code)
        self.code, self.text = code, text or code


def _attr(tag: int, name: str, werte) -> bytes:
    if not isinstance(werte, (list, tuple)):
        werte = [werte]
    aus = bytearray()
    for i, w in enumerate(werte):
        n = name.encode() if i == 0 else b""          # weitere Werte: Name leer (1setOf)
        if tag in (INTEGER, ENUM):
            v = struct.pack(">i", int(w))
        elif tag == BOOLEAN:
            v = b"\x01" if w else b"\x00"
        else:
            v = str(w).encode("utf-8")
        aus += bytes([tag]) + struct.pack(">H", len(n)) + n + struct.pack(">H", len(v)) + v
    return bytes(aus)


def anfrage(operation: int, drucker_uri: str, request_id: int = 1, attribute: bytes = b"",
            job_attribute: bytes = b"") -> bytes:
    """IPP-Anfrage (Version 2.0) mit den Pflicht-Attributen und weiteren Operations-Attributen."""
    kopf = struct.pack(">BBHI", 2, 0, operation, request_id)
    op = (bytes([OPERATION]) + _attr(CHARSET, "attributes-charset", "utf-8")
          + _attr(LANGUAGE, "attributes-natural-language", "en")
          + _attr(URI, "printer-uri", drucker_uri)
          + _attr(NAME, "requesting-user-name", "CutStock") + attribute)
    if job_attribute:
        op += bytes([JOB]) + job_attribute
    return kopf + op + bytes([END])


def antwort_lesen(daten: bytes) -> tuple[int, dict]:
    """IPP-Antwort → (Statuscode, {Name: [Werte]}) über alle Gruppen. Sammlungen
    (media-col …) werden übersprungen – CutStock fragt nur einfache Attribute ab."""
    if len(daten) < 8:
        raise IppFehler("ipp_antwort", "IPP response too short")
    status = struct.unpack(">H", daten[2:4])[0]
    i, attr, name, tiefe = 8, {}, "", 0
    while i < len(daten):
        tag = daten[i]
        i += 1
        if tag == END:
            break
        if tag < 0x10:                                  # neue Gruppe
            continue
        nlen = struct.unpack(">H", daten[i:i + 2])[0]
        n = daten[i + 2:i + 2 + nlen].decode("utf-8", "replace")
        i += 2 + nlen
        vlen = struct.unpack(">H", daten[i:i + 2])[0]
        v = daten[i + 2:i + 2 + vlen]
        i += 2 + vlen
        if tag == 0x34:                                 # Sammlung beginnt
            tiefe += 1
            if n:
                name = n
            continue
        if tag == 0x37:                                 # Sammlung endet
            tiefe = max(0, tiefe - 1)
            continue
        if tiefe:                                       # Inhalt einer Sammlung
            continue
        if n:
            name = n
        if tag in (INTEGER, ENUM) and vlen == 4:
            wert = struct.unpack(">i", v)[0]
        elif tag == BOOLEAN:
            wert = v != b"\x00"
        elif 0x40 <= tag <= 0x4F:
            wert = v.decode("utf-8", "replace")
        else:
            wert = v
        attr.setdefault(name, []).append(wert)
    return status, attr


class Drucker:
    """Ein IPP-Drucker unter `adresse` (Hostname oder IP, optional mit :Port)."""

    def __init__(self, adresse: str, pfad: str = "/ipp/print", timeout: float = 8.0):
        adresse = adresse.strip().removeprefix("ipp://").removeprefix("http://").rstrip("/")
        host = adresse.split("/")[0]
        if ":" not in host:
            host += ":631"
        self.http = f"http://{host}{pfad}"
        self.uri = f"ipp://{host}{pfad}"
        self.timeout = timeout
        self._id = 0

    def _senden(self, operation: int, attribute: bytes = b"", daten: bytes = b"",
                job_attribute: bytes = b"") -> dict:
        self._id += 1
        koerper = anfrage(operation, self.uri, self._id, attribute, job_attribute) + daten
        req = urllib.request.Request(self.http, data=koerper, method="POST",
                                     headers={"Content-Type": "application/ipp"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, attr = antwort_lesen(r.read())
        except urllib.error.HTTPError as e:
            raise IppFehler("drucker_fehler", f"HTTP {e.code}") from e
        except (OSError, ValueError) as e:
            raise IppFehler("drucker_nicht_erreichbar", str(e)) from e
        if status >= 0x0400:
            text = (attr.get("status-message") or [f"IPP status 0x{status:04x}"])[0]
            raise IppFehler("ipp_abgelehnt" if status < 0x0500 else "drucker_fehler", text)
        return attr

    def attribute(self, namen: list[str]) -> dict:
        return self._senden(GET_PRINTER_ATTRIBUTES,
                            _attr(KEYWORD, "requested-attributes", namen))

    def pruefen(self, format_: str = "application/octet-stream") -> None:
        """Validate-Job: nimmt der Drucker dieses Format an? Druckt nichts."""
        self._senden(VALIDATE_JOB, _attr(MIME, "document-format", format_))

    def drucken(self, daten: bytes, name: str = "CutStock",
                format_: str = "application/octet-stream") -> int:
        """Print-Job: schickt die Druckdaten, liefert die Auftragsnummer."""
        attr = self._senden(PRINT_JOB, _attr(NAME, "job-name", name)
                            + _attr(MIME, "document-format", format_), daten)
        try:
            return int(attr["job-id"][0])
        except (KeyError, IndexError, ValueError) as e:
            raise IppFehler("drucker_fehler", "No job-id in response") from e

    def auftrag(self, job_id: int) -> tuple[str, list[str]]:
        """Stand eines Auftrags: (wartet|druckt|fertig|abgebrochen|…, job-state-reasons)."""
        attr = self._senden(GET_JOB_ATTRIBUTES, _attr(INTEGER, "job-id", job_id)
                            + _attr(KEYWORD, "requested-attributes",
                                    ["job-state", "job-state-reasons"]))
        zustand = JOB_ZUSTAND.get(int((attr.get("job-state") or [0])[0]), "unbekannt")
        return zustand, [str(x) for x in attr.get("job-state-reasons", [])]
