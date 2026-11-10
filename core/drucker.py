"""Verbindung zu Etikettendruckern, die CutStock selbst ansteuert: Brother P-touch per USB.

libusb wird per ctypes geladen (keine Python-Abhängigkeit). Die Desktop-App bringt die
Bibliothek mit; fehlt sie oder ist kein Drucker angeschlossen, meldet status() das, und die
Oberfläche bietet nur das PDF an. Ein Auftrag auf einmal (Sperre), der Drucker wird nur
für die Dauer eines Auftrags geöffnet – danach kann z. B. der P-touch Editor ihn wieder nutzen.
"""

from __future__ import annotations

import ctypes as C
import ctypes.util
import sys
import threading
import time
from pathlib import Path

from core import ptouch

# Unterstützte Geräte: (Hersteller-ID, Produkt-ID) → Modell
GERAETE = {(0x04F9, 0x20AF): "PT-P710BT"}

_sperre = threading.Lock()
_lib = None
_lib_geladen = False


class DruckerFehler(Exception):
    """Fehler mit festem Code für Oberfläche/API (drucker_fehlt, kein_band, …)."""

    def __init__(self, code: str, text: str = "", **extra):
        super().__init__(code)
        self.code, self.text, self.extra = code, text or code, extra


class _Endpunkt(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("bEndpointAddress", C.c_uint8), ("bmAttributes", C.c_uint8),
                ("wMaxPacketSize", C.c_uint16), ("bInterval", C.c_uint8),
                ("bRefresh", C.c_uint8), ("bSynchAddress", C.c_uint8),
                ("extra", C.c_void_p), ("extra_length", C.c_int)]


class _AltSetting(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("bInterfaceNumber", C.c_uint8), ("bAlternateSetting", C.c_uint8),
                ("bNumEndpoints", C.c_uint8), ("bInterfaceClass", C.c_uint8),
                ("bInterfaceSubClass", C.c_uint8), ("bInterfaceProtocol", C.c_uint8),
                ("iInterface", C.c_uint8), ("endpoint", C.POINTER(_Endpunkt)),
                ("extra", C.c_void_p), ("extra_length", C.c_int)]


class _Schnittstelle(C.Structure):
    _fields_ = [("altsetting", C.POINTER(_AltSetting)), ("num_altsetting", C.c_int)]


class _Konfiguration(C.Structure):
    _fields_ = [("bLength", C.c_uint8), ("bDescriptorType", C.c_uint8),
                ("wTotalLength", C.c_uint16), ("bNumInterfaces", C.c_uint8),
                ("bConfigurationValue", C.c_uint8), ("iConfiguration", C.c_uint8),
                ("bmAttributes", C.c_uint8), ("MaxPower", C.c_uint8),
                ("interface", C.POINTER(_Schnittstelle)), ("extra", C.c_void_p),
                ("extra_length", C.c_int)]


def _libusb_pfade() -> list[str]:
    pfade = []
    if getattr(sys, "_MEIPASS", None):
        pfade.append(str(Path(sys._MEIPASS) / "libusb-1.0.0.dylib"))
    pfade += ["/opt/homebrew/lib/libusb-1.0.0.dylib", "/usr/local/lib/libusb-1.0.0.dylib",
              "libusb-1.0.so.0"]
    gefunden = ctypes.util.find_library("usb-1.0")
    if gefunden:
        pfade.append(gefunden)
    return pfade


def _libusb():
    """libusb laden (einmal), None wenn nicht vorhanden."""
    global _lib, _lib_geladen
    if _lib_geladen:
        return _lib
    _lib_geladen = True
    for pfad in _libusb_pfade():
        try:
            lib = C.CDLL(pfad)
        except OSError:
            continue
        lib.libusb_init.argtypes = [C.c_void_p]
        lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        lib.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p, C.c_uint16, C.c_uint16]
        lib.libusb_get_device.restype = C.c_void_p
        lib.libusb_get_device.argtypes = [C.c_void_p]
        lib.libusb_get_active_config_descriptor.argtypes = [
            C.c_void_p, C.POINTER(C.POINTER(_Konfiguration))]
        lib.libusb_free_config_descriptor.argtypes = [C.POINTER(_Konfiguration)]
        lib.libusb_claim_interface.argtypes = [C.c_void_p, C.c_int]
        lib.libusb_release_interface.argtypes = [C.c_void_p, C.c_int]
        lib.libusb_bulk_transfer.argtypes = [C.c_void_p, C.c_ubyte, C.POINTER(C.c_ubyte),
                                             C.c_int, C.POINTER(C.c_int), C.c_uint]
        lib.libusb_close.argtypes = [C.c_void_p]
        lib.libusb_error_name.restype = C.c_char_p
        if lib.libusb_init(None) == 0:
            _lib = lib
            break
    return _lib


class _Usb:
    """Ein geöffneter Drucker für die Dauer eines Auftrags."""

    def __init__(self, lib, handle, modell: str):
        self.lib, self.h, self.modell = lib, handle, modell
        cfg = C.POINTER(_Konfiguration)()
        if lib.libusb_get_active_config_descriptor(lib.libusb_get_device(handle), C.byref(cfg)):
            lib.libusb_close(handle)
            raise DruckerFehler("drucker_fehler", "USB configuration unreadable")
        try:
            alt = cfg.contents.interface[0].altsetting[0]
            self.schnittstelle = alt.bInterfaceNumber
            self.aus = self.ein = None
            for i in range(alt.bNumEndpoints):
                ep = alt.endpoint[i]
                if ep.bmAttributes & 3 == 2:   # Bulk
                    if ep.bEndpointAddress & 0x80:
                        self.ein = ep.bEndpointAddress
                    else:
                        self.aus = ep.bEndpointAddress
        finally:
            lib.libusb_free_config_descriptor(cfg)
        if self.aus is None or self.ein is None:
            lib.libusb_close(handle)
            raise DruckerFehler("drucker_fehler", "No bulk endpoints")
        if lib.libusb_claim_interface(handle, self.schnittstelle) != 0:
            lib.libusb_close(handle)
            raise DruckerFehler("drucker_belegt", "Printer is in use by another program")

    def schreiben(self, daten: bytes, timeout_ms: int = 20000):
        for i in range(0, len(daten), 4096):
            stueck = daten[i:i + 4096]
            puffer = (C.c_ubyte * len(stueck)).from_buffer_copy(stueck)
            n = C.c_int()
            r = self.lib.libusb_bulk_transfer(self.h, self.aus, puffer, len(stueck),
                                              C.byref(n), timeout_ms)
            if r != 0:
                raise DruckerFehler("drucker_fehler",
                                    f"USB write: {self.lib.libusb_error_name(r).decode()}")

    def lesen(self, timeout_ms: int = 500) -> bytes:
        puffer = (C.c_ubyte * 64)()
        n = C.c_int()
        self.lib.libusb_bulk_transfer(self.h, self.ein, puffer, 64, C.byref(n), timeout_ms)
        return bytes(puffer[:n.value])

    def status(self) -> ptouch.Status:
        self.schreiben(ptouch.STATUS_ANFRAGE)
        ende = time.monotonic() + 2.0
        while time.monotonic() < ende:
            st = ptouch.status_deuten(self.lesen())
            if st.gueltig:
                return st
        raise DruckerFehler("drucker_antwortet_nicht", "No status from printer")

    def schliessen(self):
        self.lib.libusb_release_interface(self.h, self.schnittstelle)
        self.lib.libusb_close(self.h)


def _oeffnen() -> _Usb:
    lib = _libusb()
    if lib is None:
        raise DruckerFehler("usb_fehlt", "libusb not available")
    for (vid, pid), modell in GERAETE.items():
        h = lib.libusb_open_device_with_vid_pid(None, vid, pid)
        if h:
            return _Usb(lib, h, modell)
    raise DruckerFehler("drucker_fehlt", "No supported printer connected")


def verfuegbar() -> bool:
    """libusb vorhanden (sonst gar nicht erst nach Druckern suchen)."""
    return _libusb() is not None


def status() -> dict:
    """Drucker suchen und Status lesen: {gefunden, modell, band_mm, medium, fehler, code}."""
    with _sperre:
        try:
            usb = _oeffnen()
        except DruckerFehler as e:
            return {"gefunden": False, "code": e.code}
        try:
            st = usb.status()
        except DruckerFehler as e:
            return {"gefunden": True, "modell": usb.modell, "code": e.code}
        finally:
            usb.schliessen()
    return {"gefunden": True, "modell": usb.modell, "band_mm": st.band_mm,
            "medium": st.medium, "fehler": st.fehler, "code": st.fehler[0] if st.fehler else "",
            "bandfarbe": st.bandfarbe, "schriftfarbe": st.schriftfarbe}


def drucken(bilder: list, band_mm: int, schneiden: bool = True, kette: bool = False) -> dict:
    """Etiketten (Bilder für band_mm) drucken. Prüft vorher Band und Fehler, schickt dann
    Etikett für Etikett und wartet jeweils auf „Druck fertig“. Liefert {gedruckt,
    bestaetigt, modell}; Fehler als DruckerFehler (mit gedruckt = bis dahin fertige)."""
    def bauen(medium: int) -> list[bytes]:
        return ptouch.seiten(bilder, band_mm, schneiden=schneiden, kette=kette, medium=medium)
    return _auftrag(bauen, [b.size[0] for b in bilder], band_mm)


def drucken_daten(seiten: list[bytes], laengen: list[int], band_mm: int,
                  medium: int | None = None) -> dict:
    """Fertige Druckdaten je Seite (z. B. vom Server für die Druckbrücke) drucken.
    medium: Bandart, mit der die Daten gebaut wurden – passt sie nicht zum eingelegten Band,
    wird nicht gedruckt. laengen: Seitenlängen in Punkten (für die Wartezeit)."""
    def bauen(eingelegt: int) -> list[bytes]:
        if medium is not None and medium != eingelegt:
            raise DruckerFehler("falsches_band", "Loaded tape type does not match")
        return seiten
    return _auftrag(bauen, laengen, band_mm)


def _auftrag(bauen, laengen: list[int], band_mm: int) -> dict:
    with _sperre:
        usb = _oeffnen()
        try:
            # Ein abgebrochener Auftrag (z. B. Kabel gezogen) hinterlässt den Drucker im
            # Empfangszustand: erst zurücksetzen, alte Meldungen verwerfen
            usb.schreiben(b"\x00" * 100 + b"\x1b\x40")
            while usb.lesen(200):
                pass
            st = usb.status()
            if st.fehler:
                raise DruckerFehler(st.fehler[0], st.fehler[0])
            if st.band_mm != band_mm:
                raise DruckerFehler("falsches_band", "Loaded tape does not match",
                                    eingelegt=st.band_mm, erwartet=band_mm)
            teile = bauen(0x03 if st.medium == "nicht_laminiert" else 0x01)
            fertig = 0
            for laenge, daten in zip(laengen, teile):
                usb.schreiben(daten)
                # Rückmeldung abwarten: ~20 mm/s, dazu Schneiden und Vorschub
                laenge_mm = laenge / ptouch.DPI * 25.4
                ende = time.monotonic() + 15 + laenge_mm / 10
                while True:
                    if time.monotonic() > ende:
                        raise DruckerFehler("drucker_antwortet_nicht", "No 'printed' status",
                                            gedruckt=fertig)
                    roh = usb.lesen(500)
                    antwort = ptouch.status_deuten(roh)
                    if not antwort.gueltig:
                        continue
                    if antwort.art == "fehler" or antwort.fehler:
                        raise DruckerFehler(
                            antwort.fehler[0] if antwort.fehler else "drucker_fehler",
                            "Printer reported an error", gedruckt=fertig, roh=roh.hex())
                    if antwort.art == "fertig":
                        fertig += 1
                        break
        finally:
            usb.schliessen()
    return {"gedruckt": fertig, "bestaetigt": True, "modell": usb.modell}
