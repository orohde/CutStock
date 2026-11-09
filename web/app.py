"""FastAPI backend for CutStock – wraps core/ as a REST API."""

from __future__ import annotations

import os
import signal
import sys
import tempfile
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.db import Database, LagerortInBenutzung, seed_data
from core.models import (
    Defekt,
    Einzelstueck,
    GespeicherterPlan,
    Lagerstueck,
    Maserung,
    Material,
    MaterialTyp,
    PlanBrett,
    PlanStueck,
    Projekt,
    Saegeblatt,
    Teil,
    TeilStatus,
    drehung_fuer_teil,
    stueck_code,
)
from core.optimize import (
    OptimierungsErgebnis,
    PlattenVorrat,
    Schnittplan,
    StangenVorrat,
    optimize_1d,
    optimize_1d_ga,
    optimize_2d,
    optimize_2d_ga,
    optimize_2d_nested,
    fuell_vorschlaege_1d,
    fuelle_rest_1d,
    fuelle_reste_2d,
    freie_rechtecke_2d,
)
from core.pdf import export_pdf
from core import units
from core.units import UNITS, normalize_unit
from ui.i18n import LANGUAGES, TRANSLATIONS

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = Path(os.environ.get("CUTSTOCK_DB", "/data/cutstock.db"))


def _read_version() -> str:
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            vf = Path(sys._MEIPASS) / "VERSION"
        else:
            vf = PROJECT_ROOT / "VERSION"
        return vf.read_text().strip()
    except Exception:
        return "0.0.0"


# Vor der DB eingelesen: die DB wird bei jedem Versionswechsel vorher gesichert
APP_VERSION = _read_version()

import threading
from contextvars import ContextVar

_db_local = threading.local()
# Wird bei einem Restore hochgezählt, damit alle Threads ihre veralteten
# SQLite-Verbindungen schließen und die neue Datei öffnen.
_db_generation = 0

SETTINGS_PATH = DB_PATH.parent / "settings.json"


def _lager_einstellungen() -> dict:
    """Lager-Einstellungen aus settings.json, gecacht bis sich die Datei ändert."""
    global _lager_cache
    try:
        mtime = SETTINGS_PATH.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _lager_cache[0] != mtime:
        from core.settings import Settings
        s = Settings(SETTINGS_PATH)
        _lager_cache = (mtime, {
            "nr_sperrfrist_tage": float(s.value("stock/nr_lock_days", 1) or 0),
            "reservierung": bool(s.value("stock/reservation", True)),
            "abfall_aufheben": bool(s.value("stock/waste_keep", False)),
            "abfall_untergrenze": float(s.value("stock/waste_min", 50) or 0),
            "sprache": s.value("appearance/language", "en") or "en",
        })
    return _lager_cache[1]


_lager_cache: tuple[float, dict] = (-1.0, {})


# Woher die laufende Anfrage kommt ("ui" = eigene Oberfläche, "api" = andere
# Programme), wird von der API-Key-Middleware gesetzt und landet im Lagerjournal.
_quelle: ContextVar[str] = ContextVar("cutstock_quelle", default="api")


def get_db() -> Database:
    """Thread-local Database instance — SQLite connections can't cross threads."""
    db = getattr(_db_local, "db", None)
    if db is not None and getattr(_db_local, "gen", None) == _db_generation:
        db.nr_sperrfrist_tage = _lager_einstellungen()["nr_sperrfrist_tage"]
        db.quelle = _quelle.get()
        return db
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db_local.db = Database(DB_PATH, app_version=APP_VERSION,
                            lagerort_standard=_standard_lagerort_name())
    _db_local.gen = _db_generation
    _db_local.db.nr_sperrfrist_tage = _lager_einstellungen()["nr_sperrfrist_tage"]
    _db_local.db.quelle = _quelle.get()
    return _db_local.db


def _standard_lagerort_name() -> str:
    """Name des automatisch angelegten Lagerorts in der eingestellten Sprache."""
    from ui.i18n import TRANSLATIONS as _T
    sprache = _lager_einstellungen()["sprache"]
    namen = _T.get("loc.default", {})
    return namen.get(sprache) or namen.get("en") or "Stock"


# Eagerly create tables / seed on import (main thread)
_init_db = get_db()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="CutStock API", version="1.0.0")

IS_DESKTOP = os.environ.get("CUTSTOCK_DESKTOP") == "1"
IS_DOCKER = os.environ.get("CUTSTOCK_DOCKER") == "1" or Path("/.dockerenv").exists()


# ---------------------------------------------------------------------------
# CORS – erlaubt externen Programmen den Zugriff auf die API
# ---------------------------------------------------------------------------

from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API-Key-Middleware – schützt /api/* wenn ein Key konfiguriert ist.
# Ohne Key bleibt die API offen. Mit Key passieren:
#   - Clients mit "Authorization: Bearer <Key>",
#   - die eigene Weboberfläche: Sie bekommt beim Laden der Seite ein
#     HttpOnly-Cookie (HMAC des Keys), das nur bei Same-Origin-Requests zählt,
#   - direkte Requests vom selben Rechner (127.0.0.1 / ::1), aber nur ohne
#     Proxy-Header – hinter einem Reverse-Proxy auf demselben Host käme sonst
#     jede Anfrage als „lokal“ an.
# ---------------------------------------------------------------------------

import hashlib
import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

UI_COOKIE_MAX_AGE = 30 * 24 * 3600
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")


def _current_api_key() -> str:
    from core.settings import Settings
    return Settings(SETTINGS_PATH).value("api/key", "") or ""


def _ui_token(api_key: str) -> str:
    return hmac.new(api_key.encode(), b"cutstock-ui", hashlib.sha256).hexdigest()


def _ui_cookie_name(request: StarletteRequest) -> str:
    # Cookies trennen nicht nach Port – mehrere Instanzen auf einem Host
    # (Desktop + Dev-Server) sollen sich nicht gegenseitig überschreiben.
    return f"cutstock_ui_{request.url.port or 'default'}"


def _is_same_origin(request: StarletteRequest) -> bool:
    # Browser senden Sec-Fetch-Site immer; "same-site" (andere Subdomain oder
    # anderer Port) reicht nicht.
    return request.headers.get("sec-fetch-site", "same-origin") == "same-origin"


def _is_direct_local(request: StarletteRequest) -> bool:
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        return False
    return not any(h in request.headers for h in _PROXY_HEADERS)


def _has_valid_ui_cookie(request: StarletteRequest, api_key: str) -> bool:
    cookie = request.cookies.get(_ui_cookie_name(request), "")
    return (bool(cookie) and _is_same_origin(request)
            and hmac.compare_digest(cookie, _ui_token(api_key)))


def _has_valid_bearer(request: StarletteRequest, api_key: str) -> bool:
    auth = request.headers.get("authorization", "")
    return hmac.compare_digest(auth.encode(), f"Bearer {api_key}".encode())


def _refresh_ui_cookie(request: StarletteRequest, response) -> None:
    """UI-Cookie setzen, wenn ein Key gesetzt ist und das Cookie fehlt oder veraltet ist."""
    api_key = _current_api_key()
    if not api_key:
        return
    name = _ui_cookie_name(request)
    token = _ui_token(api_key)
    if request.cookies.get(name) == token:
        return
    secure = (request.url.scheme == "https"
              or request.headers.get("x-forwarded-proto", "") == "https")
    response.set_cookie(name, token, max_age=UI_COOKIE_MAX_AGE, path="/",
                        httponly=True, samesite="strict", secure=secure)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if not request.url.path.startswith("/api/"):
            response = await call_next(request)
            _refresh_ui_cookie(request, response)
            return response

        api_key = _current_api_key()
        if api_key and not (_has_valid_bearer(request, api_key)
                            or _has_valid_ui_cookie(request, api_key)
                            or _is_direct_local(request)):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        # Eigene Oberfläche = Browser-Anfrage von derselben Seite ohne Bearer-Key
        von_ui = ("authorization" not in request.headers
                  and request.headers.get("sec-fetch-site") == "same-origin")
        _quelle.set("ui" if von_ui else "api")
        response = await call_next(request)
        # Der Key kann sich durch diesen Request geändert haben (Einstellungen,
        # Backup-Restore) – dann bekommt die Oberfläche sofort das neue Cookie.
        if _is_same_origin(request) and "sec-fetch-site" in request.headers:
            _refresh_ui_cookie(request, response)
        return response


app.add_middleware(ApiKeyMiddleware)

# Im PyInstaller-Bundle liegen die statischen Dateien unter _MEIPASS/web/static.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    STATIC_DIR = Path(sys._MEIPASS) / "web" / "static"
else:
    STATIC_DIR = Path(__file__).resolve().parent / "static"

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class MaterialIn(BaseModel):
    name: str
    typ: str = "Platte"
    dicke: float = 0.0
    querschnitt_breite: float = 0.0
    querschnitt_tiefe: float = 0.0
    maserung: str = "keine"
    besaeumung: float = 0.0
    rest_min_laenge: float = 0.0
    rest_min_breite: float = 0.0
    kuerzel: str = ""          # leer → Vorschlag aus dem Namen
    # Name aus der Lagerort-Liste (unbekannt → wird angelegt). Beim Ändern:
    # None = unverändert lassen; lagerort_reste "" = gleicher Ort wie das Material.
    lagerort: Optional[str] = None
    lagerort_reste: Optional[str] = None
    # Standard-Sägeblatt der Optimierung; None = unverändert, 0 = keins (erstes Sägeblatt)
    saegeblatt_id: Optional[int] = None


class MaterialOut(BaseModel):
    id: int
    name: str
    typ: str
    dicke: float
    querschnitt_breite: float
    querschnitt_tiefe: float
    maserung: str
    drehung_erlaubt: bool
    besaeumung: float
    rest_min_laenge: float
    rest_min_breite: float
    hat_bild: bool = False
    kuerzel: str = ""
    lagerort: str = ""
    lagerort_reste: str = ""
    saegeblatt_id: int = 0


class StockIn(BaseModel):
    material_id: int
    laenge: float
    breite: float = 0.0
    stueckzahl: int = Field(1, ge=0)   # 0 = Maß bleibt gelistet, ist aber leer
    ist_rest: bool = False


class StockOut(BaseModel):
    id: int
    material_id: int
    laenge: float
    breite: float
    stueckzahl: int
    ist_rest: bool = False


class EinzelstueckOut(BaseModel):
    id: int
    lagerstueck_id: int
    nr: int
    notiz: str
    defekt_count: int = 0
    code: str = ""               # Aufschrift, z.B. "AP4040-07"
    lagerort: str = ""           # Lagerort des Materials (Reste: Reste-Ort)
    lagerort_effektiv: str = ""  # wie lagerort (Feld bleibt für ältere Clients)
    reserviert_fuer: str = ""    # Projekt, dessen gespeicherter Plan das Stück reserviert
    material_id: int = 0
    material: str = ""
    laenge: float = 0.0
    breite: float = 0.0
    ist_rest: bool = False
    etikett_gedruckt: float = 0.0  # Zeitpunkt des letzten Etiketts (Unix-Zeit), 0 = nie


class EinzelstueckIn(BaseModel):
    notiz: str = ""


class DefectIn(BaseModel):
    position: float = 0.0
    position_y: float = 0.0
    laenge: float
    breite: float = 0.0


class DefectOut(BaseModel):
    id: int
    einzelstueck_id: int
    stueck_nr: int = 0
    position: float
    position_y: float
    laenge: float
    breite: float


class BladeIn(BaseModel):
    name: str
    schnittbreite: float = 3.0


class BladeOut(BaseModel):
    id: int
    name: str
    schnittbreite: float


class PartIn(BaseModel):
    label: str
    typ: str = "Platte"
    material_id: int
    laenge: float
    breite: float = 0.0
    stueckzahl: int = 1
    gesaegt_anzahl: int = 0
    maserung: str = "egal"
    vorrat: Optional[int] = Field(None, ge=0)   # nur beim Bearbeiten: Regal-Bestand korrigieren


class PartOut(BaseModel):
    id: int
    projekt_id: int
    label: str
    typ: str
    material_id: int
    laenge: float
    breite: float
    stueckzahl: int
    gesaegt_anzahl: int
    maserung: str
    status: str
    offen_anzahl: int
    gesamt_anzahl: int = 0     # stueckzahl × Exemplare des Projekts
    vorrat: int = 0            # fertige Teile im Regal (z.B. als Füllteil entstanden)
    herkunft_teil_id: int = 0  # nur in Schnittlisten: gesägt → Vorrat dieses Teils


class ProjectIn(BaseModel):
    name: str
    anzahl: int = Field(1, ge=1, le=10000)   # Exemplare


class ProjectOut(BaseModel):
    id: int
    name: str
    anzahl: int = 1
    teile: list[PartOut]
    plaene: list[PlanStatusOut] = []
    # Materialien, für die das Projekt in einem Sammelplan steckt: {material_id: Name}
    sammel: dict[int, str] = {}
    art: str = ""   # "" = normales Projekt, "liste" = Schnittliste, "sammel" = Sammelplan
    sammel_material_id: int = 0      # nur Sammelplan: sein Material
    mitglieder: list[int] = []       # nur Sammelplan: IDs der Mitglieds-Projekte
    # nur Sägeauftrag aus einer Vorlage (Durchgang): die Vorlage
    vorlage_id: int = 0
    vorlage_name: str = ""
    # nur Vorlage: Zahl der Durchgänge, letzter Durchgang (Unix-Zeit), laufende Durchgänge
    durchgaenge: int = 0
    zuletzt: float = 0.0
    laufend: list["TemplateRunOut"] = []


class FuellKandidatOut(BaseModel):
    teil_id: int
    label: str
    projekt: str
    projekt_id: int
    laenge: float
    breite: float = 0.0
    offen: int = 0
    vorrat: int = 0


class FuellteilIn(BaseModel):
    teil_id: int
    modus: str = "auffuellen"   # "auffuellen" (passt in die Reste) | "fest" (genau menge)
    menge: int = 0              # fest: Anzahl; auffüllen: Obergrenze (0 = unbegrenzt)


class OptimizeRequest(BaseModel):
    project_id: int
    material_id: int
    blade_id: int
    algorithm: str = "greedy"
    reste_zuerst: bool = False   # erst nur Reste verplanen, dann ganze Stücke
    # Füllteile aus anderen Projekten; None = Auswahl des bisherigen Plans behalten
    fuellteile: Optional[list[FuellteilIn]] = None
    fuell_alle_reste: Optional[bool] = None   # auch verwertbare Reste füllen
    max_pro_stange: Optional[int] = None      # Stangen: max. Teile je Stange, None = behalten


class FuellWahlIn(BaseModel):
    gruppe: str                         # Gruppe gleicher Stangenreste, z.B. "776.0"
    wahl: Optional[list[dict]] = None   # [{teil_id, anzahl}], [] = nichts, None = Automatik


class PlatzierungOut(BaseModel):
    teil_label: str
    laenge: float
    breite: float
    x: float
    y: float
    gedreht: bool
    id: int = 0            # gespeicherter Plan: ID des Plan-Stücks
    gesaegt: bool = False
    ist_fuellteil: bool = False   # Teil eines anderen Projekts → geht in dessen Vorrat


class RestStueckOut(BaseModel):
    code: str
    laenge: float
    breite: float = 0.0
    lagerort: str = ""


class SchnittplanOut(BaseModel):
    lagerstueck_id: int
    lager_laenge: float
    lager_breite: float
    stueck_nr: int = 0
    platzierungen: list[PlatzierungOut]
    reste: list[list[float]]
    verschnitt_mm: float
    verschnitt_prozent: float
    defekte: list[DefectOut] = []
    id: int = 0            # gespeicherter Plan: ID des Bretts
    verbraucht: bool = False
    stueck_code: str = ""  # Aufschrift des Stücks, z.B. "AP4040-07"
    lagerort: str = ""
    ist_rest: bool = False  # Stück ist ein Rest (sonst ganze Stange/Platte)
    reste_stuecke: list[RestStueckOut] = []   # eingebuchte Reste (nach dem Anfangen)
    # Wohin jeder Rest aus `reste` gehört: "lager" | "abfallkiste" | "weg"
    reste_ziel: list[str] = []


class MaterialBedarfOut(BaseModel):
    laenge: float
    breite: float
    anzahl: int


class OptimizeResult(BaseModel):
    schnittplaene: list[SchnittplanOut]
    fehlende_teile: list[str]
    gesamt_verschnitt_prozent: float
    materialbedarf: list[MaterialBedarfOut] = []
    # Fehlende Teile, die größer als jedes Stück im Lager sind
    zu_lang: list[str] = []
    # Gespeicherter Plan (0/leer bei reinen Berechnungsergebnissen, z.B. im PDF)
    plan_id: int = 0
    projekt_id: int = 0
    material_id: int = 0
    saegeblatt_id: Optional[int] = None
    algorithmus: str = ""
    erstellt: float = 0.0
    version: int = 0
    veraltet: bool = False      # Teile/Material/Sägeblatt seit der Berechnung geändert
    veraltet_grund: str = ""    # "teile" (Teile/Material geändert) | "anderswo" (anderswo gesägt)
    lager_fehlt: bool = False   # eingeplante, noch unbenutzte Lagerstücke fehlen
    fehlende_stuecke: list[str] = []   # deren Codes, z.B. ["AP4040-07"]
    fuellteile: list[dict] = []          # Auswahl [{teil_id, modus, menge}]
    fuell_alle_reste: bool = False
    vorrat_verfuegbar: list[dict] = []   # eigene Teile mit Vorrat: [{teil_id, label, anzahl}]
    max_pro_stange: int = 0
    # Stangen: Füllvorschläge je Gruppe gleicher Reste, siehe _reste_auffuellen_1d
    fuell_vorschlaege: list[dict] = []


class PlanStatusOut(BaseModel):
    plan_id: int
    material_id: int
    erstellt: float
    gesamt: int
    gesaegt: int
    angefangen: bool


class PieceSawnIn(BaseModel):
    gesaegt: bool


class PieceSawnOut(BaseModel):
    plan: OptimizeResult
    teil: Optional[PartOut] = None


class CopyPartsRequest(BaseModel):
    part_ids: list[int]


class MarkPlanRequest(BaseModel):
    material_id: int
    lagerstueck_id: int
    is_1d: bool
    lager_laenge: float
    lager_breite: float = 0.0
    kerf: float = 0.0
    marked_laengen: list[float] = []
    # 1D mit Defekten: Startposition je markiertem Stück (parallel zu
    # marked_laengen) und Defekte des Stücks als [position, laenge]
    marked_x: list[float] = []
    defekte: list[list[float]] = []
    total_pieces: int = 0
    reste: list[list[float]] = []
    prev_consumed: bool = False
    prev_rest_ids: list[int] = []
    prev_rest_nrs: list[int] = []   # Stücknummern der Reste (parallel zu prev_rest_ids)
    # Stücknummer des Plans: genau dieses Einzelstück wird verbraucht. Der
    # Schnappschuss (Nummer, Notiz, Defekte) kommt beim Zurücknehmen zurück.
    stueck_nr: int = 0
    prev_consumed_piece: dict | None = None
    prev_abfall: list[list[float]] = []   # vorher in die Abfallkiste gelegt [[l, b]]


class PdfRequest(BaseModel):
    ergebnis: OptimizeResult
    projekt_name: str = ""
    material_name: str = ""
    material_id: int = 0  # für das Materialbild im PDF
    saegeblatt_name: str = ""
    is_1d: bool = False
    # Vorformatierte Schnittfolge je Schnittplan (vom Frontend berechnet,
    # damit PDF und Web-Ansicht garantiert dieselbe Zerlegung zeigen)
    schnittfolgen: list[list[str]] = []
    schnittfolge_titel: str = ""   # leer = in der Sprache der Einstellungen
    # Sammelplan: Farbe je Projekt statt je Teil
    nach_projekt: bool = False


class LabelIn(BaseModel):
    title: str = ""
    line1: str = ""
    line2: str = ""
    id_text: str = ""
    kurz: str = ""      # Kurzname für sehr kleine Etiketten (leer = id_text bzw. title)


class LabelsRequest(BaseModel):
    labels: list[LabelIn]
    filename: str = "Etiketten"
    startfeld: int = 1   # erstes Feld auf dem A4-Bogen (angebrochener Bogen), Rolle: egal


class PieceLabelsIn(BaseModel):
    """Etiketten für Lagerstücke. Auswahl über codes und/oder lagerort/material,
    eingegrenzt durch die nur_*-Filter."""
    codes: list[str] = []            # bestimmte Stücke (Code oder ID)
    lagerort: Optional[str] = None   # alle Stücke an diesem Ort (ID oder Name)
    material: Optional[str] = None   # alle Stücke dieses Materials (ID oder Kürzel)
    nur_reste: bool = False
    nur_ganze: bool = False
    nur_ungedruckt: bool = False     # nur Stücke, für die noch nie ein Etikett gedruckt wurde
    startfeld: int = 1
    markieren: bool = True           # Stücke als gedruckt vermerken
    filename: str = ""


class SettingsIn(BaseModel):
    language: Optional[str] = None
    unit: Optional[str] = None              # mm | cm | in | in_frac
    unit_feet: Optional[bool] = None        # in_frac: ab 12" in Fuß und Zoll
    theme: Optional[str] = None
    hotkeys: Optional[dict[str, str]] = None
    label_format: Optional[str] = None
    label_custom_w: Optional[float] = None
    label_custom_h: Optional[float] = None
    api_enabled: Optional[bool] = None
    api_port: Optional[int] = None
    api_key: Optional[str] = None
    license_key: Optional[str] = None
    nr_lock_days: Optional[float] = None    # Sperrfrist frei gewordener Stücknummern
    reservation: Optional[bool] = None      # gespeicherte Pläne reservieren ihr Lager
    waste_keep: Optional[bool] = None       # Abfallstücke in der Abfallkiste aufheben
    waste_min: Optional[float] = None       # ... erst ab diesem Maß (mm)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _material_to_out(m: Material) -> MaterialOut:
    return MaterialOut(
        id=m.id,
        name=m.name,
        typ=m.typ.value,
        dicke=m.dicke,
        querschnitt_breite=m.querschnitt_breite,
        querschnitt_tiefe=m.querschnitt_tiefe,
        maserung=m.maserung.value,
        drehung_erlaubt=m.drehung_erlaubt,
        besaeumung=m.besaeumung,
        rest_min_laenge=m.rest_min_laenge,
        rest_min_breite=m.rest_min_breite,
        kuerzel=m.kuerzel,
        lagerort=m.lagerort,
        lagerort_reste=m.lagerort_reste,
        saegeblatt_id=m.saegeblatt_id,
        hat_bild=bool(m.bild),
    )


def _material_from_in(data: MaterialIn, mid: int | None = None) -> Material:
    return Material(
        id=mid,
        name=data.name,
        typ=MaterialTyp(data.typ),
        dicke=data.dicke,
        querschnitt_breite=data.querschnitt_breite,
        querschnitt_tiefe=data.querschnitt_tiefe,
        maserung=Maserung(data.maserung),
        besaeumung=data.besaeumung,
        rest_min_laenge=data.rest_min_laenge,
        rest_min_breite=data.rest_min_breite,
        kuerzel=data.kuerzel,
        lagerort=data.lagerort or "",
        lagerort_reste=data.lagerort_reste or "",
        saegeblatt_id=data.saegeblatt_id or 0,
    )


def _stock_to_out(ls: Lagerstueck) -> StockOut:
    return StockOut(
        id=ls.id,
        material_id=ls.material_id,
        laenge=ls.laenge,
        breite=ls.breite,
        stueckzahl=ls.stueckzahl,
        ist_rest=ls.ist_rest,
    )


def _teil_to_out(t: Teil) -> PartOut:
    return PartOut(
        id=t.id,
        projekt_id=t.projekt_id,
        label=t.label,
        typ=t.typ.value,
        material_id=t.material_id,
        laenge=t.laenge,
        breite=t.breite,
        stueckzahl=t.stueckzahl,
        gesaegt_anzahl=t.gesaegt_anzahl,
        maserung=t.maserung.value,
        status=t.status.value,
        offen_anzahl=t.offen_anzahl,
        gesamt_anzahl=t.gesamt_anzahl,
        vorrat=t.vorrat,
        herkunft_teil_id=t.herkunft_teil_id,
    )


class TemplateRunOut(BaseModel):
    """Ein Durchgang einer Vorlage (Verlauf)."""
    id: int
    auftrag_id: int = 0      # 0 = Sägeauftrag gelöscht
    name: str
    saetze: int
    gesaegt: int
    gesamt: int
    angelegt: float          # Unix-Zeit
    fertig: float = 0.0      # Unix-Zeit, 0 = noch nicht fertig


ProjectOut.model_rebuild()


def _lauf_to_out(d: dict) -> TemplateRunOut:
    return TemplateRunOut(id=d["id"], auftrag_id=d["auftrag_id"], name=d["name"],
                          saetze=d["saetze"], gesaegt=d["gesaegt"], gesamt=d["teile_gesamt"],
                          angelegt=d["angelegt"], fertig=d["fertig"])


def _vorlage_felder(p: Projekt) -> dict:
    """Zusatzfelder für Vorlagen und Durchgänge in ProjectOut."""
    db = get_db()
    if not p.id:
        return {}
    if p.art == "vorlage":
        verlauf = db.vorlage_verlauf(p.id)
        return {"durchgaenge": len(verlauf),
                "zuletzt": max((d["angelegt"] for d in verlauf), default=0.0),
                "laufend": [_lauf_to_out(d) for d in verlauf
                            if d["auftrag_id"] and not d["fertig"]]}
    if p.art == "liste":
        herkunft = db.vorlage_von_durchgang(p.id)
        if herkunft:
            return {"vorlage_id": herkunft.id, "vorlage_name": herkunft.name}
    return {}


def _projekt_to_out(p: Projekt) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        anzahl=p.anzahl,
        teile=[_teil_to_out(t) for t in p.teile],
        plaene=[PlanStatusOut(plan_id=r["id"], material_id=r["material_id"],
                              erstellt=r["erstellt"], gesamt=r["gesamt"],
                              gesaegt=r["gesaegt"], angefangen=bool(r["angefangen"]))
                for r in get_db().list_plan_status(p.id)] if p.id else [],
        sammel=get_db().sammel_von_projekt(p.id) if p.id else {},
        art=p.art,
        sammel_material_id=p.sammel_material_id,
        mitglieder=get_db().sammel_mitglieder(p.id) if p.id and p.art == "sammel" else [],
        **_vorlage_felder(p),
    )


def _out_to_ergebnis(data: OptimizeResult) -> OptimierungsErgebnis:
    """Convert API result model back to core dataclass for PDF generation."""
    from core.optimize import Platzierung, Schnittplan

    return OptimierungsErgebnis(
        schnittplaene=[
            Schnittplan(
                lagerstueck_id=sp.lagerstueck_id,
                lager_laenge=sp.lager_laenge,
                lager_breite=sp.lager_breite,
                stueck_nr=sp.stueck_nr,
                stueck_code=sp.stueck_code,
                lagerort=sp.lagerort,
                platzierungen=[
                    Platzierung(
                        teil_label=p.teil_label,
                        laenge=p.laenge,
                        breite=p.breite,
                        x=p.x,
                        y=p.y,
                        gedreht=p.gedreht,
                        ist_fuellteil=p.ist_fuellteil,
                    )
                    for p in sp.platzierungen
                ],
                reste=[tuple(r) for r in sp.reste],
                verschnitt_mm=sp.verschnitt_mm,
                verschnitt_prozent=sp.verschnitt_prozent,
                defekte=[
                    Defekt(position=d.position, position_y=d.position_y,
                           laenge=d.laenge, breite=d.breite)
                    for d in sp.defekte
                ],
            )
            for sp in data.schnittplaene
        ],
        fehlende_teile=data.fehlende_teile,
        gesamt_verschnitt_prozent=data.gesamt_verschnitt_prozent,
    )


# ---------------------------------------------------------------------------
# Material requirements estimation
# ---------------------------------------------------------------------------


def _zu_lange_teile(fehlende_labels, teile, vorrat, material) -> list[str]:
    """Fehlende Teile, die auch auf das größte Stück im Lager nicht passen (je Stück ein Label)."""
    if not fehlende_labels or not vorrat:
        return []
    is_1d = material.typ == MaterialTyp.STANGE
    rand = 2 * material.besaeumung
    teil_map = {t.label: t for t in teile}

    def passt(t) -> bool:
        if is_1d:
            return any(t.laenge <= ls.laenge - rand for ls in vorrat)
        normal_ok, gedreht_ok = drehung_fuer_teil(material.maserung, t.maserung)
        if material.maserung == Maserung.KEINE:
            normal_ok = gedreht_ok = True
        return any((normal_ok and t.laenge <= ls.laenge - rand and t.breite <= ls.breite - rand)
                   or (gedreht_ok and t.breite <= ls.laenge - rand and t.laenge <= ls.breite - rand)
                   for ls in vorrat)

    return [lbl for lbl in fehlende_labels if lbl in teil_map and not passt(teil_map[lbl])]


def _berechne_materialbedarf(fehlende_labels, teile, vorrat, material, kerf):
    """Estimate additional stock needed for parts that couldn't be placed."""
    zu_lang = set(_zu_lange_teile(fehlende_labels, teile, vorrat, material))
    fehlende_labels = [lbl for lbl in fehlende_labels if lbl not in zu_lang]
    if not fehlende_labels:
        return []

    is_1d = material.typ == MaterialTyp.STANGE
    besaeumung = material.besaeumung

    bedarf: dict[str, int] = {}
    for label in fehlende_labels:
        bedarf[label] = bedarf.get(label, 0) + 1

    teil_map = {t.label: t for t in teile}
    if is_1d:
        fehlende = [(lbl, teil_map[lbl].laenge, cnt)
                    for lbl, cnt in bedarf.items() if lbl in teil_map]
    else:
        fehlende = [(lbl, teil_map[lbl].laenge, teil_map[lbl].breite, cnt)
                    for lbl, cnt in bedarf.items() if lbl in teil_map]

    if not fehlende:
        return []

    if vorrat:
        if is_1d:
            ref = max(vorrat, key=lambda ls: ls.laenge)
            ref_l, ref_b = ref.laenge, 0.0
        else:
            ref = max(vorrat, key=lambda ls: ls.laenge * ls.breite)
            ref_l, ref_b = ref.laenge, ref.breite
    else:
        if is_1d:
            max_l = max(teil_map[lbl].laenge for lbl in bedarf if lbl in teil_map)
            ref_l = max(max_l + 2 * besaeumung + 100, 2000)
            ref_b = 0.0
        else:
            max_l = max(teil_map[lbl].laenge for lbl in bedarf if lbl in teil_map)
            max_b = max(teil_map[lbl].breite for lbl in bedarf if lbl in teil_map)
            ref_l = max(max_l + 2 * besaeumung + 100, 2440)
            ref_b = max(max_b + 2 * besaeumung + 100, 1220)

    usable_l = ref_l - 2 * besaeumung
    usable_b = (ref_b - 2 * besaeumung) if not is_1d else 0.0
    if usable_l <= 0 or (not is_1d and usable_b <= 0):
        return []

    if is_1d:
        virt = [StangenVorrat(-1, usable_l, 999)]
        erg = optimize_1d(fehlende, virt, kerf)
    else:
        virt = [PlattenVorrat(-1, usable_l, usable_b, 999)]
        teil_drehung: dict[str, tuple[bool, bool]] = {}
        for lbl in bedarf:
            if lbl in teil_map:
                t = teil_map[lbl]
                normal_ok, gedreht_ok = drehung_fuer_teil(material.maserung, t.maserung)
                teil_drehung[lbl] = (normal_ok, gedreht_ok)
        drehung = material.maserung == Maserung.KEINE
        erg = optimize_2d(fehlende, virt, kerf, drehung, teil_drehung)

    used = len(erg.schnittplaene)
    if used <= 0:
        return []

    return [MaterialBedarfOut(laenge=ref_l, breite=ref_b, anzahl=used)]


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _get_settings_dict() -> dict:
    from core.settings import Settings

    settings_path = DB_PATH.parent / "settings.json"
    s = Settings(settings_path)
    theme = s.value("appearance/theme", "system")
    return {
        "language": s.value("appearance/language", "en"),
        "unit": normalize_unit(s.value("appearance/unit", "mm")),
        "unit_feet": bool(s.value("appearance/unit_feet", True)),
        # "auto" stammt aus älteren Versionen des Dropdowns
        "theme": "system" if theme == "auto" else theme,
        "hotkeys": s.value("web/hotkeys", {}),
        "label_format": s.value("labels/format", "a4_3x8"),
        "label_custom_w": s.value("labels/custom_w", 89),
        "label_custom_h": s.value("labels/custom_h", 36),
        "api_enabled": s.value("api/enabled", False),
        "api_port": s.value("api/port", 8421),
        "api_key": s.value("api/key", ""),
        "license_key": s.value("license/key", ""),
        "nr_lock_days": s.value("stock/nr_lock_days", 1),
        "reservation": s.value("stock/reservation", True),
        "waste_keep": s.value("stock/waste_keep", False),
        "waste_min": s.value("stock/waste_min", 50),
    }


def _update_settings(data: SettingsIn):
    from core.settings import Settings

    if data.unit is not None and data.unit not in UNITS:
        raise _fehler(400, "einheit_unbekannt", f"Unknown unit, use one of: {', '.join(UNITS)}")
    settings_path = DB_PATH.parent / "settings.json"
    s = Settings(settings_path)
    if data.language is not None:
        s.setValue("appearance/language", data.language)
    if data.unit is not None:
        s.setValue("appearance/unit", data.unit)
    if data.unit_feet is not None:
        s.setValue("appearance/unit_feet", data.unit_feet)
    if data.theme is not None:
        s.setValue("appearance/theme", data.theme)
    if data.hotkeys is not None:
        s.setValue("web/hotkeys", data.hotkeys)
    if data.label_format is not None:
        s.setValue("labels/format", data.label_format)
    if data.label_custom_w is not None:
        s.setValue("labels/custom_w", data.label_custom_w)
    if data.label_custom_h is not None:
        s.setValue("labels/custom_h", data.label_custom_h)
    if data.api_enabled is not None:
        s.setValue("api/enabled", data.api_enabled)
    if data.api_port is not None:
        s.setValue("api/port", data.api_port)
    if data.api_key is not None:
        s.setValue("api/key", data.api_key)
    if data.nr_lock_days is not None:
        s.setValue("stock/nr_lock_days", max(0.0, data.nr_lock_days))
    if data.reservation is not None:
        s.setValue("stock/reservation", data.reservation)
    if data.waste_keep is not None:
        s.setValue("stock/waste_keep", data.waste_keep)
    if data.waste_min is not None:
        s.setValue("stock/waste_min", max(0.0, data.waste_min))
    if data.license_key is not None:
        s.setValue("license/key", data.license_key)


# ===========================================================================
# API Routes
# ===========================================================================

# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


@app.get("/api/materials", response_model=list[MaterialOut])
def list_materials():
    return [_material_to_out(m) for m in get_db().list_materials()]


@app.post("/api/materials", response_model=MaterialOut, status_code=201)
def create_material(data: MaterialIn):
    m = _material_from_in(data)
    try:
        m = get_db().save_material(m)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _material_to_out(m)


@app.put("/api/materials/{mid}", response_model=MaterialOut)
def update_material(mid: int, data: MaterialIn):
    db = get_db()
    existing = db.get_material(mid)
    if not existing:
        raise HTTPException(404, "Material not found")
    m = _material_from_in(data, mid)
    if data.lagerort is None:
        m.lagerort = existing.lagerort
    if data.lagerort_reste is None:
        m.lagerort_reste = existing.lagerort_reste
    if data.saegeblatt_id is None:
        m.saegeblatt_id = existing.saegeblatt_id
    try:
        m = db.save_material(m)
    except ValueError as e:
        raise HTTPException(409, str(e))
    _lagerort_wechsel_buchen(db, existing, m)
    return _material_to_out(m)


def _lagerort_wechsel_buchen(db: Database, vorher: Material, nachher: Material):
    if (vorher.lagerort, vorher.lagerort_reste) != (nachher.lagerort, nachher.lagerort_reste):
        db.journal("material_lagerort", nachher.id,
                   notiz=f"{vorher.lagerort}/{vorher.lagerort_reste or '–'} → "
                         f"{nachher.lagerort}/{nachher.lagerort_reste or '–'}")
        db.conn.commit()


@app.delete("/api/materials/{mid}", status_code=204)
def delete_material(mid: int):
    existing = get_db().get_material(mid)
    if not existing:
        raise HTTPException(404, "Material not found")
    get_db().delete_material(mid)


@app.post("/api/materials/{mid}/image", status_code=204)
async def upload_material_image(mid: int, file: UploadFile = File(...)):
    if not get_db().get_material(mid):
        raise HTTPException(404, "Material not found")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Image too large (max 5 MB)")
    get_db().save_material_image(mid, data)


@app.get("/api/materials/{mid}/image")
def get_material_image(mid: int):
    data = get_db().get_material_image(mid)
    if not data:
        raise HTTPException(404, "No image")
    ct = "image/jpeg"
    if data[:4] == b"\x89PNG":
        ct = "image/png"
    elif data[:4] == b"RIFF":
        ct = "image/webp"
    return Response(content=data, media_type=ct)


@app.delete("/api/materials/{mid}/image", status_code=204)
def delete_material_image(mid: int):
    if not get_db().get_material(mid):
        raise HTTPException(404, "Material not found")
    get_db().save_material_image(mid, None)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------


@app.get("/api/stock", response_model=list[StockOut])
def list_stock(material_id: Optional[int] = Query(None)):
    return [_stock_to_out(ls) for ls in get_db().list_lagerstuecke(material_id)]


class ReorderOut(BaseModel):
    material_id: int
    material: str
    kuerzel: str = ""
    typ: str
    lagerort: str = ""
    stock_id: Optional[int] = None     # None = Material hat gar keine Lagerzeile
    laenge: float = 0.0
    breite: float = 0.0


@app.get("/api/stock/reorder", response_model=list[ReorderOut])
def reorder_list():
    """Nachbestellliste: leere Normalmaße und Materialien ganz ohne Bestand."""
    db = get_db()
    return [ReorderOut(material_id=m.id, material=m.name, kuerzel=m.kuerzel,
                       typ=m.typ.value,
                       lagerort=m.lagerort,
                       stock_id=ls.id if ls else None,
                       laenge=ls.laenge if ls else 0.0,
                       breite=ls.breite if ls else 0.0)
            for m, ls in db.nachbestellliste()]


@app.post("/api/stock", response_model=StockOut, status_code=201)
def create_stock(data: StockIn):
    db = get_db()
    if not db.get_material(data.material_id):
        raise HTTPException(404, "Material not found")
    ls = Lagerstueck(
        material_id=data.material_id,
        laenge=data.laenge,
        breite=data.breite,
        stueckzahl=data.stueckzahl,
        ist_rest=data.ist_rest,
    )
    ls = db.save_lagerstueck(ls)
    _zugang_buchen(db, ls, db.einzelstueck_nrs_for_lagerstueck(ls.id))
    return _stock_to_out(ls)


def _zugang_buchen(db: Database, ls: Lagerstueck, nrs: list[int], art: str = "zugang"):
    m = db.get_material(ls.material_id)
    for nr in nrs:
        db.journal(art, ls.material_id, stueck_code(m.kuerzel if m else "", nr),
                   ls.laenge, ls.breite, 1)
    db.conn.commit()


@app.put("/api/stock/{sid}", response_model=StockOut)
def update_stock(sid: int, data: StockIn):
    db = get_db()
    existing = db.get_lagerstueck(sid)
    if not existing:
        raise HTTPException(404, "Stock piece not found")
    vorher = set(db.einzelstueck_nrs_for_lagerstueck(sid))
    ls = Lagerstueck(
        id=sid,
        material_id=data.material_id,
        laenge=data.laenge,
        breite=data.breite,
        stueckzahl=data.stueckzahl,
        ist_rest=data.ist_rest,
    )
    ls = db.save_lagerstueck(ls)
    nachher = set(db.einzelstueck_nrs_for_lagerstueck(sid))
    _zugang_buchen(db, ls, sorted(nachher - vorher))
    _zugang_buchen(db, existing, sorted(vorher - nachher), art="korrektur_ab")
    return _stock_to_out(ls)


@app.delete("/api/stock/{sid}", status_code=204)
def delete_stock(sid: int):
    db = get_db()
    existing = db.get_lagerstueck(sid)
    if not existing:
        raise HTTPException(404, "Stock piece not found")
    _zugang_buchen(db, existing, db.einzelstueck_nrs_for_lagerstueck(sid), art="korrektur_ab")
    db.delete_lagerstueck(sid)


# ---------------------------------------------------------------------------
# Einzelstücke (individual pieces)
# ---------------------------------------------------------------------------


def _piece_out(db: Database, e: Einzelstueck, material: Material | None,
               reserviert: dict | None = None) -> EinzelstueckOut:
    ls = db.get_lagerstueck(e.lagerstueck_id)
    ort = db.stueck_lagerort(material, ls) if material and ls else ""
    return EinzelstueckOut(
        reserviert_fuer=(reserviert or {}).get((e.lagerstueck_id, e.nr), ""),
        id=e.id, lagerstueck_id=e.lagerstueck_id, nr=e.nr, notiz=e.notiz,
        defekt_count=len(db.list_defekte(e.id)),
        code=stueck_code(material.kuerzel if material else "", e.nr),
        lagerort=ort, lagerort_effektiv=ort,
        material_id=material.id if material else 0,
        material=material.name if material else "",
        laenge=ls.laenge if ls else 0.0, breite=ls.breite if ls else 0.0,
        ist_rest=bool(ls and ls.ist_rest), etikett_gedruckt=e.etikett_gedruckt)


def _stueck_ref(db: Database, ref: str) -> Einzelstueck:
    """Einzelstück über interne ID oder Code ("AP4040-07")."""
    e = db.get_einzelstueck(int(ref)) if ref.isdigit() else None
    if e is None:
        gefunden = db.stueck_finden(ref)
        e = gefunden[2] if gefunden else None
    if e is None:
        raise _fehler(404, "stueck_unbekannt", f"Piece {ref} not found")
    return e


def _fehler(status: int, code: str, message: str, **extra) -> HTTPException:
    """Fehler mit festem Code für Programme: {"detail": {"code", "message", ...}}."""
    return HTTPException(status, {"code": code, "message": message, **extra})


def _material_of_stock(db: Database, sid: int) -> Material | None:
    ls = db.get_lagerstueck(sid)
    return db.get_material(ls.material_id) if ls else None


@app.get("/api/stock/{sid}/pieces", response_model=list[EinzelstueckOut])
def list_pieces(sid: int):
    db = get_db()
    material = _material_of_stock(db, sid)
    reserviert = (db.reservierte_stuecke(material.id)
                  if material and _lager_einstellungen()["reservierung"] else {})
    return [_piece_out(db, e, material, reserviert) for e in db.list_einzelstuecke(sid)]


@app.get("/api/pieces/{ref}", response_model=EinzelstueckOut)
def get_piece(ref: str):
    """Stück über ID oder Code: Material, Maß, Lagerort, Reservierung."""
    db = get_db()
    e = _stueck_ref(db, ref)
    material = _material_of_stock(db, e.lagerstueck_id)
    reserviert = (db.reservierte_stuecke(material.id)
                  if material and _lager_einstellungen()["reservierung"] else {})
    return _piece_out(db, e, material, reserviert)


@app.put("/api/pieces/{ref}", response_model=EinzelstueckOut)
def update_piece(ref: str, data: EinzelstueckIn):
    db = get_db()
    e = _stueck_ref(db, ref)
    e.notiz = data.notiz
    e = db.save_einzelstueck(e)
    return _piece_out(db, db.get_einzelstueck(e.id), _material_of_stock(db, e.lagerstueck_id))


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------


def _defect_out(d: Defekt, stueck_nr: int = 0) -> DefectOut:
    return DefectOut(
        id=d.id, einzelstueck_id=d.einzelstueck_id,
        stueck_nr=stueck_nr, position=d.position,
        position_y=d.position_y, laenge=d.laenge, breite=d.breite)


@app.get("/api/stock/{sid}/defects", response_model=list[DefectOut])
def list_defects_for_stock(sid: int):
    db = get_db()
    defekte_by_nr = db.list_defekte_for_lagerstueck(sid)
    result = []
    for nr, defs in sorted(defekte_by_nr.items()):
        for d in defs:
            result.append(_defect_out(d, nr))
    return result


@app.get("/api/pieces/{eid}/defects", response_model=list[DefectOut])
def list_defects(eid: int):
    db = get_db()
    e = db.get_einzelstueck(eid)
    if not e:
        raise HTTPException(404, "Piece not found")
    return [_defect_out(d, e.nr) for d in db.list_defekte(eid)]


@app.post("/api/pieces/{eid}/defects", response_model=DefectOut, status_code=201)
def create_defect(eid: int, data: DefectIn):
    db = get_db()
    e = db.get_einzelstueck(eid)
    if not e:
        raise HTTPException(404, "Piece not found")
    d = Defekt(
        einzelstueck_id=eid,
        position=data.position,
        position_y=data.position_y,
        laenge=data.laenge,
        breite=data.breite,
    )
    d = db.save_defekt(d)
    return _defect_out(d, e.nr)


@app.put("/api/defects/{did}", response_model=DefectOut)
def update_defect(did: int, data: DefectIn):
    db = get_db()
    existing = db.get_defekt(did)
    if not existing:
        raise HTTPException(404, "Defect not found")
    existing.position = data.position
    existing.position_y = data.position_y
    existing.laenge = data.laenge
    existing.breite = data.breite
    existing = db.save_defekt(existing)
    e = db.get_einzelstueck(existing.einzelstueck_id)
    return _defect_out(existing, e.nr if e else 0)


@app.delete("/api/defects/{did}", status_code=204)
def delete_defect(did: int):
    existing = get_db().get_defekt(did)
    if not existing:
        raise HTTPException(404, "Defect not found")
    get_db().delete_defekt(did)


# ---------------------------------------------------------------------------
# Lager: Lagerorte, Zugang/Entnahme, Abfallkiste, Journal
#
# Für Programme gedacht (Scanner, Maschinen, Skripte) wie für die Oberfläche:
# Materialien gehen über ID oder Kürzel, Stücke über ID oder Code ("AP4040-07"),
# Lagerorte über ID oder Namen. Fehler kommen als {"detail": {"code", "message"}}.
# ---------------------------------------------------------------------------


class LocationIn(BaseModel):
    name: str


class LocationOut(BaseModel):
    id: int
    name: str
    materialien: int = 0   # Materialien, deren Bestand oder Reste hier liegen
    stuecke: int = 0       # Stücke an diesem Ort


class LocationStockOut(BaseModel):
    stock_id: int
    laenge: float
    breite: float
    stueckzahl: int
    ist_rest: bool
    stuecke: list[EinzelstueckOut] = []


class LocationMaterialOut(BaseModel):
    material_id: int
    name: str
    kuerzel: str
    typ: str
    rolle: str             # "bestand" = Ort des Materials, "reste" = nur seine Reste
    bestand: list[LocationStockOut] = []


class MaterialLocationIn(BaseModel):
    lagerort: Optional[str] = None        # Name oder ID; None = unverändert
    lagerort_reste: Optional[str] = None  # "" = gleicher Ort wie das Material


class ReceiveIn(BaseModel):
    material: str          # ID oder Kürzel
    laenge: float = Field(gt=0)
    breite: float = 0.0
    anzahl: int = Field(1, ge=1, le=1000)
    ist_rest: bool = False


class ReceiveOut(BaseModel):
    stock_id: int
    codes: list[str]
    lagerort: str


class TakeIn(BaseModel):
    # verbraucht | verkauft | defekt | abfall (= in die Abfallkiste, falls eingeschaltet)
    grund: str = "verbraucht"
    notiz: str = ""
    trotzdem: bool = False   # auch wenn ein gespeicherter Plan das Stück reserviert


class TakeOut(BaseModel):
    code: str
    grund: str
    reserviert_fuer: str = ""
    abfallkiste: bool = False


class WasteIn(BaseModel):
    material: str          # ID oder Kürzel
    laenge: float = Field(gt=0)
    breite: float = 0.0
    anzahl: int = Field(1, ge=1, le=1000)


class WasteOut(BaseModel):
    material_id: int
    material: str
    kuerzel: str
    typ: str
    laenge: float
    breite: float
    anzahl: int


class JournalOut(BaseModel):
    id: int
    zeit: float
    art: str
    material_id: int
    material: str
    code: str
    laenge: float
    breite: float
    anzahl: int
    quelle: str
    notiz: str


TAKE_GRUENDE = ("verbraucht", "verkauft", "defekt", "abfall")


def _lagerort_ref(db: Database, ref: str) -> dict:
    ort = db.get_lagerort(ref)
    if not ort:
        raise _fehler(404, "lagerort_unbekannt", f"Location {ref} not found")
    return ort


def _material_ref(db: Database, ref: str) -> Material:
    m = db.material_finden(ref)
    if not m:
        raise _fehler(404, "material_unbekannt", f"Material {ref} not found")
    return m


def _lagerort_fehler(e: ValueError) -> HTTPException:
    texte = {"name_leer": "Name is empty",
             "lagerort_vorhanden": "A location with this name already exists",
             "letzter_lagerort": "The last location cannot be deleted",
             "ziel_ungueltig": "Invalid target location"}
    return _fehler(409, str(e), texte.get(str(e), str(e)))


@app.get("/api/locations", response_model=list[LocationOut])
def list_locations():
    return [LocationOut(**o) for o in get_db().list_lagerorte()]


@app.post("/api/locations", response_model=LocationOut, status_code=201)
def create_location(data: LocationIn):
    try:
        return LocationOut(**get_db().lagerort_anlegen(data.name))
    except ValueError as e:
        raise _lagerort_fehler(e)


@app.put("/api/locations/{ref}", response_model=LocationOut)
def rename_location(ref: str, data: LocationIn):
    db = get_db()
    ort = _lagerort_ref(db, ref)
    try:
        db.lagerort_umbenennen(ort["id"], data.name)
    except ValueError as e:
        raise _lagerort_fehler(e)
    return next(LocationOut(**o) for o in db.list_lagerorte() if o["id"] == ort["id"])


@app.delete("/api/locations/{ref}", status_code=204)
def delete_location(ref: str, ziel: Optional[str] = Query(None)):
    """Lagerort löschen. Nutzen ihn noch Materialien, muss `ziel` (ID oder Name)
    sagen, wohin sie kommen – sonst 409 mit code "lagerort_in_benutzung"."""
    db = get_db()
    ort = _lagerort_ref(db, ref)
    ziel_id = _lagerort_ref(db, ziel)["id"] if ziel else 0
    try:
        db.lagerort_loeschen(ort["id"], ziel_id)
    except LagerortInBenutzung as e:
        raise _fehler(409, "lagerort_in_benutzung", "Location is still used by materials",
                      materialien=e.materialien)
    except ValueError as e:
        raise _lagerort_fehler(e)


@app.get("/api/locations/{ref}/contents", response_model=list[LocationMaterialOut])
def location_contents(ref: str):
    """Was an einem Lagerort liegt: Materialien mit ihren Stücken."""
    db = get_db()
    ort = _lagerort_ref(db, ref)
    reservierung = _lager_einstellungen()["reservierung"]
    out = []
    for m, rolle in db.lagerort_inhalt(ort["name"]):
        reserviert = db.reservierte_stuecke(m.id) if reservierung else {}
        out.append(LocationMaterialOut(
            material_id=m.id, name=m.name, kuerzel=m.kuerzel, typ=m.typ.value, rolle=rolle,
            bestand=[LocationStockOut(
                stock_id=ls.id, laenge=ls.laenge, breite=ls.breite,
                stueckzahl=ls.stueckzahl, ist_rest=ls.ist_rest,
                stuecke=[_piece_out(db, e, m, reserviert)
                         for e in db.list_einzelstuecke(ls.id)])
                for ls in db.lagerort_stuecke(m, rolle)]))
    return out


@app.put("/api/materials/{ref}/location", response_model=MaterialOut)
def assign_material_location(ref: str, data: MaterialLocationIn):
    """Material einem Lagerort zuweisen (und optional einem Ort für seine Reste)."""
    db = get_db()
    vorher = _material_ref(db, ref)
    m = replace(vorher)
    if data.lagerort is not None:
        m.lagerort = _lagerort_ref(db, data.lagerort)["name"]
    if data.lagerort_reste is not None:
        m.lagerort_reste = (_lagerort_ref(db, data.lagerort_reste)["name"]
                            if data.lagerort_reste.strip() else "")
    m = db.save_material(m)
    _lagerort_wechsel_buchen(db, vorher, m)
    return _material_to_out(m)


@app.post("/api/stock/receive", response_model=ReceiveOut, status_code=201)
def receive_stock(data: ReceiveIn):
    """Zugang: Stücke einbuchen (gleiche Maße werden zusammengefasst).
    Liefert die Codes der neuen Stücke fürs Beschriften."""
    db = get_db()
    m = _material_ref(db, data.material)
    breite = data.breite if m.typ == MaterialTyp.PLATTE else 0.0
    ls = next((e for e in db.list_lagerstuecke(m.id)
               if abs(e.laenge - data.laenge) < 0.1 and abs(e.breite - breite) < 0.1
               and e.ist_rest == data.ist_rest), None) or Lagerstueck(
        material_id=m.id, laenge=data.laenge, breite=breite, stueckzahl=0,
        ist_rest=data.ist_rest)
    vorher = set(db.einzelstueck_nrs_for_lagerstueck(ls.id)) if ls.id else set()
    ls.stueckzahl += data.anzahl
    ls = db.save_lagerstueck(ls)
    neu = sorted(set(db.einzelstueck_nrs_for_lagerstueck(ls.id)) - vorher)
    _zugang_buchen(db, ls, neu)
    return ReceiveOut(stock_id=ls.id, codes=[stueck_code(m.kuerzel, nr) for nr in neu],
                      lagerort=db.stueck_lagerort(m, ls))


@app.post("/api/pieces/{ref}/take", response_model=TakeOut)
def take_piece(ref: str, data: TakeIn):
    """Ein Stück aus dem Lager nehmen. Reserviert es ein gespeicherter Plan, gibt es
    409 "stueck_reserviert" – mit trotzdem=true wird es dennoch entnommen."""
    if data.grund not in TAKE_GRUENDE:
        raise _fehler(400, "grund_ungueltig", f"grund must be one of {', '.join(TAKE_GRUENDE)}")
    db = get_db()
    e = _stueck_ref(db, ref)
    ls = db.get_lagerstueck(e.lagerstueck_id)
    m = db.get_material(ls.material_id)
    code = stueck_code(m.kuerzel, e.nr)
    projekt = (db.reservierte_stuecke(m.id).get((ls.id, e.nr), "")
               if _lager_einstellungen()["reservierung"] else "")
    if projekt and not data.trotzdem:
        raise _fehler(409, "stueck_reserviert", f"{code} is reserved by “{projekt}”",
                      projekt=projekt)
    notiz = data.notiz.strip()
    if projekt:
        notiz = (notiz + " · " if notiz else "") + f"reserviert: {projekt}"
    db.lager_verbrauchen(ls.id, stueck_nr=e.nr)
    db.journal("entnahme", m.id, code, ls.laenge, ls.breite, 1,
               notiz=f"{data.grund}" + (f" · {notiz}" if notiz else ""))
    in_kiste = data.grund == "abfall" and _lager_einstellungen()["abfall_aufheben"]
    if in_kiste:
        db.abfall_aendern(m.id, ls.laenge, ls.breite, 1, commit=False)
        db.journal("abfall_ein", m.id, "", ls.laenge, ls.breite, 1)
    db.conn.commit()
    return TakeOut(code=code, grund=data.grund, reserviert_fuer=projekt, abfallkiste=in_kiste)


@app.get("/api/waste", response_model=list[WasteOut])
def list_waste(material: Optional[str] = Query(None)):
    db = get_db()
    mid = _material_ref(db, material).id if material else None
    return [WasteOut(**w) for w in db.abfall_liste(mid)]


@app.post("/api/waste", response_model=list[WasteOut], status_code=201)
def add_waste(data: WasteIn):
    """Abschnitte in die Abfallkiste legen (ohne Code, nur Material + Maß + Anzahl)."""
    db = get_db()
    m = _material_ref(db, data.material)
    breite = data.breite if m.typ == MaterialTyp.PLATTE else 0.0
    db.abfall_aendern(m.id, data.laenge, breite, data.anzahl, commit=False)
    db.journal("abfall_ein", m.id, "", data.laenge, breite, data.anzahl)
    db.conn.commit()
    return [WasteOut(**w) for w in db.abfall_liste(m.id)]


@app.post("/api/waste/take", response_model=list[WasteOut])
def take_waste(data: WasteIn):
    """Abschnitte aus der Abfallkiste nehmen."""
    db = get_db()
    m = _material_ref(db, data.material)
    breite = data.breite if m.typ == MaterialTyp.PLATTE else 0.0
    vorhanden = next((w["anzahl"] for w in db.abfall_liste(m.id)
                      if _mass_schluessel(w["laenge"], w["breite"])
                      == _mass_schluessel(data.laenge, breite)), 0)
    if vorhanden < data.anzahl:
        raise _fehler(409, "abfall_zu_wenig", f"Only {vorhanden} piece(s) of this size in the bin",
                      vorhanden=vorhanden)
    db.abfall_aendern(m.id, data.laenge, breite, -data.anzahl, commit=False)
    db.journal("abfall_ab", m.id, "", data.laenge, breite, data.anzahl)
    db.conn.commit()
    return [WasteOut(**w) for w in db.abfall_liste(m.id)]


@app.delete("/api/waste", status_code=204)
def empty_waste(material: Optional[str] = Query(None)):
    """Abfallkiste leeren – ganz oder nur für ein Material."""
    db = get_db()
    m = _material_ref(db, material) if material else None
    if m:
        n = db.abfall_leeren(m.id)
        db.journal("abfall_leer", m.id, "", 0, 0, n)
    else:
        for mid in {w["material_id"] for w in db.abfall_liste()}:
            n = db.abfall_leeren(mid)
            db.journal("abfall_leer", mid, "", 0, 0, n)
    db.conn.commit()


@app.get("/api/journal", response_model=list[JournalOut])
def stock_journal(material: Optional[str] = Query(None), seit: float = Query(0.0),
                  limit: int = Query(200)):
    """Lagerbuchungen, neueste zuerst. `seit` = Unix-Zeit."""
    db = get_db()
    mid = _material_ref(db, material).id if material else None
    return [JournalOut(**j) for j in db.journal_liste(mid, seit, limit)]


# ---------------------------------------------------------------------------
# Saw Blades
# ---------------------------------------------------------------------------


@app.get("/api/blades", response_model=list[BladeOut])
def list_blades():
    return [
        BladeOut(id=b.id, name=b.name, schnittbreite=b.schnittbreite)
        for b in get_db().list_saegeblaetter()
    ]


@app.post("/api/blades", response_model=BladeOut, status_code=201)
def create_blade(data: BladeIn):
    s = Saegeblatt(name=data.name, schnittbreite=data.schnittbreite)
    s = get_db().save_saegeblatt(s)
    return BladeOut(id=s.id, name=s.name, schnittbreite=s.schnittbreite)


@app.put("/api/blades/{bid}", response_model=BladeOut)
def update_blade(bid: int, data: BladeIn):
    s = Saegeblatt(id=bid, name=data.name, schnittbreite=data.schnittbreite)
    s = get_db().save_saegeblatt(s)
    return BladeOut(id=s.id, name=s.name, schnittbreite=s.schnittbreite)


@app.delete("/api/blades/{bid}", status_code=204)
def delete_blade(bid: int):
    get_db().delete_saegeblatt(bid)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(art: str = ""):
    """Projekte samt Sägeaufträgen; ?art=sammel nur die Sammelpläne, ?art=alle alles
    (Sammelpläne zuletzt, ohne Vorlagen), ?art=liste nur die Sägeaufträge, ?art=projekt nur
    normale, ?art=vorlage nur die Vorlagen."""
    if art not in ("", "sammel", "alle", "liste", "projekt", "vorlage"):
        raise HTTPException(
            400, "art must be '', 'projekt', 'liste', 'sammel', 'vorlage' or 'alle'")
    db = get_db()
    if art == "vorlage":
        return [_projekt_to_out(p) for p in db.list_projekte(vorlagen=True)]
    if art in ("liste", "projekt"):
        return [_projekt_to_out(p) for p in db.list_projekte()
                if (p.art == "liste") == (art == "liste")]
    projekte = [] if art == "sammel" else db.list_projekte()
    if art:
        projekte += db.list_projekte(sammel=True)
    return [_projekt_to_out(p) for p in projekte]


class CutJobRef(BaseModel):
    projekt_id: int
    name: str
    anzahl: int


class AllPartOut(BaseModel):
    teil_id: int
    label: str
    projekt_id: int
    projekt: str
    material_id: int
    laenge: float
    breite: float
    offen: int
    gesamt: int
    vorrat: int                               # Fertigteile
    beauftragt: int = 0                       # offen in Sägeaufträgen
    auftraege: list[CutJobRef] = []
    verplant: int = 0                         # ungesägt in Plänen anderer Projekte (Füllteile)
    sammelplan_id: int = 0                    # Material dieses Projekts läuft im Sammelplan
    sammelplan: str = ""
    verfuegbar: int = 0                       # offen − beauftragt − verplant (0 im Sammelplan)


class PartMaterialOut(BaseModel):
    material_id: int
    material: str
    typ: str
    teile: int                    # Teile mit verfügbarer Menge
    stueck: int                   # verfügbare Stück
    einheit: str                  # "mm" (Stangen, Länge) oder "mm2" (Platten, Fläche)
    bedarf: float                 # grob: Σ Länge (+ Schnittfuge) bzw. Σ Fläche
    lager: float                  # nutzbare Länge bzw. Fläche im Lager
    reicht: bool
    fehlt_stueck: int = 0         # grob: so viele größte Lagerstücke fehlen


class CutListEntry(BaseModel):
    teil_id: int
    menge: int = Field(ge=1, le=10000)


class CutListIn(BaseModel):
    name: str = Field("", max_length=200)   # leer = „Sägeauftrag <Datum>“
    eintraege: list[CutListEntry] = Field(min_length=1)


class TakeStockIn(BaseModel):
    anzahl: int = Field(0, ge=0)   # 0 = so viele wie möglich


def _alle_teile_out(db: Database) -> list[AllPartOut]:
    vp = db.teile_verplanung()
    erg = []
    for k in db.alle_teile():
        t = k["teil"]
        auftraege = [CutJobRef(**a) for a in vp["beauftragt"].get(t.id, [])]
        beauftragt = sum(a.anzahl for a in auftraege)
        verplant = vp["in_plaenen"].get(t.id, 0)
        sid, sname = vp["sammel"].get((t.projekt_id, t.material_id), (0, ""))
        verfuegbar = 0 if sid else max(0, t.offen_anzahl - beauftragt - verplant)
        erg.append(AllPartOut(
            teil_id=t.id, label=t.label, projekt=k["projekt"], projekt_id=t.projekt_id,
            material_id=t.material_id, laenge=t.laenge, breite=t.breite,
            offen=t.offen_anzahl, gesamt=t.gesamt_anzahl, vorrat=t.vorrat,
            beauftragt=beauftragt, auftraege=auftraege, verplant=verplant,
            sammelplan_id=sid, sammelplan=sname, verfuegbar=verfuegbar))
    return erg


@app.get("/api/parts", response_model=list[AllPartOut])
def list_all_parts():
    """Alle Teile aller Projekte – für den Reiter „Teile“, mit dem, was davon schon
    verplant ist (Sägeauftrag, Sammelplan, Füllteil) und was noch verfügbar ist."""
    return _alle_teile_out(get_db())


@app.get("/api/parts/materials", response_model=list[PartMaterialOut])
def parts_by_material():
    """Verfügbare Teile je Material mit grober Lager-Schätzung (Länge bzw. Fläche).
    Die genaue Antwort gibt erst die Optimierung."""
    db = get_db()
    blaetter = db.list_saegeblaetter()
    kerf = blaetter[0].schnittbreite if blaetter else 0.0
    je_mat: dict[int, list[AllPartOut]] = {}
    for x in _alle_teile_out(db):
        if x.verfuegbar > 0:
            je_mat.setdefault(x.material_id, []).append(x)
    erg = []
    for mid, teile in je_mat.items():
        m = db.get_material(mid)
        if not m:
            continue
        stange = m.typ == MaterialTyp.STANGE
        rand = 2 * (m.besaeumung or 0)
        if stange:
            bedarf = sum((x.laenge + kerf) * x.verfuegbar for x in teile)
            groessen = [(max(0.0, ls.laenge - rand), ls.stueckzahl)
                        for ls in db.list_lagerstuecke(mid)]
        else:
            bedarf = sum(x.laenge * x.breite * x.verfuegbar for x in teile)
            groessen = [(max(0.0, ls.laenge - rand) * max(0.0, ls.breite - rand), ls.stueckzahl)
                        for ls in db.list_lagerstuecke(mid)]
        lager = sum(g * n for g, n in groessen)
        groesste = max((g for g, _ in groessen), default=0.0)
        if not groesste:   # leeres Lager: nach dem Teil schätzen
            groesste = max((x.laenge if stange else x.laenge * x.breite) for x in teile)
        fehlt = 0 if bedarf <= lager else -(-(bedarf - lager) // groesste)
        erg.append(PartMaterialOut(
            material_id=mid, material=m.name, typ=m.typ.value, teile=len(teile),
            stueck=sum(x.verfuegbar for x in teile), einheit="mm" if stange else "mm2",
            bedarf=round(bedarf, 1), lager=round(lager, 1), reicht=bedarf <= lager,
            fehlt_stueck=int(fehlt)))
    return sorted(erg, key=lambda e: e.material.lower())


@app.post("/api/parts/{ref}/take-stock", response_model=PartOut)
def take_stock_of_part(ref: int, data: TakeStockIn = TakeStockIn()):
    """Fertigteile eines Teils als gesägt übernehmen (höchstens so viele wie offen)."""
    db = get_db()
    if not db.get_teil(ref):
        raise HTTPException(404, "Part not found")
    db.vorrat_uebernehmen_teil(ref, data.anzahl)
    return _teil_to_out(db.get_teil(ref))


def _datum_heute() -> tuple[str, str]:
    """(Sprache, heutiges Datum in deren Schreibweise) für vergebene Namen."""
    import datetime
    lang = _get_settings_dict().get("language", "en")
    heute = datetime.date.today()
    return lang, heute.strftime("%d.%m.%Y") if lang in ("de", "fr", "it") else heute.isoformat()


def _saegeauftrag_name() -> str:
    lang, datum = _datum_heute()
    vorlage = WEB_EXTRA_TRANSLATIONS["parts.list_default"]
    return vorlage.get(lang, vorlage["en"]).replace("{datum}", datum)


@app.post("/api/cut-lists", response_model=ProjectOut, status_code=201)
def create_cut_list(data: CutListIn):
    """Sägeauftrag (intern „Schnittliste“, art='liste') aus einzelnen Teilen: wird wie ein
    Projekt optimiert und gesägt. Gesägt zählt beim Herkunftsteil, Überschuss geht zu
    dessen Fertigteilen. Ohne Name heißt er „Sägeauftrag <Datum>“."""
    db = get_db()
    erlaubt = {k["teil"].id for k in db.alle_teile()}
    mengen: dict[int, int] = {}
    for e in data.eintraege:
        if e.teil_id not in erlaubt:
            raise HTTPException(404, f"Part {e.teil_id} not found")
        mengen[e.teil_id] = mengen.get(e.teil_id, 0) + e.menge
    liste = db.schnittliste_anlegen(data.name.strip() or _saegeauftrag_name(),
                                    list(mengen.items()))
    return _projekt_to_out(liste)


class TemplateIn(BaseModel):
    name: str = Field("", max_length=200)   # leer: beim Speichern aus Projekt dessen Name


class TemplateRunIn(BaseModel):
    saetze: int = Field(1, ge=1, le=1000)
    name: str = Field("", max_length=200)   # leer = „<Vorlage> – <Datum>“


def _vorlage_holen(db: Database, vid: int) -> Projekt:
    v = db.get_projekt(vid)
    if not v or v.art != "vorlage":
        raise _fehler(404, "vorlage_unbekannt", f"Template {vid} not found")
    return v


def _nicht_vorlage(p: Projekt):
    """Vorlagen werden nie optimiert oder gesägt – nur ihre Durchgänge."""
    if p.art == "vorlage":
        raise _fehler(400, "vorlage_nicht_saegbar",
                      "A template is never cut itself; start a run from it")


@app.post("/api/templates", response_model=ProjectOut, status_code=201)
def create_template(data: TemplateIn):
    """Neue, leere Vorlage (Teile danach über /api/projects/{id}/parts)."""
    name = data.name.strip()
    if not name:
        raise _fehler(400, "name_leer", "Name must not be empty")
    return _projekt_to_out(get_db().vorlage_anlegen(name))


@app.post("/api/projects/{pid}/as-template", response_model=ProjectOut, status_code=201)
def save_as_template(pid: int, data: TemplateIn):
    """Vorlage aus einem Projekt, Sägeauftrag oder einer anderen Vorlage (Kopie der Teile,
    Stückzahl je Exemplar). Das Original bleibt unverändert."""
    db = get_db()
    quelle = db.get_projekt(pid)
    if not quelle:
        raise HTTPException(404, "Project not found")
    if quelle.art == "sammel":
        raise _sammel_ohne_teile()
    name = data.name.strip() or quelle.name
    return _projekt_to_out(db.vorlage_aus_projekt(pid, name))


@app.post("/api/templates/{vid}/run", response_model=ProjectOut, status_code=201)
def run_template(vid: int, data: TemplateRunIn):
    """Durchgang: neuer Sägeauftrag mit den Teilen der Vorlage × Sätze. Wird wie jeder
    Sägeauftrag optimiert (gegen das aktuelle Lager) und gesägt; gesägt zählt nur beim
    Durchgang selbst."""
    db = get_db()
    v = _vorlage_holen(db, vid)
    if not v.teile:
        raise _fehler(400, "vorlage_leer", "The template has no parts")
    name = data.name.strip()
    if not name:
        _, datum = _datum_heute()
        name = f"{v.name} – {datum}"
    return _projekt_to_out(db.durchgang_anlegen(vid, data.saetze, name))


@app.get("/api/templates/{vid}/runs", response_model=list[TemplateRunOut])
def template_runs(vid: int):
    """Verlauf einer Vorlage, neueste zuerst."""
    db = get_db()
    _vorlage_holen(db, vid)
    return [_lauf_to_out(d) for d in db.vorlage_verlauf(vid)]


@app.get("/api/projects/{pid}", response_model=ProjectOut)
def get_project(pid: int):
    p = get_db().get_projekt(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return _projekt_to_out(p)


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectIn):
    p = Projekt(name=data.name, anzahl=data.anzahl)
    p = get_db().save_projekt(p)
    p.teile = []
    return _projekt_to_out(p)


@app.put("/api/projects/{pid}", response_model=ProjectOut)
def update_project(pid: int, data: ProjectIn):
    existing = get_db().get_projekt(pid)
    if not existing:
        raise HTTPException(404, "Project not found")
    existing.name = data.name
    # Ein Sammelplan wird genau einmal gesägt; die Exemplare stecken in den Mitgliedern
    existing.anzahl = 1 if existing.art == "sammel" else data.anzahl
    get_db().save_projekt(existing)
    return _projekt_to_out(get_db().get_projekt(pid))


@app.post("/api/projects/{pid}/clone", response_model=ProjectOut, status_code=201)
def clone_project(pid: int):
    db = get_db()
    existing = db.get_projekt(pid)
    if not existing:
        raise HTTPException(404, "Project not found")
    if existing.art == "sammel":
        raise _sammel_ohne_teile()
    # Schnittliste (samt Herkunft) und Vorlage behalten beim Duplizieren ihre Art
    art = existing.art if existing.art in ("liste", "vorlage") else ""
    clone = Projekt(name=f"{existing.name} (Kopie)", anzahl=existing.anzahl, art=art)
    clone = db.save_projekt(clone)
    for t in db.list_teile(pid):
        ct = Teil(
            projekt_id=clone.id,
            label=t.label,
            typ=t.typ,
            material_id=t.material_id,
            laenge=t.laenge,
            breite=t.breite,
            stueckzahl=t.stueckzahl,
            gesaegt_anzahl=0,
            maserung=t.maserung,
            herkunft_teil_id=t.herkunft_teil_id,
        )
        db.save_teil(ct)
    clone.teile = db.list_teile(clone.id)
    return _projekt_to_out(clone)


@app.post("/api/projects/{pid}/copy-parts", response_model=list[PartOut], status_code=201)
def copy_parts_to_project(pid: int, data: CopyPartsRequest):
    db = get_db()
    target = db.get_projekt(pid)
    if not target:
        raise HTTPException(404, "Target project not found")
    if target.art == "sammel":
        raise _sammel_ohne_teile()
    copied = []
    for tid in data.part_ids:
        rows = db.conn.execute("SELECT * FROM teil WHERE id=?", (tid,)).fetchone()
        if not rows:
            continue
        ct = Teil(
            projekt_id=pid,
            label=rows["label"],
            typ=MaterialTyp(rows["typ"]),
            material_id=rows["material_id"],
            laenge=rows["laenge"],
            breite=rows["breite"],
            stueckzahl=rows["stueckzahl"],
            gesaegt_anzahl=0,
            maserung=Maserung(rows["maserung"]),
        )
        ct = db.save_teil(ct)
        copied.append(_teil_to_out(ct))
    return copied


def _sammel_ohne_teile() -> HTTPException:
    return _fehler(400, "sammel_ohne_teile",
                   "A combined plan has no parts of its own; edit them in the member projects")


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: int):
    """Projekt löschen. Ein Sammelplan verschwindet samt Plan und Mitgliederliste:
    Gesägtes zählt schon in den Mitglieds-Projekten, der Rest wird dort wieder offen,
    reservierte Lagerstücke werden frei."""
    existing = get_db().get_projekt(pid)
    if not existing:
        raise HTTPException(404, "Project not found")
    get_db().delete_projekt(pid)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


@app.get("/api/projects/{pid}/parts", response_model=list[PartOut])
def list_parts(pid: int):
    return [_teil_to_out(t) for t in get_db().list_teile(pid)]


@app.post("/api/projects/{pid}/parts", response_model=PartOut, status_code=201)
def create_part(pid: int, data: PartIn):
    existing = get_db().get_projekt(pid)
    if not existing:
        raise HTTPException(404, "Project not found")
    if existing.art == "sammel":
        raise _sammel_ohne_teile()
    if existing.art == "vorlage":
        data.gesaegt_anzahl = 0   # eine Vorlage hat keinen Fortschritt
    t = Teil(
        projekt_id=pid,
        label=data.label,
        typ=MaterialTyp(data.typ),
        material_id=data.material_id,
        laenge=data.laenge,
        breite=data.breite,
        stueckzahl=data.stueckzahl,
        gesaegt_anzahl=data.gesaegt_anzahl,
        maserung=Maserung(data.maserung),
    )
    t = get_db().save_teil(t)
    return _teil_to_out(t)


@app.put("/api/parts/{tid}", response_model=PartOut)
def update_part(tid: int, data: PartIn):
    t = Teil(
        id=tid,
        projekt_id=0,
        label=data.label,
        typ=MaterialTyp(data.typ),
        material_id=data.material_id,
        laenge=data.laenge,
        breite=data.breite,
        stueckzahl=data.stueckzahl,
        gesaegt_anzahl=data.gesaegt_anzahl,
        maserung=Maserung(data.maserung),
    )
    # Preserve the original projekt_id from DB
    rows = get_db().conn.execute("SELECT projekt_id FROM teil WHERE id=?", (tid,)).fetchone()
    if not rows:
        raise HTTPException(404, "Part not found")
    t.projekt_id = rows["projekt_id"]
    if (pr := get_db().get_projekt(t.projekt_id)) and pr.art == "vorlage":
        t.gesaegt_anzahl = 0
        data.vorrat = None
    get_db().save_teil(t)
    if data.vorrat is not None:
        get_db().teil_vorrat_setzen(tid, data.vorrat)
    return _teil_to_out(get_db().get_teil(tid))


@app.delete("/api/parts/{tid}", status_code=204)
def delete_part(tid: int):
    get_db().delete_teil(tid)


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------


@dataclass
class _Lagerlage:
    """Was beim Optimieren eines Materials an Lager verfügbar ist."""
    nrs_map: dict          # Lagerzeile → freie Stücknummern (ohne reservierte)
    vorrat_alle: list      # alle Lagerzeilen (für den Materialbedarf)
    vorrat: list           # Lagerzeilen mit Stückzahl = freie Nummern
    defekte_map: dict      # Lagerzeile → Stücknummer → Defekte
    defekte_lauf: dict     # wie defekte_map, aber auf laufende Nummern 1..n


def _lagerlage(db: Database, material_id: int, ausser_projekt: int,
               auch_ausser: tuple[int, ...] = ()) -> _Lagerlage:
    """Verfügbares Lager. Reservierung: Noch nicht angefangene Bretter gespeicherter
    Pläne ANDERER Projekte sind tabu (außer denen in auch_ausser)."""
    defekte_map = db.list_defekte_for_material(material_id)
    nrs_map = db.einzelstueck_nrs_for_material(material_id)
    if _lager_einstellungen()["reservierung"]:
        reserviert = set(db.reservierte_stuecke(
            material_id, ausser_projekt=ausser_projekt, auch_ausser=auch_ausser))
        nrs_map = {lid: [nr for nr in nrs if (lid, nr) not in reserviert]
                   for lid, nrs in nrs_map.items()}
    return _lage_aus(nrs_map, db.list_lagerstuecke(material_id), defekte_map)


def _lage_aus(nrs_map: dict, vorrat_alle: list, defekte_map: dict) -> _Lagerlage:
    vorrat = [replace(ls, stueckzahl=len(nrs_map.get(ls.id, []))) for ls in vorrat_alle]
    vorrat = [ls for ls in vorrat if ls.stueckzahl > 0]
    # Der Optimizer zählt die Kopien eines Lagerstücks lückenlos 1..anzahl,
    # echte Stücknummern haben Lücken (verbraucht/reserviert). Defekte auf die
    # laufende Nummer umschlüsseln und das Ergebnis danach zurückübersetzen.
    defekte_lauf = {
        lid: {i + 1: by_nr[nr] for i, nr in enumerate(nrs_map.get(lid, []))
              if nr in by_nr}
        for lid, by_nr in defekte_map.items()
    }
    return _Lagerlage(nrs_map, vorrat_alle, vorrat, defekte_map, defekte_lauf)


def _lage_ohne(lage: _Lagerlage, erg: OptimierungsErgebnis) -> _Lagerlage:
    """Lagerlage ohne die Stücke, die ein Ergebnis schon belegt."""
    belegt = {(sp.lagerstueck_id, sp.stueck_nr) for sp in erg.schnittplaene}
    nrs_map = {lid: [nr for nr in nrs if (lid, nr) not in belegt]
               for lid, nrs in lage.nrs_map.items()}
    return _lage_aus(nrs_map, lage.vorrat_alle, lage.defekte_map)


def _berechnen(material: Material, kerf: float, algorithm: str, reste_zuerst: bool,
               teile: list[Teil], mengen: dict[int, int], lage: _Lagerlage,
               max_pro_stange: int = 0) -> OptimierungsErgebnis:
    """Teile (Mengen je ID) auf das freie Lager verteilen, ohne zu speichern.

    max_pro_stange > 0 (nur Stangen): höchstens so viele Teile je Stange. Das kann
    nur der Muster-Optimierer, der genetische Algorithmus wird dann übergangen.
    """
    is_1d = material.typ == MaterialTyp.STANGE
    besaeumung = material.besaeumung
    teil_drehung: dict[str, tuple[bool, bool]] = {}
    for t in teile:
        normal_ok, gedreht_ok = drehung_fuer_teil(material.maserung, t.maserung)
        teil_drehung[t.label] = (normal_ok, gedreht_ok)
    drehung_erlaubt = material.maserung == Maserung.KEINE

    def rechnen(lager: list[Lagerstueck], mengen: dict[int, int]) -> OptimierungsErgebnis:
        tl = [t for t in teile if mengen.get(t.id, 0) > 0]
        if is_1d:
            teil_tuples = [(t.label, t.laenge, mengen[t.id]) for t in tl]
            stock = [StangenVorrat(ls.id, ls.laenge - 2 * besaeumung, ls.stueckzahl)
                     for ls in lager if ls.laenge - 2 * besaeumung > 0]
            if algorithm == "ga" and not max_pro_stange:
                return optimize_1d_ga(teil_tuples, stock, kerf, lage.defekte_lauf)
            return optimize_1d(teil_tuples, stock, kerf, lage.defekte_lauf,
                               max_pro_stange=max_pro_stange)
        teil_tuples = [(t.label, t.laenge, t.breite, mengen[t.id]) for t in tl]
        stock = [PlattenVorrat(ls.id, ls.laenge - 2 * besaeumung,
                               ls.breite - 2 * besaeumung, ls.stueckzahl)
                 for ls in lager]
        if algorithm == "ga":
            return optimize_2d_ga(teil_tuples, stock, kerf, drehung_erlaubt,
                                  teil_drehung, lage.defekte_lauf)
        if algorithm == "nested":
            return optimize_2d_nested(teil_tuples, stock, kerf, drehung_erlaubt,
                                      teil_drehung, lage.defekte_lauf)
        return optimize_2d(teil_tuples, stock, kerf, drehung_erlaubt,
                           teil_drehung, lage.defekte_lauf)

    reste = [ls for ls in lage.vorrat if ls.ist_rest]
    ganze = [ls for ls in lage.vorrat if not ls.ist_rest]
    if reste_zuerst and reste and ganze:
        # 1. Durchgang nur mit Resten, 2. Durchgang mit ganzen Stücken für den Rest
        erg_reste = rechnen(reste, mengen)
        noch = _fehlende_mengen(erg_reste.fehlende_teile, teile, mengen)
        erg_ganz = rechnen(ganze, noch) if noch else OptimierungsErgebnis()
        ergebnis = OptimierungsErgebnis(
            schnittplaene=erg_reste.schnittplaene + erg_ganz.schnittplaene,
            fehlende_teile=erg_ganz.fehlende_teile)
    else:
        ergebnis = rechnen(lage.vorrat, mengen)

    for sp in ergebnis.schnittplaene:
        nrs = lage.nrs_map.get(sp.lagerstueck_id, [])
        if 0 < sp.stueck_nr <= len(nrs):
            sp.stueck_nr = nrs[sp.stueck_nr - 1]
    return ergebnis


def _saegeblatt_merken(db: Database, material: Material, blade: Saegeblatt):
    """Wer mit einem anderen Sägeblatt rechnet, macht es zum Standard des Materials."""
    if material.saegeblatt_id != blade.id:
        db.set_material_saegeblatt(material.id, blade.id)


def _schon_geplant(behalten: list[PlanBrett]) -> dict[int, int]:
    """Ungesägte Stücke auf behaltenen (angefangenen) Brettern, je Teil."""
    n: dict[int, int] = {}
    for b in behalten:
        for st in b.stuecke:
            if not st.gesaegt and st.teil_id:
                n[st.teil_id] = n.get(st.teil_id, 0) + 1
    return n


@app.post("/api/optimize", response_model=OptimizeResult)
def run_optimization(req: OptimizeRequest):
    """Berechnen und als Plan des Projekts für dieses Material speichern.

    Ist der bisherige Plan schon angefangen, bleiben angefangene Bretter erhalten:
    2D-Platten samt ihrer ungesägten Teile (deren Fläche steht nicht im Lager),
    1D-Stangen nur mit den gesägten Teilen – ihr Rest ist bereits eingebucht.
    Neu verteilt wird nur, was darauf nicht (mehr) liegt.
    """
    projekt = get_db().get_projekt(req.project_id)
    if not projekt:
        raise HTTPException(404, "Project not found")
    if projekt.art == "sammel":
        raise HTTPException(400, "Use /api/sammel/optimize for collective plans")
    _nicht_vorlage(projekt)

    material = get_db().get_material(req.material_id)
    if not material:
        raise HTTPException(404, "Material not found")

    blades = get_db().list_saegeblaetter()
    blade = next((b for b in blades if b.id == req.blade_id), None)
    if not blade:
        raise HTTPException(404, "Saw blade not found")

    db = get_db()
    _saegeblatt_merken(db, material, blade)
    is_1d = material.typ == MaterialTyp.STANGE
    alt = db.get_plan(req.project_id, req.material_id)
    fuell_auswahl = ([f.model_dump() for f in req.fuellteile] if req.fuellteile is not None
                     else (alt.fuellteile if alt else []))
    fuell_alle = (req.fuell_alle_reste if req.fuell_alle_reste is not None
                  else (alt.fuell_alle_reste if alt else False))
    max_pro_stange = 0
    if is_1d:
        max_pro_stange = max(0, req.max_pro_stange if req.max_pro_stange is not None
                             else (alt.max_pro_stange if alt else 0))
    fuell_wahl = alt.fuell_wahl if alt else {}
    behalten = _angefangene_bretter(alt, is_1d)
    schon_geplant = _schon_geplant(behalten)
    # Was ungesägt in anderen Plänen liegt (Sammelplan, Füllteil), ist schon verplant
    anderswo = db.ungesaegt_in_plaenen(req.material_id, ausser_projekt=req.project_id)
    offen = {t.id: t.offen_anzahl - schon_geplant.get(t.id, 0) - anderswo.get(t.id, 0)
             for t in projekt.teile}

    # Filter parts for this material that are not fully cut (or already on a kept board)
    teile = [t for t in projekt.teile
             if t.material_id == req.material_id and offen[t.id] > 0]
    if not teile:
        if behalten:
            return _plan_speichern(projekt, material, blade, req.algorithm, behalten,
                                   [], [], fuell_auswahl, fuell_alle, max_pro_stange,
                                   fuell_wahl)
        if any(anderswo.get(t.id) for t in projekt.teile if t.material_id == material.id):
            sammel = db.sammel_von_projekt(projekt.id).get(material.id)
            raise HTTPException(409, f"All open parts are already in “{sammel}”."
                                if sammel else "All open parts are already in another plan")
        raise HTTPException(400, "No open parts for this material")

    fuell_fest, fuell_auf = _fuellteile_laden(db, projekt, material, fuell_auswahl)
    for ft in fuell_fest:
        offen[ft.id] = next(int(f["menge"]) for f in fuell_auswahl if f["teil_id"] == ft.id)
    teile = teile + fuell_fest
    fuell_ids = {t.id for t in fuell_fest} | {t.id for t, _ in fuell_auf}

    kerf = blade.schnittbreite
    lage = _lagerlage(db, req.material_id, ausser_projekt=req.project_id)
    ergebnis = _berechnen(material, kerf, req.algorithm, req.reste_zuerst, teile,
                          {t.id: offen[t.id] for t in teile}, lage, max_pro_stange)

    neue = _ergebnis_to_bretter(ergebnis, lage.defekte_map, teile, offen)
    for b in neue:
        for st in b.stuecke:
            st.ist_fuellteil = st.teil_id in fuell_ids
    vorschlaege: list[dict] = []
    if fuell_auf:
        vorschlaege = _reste_auffuellen(neue, fuell_auf, kerf, material, fuell_alle,
                                        fuell_wahl, max_pro_stange)
    bedarf = []
    zu_lang = _zu_lange_teile(ergebnis.fehlende_teile, teile, lage.vorrat_alle, material)
    if ergebnis.fehlende_teile:
        bedarf = [m.model_dump() for m in _berechne_materialbedarf(
            ergebnis.fehlende_teile, teile, lage.vorrat_alle, material, kerf)]
    return _plan_speichern(projekt, material, blade, req.algorithm, behalten + neue,
                           ergebnis.fehlende_teile, bedarf, fuell_auswahl, fuell_alle,
                           max_pro_stange, fuell_wahl, vorschlaege, zu_lang)


def _fuellteile_laden(db: Database, projekt: Projekt, material: Material, auswahl: list[dict]
                      ) -> tuple[list[Teil], list[tuple[Teil, int]]]:
    """Füllteil-Auswahl eines Plans in Teile umwandeln: (fest, [(Teil, Menge)] zum Auffüllen).

    Füllteile sind Teile anderer Projekte desselben Materials. Im Plan heißen sie
    "Label → Projekt", damit sie unterscheidbar sind (der Optimizer kennt nur Labels).
    "fest" stammt aus älteren Plänen (genau diese Menge, notfalls mit mehr Material);
    neue Auswahlen füllen nur auf, eine Menge ist dann Obergrenze und Vorrang zugleich.
    """
    fest: list[Teil] = []
    auf: list[tuple[Teil, int]] = []
    for f in auswahl:
        t = db.get_teil(f["teil_id"])
        if not t or t.material_id != material.id or t.projekt_id == projekt.id:
            continue
        herkunft = db.get_projekt(t.projekt_id)
        ft = replace(t, label=f"{t.label} → {herkunft.name if herkunft else '?'}")
        if f.get("modus") == "fest":
            if int(f.get("menge") or 0) > 0:
                fest.append(ft)
        else:
            auf.append((ft, int(f.get("menge") or 0)))
    return fest, auf


@app.post("/api/plans/{plan_id}/fill-choice", response_model=OptimizeResult)
def set_fill_choice(plan_id: int, data: FuellWahlIn):
    """Füllung einer Gruppe gleicher Stangenreste wählen (wahl=None: Automatik).

    Rechnet nur den Auffüll-Durchgang neu; die Teile des Projekts bleiben, wo sie
    sind. Angefangene Stangen bleiben unverändert.
    """
    db = get_db()
    plan = db.get_plan_by_id(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    projekt = db.get_projekt(plan.projekt_id)
    material = db.get_material(plan.material_id)
    if not projekt or not material or material.typ != MaterialTyp.STANGE:
        raise HTTPException(400, "Fill choice is only available for bars")
    wahl = dict(plan.fuell_wahl)
    if data.wahl is None:
        wahl.pop(data.gruppe, None)
    else:
        wahl[data.gruppe] = [{"teil_id": int(w["teil_id"]), "anzahl": int(w["anzahl"])}
                             for w in data.wahl if int(w.get("anzahl") or 0) > 0]
    _, auf = _fuellteile_laden(db, projekt, material, plan.fuellteile)
    auf_ids = {t.id for t, _ in auf}
    kerf = plan.kerf
    offen = []
    for b in plan.bretter:
        if b.verbraucht or any(st.gesaegt for st in b.stuecke):
            continue
        # Bisherige Auffüll-Teile herunternehmen, Rest wie vor dem Auffüllen
        ohne = [st for st in b.stuecke if not (st.ist_fuellteil and st.teil_id in auf_ids)]
        if len(ohne) != len(b.stuecke) and ohne:
            b.stuecke = ohne
            genutzt = sum(st.laenge for st in ohne)
            b.verschnitt_mm = max(0.0, b.lager_laenge - genutzt - kerf * (len(ohne) - 1))
            b.verschnitt_prozent = round(b.verschnitt_mm / b.lager_laenge * 100, 1)
            rest = b.lager_laenge - (max(st.x + st.laenge for st in ohne) + kerf)
            b.reste = [[rest]] if rest > 0 else []
        offen.append(b)
    plan.fuell_vorschlaege = (_reste_auffuellen_1d(offen, auf, kerf, material,
                                                   plan.fuell_alle_reste, wahl,
                                                   plan.max_pro_stange)
                              if auf else [])
    gruppen = {g["gruppe"] for g in plan.fuell_vorschlaege}
    plan.fuell_wahl = {k: v for k, v in wahl.items() if k in gruppen}
    return _plan_to_out(db.save_plan(plan))


# ---------------------------------------------------------------------------
# Sammelplan: ein Material, mehrere Projekte gemeinsam optimieren
# ---------------------------------------------------------------------------


class SammelKandidatOut(BaseModel):
    projekt_id: int
    name: str
    offen: int              # Stück, die in den Sammelplan dürfen
    bedarf: float           # deren Gesamtlänge (mm) bzw. -fläche (mm²)
    gesperrt: int = 0       # Stück, die ungesägt in einem anderen Plan liegen
    einzelplan: str = ""    # "" | "offen" (nicht angefangen) | "angefangen"
    mitglied: bool = False


class SammelOut(BaseModel):
    sammel_id: int = 0      # 0 = noch kein Sammelplan für dieses Material
    name: str = ""
    kandidaten: list[SammelKandidatOut] = []


class SammelRequest(BaseModel):
    material_id: int
    projekt_ids: list[int]
    blade_id: int
    algorithm: str = "greedy"
    reste_zuerst: bool = False


class VergleichOut(BaseModel):
    getrennt_bretter: int
    gemeinsam_bretter: int
    getrennt_menge: float    # verbrauchte Lagerlänge (mm) bzw. -fläche (mm²)
    gemeinsam_menge: float
    fehlende_getrennt: int
    fehlende_gemeinsam: int
    getrennt_reste: int = 0      # davon Reststücke (bei „Reste zuerst“ gewollt viele)
    gemeinsam_reste: int = 0


def _offener_einzelplan(db: Database, projekt_id: int, material_id: int
                        ) -> GespeicherterPlan | None:
    """Nicht angefangener Einzelplan – den ersetzt der Sammelplan."""
    plan = db.get_plan(projekt_id, material_id)
    return plan if plan and not any(b.verbraucht for b in plan.bretter) else None


def _sammel_teile(db: Database, material: Material, projekt_ids: list[int],
                  ausser_projekt: int, schon_geplant: dict[int, int] | None = None
                  ) -> tuple[list[Teil], dict[int, int]]:
    """Offene Teile der Projekte für den Sammelplan, umbenannt in „Label → Projekt“.

    Teilgenaue Sperre: Was ungesägt in einem anderen Plan liegt, bleibt dort –
    außer im nicht angefangenen Einzelplan des Projekts, den der Sammelplan ersetzt.
    """
    anderswo = db.ungesaegt_in_plaenen(material.id, ausser_projekt=ausser_projekt)
    schon_geplant = schon_geplant or {}
    teile, offen = [], {}
    for pid in projekt_ids:
        pr = db.get_projekt(pid)
        if not pr or pr.art in ("sammel", "vorlage"):
            continue
        einzel = _offener_einzelplan(db, pid, material.id)
        eigene = _schon_geplant(einzel.bretter) if einzel else {}
        for t in pr.teile:
            if t.material_id != material.id:
                continue
            gesperrt = anderswo.get(t.id, 0) - eigene.get(t.id, 0)
            n = t.offen_anzahl - gesperrt - schon_geplant.get(t.id, 0)
            if n > 0:
                teile.append(replace(t, label=f"{t.label} → {pr.name}"))
                offen[t.id] = n
    return teile, offen


def _verbrauch(erg: OptimierungsErgebnis, is_1d: bool) -> float:
    return sum(sp.lager_laenge if is_1d else sp.lager_laenge * sp.lager_breite
               for sp in erg.schnittplaene)


@app.get("/api/sammel/{mid}", response_model=SammelOut)
def get_sammel(mid: int):
    """Sammelplan-Status eines Materials und alle Projekte, die mitmachen können."""
    db = get_db()
    material = db.get_material(mid)
    if not material:
        raise HTTPException(404, "Material not found")
    is_1d = material.typ == MaterialTyp.STANGE
    sammel = db.get_sammel(mid)
    sammel_id = sammel.id if sammel else 0
    mitglieder = set(db.sammel_mitglieder(sammel_id)) if sammel else set()
    # Gesperrt = ungesägt in Plänen außer dem Sammelplan und dem eigenen, nicht
    # angefangenen Einzelplan (den verwirft das Optimieren)
    anderswo = db.ungesaegt_in_plaenen(mid, ausser_projekt=sammel_id)
    kandidaten = []
    for pr in db.list_projekte():
        teile = [t for t in pr.teile if t.material_id == mid]
        if not teile:
            continue
        einzel = db.get_plan(pr.id, mid)
        angefangen = bool(einzel and any(b.verbraucht for b in einzel.bretter))
        eigene = _schon_geplant(einzel.bretter) if einzel and not angefangen else {}
        offen, bedarf, gesperrt = 0, 0.0, 0
        for t in teile:
            gesp = anderswo.get(t.id, 0) - eigene.get(t.id, 0)
            n = max(0, t.offen_anzahl - gesp)
            gesperrt += min(gesp, t.offen_anzahl)
            offen += n
            bedarf += n * (t.laenge if is_1d else t.laenge * t.breite)
        if offen == 0 and gesperrt == 0 and pr.id not in mitglieder:
            continue
        kandidaten.append(SammelKandidatOut(
            projekt_id=pr.id, name=pr.name, offen=offen, bedarf=bedarf, gesperrt=gesperrt,
            einzelplan="angefangen" if angefangen else ("offen" if einzel else ""),
            mitglied=pr.id in mitglieder))
    return SammelOut(sammel_id=sammel_id, name=sammel.name if sammel else "",
                     kandidaten=kandidaten)


class SammelCreateIn(BaseModel):
    material: str                      # ID oder Kürzel
    projekte: list[str] = Field(min_length=1)   # IDs oder Namen
    name: str = ""                     # leer = „Sammelplan <Material>“


class SammelMembersIn(BaseModel):
    projekte: list[str] = Field(min_length=1)   # IDs oder Namen


def _mitglieder_ref(db: Database, refs: list[str]) -> list[int]:
    """Projekt-IDs zu IDs/Namen; nur normale Projekte und Schnittlisten."""
    ids = []
    for ref in refs:
        pr = db.projekt_finden(ref)
        if not pr or pr.art in ("sammel", "vorlage"):
            raise _fehler(404, "projekt_unbekannt", f"Project {ref} not found")
        if pr.id not in ids:
            ids.append(pr.id)
    return ids


@app.post("/api/sammel", response_model=ProjectOut, status_code=201)
def create_sammel(data: SammelCreateIn):
    """Sammelplan anlegen (noch ohne Schnittplan – gerechnet wird mit /api/sammel/optimize).

    Je Material gibt es höchstens einen; ist schon einer da, kommt 409 mit seiner ID.
    """
    db = get_db()
    material = _material_ref(db, data.material)
    if alt := db.get_sammel(material.id):
        raise _fehler(409, "sammel_vorhanden",
                      f"“{material.name}” already has a combined plan", sammel_id=alt.id)
    ids = _mitglieder_ref(db, data.projekte)
    sammel = db.sammel_anlegen(material.id, data.name.strip() or f"Sammelplan {material.name}")
    db.sammel_mitglieder_setzen(sammel.id, ids)
    return _projekt_to_out(db.get_projekt(sammel.id))


@app.post("/api/sammel/{material}/restart", response_model=ProjectOut)
def restart_sammel(material: str):
    """Sammelplan noch einmal sägen: In allen Mitglieds-Projekten geht der Fortschritt
    der Teile dieses Materials auf 0, der Sammelplan und die Einzelpläne der Mitglieder
    für dieses Material werden gelöscht. Andere Materialien und das Lager bleiben."""
    db = get_db()
    mat = _material_ref(db, material)
    sammel = db.get_sammel(mat.id)
    if not sammel:
        raise _fehler(404, "sammel_unbekannt", f"“{mat.name}” has no combined plan")
    db.sammel_neu_starten(sammel.id, mat.id)
    return _projekt_to_out(db.get_projekt(sammel.id))


@app.put("/api/sammel/{material}/members", response_model=ProjectOut)
def set_sammel_members(material: str, data: SammelMembersIn):
    """Mitglieder des Sammelplans eines Materials (ID oder Kürzel) ersetzen.

    Ein schon berechneter Plan bleibt stehen und gilt danach als veraltet."""
    db = get_db()
    mat = _material_ref(db, material)
    sammel = db.get_sammel(mat.id)
    if not sammel:
        raise _fehler(404, "sammel_unbekannt", f"“{mat.name}” has no combined plan")
    db.sammel_mitglieder_setzen(sammel.id, _mitglieder_ref(db, data.projekte))
    return _projekt_to_out(db.get_projekt(sammel.id))


@app.post("/api/sammel/optimize", response_model=OptimizeResult)
def optimize_sammel(req: SammelRequest):
    """Sammelplan anlegen bzw. ersetzen und berechnen.

    Nicht angefangene Einzelpläne der Mitglieder für dieses Material werden verworfen,
    angefangene bleiben (ihre ungesägten Teile sind gesperrt). Ist der bisherige
    Sammelplan fertig gesägt, beginnt ein neuer; sonst bleiben angefangene Bretter.
    """
    db = get_db()
    material = db.get_material(req.material_id)
    if not material:
        raise HTTPException(404, "Material not found")
    blade = next((b for b in db.list_saegeblaetter() if b.id == req.blade_id), None)
    if not blade:
        raise HTTPException(404, "Saw blade not found")
    projekt_ids = [pid for pid in dict.fromkeys(req.projekt_ids)
                   if (pr := db.get_projekt(pid)) and pr.art not in ("sammel", "vorlage")]
    if not projekt_ids:
        raise HTTPException(400, "No projects selected")

    _saegeblatt_merken(db, material, blade)
    is_1d = material.typ == MaterialTyp.STANGE
    sammel = db.get_sammel(material.id) or db.sammel_anlegen(
        material.id, f"Sammelplan {material.name}")

    # Erst prüfen, ob es etwas zu sägen gibt – vorher nichts verwerfen. Ein fertig
    # gesägter Plan bleibt sonst stehen (früher war er danach weg).
    alt = db.get_plan(sammel.id, material.id)
    alt_fertig = bool(alt) and all(st.gesaegt for b in alt.bretter for st in b.stuecke)
    behalten = [] if alt_fertig else _angefangene_bretter(alt, is_1d)
    teile, offen = _sammel_teile(db, material, projekt_ids, sammel.id,
                                 _schon_geplant(behalten))
    if not teile and not behalten:
        raise _fehler(400, "sammel_nichts_offen",
                      "Nothing is open in this material in the member projects; "
                      "restart the combined plan first")

    for pid in projekt_ids:
        if einzel := _offener_einzelplan(db, pid, material.id):
            db.delete_plan(einzel.id)
    if alt_fertig:
        db.delete_plan(alt.id)
    db.sammel_mitglieder_setzen(sammel.id, projekt_ids)
    sammel = db.get_projekt(sammel.id)
    if not teile:
        return _plan_speichern(sammel, material, blade, req.algorithm, behalten, [], [])

    kerf = blade.schnittbreite
    lage = _lagerlage(db, material.id, ausser_projekt=sammel.id)
    ergebnis = _berechnen(material, kerf, req.algorithm, req.reste_zuerst, teile,
                          dict(offen), lage)
    neue = _ergebnis_to_bretter(ergebnis, lage.defekte_map, teile, offen)
    bedarf = []
    zu_lang = _zu_lange_teile(ergebnis.fehlende_teile, teile, lage.vorrat_alle, material)
    if ergebnis.fehlende_teile:
        bedarf = [m.model_dump() for m in _berechne_materialbedarf(
            ergebnis.fehlende_teile, teile, lage.vorrat_alle, material, kerf)]
    return _plan_speichern(sammel, material, blade, req.algorithm, behalten + neue,
                           ergebnis.fehlende_teile, bedarf, zu_lang=zu_lang)


@app.post("/api/sammel/compare", response_model=VergleichOut)
def compare_sammel(req: SammelRequest):
    """Was spart der Sammelplan? Jedes Projekt einzeln gegen alle gemeinsam rechnen.

    Nichts wird gespeichert. Getrennt wird nacheinander gerechnet: Jedes Projekt
    bekommt nur das Lager, das die vorigen übrig lassen – wie echte Einzelpläne,
    die sich das Lager teilen (sonst zählten z. B. dieselben Reste mehrfach).
    """
    db = get_db()
    material = db.get_material(req.material_id)
    if not material:
        raise HTTPException(404, "Material not found")
    blade = next((b for b in db.list_saegeblaetter() if b.id == req.blade_id), None)
    if not blade:
        raise HTTPException(404, "Saw blade not found")
    is_1d = material.typ == MaterialTyp.STANGE
    sammel = db.get_sammel(material.id)
    ausser = sammel.id if sammel else 0
    # Nicht angefangene Einzelpläne verschwinden mit dem Sammelplan → ihr Lager zählt mit
    ersetzt = tuple(pid for pid in req.projekt_ids
                    if _offener_einzelplan(db, pid, material.id))
    lage = _lagerlage(db, material.id, ausser_projekt=ausser, auch_ausser=ersetzt)
    kerf = blade.schnittbreite

    def rechne(pids: list[int], lage: _Lagerlage) -> OptimierungsErgebnis:
        teile, offen = _sammel_teile(db, material, pids, ausser)
        if not teile:
            return OptimierungsErgebnis()
        return _berechnen(material, kerf, req.algorithm, req.reste_zuerst, teile, offen, lage)

    getrennt = []
    rest_lage = lage
    for pid in req.projekt_ids:
        getrennt.append(rechne([pid], rest_lage))
        rest_lage = _lage_ohne(rest_lage, getrennt[-1])
    gemeinsam = rechne(req.projekt_ids, lage)
    rest_ids = {ls.id for ls in lage.vorrat_alle if ls.ist_rest}

    def reste(erg: OptimierungsErgebnis) -> int:
        return sum(1 for sp in erg.schnittplaene if sp.lagerstueck_id in rest_ids)

    return VergleichOut(
        getrennt_bretter=sum(len(e.schnittplaene) for e in getrennt),
        gemeinsam_bretter=len(gemeinsam.schnittplaene),
        getrennt_menge=sum(_verbrauch(e, is_1d) for e in getrennt),
        gemeinsam_menge=_verbrauch(gemeinsam, is_1d),
        fehlende_getrennt=sum(len(e.fehlende_teile) for e in getrennt),
        fehlende_gemeinsam=len(gemeinsam.fehlende_teile),
        getrennt_reste=sum(reste(e) for e in getrennt),
        gemeinsam_reste=reste(gemeinsam),
    )


# ---------------------------------------------------------------------------
# Gespeicherte Schnittpläne
# ---------------------------------------------------------------------------


def _fehlende_mengen(labels: list[str], teile: list[Teil], mengen: dict[int, int]
                     ) -> dict[int, int]:
    """Nicht platzierte Labels wieder auf Teile (IDs) verteilen."""
    noch: dict[int, int] = {}
    for label in labels:
        t = next((t for t in teile if t.label == label
                  and noch.get(t.id, 0) < mengen.get(t.id, 0)), None)
        if t:
            noch[t.id] = noch.get(t.id, 0) + 1
    return noch


def _angefangene_bretter(alt: GespeicherterPlan | None, is_1d: bool) -> list[PlanBrett]:
    """Bretter des alten Plans, die beim Neuberechnen erhalten bleiben."""
    if not alt:
        return []
    behalten = []
    for b in alt.bretter:
        if not b.verbraucht:
            continue
        if is_1d:
            # Rest der Stange ist schon im Lager → nur das Gesägte bleibt im Plan
            b.stuecke = [st for st in b.stuecke if st.gesaegt]
            genutzt = sum(st.laenge for st in b.stuecke)
            b.verschnitt_mm = max(0.0, b.lager_laenge - genutzt)
            b.verschnitt_prozent = (b.verschnitt_mm / b.lager_laenge * 100
                                    if b.lager_laenge else 0.0)
        b.id = None
        for st in b.stuecke:
            st.id = None
        behalten.append(b)
    return behalten


def _ergebnis_to_bretter(erg: OptimierungsErgebnis, defekte_map, teile,
                         offen: dict[int, int]) -> list[PlanBrett]:
    """Optimierungsergebnis in Plan-Bretter umwandeln, Teile per ID zuordnen.

    Der Optimizer kennt nur Labels. Bei mehrfach vergebenen Labels werden die
    Platzierungen der Reihe nach auf die Teile verteilt (je bis zu ihrer offenen Anzahl).
    """
    rest = {t.id: offen[t.id] for t in teile}
    nach_label: dict[str, list[Teil]] = {}
    for t in teile:
        nach_label.setdefault(t.label, []).append(t)

    def teil_id(label: str) -> int | None:
        kandidaten = nach_label.get(label, [])
        for t in kandidaten:
            if rest[t.id] > 0:
                rest[t.id] -= 1
                return t.id
        return kandidaten[0].id if kandidaten else None

    bretter = []
    for sp in erg.schnittplaene:
        defs = (defekte_map or {}).get(sp.lagerstueck_id, {}).get(sp.stueck_nr, [])
        bretter.append(PlanBrett(
            lagerstueck_id=sp.lagerstueck_id, stueck_nr=sp.stueck_nr,
            lager_laenge=sp.lager_laenge, lager_breite=sp.lager_breite,
            reste=[list(r) for r in sp.reste],
            defekte=[{"position": d.position, "position_y": d.position_y,
                      "laenge": d.laenge, "breite": d.breite} for d in defs],
            verschnitt_mm=sp.verschnitt_mm, verschnitt_prozent=sp.verschnitt_prozent,
            stuecke=[PlanStueck(teil_id=teil_id(p.teil_label), teil_label=p.teil_label,
                                laenge=p.laenge, breite=p.breite, x=p.x, y=p.y,
                                gedreht=p.gedreht)
                     for p in sp.platzierungen],
        ))
    return bretter


def _plan_teile(projekt: Projekt, material_id: int) -> list[Teil]:
    """Teile, für die ein Plan gilt – beim Sammelplan die aller Mitglieder."""
    if projekt.art != "sammel":
        return [t for t in projekt.teile if t.material_id == material_id]
    db = get_db()
    return [t for pid in db.sammel_mitglieder(projekt.id)
            if (pr := db.get_projekt(pid)) for t in pr.teile if t.material_id == material_id]


def _eingabe_hash(projekt: Projekt, material: Material, kerf: float) -> str:
    """Fingerabdruck der Eingaben, die sich NICHT durchs Sägen ändern.

    Fortschritt (gesaegt_anzahl) und Lager gehören bewusst nicht dazu.
    """
    import hashlib
    import json
    teile = sorted((t.id, t.laenge, t.breite, t.maserung.value, t.gesamt_anzahl)
                   for t in _plan_teile(projekt, material.id))
    raw = json.dumps([teile, material.besaeumung, material.maserung.value, kerf])
    return hashlib.sha1(raw.encode()).hexdigest()


def _plan_speichern(projekt, material, blade, algorithmus, bretter, fehlende, bedarf,
                    fuellteile=(), fuell_alle_reste=False, max_pro_stange=0,
                    fuell_wahl=None, fuell_vorschlaege=(), zu_lang=()) -> OptimizeResult:
    db = get_db()
    plan = GespeicherterPlan(
        projekt_id=projekt.id, material_id=material.id, saegeblatt_id=blade.id,
        kerf=blade.schnittbreite, algorithmus=algorithmus,
        eingabe_hash=_eingabe_hash(projekt, material, blade.schnittbreite),
        fehlende_teile=list(fehlende), materialbedarf=list(bedarf), bretter=bretter,
        fuellteile=list(fuellteile), fuell_alle_reste=bool(fuell_alle_reste),
        max_pro_stange=int(max_pro_stange or 0), fuell_vorschlaege=list(fuell_vorschlaege),
        zu_lang=list(zu_lang),
    )
    # Nur Wahlen für Gruppen, die es im neuen Plan gibt
    gruppen = {g["gruppe"] for g in plan.fuell_vorschlaege}
    plan.fuell_wahl = {k: v for k, v in (fuell_wahl or {}).items() if k in gruppen}
    return _plan_to_out(db.save_plan(plan))


def _reste_auffuellen(bretter: list[PlanBrett], auffuellen: list[tuple[Teil, int]],
                      kerf: float, material: Material, alle_reste: bool,
                      wahl: dict | None = None, max_pro_stange: int = 0) -> list[dict]:
    """Durchgang 2: Reste mit Füllteilen belegen. Liefert bei Stangen die Vorschläge."""
    if material.typ != MaterialTyp.STANGE:
        _reste_auffuellen_2d(bretter, auffuellen, kerf, material, alle_reste)
        return []
    return _reste_auffuellen_1d(bretter, auffuellen, kerf, material, alle_reste, wahl,
                                max_pro_stange)


def _reste_auffuellen_2d(bretter: list[PlanBrett], auffuellen: list[tuple[Teil, int]],
                         kerf: float, material: Material, alle_reste: bool):
    """Freie Flächen der Platten mit Füllteilen belegen (Durchgang 2).

    Wie bei Stangen standardmäßig nur Abfall: Flächen, die beim Einbuchen nicht ins
    Lager kämen (kleiner als das Mindest-Restmaß). Ohne Mindest-Restmaß ist jede
    freie Fläche auffüllbar. Platten mit Defekten bleiben außen vor.
    """
    min_l, min_b = material.rest_min_laenge, material.rest_min_breite
    ohne_min = min_l <= 0 and min_b <= 0

    def abfall(fr) -> bool:
        return fr.laenge < min_l or fr.breite < min_b

    kandidaten_bretter, flaechen = [], []
    for b in bretter:
        if b.defekte or not b.stuecke:
            continue
        frei = freie_rechtecke_2d([(st.x, st.y, st.laenge, st.breite) for st in b.stuecke],
                                  b.lager_laenge, b.lager_breite, kerf)
        frei = [fr for fr in frei if alle_reste or ohne_min or abfall(fr)]
        if frei:
            kandidaten_bretter.append(b)
            flaechen.append(frei)
    if not kandidaten_bretter:
        return
    nach_id = {t.id: t for t, _ in auffuellen}
    kandidaten = []
    for t, m in auffuellen:
        normal_ok, gedreht_ok = drehung_fuer_teil(material.maserung, t.maserung)
        kandidaten.append((t.id, t.laenge, t.breite, m if m > 0 else 10 ** 6,
                           normal_ok, gedreht_ok))
    for pi, tid, pl in fuelle_reste_2d(flaechen, kandidaten, kerf):
        t = nach_id[tid]
        kandidaten_bretter[pi].stuecke.append(PlanStueck(
            teil_id=tid, teil_label=t.label, laenge=pl.laenge, breite=pl.breite,
            x=pl.x, y=pl.y, gedreht=pl.gedreht, ist_fuellteil=True))
    for b in kandidaten_bretter:
        flaeche = b.lager_laenge * b.lager_breite
        b.verschnitt_mm = max(0.0, flaeche - sum(st.laenge * st.breite for st in b.stuecke))
        b.verschnitt_prozent = round(b.verschnitt_mm / flaeche * 100, 1) if flaeche else 0
        b.reste = [[fr.laenge, fr.breite] for fr in freie_rechtecke_2d(
            [(st.x, st.y, st.laenge, st.breite) for st in b.stuecke],
            b.lager_laenge, b.lager_breite, kerf)]


def _reste_auffuellen_1d(bretter: list[PlanBrett], auffuellen: list[tuple[Teil, int]],
                         kerf: float, material: Material, alle_reste: bool,
                         wahl: dict | None = None, max_pro_stange: int = 0) -> list[dict]:
    """Den Rest am Ende jeder Stange mit Füllteilen belegen (Durchgang 2).

    Standard: nur echter Abfall, also Reste unter dem Mindest-Restmaß. Hat das
    Material kein Mindest-Restmaß, gilt jeder Rest als auffüllbar. Stangen, die
    "Max. je Stange" voll ausschöpfen, sind immer auffüllbar – dafür ist der
    Platz frei geblieben. Stangen mit Defekten bleiben außen vor (ihre freien
    Stücke liegen nicht am Ende).

    Stangen mit gleichem Rest bilden eine Gruppe (Schlüssel: Rest auf 0,1 mm).
    Je Gruppe gibt es Vorschläge (mit den Mengen vor ihrer ersten Stange).
    `wahl` legt je Gruppe eine Füllung fest ({gruppe: [{teil_id, anzahl}]}, [] =
    nichts); reicht die Menge für eine Stange nicht mehr, füllt dort die Automatik.
    Teile mit Mengenangabe werden bevorzugt (siehe fuelle_rest_1d).
    Liefert die Gruppen: [{gruppe, rest, stangen, vorschlaege: [{teile, rest}],
    gewaehlt (Index, -1 = nichts), manuell, automatisch (Stangen ohne die Wahl)}].
    """
    wahl = wahl or {}
    rest_min = material.rest_min_laenge
    vorrat = {t.id: (m if m > 0 else 10 ** 6) for t, m in auffuellen}
    bevorzugt = {t.id: m > 0 for t, m in auffuellen}
    nach_id = {t.id: t for t, _ in auffuellen}
    gruppen: dict[str, dict] = {}

    def teile_liste(anzahl: dict[int, int]) -> list[dict]:
        return [{"teil_id": tid, "label": nach_id[tid].label,
                 "laenge": nach_id[tid].laenge, "anzahl": n}
                for tid, n in sorted(anzahl.items(), key=lambda e: -nach_id[e[0]].laenge)]

    for b in bretter:
        if b.defekte or not b.stuecke:
            continue
        ende = max(st.x + st.laenge for st in b.stuecke)
        start = ende + kerf
        rest = b.lager_laenge - start
        am_limit = max_pro_stange > 0 and len(b.stuecke) >= max_pro_stange
        if rest <= 0 or not (alle_reste or am_limit or rest_min <= 0 or rest < rest_min):
            continue
        kandidaten = [(tid, nach_id[tid].laenge, n, bevorzugt[tid])
                      for tid, n in vorrat.items() if n > 0]
        key = f"{rest:.1f}"
        g = gruppen.get(key)
        if g is None:
            vorschlaege = fuell_vorschlaege_1d(rest, kerf, kandidaten, knoten=20_000)
            if not vorschlaege:
                continue   # hier passt kein Füllteil hinein
            g = gruppen[key] = {
                "gruppe": key, "rest": round(rest, 1), "stangen": 0,
                "vorschlaege": [{"teile": teile_liste(a), "rest": round(r, 1)}
                                for a, r in vorschlaege],
                "gewaehlt": None, "manuell": key in wahl, "automatisch": 0}
        g["stangen"] += 1

        gewaehlt = None
        if key in wahl:
            soll = {int(w["teil_id"]): int(w["anzahl"]) for w in wahl[key]}
            belegt = sum((nach_id[tid].laenge + kerf) * n
                         for tid, n in soll.items() if tid in nach_id)
            if (all(tid in nach_id and vorrat[tid] >= n for tid, n in soll.items())
                    and belegt <= rest + kerf + 1e-6):
                gewaehlt = [tid for tid, n in soll.items() for _ in range(n)]
                gewaehlt.sort(key=lambda tid: -nach_id[tid].laenge)
            else:
                g["automatisch"] += 1
        if gewaehlt is None:
            gewaehlt = fuelle_rest_1d(rest, kerf, kandidaten)

        if g["stangen"] == 1:
            anzahl: dict[int, int] = {}
            for tid in gewaehlt:
                anzahl[tid] = anzahl.get(tid, 0) + 1
            liste = teile_liste(anzahl)
            if not liste:
                g["gewaehlt"] = -1
            else:
                idx = next((i for i, v in enumerate(g["vorschlaege"]) if v["teile"] == liste), None)
                if idx is None:   # z.B. Automatik außerhalb der Liste → vorne dazu
                    belegt = sum((it["laenge"] + kerf) * it["anzahl"] for it in liste)
                    g["vorschlaege"].insert(0, {"teile": liste,
                                                "rest": round(max(0.0, rest - belegt), 1)})
                    idx = 0
                g["gewaehlt"] = idx

        pos = start
        for tid in gewaehlt:
            t = nach_id[tid]
            b.stuecke.append(PlanStueck(teil_id=tid, teil_label=t.label, laenge=t.laenge,
                                        x=pos, ist_fuellteil=True))
            pos += t.laenge + kerf
            vorrat[tid] -= 1
        genutzt = sum(st.laenge for st in b.stuecke)
        b.verschnitt_mm = max(0.0, b.lager_laenge - genutzt - kerf * (len(b.stuecke) - 1))
        b.verschnitt_prozent = round(b.verschnitt_mm / b.lager_laenge * 100, 1)
        rest_neu = b.lager_laenge - (max(st.x + st.laenge for st in b.stuecke) + kerf)
        b.reste = [[rest_neu]] if rest_neu > 0 else []
    return list(gruppen.values())


def _plan_ueberplant(db: Database, plan: GespeicherterPlan) -> bool:
    """Liegen mehr ungesägte Stücke eines Teils im Plan, als noch offen sind?
    Passiert, wenn das Teil inzwischen anderswo gesägt wurde (Sägeauftrag, Füllteil)."""
    ungesaegt: dict[int, int] = {}
    for b in plan.bretter:
        for st in b.stuecke:
            if st.teil_id and not st.gesaegt and not st.ist_fuellteil:
                ungesaegt[st.teil_id] = ungesaegt.get(st.teil_id, 0) + 1
    for tid, n in ungesaegt.items():
        t = db.get_teil(tid)
        if t and n > t.offen_anzahl:
            return True
    return False


def _veraltet_grund(db: Database, plan: GespeicherterPlan, projekt: Projekt | None,
                    material: Material | None) -> str:
    """Warum der Plan nicht mehr passt: "teile", "anderswo" oder "" (passt)."""
    if (projekt is None or material is None
            or _eingabe_hash(projekt, material, plan.kerf) != plan.eingabe_hash):
        return "teile"
    return "anderswo" if _plan_ueberplant(db, plan) else ""


def _plan_to_out(plan: GespeicherterPlan) -> OptimizeResult:
    db = get_db()
    material = db.get_material(plan.material_id)
    projekt = db.get_projekt(plan.projekt_id)
    is_1d = material is not None and material.typ == MaterialTyp.STANGE

    # Noch nicht angefangene Bretter: gibt es genau diese Stücke noch im Lager?
    nrs_map = db.einzelstueck_nrs_for_material(plan.material_id)
    kuerzel = material.kuerzel if material else ""
    lager_fehlt = False
    fehlende_stuecke: list[str] = []
    for b in plan.bretter:
        if b.verbraucht:
            continue
        nrs = nrs_map.get(b.lagerstueck_id)
        if not nrs or (b.stueck_nr and b.stueck_nr not in nrs):
            lager_fehlt = True
            if b.stueck_nr:
                fehlende_stuecke.append(stueck_code(kuerzel, b.stueck_nr))

    mat_ort = material.lagerort if material else ""
    reste_ort = (material.lagerort_reste or mat_ort) if material else ""

    def stueck_ort(lagerstueck_id: int, nr: int) -> str:
        ls = db.get_lagerstueck(lagerstueck_id)
        return reste_ort if ls and ls.ist_rest else mat_ort

    def brett_ort(b: PlanBrett) -> str:
        if b.verbraucht:
            return reste_ort if (b.verbrauchtes_stueck or {}).get("ist_rest") else mat_ort
        return stueck_ort(b.lagerstueck_id, b.stueck_nr)

    def reste(b: PlanBrett) -> list[RestStueckOut]:
        out = []
        for lid, nr in b.rest_ids:
            ls = db.get_lagerstueck(lid)
            if ls and nr:
                out.append(RestStueckOut(code=stueck_code(kuerzel, nr), laenge=ls.laenge,
                                         breite=ls.breite, lagerort=stueck_ort(lid, nr)))
        return out

    rest_zeilen = {ls.id for ls in db.list_lagerstuecke(plan.material_id) if ls.ist_rest}

    gesamt, genutzt = 0.0, 0.0
    for b in plan.bretter:
        if is_1d:
            gesamt += b.lager_laenge
            genutzt += sum(st.laenge for st in b.stuecke)
        else:
            gesamt += b.lager_laenge * b.lager_breite
            genutzt += sum(st.laenge * st.breite for st in b.stuecke)

    return OptimizeResult(
        schnittplaene=[
            SchnittplanOut(
                id=b.id, lagerstueck_id=b.lagerstueck_id, lager_laenge=b.lager_laenge,
                lager_breite=b.lager_breite, stueck_nr=b.stueck_nr,
                platzierungen=[
                    PlatzierungOut(id=st.id, teil_label=st.teil_label, laenge=st.laenge,
                                   breite=st.breite, x=st.x, y=st.y, gedreht=st.gedreht,
                                   gesaegt=st.gesaegt, ist_fuellteil=st.ist_fuellteil)
                    for st in b.stuecke],
                reste=b.reste, verschnitt_mm=b.verschnitt_mm,
                verschnitt_prozent=b.verschnitt_prozent,
                defekte=[DefectOut(id=0, einzelstueck_id=0, stueck_nr=b.stueck_nr,
                                   position=d.get("position", 0),
                                   position_y=d.get("position_y", 0),
                                   laenge=d.get("laenge", 0), breite=d.get("breite", 0))
                         for d in b.defekte],
                verbraucht=b.verbraucht,
                stueck_code=stueck_code(kuerzel, b.stueck_nr),
                lagerort=brett_ort(b),
                # Verbrauchte Lagerzeilen sind evtl. gelöscht → Schnappschuss fragen
                ist_rest=(b.lagerstueck_id in rest_zeilen
                          or bool((b.verbrauchtes_stueck or {}).get("ist_rest"))),
                reste_stuecke=reste(b),
                reste_ziel=[_rest_ziel(material, r[0], r[1] if len(r) > 1 else 0.0)
                            if material and r else "weg" for r in b.reste],
            )
            for b in plan.bretter],
        fehlende_teile=plan.fehlende_teile,
        gesamt_verschnitt_prozent=round((1 - genutzt / gesamt) * 100, 1) if gesamt else 0.0,
        materialbedarf=[MaterialBedarfOut(**m) for m in plan.materialbedarf],
        zu_lang=plan.zu_lang,
        plan_id=plan.id, projekt_id=plan.projekt_id, material_id=plan.material_id,
        saegeblatt_id=plan.saegeblatt_id, algorithmus=plan.algorithmus,
        erstellt=plan.erstellt, version=plan.version,
        veraltet=bool(grund := _veraltet_grund(db, plan, projekt, material)),
        veraltet_grund=grund,
        lager_fehlt=lager_fehlt,
        fehlende_stuecke=fehlende_stuecke,
        fuellteile=plan.fuellteile,
        fuell_alle_reste=plan.fuell_alle_reste,
        max_pro_stange=plan.max_pro_stange,
        fuell_vorschlaege=plan.fuell_vorschlaege,
        vorrat_verfuegbar=[
            {"teil_id": t.id, "label": t.label, "anzahl": min(t.vorrat, t.offen_anzahl)}
            for t in (projekt.teile if projekt else [])
            if t.material_id == plan.material_id and t.vorrat > 0 and t.offen_anzahl > 0],
    )


def _brett_abgleichen(db: Database, plan: GespeicherterPlan, brett: PlanBrett,
                      is_1d: bool):
    """Lagerbestand eines Bretts an seine gesägten Stücke anpassen (Zustand in der DB)."""
    marked = [st for st in brett.stuecke if st.gesaegt]
    res = _mark_plan_core(db, MarkPlanRequest(
        material_id=plan.material_id, lagerstueck_id=brett.lagerstueck_id,
        is_1d=is_1d, lager_laenge=brett.lager_laenge, lager_breite=brett.lager_breite,
        kerf=plan.kerf, marked_laengen=[st.laenge for st in marked],
        marked_x=[st.x for st in marked],
        defekte=[[d.get("position", 0), d.get("laenge", 0)] for d in brett.defekte]
        if is_1d else [],
        total_pieces=len(brett.stuecke), reste=brett.reste,
        prev_consumed=brett.verbraucht,
        prev_rest_ids=[r[0] for r in brett.rest_ids],
        prev_rest_nrs=[r[1] for r in brett.rest_ids],
        stueck_nr=brett.stueck_nr, prev_consumed_piece=brett.verbrauchtes_stueck,
        prev_abfall=brett.abfall,
    ))
    alte_id = brett.lagerstueck_id
    brett.verbraucht = res["consumed"]
    brett.rest_ids = [[rid, nr] for rid, nr in zip(res["rest_ids"], res["rest_nrs"])]
    brett.lagerstueck_id = res["lagerstueck_id"]
    brett.verbrauchtes_stueck = res["consumed_piece"]
    brett.abfall = res["abfall"]
    db.save_brett_zustand(brett)
    if brett.lagerstueck_id != alte_id:
        # Zurückgebucht in eine neue Lagerzeile: unbenutzte Bretter aller Pläne mitziehen
        db.conn.execute(
            """UPDATE schnittplan_brett SET lagerstueck_id=?
               WHERE lagerstueck_id=? AND verbraucht=0""",
            (brett.lagerstueck_id, alte_id))
        db.conn.commit()


# ---------------------------------------------------------------------------
# Arbeitsliste der Optimierung: was gibt es zu sägen, und wie weit ist es?
# ---------------------------------------------------------------------------

# Reihenfolge für den Gesamtstatus eines Eintrags (wichtigstes zuerst)
_STATUS_RANG = ["veraltet", "in_arbeit", "bereit", "kein_plan", "verplant", "sammel", "fertig"]


class WorkProjectRef(BaseModel):
    projekt_id: int
    name: str


class WorklistLineOut(BaseModel):
    material_id: int
    material: str
    typ: str
    teile: int = 0        # Teile mit offener Menge
    offen: int = 0        # Stück noch zu sägen
    # kein_plan | bereit | in_arbeit | veraltet | fertig | sammel (im Sammelplan)
    # | verplant (alles offene steckt in Sägeaufträgen/anderen Plänen)
    status: str
    veraltet_grund: str = ""
    plan_id: int = 0
    gesamt: int = 0       # Stücke im Plan
    gesaegt: int = 0
    sammelplan_id: int = 0
    sammelplan: str = ""
    # Andere Projekte, die dieses Material auch brauchen (Vorschlag Sammelplan)
    auch_in: list[WorkProjectRef] = []
    # Status „verplant“: die Sägeaufträge, in denen die offenen Teile stecken
    auftraege: list[WorkProjectRef] = []


class WorklistEntryOut(BaseModel):
    art: str              # "sammel" | "liste" (Sägeauftrag) | "projekt"
    projekt_id: int
    name: str
    status: str
    materialien: list[WorklistLineOut]


def _arbeits_zeile(db: Database, projekt: Projekt, material: Material, teile: list[Teil],
                   sammel: tuple[int, str] | None) -> WorklistLineOut:
    offen = sum(t.offen_anzahl for t in teile)
    plan = db.get_plan(projekt.id, material.id)
    stuecke = [st for b in plan.bretter for st in b.stuecke] if plan else []
    gesaegt = sum(1 for st in stuecke if st.gesaegt)
    grund = ""
    if offen == 0 and gesaegt == len(stuecke):
        status = "fertig"
    elif sammel:
        status = "sammel"
    elif plan:
        grund = _veraltet_grund(db, plan, projekt, material)
        if not grund and gesaegt == len(stuecke):
            grund = "teile"   # alles gesägt, aber noch Teile offen (z.B. Menge erhöht)
        status = "veraltet" if grund else ("in_arbeit" if gesaegt else "bereit")
    else:
        anderswo = db.ungesaegt_in_plaenen(material.id, ausser_projekt=projekt.id)
        frei = sum(max(0, t.offen_anzahl - anderswo.get(t.id, 0)) for t in teile)
        status = "kein_plan" if frei or projekt.art == "sammel" else "verplant"
    auftraege: dict[int, str] = {}
    if status == "verplant":
        beauftragt = db.beauftragt(material.id)
        for t in teile:
            for a in beauftragt.get(t.id, []):
                auftraege[a["projekt_id"]] = a["name"]
    return WorklistLineOut(
        material_id=material.id, material=material.name, typ=material.typ.value,
        teile=sum(1 for t in teile if t.offen_anzahl > 0), offen=offen, status=status,
        veraltet_grund=grund, plan_id=plan.id if plan else 0, gesamt=len(stuecke),
        gesaegt=gesaegt, sammelplan_id=sammel[0] if sammel else 0,
        sammelplan=sammel[1] if sammel else "",
        auftraege=[WorkProjectRef(projekt_id=k, name=v) for k, v in auftraege.items()])


@app.get("/api/worklist", response_model=list[WorklistEntryOut])
def get_worklist(fertige: bool = False):
    """Alles, was gesägt werden kann: Sammelpläne, Sägeaufträge, Projekte je Material,
    mit Status und Fortschritt des Plans. ?fertige=true zeigt auch fertig Gesägtes."""
    db = get_db()
    materialien = {m.id: m for m in db.list_materials()}
    sammel_je_mat = {}
    eintraege: list[WorklistEntryOut] = []
    for s in db.list_projekte(sammel=True):
        mat = materialien.get(s.sammel_material_id)
        if not mat:
            continue
        sammel_je_mat[mat.id] = (s.id, s.name)
        teile = _plan_teile(s, mat.id)
        eintraege.append(WorklistEntryOut(art="sammel", projekt_id=s.id, name=s.name,
                                          status="", materialien=[
                                              _arbeits_zeile(db, s, mat, teile, None)]))
    mitglied_in = {(pid, mid): sammel_je_mat[mid] for mid in sammel_je_mat
                   for pid in db.sammel_mitglieder(sammel_je_mat[mid][0])}
    projekte = db.list_projekte()
    for p in sorted(projekte, key=lambda p: p.art != "liste"):
        zeilen = []
        for mid in dict.fromkeys(t.material_id for t in p.teile):
            if mat := materialien.get(mid):
                zeilen.append(_arbeits_zeile(db, p, mat, [t for t in p.teile
                                                          if t.material_id == mid],
                                             mitglied_in.get((p.id, mid))))
        eintraege.append(WorklistEntryOut(art="liste" if p.art == "liste" else "projekt",
                                          projekt_id=p.id, name=p.name, status="",
                                          materialien=zeilen))
    # Vorschlag Sammelplan: gleiches Material in mehreren Projekten, noch ohne Sammelplan
    frei: dict[int, list[WorkProjectRef]] = {}
    for e in eintraege:
        if e.art == "projekt":
            for z in e.materialien:
                if z.status in ("kein_plan", "bereit") and z.material_id not in sammel_je_mat:
                    frei.setdefault(z.material_id, []).append(
                        WorkProjectRef(projekt_id=e.projekt_id, name=e.name))
    for e in eintraege:
        if e.art == "projekt":
            for z in e.materialien:
                if z.status in ("kein_plan", "bereit"):
                    z.auch_in = [r for r in frei.get(z.material_id, [])
                                 if r.projekt_id != e.projekt_id]
        if not fertige:
            e.materialien = [z for z in e.materialien if z.status != "fertig"]
        e.status = min((z.status for z in e.materialien), key=_STATUS_RANG.index,
                       default="fertig")
    return [e for e in eintraege if e.materialien]


def _plan_is_1d(db: Database, plan: GespeicherterPlan) -> bool:
    material = db.get_material(plan.material_id)
    return material is not None and material.typ == MaterialTyp.STANGE


@app.get("/api/projects/{pid}/plans/{mid}", response_model=Optional[OptimizeResult])
def get_saved_plan(pid: int, mid: int):
    """Gespeicherter Plan oder null, wenn für Projekt+Material noch keiner existiert."""
    plan = get_db().get_plan(pid, mid)
    return _plan_to_out(plan) if plan else None


@app.post("/api/plan-pieces/{sid}", response_model=PieceSawnOut)
def set_piece_sawn(sid: int, data: PieceSawnIn):
    """Ein Stück als gesägt markieren/zurücknehmen – Fortschritt und Lager inklusive.

    Idempotent: Der Zielzustand wird gesetzt, nicht umgeschaltet.
    """
    db = get_db()
    plan = db.get_plan_for_stueck(sid)
    if not plan:
        raise HTTPException(404, "Plan piece not found")
    brett = next(b for b in plan.bretter if any(st.id == sid for st in b.stuecke))
    stueck = next(st for st in brett.stuecke if st.id == sid)
    teil = None
    if stueck.gesaegt != data.gesaegt:
        stueck.gesaegt = data.gesaegt
        if stueck.teil_id:
            _gesaegt_buchen(db, stueck, 1 if data.gesaegt else -1)
        db.set_stueck_gesaegt(sid, data.gesaegt, stueck.buchung)
        _brett_abgleichen(db, plan, brett, _plan_is_1d(db, plan))
        db.plan_geaendert(plan.id)
    if stueck.teil_id:
        t = db.get_teil(stueck.teil_id)
        teil = _teil_to_out(t) if t else None
    return PieceSawnOut(plan=_plan_to_out(db.get_plan_by_id(plan.id)), teil=teil)


@app.delete("/api/plans/{plan_id}", status_code=204)
def discard_plan(plan_id: int):
    """Plan verwerfen: gibt reservierte Bretter frei. Fortschritt und Lager bleiben.

    Ein verworfener Sammelplan verschwindet samt Mitgliederliste."""
    db = get_db()
    plan = db.get_plan_by_id(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.delete_plan(plan_id)
    projekt = db.get_projekt(plan.projekt_id)
    if projekt and projekt.art == "sammel":
        db.delete_projekt(projekt.id)


def _gesaegt_buchen(db: Database, st: PlanStueck, delta: int):
    """Gesägtes Stück verbuchen (delta +1 sägen, -1 zurücknehmen), setzt st.buchung.

    Füllteile und Teile eines Sägeauftrags zählen zuerst beim (Herkunfts-)Teil als
    gesägt, solange dort etwas offen ist; erst der Überschuss geht zu den Fertigteilen
    (teil.vorrat). Ein Sägeauftrag zählt seinen eigenen Fortschritt immer mit.
    Zurücknehmen bucht genau das zurück, was beim Sägen passiert ist."""
    teil = db.get_teil(st.teil_id)
    if not teil:
        return
    ziel_id = st.teil_id if st.ist_fuellteil else teil.herkunft_teil_id
    if not st.ist_fuellteil:
        db.teil_gesaegt_aendern(st.teil_id, delta)
        if not ziel_id:
            return
    if delta > 0:
        ziel = db.get_teil(ziel_id)
        st.buchung = "teil" if ziel and ziel.offen_anzahl > 0 else "vorrat"
    if st.buchung == "teil":
        db.teil_gesaegt_aendern(ziel_id, delta)
    else:   # "vorrat", oder "" = vor 2026.10.77 gesägt (ging immer zu den Fertigteilen)
        db.teil_vorrat_aendern(ziel_id, delta)
    if delta < 0:
        st.buchung = ""


@app.get("/api/projects/{pid}/fill-candidates/{mid}", response_model=list[FuellKandidatOut])
def fill_candidates(pid: int, mid: int):
    """Mögliche Füllteile: Teile desselben Materials aus allen anderen Projekten."""
    return [FuellKandidatOut(teil_id=k["teil"].id, label=k["teil"].label, projekt=k["projekt"],
                             projekt_id=k["teil"].projekt_id, laenge=k["teil"].laenge,
                             breite=k["teil"].breite, offen=k["teil"].offen_anzahl,
                             vorrat=k["teil"].vorrat)
            for k in get_db().fuellteil_kandidaten(pid, mid)]


@app.post("/api/projects/{pid}/take-stock/{mid}", response_model=ProjectOut)
def take_part_stock(pid: int, mid: int):
    """Teile-Vorrat ("Regal") dieses Projekts/Materials als gesägt übernehmen."""
    db = get_db()
    projekt = db.get_projekt(pid)
    if not projekt:
        raise HTTPException(404, "Project not found")
    _nicht_vorlage(projekt)
    db.vorrat_uebernehmen(pid, mid)
    return _projekt_to_out(db.get_projekt(pid))


@app.post("/api/plans/{plan_id}/confirm-all", response_model=OptimizeResult)
def confirm_all_pieces(plan_id: int):
    """Alle noch offenen Stücke des Plans als gesägt markieren."""
    db = get_db()
    plan = db.get_plan_by_id(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    is_1d = _plan_is_1d(db, plan)
    for brett in plan.bretter:
        offen = [st for st in brett.stuecke if not st.gesaegt]
        if not offen:
            continue
        for st in offen:
            st.gesaegt = True
            if st.teil_id:
                _gesaegt_buchen(db, st, 1)
            db.set_stueck_gesaegt(st.id, True, st.buchung)
        _brett_abgleichen(db, plan, brett, is_1d)
    db.plan_geaendert(plan.id)
    return _plan_to_out(db.get_plan_by_id(plan.id))


@app.post("/api/projects/{pid}/restart", response_model=ProjectOut)
def restart_project(pid: int):
    """Projekt nochmal sägen: Fortschritt auf 0, Pläne weg, Lager bleibt wie es ist."""
    db = get_db()
    projekt = db.get_projekt(pid)
    if not projekt:
        raise HTTPException(404, "Project not found")
    _nicht_vorlage(projekt)
    db.projekt_neu_starten(pid)
    return _projekt_to_out(db.get_projekt(pid))


def _mark_plan_core(db: Database, req: MarkPlanRequest) -> dict:
    """Lagerbestand für EIN Brett eines Schnittplans anpassen.

    Beim ersten markierten Stück wird das Lagerstück verbraucht; der tatsächliche
    Rest (1D: Länge − Σ markiert − Kerf·Anzahl; 2D: plan.reste nur wenn komplett)
    wird eingebucht. Vorher gebuchte Reste werden zuerst entfernt (idempotent).
    Ohne Markierungen wird der Verbrauch rückgängig gemacht.
    """
    consumed = req.prev_consumed
    consumed_piece = req.prev_consumed_piece
    lagerstueck_id = req.lagerstueck_id
    material = db.get_material(req.material_id)
    kuerzel = material.kuerzel if material else ""
    # Zuvor gebuchte Reste immer entfernen und ggf. neu buchen. Fürs Journal
    # merken, was vorher da war – gebucht wird nur der Unterschied.
    reste_vorher: list[tuple[float, float, str]] = []
    for i, rid in enumerate(req.prev_rest_ids):
        nr = req.prev_rest_nrs[i] if i < len(req.prev_rest_nrs) else 0
        ls = db.get_lagerstueck(rid)
        if ls:
            reste_vorher.append((ls.laenge, ls.breite, stueck_code(kuerzel, nr)))
        db.lager_verbrauchen(rid, stueck_nr=nr)
    for l, b in req.prev_abfall:
        db.abfall_aendern(req.material_id, l, b, -1, commit=False)
    rest_ids: list[int] = []
    rest_nrs: list[int] = []
    abfall: list[list[float]] = []
    reste_nachher: list[tuple[float, float, str]] = []
    plan_stueck = stueck_code(kuerzel, req.stueck_nr)

    n_marked = len(req.marked_laengen)
    if n_marked > 0:
        if not consumed:
            ls = db.get_lagerstueck(req.lagerstueck_id)
            consumed_piece = db.lager_verbrauchen(req.lagerstueck_id,
                                                  stueck_nr=req.stueck_nr)
            consumed = True
            if ls:
                db.journal("plan_verbrauch", req.material_id, plan_stueck,
                           ls.laenge, ls.breite, 1)
        # Der größte Rest erbt den Code des angesägten Stücks – dessen Etikett
        # klebt ja noch drauf. Weitere Reste bekommen freie Nummern.
        erbe_nr = (consumed_piece or {}).get("nr", 0) or req.stueck_nr
        if req.is_1d:
            if req.defekte:
                rest_vals = _reste_1d_mit_defekten(req)
            else:
                rest_vals = [req.lager_laenge - sum(req.marked_laengen)
                             - req.kerf * n_marked]
            reste = [(v, 0.0) for v in rest_vals if v > 0]
        else:
            # 2D: Sobald das Brett angesägt wird, die Reststücke des Plans
            # einbuchen (durchgängige Schnitte). Beim Zurücknehmen aller
            # Markierungen werden sie über prev_rest_ids wieder entfernt.
            reste = [(r[0], r[1]) for r in req.reste
                     if len(r) >= 2 and r[0] > 0 and r[1] > 0]
        for laenge, breite in sorted(reste, key=lambda r: r[0] * max(r[1], 1),
                                     reverse=True):
            r = db.rest_einbuchen(req.material_id, laenge, breite, wunsch_nr=erbe_nr)
            if r:
                rest_ids.append(r[0].id)
                rest_nrs.append(r[1])
                reste_nachher.append((r[0].laenge, r[0].breite, stueck_code(kuerzel, r[1])))
                if r[1] == erbe_nr:
                    erbe_nr = 0
            elif material and _rest_ziel(material, laenge, breite) == "abfallkiste":
                db.abfall_aendern(req.material_id, laenge, breite, 1, commit=False)
                abfall.append([laenge, breite])
    elif consumed:
        # Alle Markierungen entfernt → Original-Lagerstück zurückbuchen
        lagerstueck_id = _lagerstueck_zurueckbuchen(db, req)
        consumed = False
        consumed_piece = None
        ls = db.get_lagerstueck(lagerstueck_id)
        if ls:
            db.journal("plan_zurueck", req.material_id, plan_stueck, ls.laenge, ls.breite, 1)

    _reste_journal(db, req.material_id, reste_vorher, reste_nachher)
    _abfall_journal(db, req.material_id, req.prev_abfall, abfall)
    db.conn.commit()
    return {"consumed": consumed, "rest_ids": rest_ids, "rest_nrs": rest_nrs,
            "lagerstueck_id": lagerstueck_id, "consumed_piece": consumed_piece,
            "abfall": abfall}


def _rest_ziel(material: Material, laenge: float, breite: float = 0.0) -> str:
    """Wohin ein Abschnitt gehört: "lager", "abfallkiste" oder "weg".

    Gleiche Regel wie db.rest_einbuchen: ab dem Mindest-Restmaß ins Lager. Darunter
    in die Abfallkiste, wenn sie eingeschaltet ist und das Stück die Untergrenze
    erreicht (Platten: die schmalere Seite).
    """
    if material.typ == MaterialTyp.STANGE:
        if laenge >= material.rest_min_laenge:
            return "lager"
        mass = laenge
    else:
        if laenge >= material.rest_min_laenge and breite >= material.rest_min_breite:
            return "lager"
        mass = min(laenge, breite)
    e = _lager_einstellungen()
    if e["abfall_aufheben"] and mass > 0 and mass >= e["abfall_untergrenze"]:
        return "abfallkiste"
    return "weg"


def _mass_schluessel(l: float, b: float) -> tuple[float, float]:
    return round(l, 1), round(b or 0.0, 1)


def _reste_journal(db: Database, mid: int, vorher: list, nachher: list):
    """Nur geänderte Reste buchen – das Neu-Einbuchen beim Abhaken ist sonst Rauschen."""
    rest = [_mass_schluessel(l, b) for l, b, _ in vorher]
    for l, b, code in nachher:
        k = _mass_schluessel(l, b)
        if k in rest:
            rest.remove(k)
        else:
            db.journal("rest_ein", mid, code, l, b, 1)
    for l, b, code in vorher:
        k = _mass_schluessel(l, b)
        if k in rest:
            rest.remove(k)
            db.journal("rest_zurueck", mid, code, l, b, 1)


def _abfall_journal(db: Database, mid: int, vorher: list, nachher: list):
    alt = [_mass_schluessel(l, b) for l, b in vorher]
    for l, b in nachher:
        k = _mass_schluessel(l, b)
        if k in alt:
            alt.remove(k)
        else:
            db.journal("abfall_ein", mid, "", l, b, 1)
    for l, b in alt:
        db.journal("abfall_zurueck", mid, "", l, b, 1)


def _reste_1d_mit_defekten(req: MarkPlanRequest) -> list[float]:
    """Reststücke einer Stange mit Defekten nach den markierten Schnitten.

    Defektzonen werden als Abfall herausgeschnitten, damit kein Rest mit
    (dann nicht mehr markiertem) Defekt ins Lager kommt. Jedes markierte
    Stück belegt zusätzlich die Schnittfuge links und rechts davon.
    """
    belegt = [(d[0], d[0] + d[1]) for d in req.defekte if len(d) >= 2]
    belegt += [(x - req.kerf, x + l + req.kerf)
               for x, l in zip(req.marked_x, req.marked_laengen)]
    reste: list[float] = []
    pos = 0.0
    for start, ende in sorted(belegt):
        if start > pos:
            reste.append(start - pos)
        pos = max(pos, ende)
    if req.lager_laenge > pos:
        reste.append(req.lager_laenge - pos)
    return reste


def _lagerstueck_zurueckbuchen(db: Database, req: MarkPlanRequest) -> int:
    """Verbrauchtes Lagerstück mit seinen Originalmaßen wieder einbuchen.

    Der Plan kennt nur die besäumten Maße (Original − 2·Besäumung). Existiert die
    Lagerzeile noch, wird nur die Stückzahl erhöht; sonst wird sie neu angelegt
    (bzw. mit einer gleich großen Zeile zusammengefasst). Liefert die ID zurück.
    """
    ls = db.get_lagerstueck(req.lagerstueck_id)
    if ls is None:
        mat = db.get_material(req.material_id)
        trim = 2 * (mat.besaeumung if mat else 0.0)
        laenge = req.lager_laenge + trim
        breite = 0.0 if req.is_1d else req.lager_breite + trim
        ls = next((e for e in db.list_lagerstuecke(req.material_id)
                   if abs(e.laenge - laenge) < 0.1 and abs(e.breite - breite) < 0.1),
                  None)
        if ls is None:
            ls = Lagerstueck(material_id=req.material_id, laenge=laenge,
                             breite=breite, stueckzahl=0)
    ls, neue_nr = db.stueck_hinzufuegen(ls)
    if req.prev_consumed_piece:
        db.einzelstueck_wiederherstellen(ls.id, neue_nr, req.prev_consumed_piece)
    return ls.id


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _pdf_rest_ziel(material_id: int):
    """Wohin die Abschnitte im PDF gehören; ohne Material keine Angabe."""
    material = get_db().get_material(material_id) if material_id else None
    if material is None:
        return None
    return lambda laenge, breite: _rest_ziel(material, laenge, breite)


@app.post("/api/pdf")
def generate_pdf(req: PdfRequest):
    ergebnis = _out_to_ergebnis(req.ergebnis)
    cfg = _get_settings_dict()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        export_pdf(
            ergebnis,
            tmp_path,
            projekt_name=req.projekt_name,
            material_name=req.material_name,
            saegeblatt_name=req.saegeblatt_name,
            is_1d=req.is_1d,
            schnittfolgen=req.schnittfolgen,
            schnittfolge_titel=req.schnittfolge_titel,
            nach_projekt=req.nach_projekt,
            material_bild=(get_db().get_material_image(req.material_id) or b""
                           if req.material_id else b""),
            rest_ziel=_pdf_rest_ziel(req.material_id),
            unit=cfg["unit"],
            feet=cfg["unit_feet"],
            language=cfg["language"],
        )
        return FileResponse(
            tmp_path,
            media_type="application/pdf",
            filename=f"CutStock-{req.projekt_name or 'Schnittplan'}.pdf",
            headers={"Content-Disposition": f'attachment; filename="CutStock-{req.projekt_name or "Schnittplan"}.pdf"'},
        )
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(500, f"PDF generation failed: {e}")


# ---------------------------------------------------------------------------
# Labels (Etiketten für Teile und Reste)
# ---------------------------------------------------------------------------


def _labels_pdf(labels: list[dict], filename: str, startfeld: int = 1) -> FileResponse:
    from core.labels import export_labels

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cfg = _get_settings_dict()
        export_labels(labels, tmp_path,
                      title=filename,
                      fmt=str(cfg.get("label_format") or "a4_3x8"),
                      custom_w=float(cfg.get("label_custom_w") or 0),
                      custom_h=float(cfg.get("label_custom_h") or 0),
                      start=startfeld)
        fname = f"CutStock-{filename}.pdf"
        return FileResponse(
            tmp_path,
            media_type="application/pdf",
            filename=fname,
            headers={"Content-Disposition": f'attachment; filename="{fname}"',
                     "X-Label-Count": str(len(labels))},
        )
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(500, f"Label generation failed: {e}")


@app.post("/api/labels")
def generate_labels(req: LabelsRequest):
    if not req.labels:
        raise HTTPException(400, "No labels")
    return _labels_pdf([l.model_dump() for l in req.labels], req.filename, req.startfeld)


def _mass_text(laenge: float, breite: float, unit: str, feet: bool = True) -> str:
    """Maß wie in der Oberfläche: "640 mm" bzw. "800 × 600 mm" in der eingestellten Einheit."""
    return units.dimensions(laenge, breite, unit, feet)


class LabelFormatOut(BaseModel):
    key: str
    gruppe: str          # bogen | bogen_klein | rolle | rolle_klein | endlos
    breite: float        # mm (0 bei Endlos: Länge ergibt sich aus dem Inhalt)
    hoehe: float         # mm
    ware: str            # z. B. "Brother DK-11204", "Avery L7651"
    je_bogen: int = 0    # Etiketten je A4-Bogen, 0 = Rolle


class LabelPreviewItem(BaseModel):
    text: str
    fett: bool
    groesse: float       # Schriftgröße in pt
    x: float             # mm von links (bei rechts=True: rechte Kante)
    y: float             # mm von oben bis zur Grundlinie
    grau: bool
    rechts: bool


class LabelPreviewOut(BaseModel):
    format: str
    breite: float
    hoehe: float
    elemente: list[LabelPreviewItem]


@app.get("/api/labels/formats", response_model=list[LabelFormatOut])
def label_formats():
    """Alle Etikettenformate (Bögen, Rollen, Endlos); dazu kommt "custom" (eigenes Maß)."""
    from core.labels import formats
    return [LabelFormatOut(**{k: f[k] for k in LabelFormatOut.model_fields}) for f in formats()]


@app.get("/api/labels/preview", response_model=LabelPreviewOut)
def label_preview(format: str = "", title: str = "Alu Profil 40x40", line1: str = "1200 mm",
                  line2: str = "Regal 3", id_text: str = "AP40-07"):
    """Musteretikett im eingestellten (oder angegebenen) Format: Größe und Textpositionen
    genau wie im PDF – für die Vorschau in den Einstellungen."""
    from reportlab.lib.units import mm as MM
    from core.labels import ENDLESS_FORMATS, _endlos_gross, label_size, layout
    cfg = _get_settings_dict()
    fmt = format or str(cfg.get("label_format") or "a4_3x8")
    lab = {"title": title, "line1": line1, "line2": line2, "id_text": id_text}
    w, h = label_size(fmt, lab, float(cfg.get("label_custom_w") or 0),
                      float(cfg.get("label_custom_h") or 0))
    gross = _endlos_gross(h * MM) if fmt in ENDLESS_FORMATS else None
    elemente = [LabelPreviewItem(text=i["text"], fett=i["font"].endswith("Bold"),
                                 groesse=round(i["size"], 2), x=round(i["x"] / MM, 2),
                                 y=round(h - i["y"] / MM, 2), grau=i["color"] != "#000000",
                                 rechts=i["rechts"])
                for i in layout(lab, w * MM, h * MM, gross)]
    return LabelPreviewOut(format=fmt, breite=round(w, 2), hoehe=round(h, 2), elemente=elemente)


@app.post("/api/labels/pieces")
def piece_labels(req: PieceLabelsIn):
    """Etiketten für Lagerstücke: Material, Maß, Lagerort, Code. Druckt nur die
    ausgewählten (codes, lagerort, material, nur_*-Filter) und vermerkt sie als
    gedruckt – darauf baut nur_ungedruckt auf."""
    db = get_db()
    stuecke: list[tuple[Material, Lagerstueck, Einzelstueck]] = []
    if req.codes:
        for ref in req.codes:
            e = _stueck_ref(db, str(ref))
            ls = db.get_lagerstueck(e.lagerstueck_id)
            stuecke.append((db.get_material(ls.material_id), ls, e))
    elif req.lagerort or req.material:
        nur_mat = _material_ref(db, req.material) if req.material else None
        if req.lagerort:
            ort = _lagerort_ref(db, req.lagerort)
            zeilen = [(m, ls) for m, rolle in db.lagerort_inhalt(ort["name"])
                      if not nur_mat or m.id == nur_mat.id
                      for ls in db.lagerort_stuecke(m, rolle)]
        else:
            zeilen = [(nur_mat, ls) for ls in db.list_lagerstuecke(nur_mat.id)]
        stuecke = [(m, ls, e) for m, ls in zeilen for e in db.list_einzelstuecke(ls.id)]
    else:
        raise _fehler(400, "auswahl_fehlt", "Give codes, lagerort or material")

    stuecke = [(m, ls, e) for m, ls, e in stuecke
               if not (req.nur_reste and not ls.ist_rest)
               and not (req.nur_ganze and ls.ist_rest)
               and not (req.nur_ungedruckt and e.etikett_gedruckt)]
    if not stuecke:
        raise _fehler(404, "keine_stuecke", "No pieces match the selection")
    stuecke = stuecke[:1000]

    cfg = _get_settings_dict()
    unit, feet = cfg["unit"], cfg["unit_feet"]
    labels = [{"title": m.name, "line1": _mass_text(ls.laenge, ls.breite, unit, feet),
               "line2": db.stueck_lagerort(m, ls), "id_text": stueck_code(m.kuerzel, e.nr)}
              for m, ls, e in stuecke]
    namen = {m.name for m, _, _ in stuecke}
    name = req.filename or (labels[0]["id_text"] if len(labels) == 1
                            else namen.pop() if len(namen) == 1 else "Etiketten")
    antwort = _labels_pdf(labels, name, req.startfeld)
    if req.markieren:
        db.etiketten_gedruckt([e.id for _, _, e in stuecke])
    return antwort


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@app.get("/api/settings")
def get_settings():
    return _get_settings_dict()


@app.put("/api/settings")
def update_settings(data: SettingsIn):
    _update_settings(data)
    return _get_settings_dict()


@app.get("/api/license")
def get_license():
    from core.license import get_license_info
    settings_path = DB_PATH.parent / "settings.json"
    info = get_license_info(settings_path)
    return {
        "valid": info.valid,
        "type": info.license_type,
        "holder": info.holder,
        "issued": info.issued,
        "expires": info.expires,
        "error": info.error,
    }


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


GITHUB_REPO = "orohde/CutStock"


@app.get("/api/version")
def get_version():
    return {
        "version": APP_VERSION,
        "repo": GITHUB_REPO,
        "github_url": f"https://github.com/{GITHUB_REPO}",
        "website_url": "https://cutstock.app/",
        "releases_api": f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        # Bestimmt, welche Update-Anleitung die Oberfläche zeigt
        "docker": IS_DOCKER,
    }


# ---------------------------------------------------------------------------
# Backup / Restore
# ---------------------------------------------------------------------------


@app.get("/api/backup")
def create_backup():
    """Datenbank + Einstellungen als ZIP herunterladen (wie Desktop-App)."""
    import io
    import zipfile

    get_db().conn.commit()  # sicherstellen, dass alles in der .db-Datei liegt

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.exists():
            zf.write(DB_PATH, DB_PATH.name)
        if SETTINGS_PATH.exists():
            zf.write(SETTINGS_PATH, SETTINGS_PATH.name)
    buf.seek(0)

    from datetime import date, datetime, timezone
    try:
        today = date.today().isoformat()
    except Exception:
        today = datetime.now(timezone.utc).date().isoformat()

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="cutstock_backup_{today}.zip"'},
    )


@app.post("/api/restore")
async def restore_backup(file: UploadFile = File(...)):
    """Backup-ZIP hochladen und Datenbank (+ Einstellungen) ersetzen."""
    global _db_generation
    import io
    import zipfile

    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        names = zf.namelist()
    except zipfile.BadZipFile:
        raise HTTPException(400, "invalid_backup")

    if DB_PATH.name not in names:
        raise HTTPException(400, "invalid_backup")

    db_bytes = zf.read(DB_PATH.name)
    settings_bytes = zf.read(SETTINGS_PATH.name) if SETTINGS_PATH.name in names else None

    # Aktuelle Verbindung dieses Threads schließen, Datei atomar ersetzen
    try:
        get_db().close()
    except Exception:
        pass

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(DB_PATH.suffix + ".restore")
    tmp.write_bytes(db_bytes)
    os.replace(tmp, DB_PATH)
    if settings_bytes is not None:
        SETTINGS_PATH.write_bytes(settings_bytes)

    # Alle Threads zwingen, neu zu verbinden
    _db_generation += 1
    get_db()  # aktuelle Verbindung neu aufbauen
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------


WEB_EXTRA_TRANSLATIONS = {
    "fill.qty_any": {"de": "beliebig", "en": "any", "fr": "libre", "it": "libero"},
    "fill.apply": {"de": "Übernehmen und optimieren", "en": "Apply and optimize",
                   "fr": "Appliquer et optimiser", "it": "Applica e ottimizza"},
    "fill.nothing_fits": {
        "de": "Kein Füllteil passt in die Reste.",
        "en": "No fill part fits into the remnants.",
        "fr": "Aucune pièce de remplissage ne rentre dans les chutes.",
        "it": "Nessun pezzo di riempimento entra negli sfridi."},
    "fill.nothing_fits_waste": {
        "de": "Kein Füllteil passt in den Abfall. Verwertbare Reste werden nur mit „Auch verwertbare Reste auffüllen“ belegt.",
        "en": "No fill part fits into the waste. Usable remnants are only filled with “Also fill usable remnants”.",
        "fr": "Aucune pièce de remplissage ne rentre dans les déchets. Les chutes réutilisables ne sont remplies qu’avec « Remplir aussi les chutes réutilisables ».",
        "it": "Nessun pezzo di riempimento entra negli scarti. Gli sfridi riutilizzabili vengono riempiti solo con «Riempi anche gli sfridi riutilizzabili»."},
    "opt.max_per_bar": {"de": "Max. je Stange", "en": "Max. per bar", "fr": "Max. par barre", "it": "Max. per barra"},
    "opt.max_per_bar_hint": {
        "de": "Höchstens so viele Teile auf eine Stange – lässt gezielt Platz für Füllteile. Leer = so viele wie passen.",
        "en": "At most this many parts per bar – deliberately leaves room for filler parts. Empty = as many as fit.",
        "fr": "Au plus ce nombre de pièces par barre – laisse volontairement de la place pour les pièces de remplissage. Vide = autant que possible.",
        "it": "Al massimo questi pezzi per barra – lascia apposta spazio per i pezzi di riempimento. Vuoto = quanti ci stanno.",
    },
    "sug.title": {"de": "Füllung der Reste", "en": "Filling the remnants", "fr": "Remplissage des chutes", "it": "Riempimento degli sfridi"},
    "sug.hint": {
        "de": "Die Wahl gilt für alle Stangen mit diesem Rest. Teile mit Mengenangabe haben bei gleichem Abfall Vorrang, danach weniger Schnitte.",
        "en": "The choice applies to all bars with this remnant. With equal waste, parts with a quantity take priority, then fewer cuts.",
        "fr": "Le choix vaut pour toutes les barres avec cette chute. À chute égale, les pièces avec quantité sont prioritaires, puis moins de coupes.",
        "it": "La scelta vale per tutte le barre con questo sfrido. A parità di scarto hanno la precedenza i pezzi con quantità, poi meno tagli.",
    },
    "sug.group": {"de": "Rest {rest} auf {n} Stange(n)", "en": "Remnant {rest} on {n} bar(s)",
                  "fr": "Chute {rest} sur {n} barre(s)", "it": "Sfrido {rest} su {n} barra/e"},
    "sug.rest_after": {"de": "danach {rest} Abfall", "en": "then {rest} waste", "fr": "ensuite {rest} de chute", "it": "poi {rest} di scarto"},
    "sug.manual": {"de": "von Hand gewählt", "en": "chosen by hand", "fr": "choisi à la main", "it": "scelto a mano"},
    "sug.automatic": {"de": "automatisch", "en": "automatic", "fr": "automatique", "it": "automatico"},
    "sug.choose": {"de": "Wählen", "en": "Choose", "fr": "Choisir", "it": "Scegli"},
    "sug.chosen": {"de": "gewählt", "en": "chosen", "fr": "choisi", "it": "scelto"},
    "sug.nothing": {"de": "Nichts einplanen", "en": "Plan nothing", "fr": "Ne rien prévoir", "it": "Niente"},
    "sug.auto": {"de": "Automatik", "en": "Automatic", "fr": "Automatique", "it": "Automatico"},
    "sug.fallback": {
        "de": "Bei {n} Stange(n) reichte die Menge nicht für diese Wahl – dort automatisch gefüllt.",
        "en": "On {n} bar(s) the quantity didn't suffice for this choice – filled automatically there.",
        "fr": "Sur {n} barre(s), la quantité ne suffisait pas pour ce choix – rempli automatiquement.",
        "it": "Su {n} barra/e la quantità non bastava per questa scelta – riempito automaticamente.",
    },
    "mat.empty": {"de": "Keine Materialien vorhanden.", "en": "No materials.", "fr": "Aucun matériau.", "it": "Nessun materiale."},
    "stock.empty": {"de": "Kein Lagerbestand.", "en": "No stock.", "fr": "Pas de stock.", "it": "Nessuna scorta."},
    "stock.qty_zero_hint": {
        "de": "0 = Maß bleibt gelistet und steht auf der Nachbestellliste.",
        "en": "0 = size stays listed and appears on the reorder list.",
        "fr": "0 = la dimension reste listée et figure sur la liste de réapprovisionnement.",
        "it": "0 = la misura resta in elenco e compare nella lista da riordinare."},
    "stock.zero_hint": {
        "de": "Leer – steht auf der Nachbestellliste", "en": "Empty – on the reorder list",
        "fr": "Vide – sur la liste de réapprovisionnement", "it": "Vuoto – nella lista da riordinare"},
    "reorder.button": {"de": "Nachbestellen …", "en": "Reorder …", "fr": "Réapprovisionner …", "it": "Riordina …"},
    "reorder.title": {"de": "Nachbestellen", "en": "Reorder", "fr": "Réapprovisionner", "it": "Da riordinare"},
    "reorder.hint": {
        "de": "Leere Normalmaße und Materialien ohne Bestand. Klick auf eine Zeile öffnet das Material.",
        "en": "Empty standard sizes and materials without stock. Click a row to open the material.",
        "fr": "Dimensions standard vides et matériaux sans stock. Cliquez sur une ligne pour ouvrir le matériau.",
        "it": "Misure standard vuote e materiali senza scorta. Clic su una riga apre il materiale."},
    "reorder.empty": {"de": "Nichts nachzubestellen.", "en": "Nothing to reorder.",
                      "fr": "Rien à réapprovisionner.", "it": "Niente da riordinare."},
    "reorder.material": {"de": "Material", "en": "Material", "fr": "Matériau", "it": "Materiale"},
    "reorder.size": {"de": "Maß", "en": "Size", "fr": "Dimension", "it": "Misura"},
    "reorder.location": {"de": "Lagerort", "en": "Location", "fr": "Emplacement", "it": "Ubicazione"},
    "reorder.no_stock": {"de": "kein Bestand", "en": "no stock", "fr": "pas de stock", "it": "nessuna scorta"},
    "reorder.copy": {"de": "Kopieren", "en": "Copy", "fr": "Copier", "it": "Copia"},
    "reorder.copied": {"de": "Liste kopiert.", "en": "List copied.", "fr": "Liste copiée.", "it": "Lista copiata."},
    "reorder.copy_failed": {"de": "Kopieren nicht möglich.", "en": "Copy failed.",
                            "fr": "Copie impossible.", "it": "Copia non riuscita."},
    "parts.empty": {"de": "Keine Teile vorhanden.", "en": "No parts.", "fr": "Aucune pièce.", "it": "Nessuna parte."},
    "blade.empty": {"de": "Keine Sägeblätter.", "en": "No blades.", "fr": "Aucune lame.", "it": "Nessuna lama."},
    "proj.edit": {"de": "Projekt bearbeiten", "en": "Edit project", "fr": "Modifier le projet", "it": "Modifica progetto"},
    "proj.empty": {"de": "Keine Projekte.", "en": "No projects.", "fr": "Aucun projet.", "it": "Nessun progetto."},
    "error.pdf_failed": {"de": "PDF-Export fehlgeschlagen.", "en": "PDF export failed.", "fr": "Export PDF échoué.", "it": "Esportazione PDF fallita."},
    "defect.title": {"de": "Defekte", "en": "Defects", "fr": "Défauts", "it": "Difetti"},
    "defect.new": {"de": "Defekt hinzufügen", "en": "Add defect", "fr": "Ajouter un défaut", "it": "Aggiungi difetto"},
    "defect.edit": {"de": "Defekt bearbeiten", "en": "Edit defect", "fr": "Modifier le défaut", "it": "Modifica difetto"},
    "defect.position": {"de": "Position", "en": "Position", "fr": "Position", "it": "Posizione"},
    "defect.position_y": {"de": "Position Y", "en": "Position Y", "fr": "Position Y", "it": "Posizione Y"},
    "defect.length": {"de": "Länge", "en": "Length", "fr": "Longueur", "it": "Lunghezza"},
    "defect.width": {"de": "Breite", "en": "Width", "fr": "Largeur", "it": "Larghezza"},
    "defect.empty": {"de": "Keine Defekte.", "en": "No defects.", "fr": "Aucun défaut.", "it": "Nessun difetto."},
    "defect.select_stock": {"de": "Bitte zuerst ein Lagerstück wählen.", "en": "Please select a stock piece first.", "fr": "Veuillez d'abord sélectionner une pièce.", "it": "Selezionare prima un pezzo."},
    "defect.select_piece": {"de": "Bitte Stücknummer wählen.", "en": "Please select a piece number.", "fr": "Veuillez sélectionner un numéro de pièce.", "it": "Selezionare un numero di pezzo."},
    "piece.title": {"de": "Einzelstücke", "en": "Individual pieces", "fr": "Pièces individuelles", "it": "Pezzi individuali"},
    "piece.nr": {"de": "Stück", "en": "Piece", "fr": "Pièce", "it": "Pezzo"},
    "piece.note": {"de": "Notiz", "en": "Note", "fr": "Note", "it": "Nota"},
    "piece.defects": {"de": "Defekte", "en": "Defects", "fr": "Défauts", "it": "Difetti"},
    "dlg.delete_defect": {"de": "Defekt wirklich entfernen?", "en": "Really delete this defect?", "fr": "Vraiment supprimer ce défaut ?", "it": "Eliminare davvero questo difetto?"},
    "set.api": {"de": "REST-API", "en": "REST API", "fr": "API REST", "it": "API REST"},
    "set.api_enabled": {"de": "API aktivieren:", "en": "Enable API:", "fr": "Activer l’API :", "it": "Attiva API:"},
    "set.api_port": {"de": "Port:", "en": "Port:", "fr": "Port :", "it": "Porta:"},
    "set.api_key": {"de": "API-Key:", "en": "API key:", "fr": "Clé API :", "it": "Chiave API:"},
    "set.api_key_generate": {"de": "Generieren", "en": "Generate", "fr": "Générer", "it": "Genera"},
    "set.api_key_copy": {"de": "Kopieren", "en": "Copy", "fr": "Copier", "it": "Copia"},
    "set.api_key_generated": {"de": "API-Key generiert.", "en": "API key generated.", "fr": "Clé API générée.", "it": "Chiave API generata."},
    "set.api_key_copied": {"de": "API-Key kopiert.", "en": "API key copied.", "fr": "Clé API copiée.", "it": "Chiave API copiata."},
    "set.unit_mm": {"de": "Millimeter (mm)", "en": "Millimetres (mm)", "fr": "Millimètres (mm)", "it": "Millimetri (mm)"},
    "set.unit_cm": {"de": "Zentimeter (cm)", "en": "Centimetres (cm)", "fr": "Centimètres (cm)", "it": "Centimetri (cm)"},
    "set.unit_in": {"de": "Zoll dezimal (1.75\")", "en": "Inches, decimal (1.75\")", "fr": "Pouces décimaux (1.75\")", "it": "Pollici decimali (1.75\")"},
    "set.unit_in_frac": {"de": "Zoll als Bruch (1 3/4\")", "en": "Inches, fractional (1 3/4\")", "fr": "Pouces en fractions (1 3/4\")", "it": "Pollici in frazioni (1 3/4\")"},
    "set.unit_feet": {"de": "Ab 12\" in Fuß und Zoll:", "en": "Feet and inches from 12\":", "fr": "Pieds et pouces dès 12\" :", "it": "Piedi e pollici da 12\":"},
    "set.theme_system": {"de": "Auto (System)", "en": "Auto (system)", "fr": "Auto (système)", "it": "Auto (sistema)"},
    "set.theme_light": {"de": "Hell", "en": "Light", "fr": "Clair", "it": "Chiaro"},
    "set.theme_dark": {"de": "Dunkel", "en": "Dark", "fr": "Sombre", "it": "Scuro"},
    "set.api_hint": {
        "de": "Änderungen am Port werden nach einem Neustart wirksam. Ohne API-Key ist die API für jeden erreichbar, der den Server erreicht. Mit Key müssen externe Programme „Authorization: Bearer <Key>“ mitsenden; die eigene Weboberfläche und Zugriffe vom selben Rechner brauchen ihn nicht.",
        "en": "Port changes take effect after a restart. Without an API key, anyone who can reach the server can use the API. With a key, external programs must send “Authorization: Bearer <key>”; this web interface and requests from the same computer don’t need it.",
        "fr": "Les changements de port prennent effet après un redémarrage. Sans clé API, l’API est accessible à toute personne pouvant joindre le serveur. Avec une clé, les programmes externes doivent envoyer « Authorization: Bearer <clé> » ; cette interface web et les accès depuis le même ordinateur n’en ont pas besoin.",
        "it": "Le modifiche alla porta hanno effetto dopo un riavvio. Senza chiave API, l’API è accessibile a chiunque raggiunga il server. Con una chiave, i programmi esterni devono inviare “Authorization: Bearer <chiave>”; questa interfaccia web e gli accessi dallo stesso computer non ne hanno bisogno.",
    },
    "stat.material_needed": {"de": "Materialbedarf", "en": "Material needed", "fr": "Matériel nécessaire", "it": "Materiale necessario"},
    "stat.add_to_stock": {"de": "Ins Lager", "en": "Add to stock", "fr": "Ajouter au stock", "it": "Aggiungi a scorte"},
    "stat.stock_added": {"de": "Lagerbestand ergänzt.", "en": "Stock added.", "fr": "Stock ajouté.", "it": "Scorte aggiunte."},
    # Update-Hinweis mit Anleitung (Schritte durch Zeilenumbruch getrennt)
    "btn.close": {"de": "Schließen", "en": "Close", "fr": "Fermer", "it": "Chiudi"},
    "upd.button": {"de": "Update verfügbar", "en": "Update available", "fr": "Mise à jour disponible", "it": "Aggiornamento disponibile"},
    "upd.title": {"de": "Neue Version {version}", "en": "New version {version}", "fr": "Nouvelle version {version}", "it": "Nuova versione {version}"},
    "upd.current": {
        "de": "Installiert ist Version {current}. Deine Daten bleiben beim Update erhalten – CutStock sichert die Datenbank automatisch, bevor die neue Version sie zum ersten Mal öffnet.",
        "en": "Installed version: {current}. Your data is kept during the update – CutStock backs up the database automatically before the new version opens it for the first time.",
        "fr": "Version installée : {current}. Vos données sont conservées – CutStock sauvegarde automatiquement la base de données avant que la nouvelle version ne l’ouvre.",
        "it": "Versione installata: {current}. I tuoi dati restano invariati – CutStock salva automaticamente il database prima che la nuova versione lo apra.",
    },
    "upd.whats_new": {"de": "Was ist neu?", "en": "What’s new?", "fr": "Quoi de neuf ?", "it": "Novità"},
    "upd.how_docker": {
        "de": "So aktualisierst du CutStock – je nachdem, worauf es läuft:",
        "en": "How to update CutStock – depending on where it runs:",
        "fr": "Comment mettre à jour CutStock – selon l’endroit où il tourne :",
        "it": "Come aggiornare CutStock – a seconda di dove è in esecuzione:",
    },
    "upd.synology": {"de": "Synology (Container Manager)", "en": "Synology (Container Manager)", "fr": "Synology (Container Manager)", "it": "Synology (Container Manager)"},
    "upd.synology_steps": {
        "de": "Container Manager öffnen\nLinks auf „Image“ klicken\nBei cutstock auf „Update verfügbar“ klicken und bestätigen\nEtwa eine Minute warten, dann diese Seite neu laden",
        "en": "Open Container Manager\nClick “Image” on the left\nClick “Update available” next to cutstock and confirm\nWait about a minute, then reload this page",
        "fr": "Ouvrir Container Manager\nCliquer sur « Image » à gauche\nCliquer sur « Mise à jour disponible » à côté de cutstock et confirmer\nAttendre environ une minute, puis recharger cette page",
        "it": "Aprire Container Manager\nFare clic su “Immagine” a sinistra\nFare clic su “Aggiornamento disponibile” accanto a cutstock e confermare\nAttendere circa un minuto, poi ricaricare questa pagina",
    },
    "upd.synology_hint": {
        "de": "Kein „Update verfügbar“ zu sehen? Dann wurde das Image mit fester Versionsnummer statt „latest“ eingerichtet.",
        "en": "No “Update available” shown? Then the image was set up with a fixed version number instead of “latest”.",
        "fr": "Pas de « Mise à jour disponible » ? L’image a alors été configurée avec un numéro de version fixe au lieu de « latest ».",
        "it": "Nessun “Aggiornamento disponibile”? Allora l’immagine è stata configurata con un numero di versione fisso invece di “latest”.",
    },
    "upd.unraid": {"de": "Unraid", "en": "Unraid", "fr": "Unraid", "it": "Unraid"},
    "upd.unraid_steps": {
        "de": "Im Unraid-Menü „Docker“ öffnen\nBei CutStock auf „update ready“ und dann „apply update“ klicken\nNach dem Neustart diese Seite neu laden",
        "en": "Open “Docker” in the Unraid menu\nClick “update ready” next to CutStock, then “apply update”\nReload this page after the restart",
        "fr": "Ouvrir « Docker » dans le menu Unraid\nCliquer sur « update ready » à côté de CutStock, puis « apply update »\nRecharger cette page après le redémarrage",
        "it": "Aprire “Docker” nel menu di Unraid\nFare clic su “update ready” accanto a CutStock, poi “apply update”\nRicaricare questa pagina dopo il riavvio",
    },
    "upd.compose": {"de": "Docker Compose (Kommandozeile)", "en": "Docker Compose (command line)", "fr": "Docker Compose (ligne de commande)", "it": "Docker Compose (riga di comando)"},
    "upd.desktop": {
        "de": "Lade die neue Version herunter und ersetze damit die bisherige App. Deine Daten bleiben erhalten.",
        "en": "Download the new version and replace the existing app with it. Your data is kept.",
        "fr": "Téléchargez la nouvelle version et remplacez l’application existante. Vos données sont conservées.",
        "it": "Scarica la nuova versione e sostituisci l’app esistente. I tuoi dati restano invariati.",
    },
    # Sammelplan (Optimieren nach Material)
    "sammel.mode": {"de": "Optimieren nach", "en": "Optimize by", "fr": "Optimiser par", "it": "Ottimizza per"},
    "sammel.mode_project": {"de": "Projekt", "en": "Project", "fr": "Projet", "it": "Progetto"},
    "sammel.mode_material": {"de": "Material (Sammelplan)", "en": "Material (combined plan)", "fr": "Matériau (plan groupé)", "it": "Materiale (piano combinato)"},
    "sammel.projects": {"de": "Projekte mit diesem Material", "en": "Projects using this material", "fr": "Projets utilisant ce matériau", "it": "Progetti con questo materiale"},
    "sammel.col_open": {"de": "Offen", "en": "Open", "fr": "Ouvert", "it": "Aperti"},
    "sammel.col_need": {"de": "Bedarf", "en": "Needed", "fr": "Besoin", "it": "Fabbisogno"},
    "sammel.col_note": {"de": "Hinweis", "en": "Note", "fr": "Remarque", "it": "Nota"},
    "sammel.none": {"de": "Kein Projekt braucht dieses Material.", "en": "No project needs this material.", "fr": "Aucun projet n’utilise ce matériau.", "it": "Nessun progetto usa questo materiale."},
    "sammel.member": {"de": "im Sammelplan", "en": "in combined plan", "fr": "dans le plan groupé", "it": "nel piano combinato"},
    "sammel.replaces_single": {"de": "Einzelplan wird ersetzt", "en": "replaces its own plan", "fr": "remplace son plan", "it": "sostituisce il suo piano"},
    "sammel.locked": {"de": "{n} Stück in angefangenem Plan", "en": "{n} pcs in a started plan", "fr": "{n} pièces dans un plan commencé", "it": "{n} pezzi in un piano iniziato"},
    "sammel.compare": {"de": "Vergleichen", "en": "Compare", "fr": "Comparer", "it": "Confronta"},
    "sammel.compare_result": {"de": "Getrennt: {sep} · Gemeinsam: {tog}", "en": "Separately: {sep} · Combined: {tog}", "fr": "Séparément : {sep} · Ensemble : {tog}", "it": "Separati: {sep} · Insieme: {tog}"},
    "sammel.compare_missing": {
        "de": "Es fehlt Material – der Vergleich ist nur bedingt aussagekräftig.",
        "en": "Material is missing – the comparison is only indicative.",
        "fr": "Il manque du matériau – la comparaison n’est qu’indicative.",
        "it": "Manca materiale – il confronto è solo indicativo.",
    },
    "sammel.bar_one": {"de": "1 ganze Stange", "en": "1 full bar", "fr": "1 barre entière", "it": "1 barra intera"},
    "sammel.bar_n": {"de": "{n} ganze Stangen", "en": "{n} full bars", "fr": "{n} barres entières", "it": "{n} barre intere"},
    "sammel.board_one": {"de": "1 ganze Platte", "en": "1 full board", "fr": "1 panneau entier", "it": "1 pannello intero"},
    "sammel.board_n": {"de": "{n} ganze Platten", "en": "{n} full boards", "fr": "{n} panneaux entiers", "it": "{n} pannelli interi"},
    "sammel.rest_one": {"de": "1 Rest", "en": "1 offcut", "fr": "1 chute", "it": "1 ritaglio"},
    "sammel.rest_n": {"de": "{n} Reste", "en": "{n} offcuts", "fr": "{n} chutes", "it": "{n} ritagli"},
    "sammel.fewer": {"de": "Gemeinsam: {what} weniger", "en": "Combined: {what} fewer", "fr": "Ensemble : {what} de moins", "it": "Insieme: {what} in meno"},
    "sammel.no_fewer_bars": {"de": "Gemeinsam: keine ganze Stange weniger", "en": "Combined: no fewer full bars", "fr": "Ensemble : pas moins de barres entières", "it": "Insieme: nessuna barra intera in meno"},
    "sammel.no_fewer_boards": {"de": "Gemeinsam: keine ganze Platte weniger", "en": "Combined: no fewer full boards", "fr": "Ensemble : pas moins de panneaux entiers", "it": "Insieme: nessun pannello intero in meno"},
    "bar.title": {"de": "Stange {n}", "en": "Bar {n}", "fr": "Barre {n}", "it": "Barra {n}"},
    "bar.whole": {"de": "ganze Stange", "en": "full bar", "fr": "barre entière", "it": "barra intera"},
    "bar.rest": {"de": "Rest", "en": "offcut", "fr": "chute", "it": "ritaglio"},
    "bar.one_part": {"de": "1 Teil", "en": "1 part", "fr": "1 pièce", "it": "1 pezzo"},
    "bar.n_parts": {"de": "{n} Teile", "en": "{n} parts", "fr": "{n} pièces", "it": "{n} pezzi"},
    "bar.left": {"de": "übrig {menge}", "en": "{menge} left", "fr": "reste {menge}", "it": "avanzo {menge}"},
    "bar.to_stock": {"de": "zurück ins Lager", "en": "back to stock", "fr": "retour en stock", "it": "torna in magazzino"},
    "bar.to_waste": {"de": "wegwerfen", "en": "throw away", "fr": "à jeter", "it": "da buttare"},
    "bar.to_box": {"de": "in die Abfallkiste", "en": "into the offcut bin", "fr": "dans le bac à chutes", "it": "nella cassa degli sfridi"},
    "bar.no_left": {"de": "kein Rest", "en": "no offcut", "fr": "aucune chute", "it": "nessun ritaglio"},
    "plate.title": {"de": "Platte {n}", "en": "Panel {n}", "fr": "Panneau {n}", "it": "Pannello {n}"},
    "plate.whole": {"de": "ganze Platte", "en": "full panel", "fr": "panneau entier", "it": "pannello intero"},
    "plate.used": {"de": "{p} % genutzt", "en": "{p} % used", "fr": "{p} % utilisé", "it": "{p} % usato"},
    "plate.rest_to_stock": {"de": "Rest {masse} → zurück ins Lager", "en": "offcut {masse} → back to stock", "fr": "chute {masse} → retour en stock", "it": "ritaglio {masse} → torna in magazzino"},
    "plate.small_one": {"de": "1 kleines Stück → wegwerfen", "en": "1 small piece → throw away", "fr": "1 petite chute → à jeter", "it": "1 pezzo piccolo → da buttare"},
    "plate.small_n": {"de": "{n} kleine Stücke → wegwerfen", "en": "{n} small pieces → throw away", "fr": "{n} petites chutes → à jeter", "it": "{n} pezzi piccoli → da buttare"},
    "plate.box_one": {"de": "1 kleines Stück → Abfallkiste", "en": "1 small piece → offcut bin", "fr": "1 petite chute → bac à chutes", "it": "1 pezzo piccolo → cassa sfridi"},
    "plate.box_n": {"de": "{n} kleine Stücke → Abfallkiste", "en": "{n} small pieces → offcut bin", "fr": "{n} petites chutes → bac à chutes", "it": "{n} pezzi piccoli → cassa sfridi"},
    "sammel.select_projects": {"de": "Bitte mindestens ein Projekt auswählen.", "en": "Please select at least one project.", "fr": "Veuillez choisir au moins un projet.", "it": "Seleziona almeno un progetto."},
    "sammel.confirm_replace": {
        "de": "Die Einzelpläne von {names} sind noch nicht angefangen und werden durch den Sammelplan ersetzt.",
        "en": "The plans of {names} have not been started and will be replaced by the combined plan.",
        "fr": "Les plans de {names} ne sont pas commencés et seront remplacés par le plan groupé.",
        "it": "I piani di {names} non sono iniziati e saranno sostituiti dal piano combinato.",
    },
    "sammel.in_plan_hint": {
        "de": "Dieses Material wird im „{name}“ gesägt.",
        "en": "This material is cut in “{name}”.",
        "fr": "Ce matériau est découpé dans « {name} ».",
        "it": "Questo materiale viene tagliato in “{name}”.",
    },
    "sammel.stat_projects": {"de": "Projekte", "en": "Projects", "fr": "Projets", "it": "Progetti"},
    "sammel.one_project": {"de": "1 Projekt", "en": "1 project", "fr": "1 projet", "it": "1 progetto"},
    "sammel.n_projects": {"de": "{n} Projekte", "en": "{n} projects", "fr": "{n} projets", "it": "{n} progetti"},
    "tab.parts": {"de": "Teile", "en": "Parts", "fr": "Pièces", "it": "Pezzi"},
    "parts.title": {"de": "Offene Teile", "en": "Open parts", "fr": "Pièces à couper", "it": "Pezzi da tagliare"},
    "parts.summary": {"de": "· {p} Projekte · {n} Stück noch zu sägen", "en": "· {p} projects · {n} pieces still to cut",
                      "fr": "· {p} projets · {n} pièces encore à couper", "it": "· {p} progetti · {n} pezzi ancora da tagliare"},
    "parts.hint": {
        "de": "Hake Teile an, die du zusammen sägen willst. Sortiert nach Material, weil immer ein Material auf einmal gesägt wird.",
        "en": "Tick the parts you want to cut together. Sorted by material, because you always cut one material at a time.",
        "fr": "Cochez les pièces à couper ensemble. Triées par matériau, car on coupe toujours un matériau à la fois.",
        "it": "Spunta i pezzi da tagliare insieme. Ordinati per materiale, perché si taglia sempre un materiale alla volta.",
    },
    "parts.filter_material": {"de": "Material", "en": "Material", "fr": "Matériau", "it": "Materiale"},
    "parts.filter_project": {"de": "Projekt", "en": "Project", "fr": "Projet", "it": "Progetto"},
    "parts.all": {"de": "alle", "en": "all", "fr": "tous", "it": "tutti"},
    "parts.show_done": {"de": "auch fertige zeigen", "en": "show finished too", "fr": "afficher aussi les terminées", "it": "mostra anche i finiti"},
    "parts.col_part": {"de": "Teil", "en": "Part", "fr": "Pièce", "it": "Pezzo"},
    "parts.col_size": {"de": "Maße", "en": "Size", "fr": "Dimensions", "it": "Misure"},
    "parts.col_open": {"de": "offen", "en": "open", "fr": "ouvert", "it": "aperti"},
    "parts.col_qty": {"de": "sägen", "en": "cut", "fr": "couper", "it": "tagliare"},
    "parts.free": {"de": "({n} frei)", "en": "({n} free)", "fr": "({n} libres)", "it": "({n} liberi)"},
    "parts.none": {"de": "Keine Teile gefunden.", "en": "No parts found.", "fr": "Aucune pièce trouvée.", "it": "Nessun pezzo trovato."},
    "parts.empty_all": {
        "de": "Noch keine Teile. Lege im Reiter Projekte ein Projekt mit Teilen an.",
        "en": "No parts yet. Create a project with parts in the Projects tab.",
        "fr": "Aucune pièce pour l’instant. Créez un projet avec des pièces dans l’onglet Projets.",
        "it": "Ancora nessun pezzo. Crea un progetto con pezzi nella scheda Progetti.",
    },
    "parts.group_info_one": {"de": "· 1 Teil · {n} Stück", "en": "· 1 part · {n} pieces",
                             "fr": "· 1 pièce · {n} unités", "it": "· 1 pezzo · {n} unità"},
    "parts.group_info": {"de": "· {teile} Teile · {n} Stück", "en": "· {teile} parts · {n} pieces",
                         "fr": "· {teile} pièces · {n} unités", "it": "· {teile} pezzi · {n} unità"},
    "parts.stock_ok": {"de": "Lager reicht", "en": "Enough stock", "fr": "Stock suffisant", "it": "Scorta sufficiente"},
    "parts.stock_low_bars": {"de": "Lager fehlt ca. {n} Stangen", "en": "About {n} bars short",
                             "fr": "Il manque env. {n} barres", "it": "Mancano circa {n} barre"},
    "parts.stock_low_panels": {"de": "Lager fehlt ca. {n} Platten", "en": "About {n} panels short",
                               "fr": "Il manque env. {n} panneaux", "it": "Mancano circa {n} pannelli"},
    "parts.estimate_hint": {
        "de": "Grobe Schätzung über Länge bzw. Fläche. Genau rechnet erst die Optimierung.",
        "en": "Rough estimate by length or area. The optimization gives the exact answer.",
        "fr": "Estimation grossière par longueur ou surface. L’optimisation donne la réponse exacte.",
        "it": "Stima approssimativa per lunghezza o superficie. Il calcolo esatto lo fa l’ottimizzazione.",
    },
    "parts.in_sammel": {"de": "im {name}", "en": "in {name}", "fr": "dans {name}", "it": "in {name}"},
    "parts.in_job": {"de": "{n} im Sägeauftrag „{name}“", "en": "{n} in cut job “{name}”",
                     "fr": "{n} dans l’ordre de coupe « {name} »", "it": "{n} nell’ordine di taglio «{name}»"},
    "parts.as_filler_planned": {"de": "{n} als Füllteil verplant", "en": "{n} planned as filler parts",
                                "fr": "{n} prévues comme pièces de remplissage", "it": "{n} previsti come pezzi di riempimento"},
    "parts.finished": {"de": "{n} Fertigteile", "en": "{n} finished parts", "fr": "{n} pièces finies", "it": "{n} pezzi finiti"},
    "parts.take": {"de": "{n} übernehmen", "en": "use {n}", "fr": "utiliser {n}", "it": "usa {n}"},
    "parts.taken": {"de": "Fertigteile von „{label}“ als gesägt übernommen", "en": "Finished parts of “{label}” counted as cut",
                    "fr": "Pièces finies de « {label} » comptées comme coupées", "it": "Pezzi finiti di «{label}» contati come tagliati"},
    "parts.selected_one": {"de": "{teile} Teile, {n} Stück aus {material}", "en": "{teile} parts, {n} pieces of {material}",
                           "fr": "{teile} pièces, {n} unités en {material}", "it": "{teile} pezzi, {n} unità di {material}"},
    "parts.selected_many": {"de": "{teile} Teile, {n} Stück aus {m} Materialien", "en": "{teile} parts, {n} pieces of {m} materials",
                            "fr": "{teile} pièces, {n} unités de {m} matériaux", "it": "{teile} pezzi, {n} unità di {m} materiali"},
    "parts.clear": {"de": "Auswahl aufheben", "en": "Clear selection", "fr": "Effacer la sélection", "it": "Annulla selezione"},
    "parts.saw_now": {"de": "Jetzt sägen →", "en": "Cut now →", "fr": "Couper maintenant →", "it": "Taglia ora →"},
    "parts.list_default": {"de": "Sägeauftrag {datum}", "en": "Cut job {datum}", "fr": "Ordre de coupe {datum}", "it": "Ordine di taglio {datum}"},
    "parts.list_created": {"de": "Sägeauftrag „{name}“ angelegt", "en": "Cut job “{name}” created", "fr": "Ordre de coupe « {name} » créé", "it": "Ordine di taglio «{name}» creato"},
    "parts.list_done": {
        "de": "Der Sägeauftrag „{name}“ ist komplett gesägt, alle Teile sind bei ihren Projekten verbucht.\n\nAuftrag jetzt löschen?",
        "en": "Cut job “{name}” is fully cut; all parts are booked to their projects.\n\nDelete the job now?",
        "fr": "L’ordre de coupe « {name} » est entièrement coupé ; toutes les pièces sont comptées dans leurs projets.\n\nSupprimer l’ordre maintenant ?",
        "it": "L’ordine di taglio «{name}» è tutto tagliato; tutti i pezzi sono contati nei loro progetti.\n\nEliminare ora l’ordine?",
    },
    "parts.as_fill": {"de": "In Reste von … mitsägen", "en": "Cut into remnants of …", "fr": "Couper dans les chutes de …", "it": "Taglia negli sfridi di …"},
    "parts.fill_go": {"de": "Mitsägen", "en": "Add and cut", "fr": "Ajouter", "it": "Aggiungi"},
    "parts.fill_target": {"de": "In den Resten von Projekt", "en": "Into the remnants of project", "fr": "Dans les chutes du projet", "it": "Negli sfridi del progetto"},
    "parts.fill_hint": {
        "de": "Der Plan dieses Projekts wird gleich neu berechnet: Die Teile kommen in den Abfall seiner Stangen bzw. Platten (die Menge ist Obergrenze und hat Vorrang). Gesägt zählen sie bei ihrem eigenen Projekt, Überzählige kommen zu den Fertigteilen.",
        "en": "This project's plan is recalculated right away: the parts go into the waste of its bars or panels (the quantity is a maximum and takes priority). Once cut they count for their own project; any extra go to the finished parts.",
        "fr": "Le plan de ce projet est recalculé tout de suite : les pièces vont dans les chutes de ses barres ou panneaux (la quantité est un maximum prioritaire). Une fois coupées, elles comptent pour leur propre projet ; le surplus va aux pièces finies.",
        "it": "Il piano di questo progetto viene ricalcolato subito: i pezzi vanno negli scarti delle sue barre o pannelli (la quantità è un massimo con precedenza). Una volta tagliati contano per il loro progetto; quelli in più vanno ai pezzi finiti.",
    },
    "parts.fill_one_material": {"de": "Mitsägen geht nur mit Teilen aus einem Material.", "en": "Only parts of one material can be cut into remnants.", "fr": "Seules des pièces d’un même matériau peuvent être coupées dans les chutes.", "it": "Solo pezzi di un unico materiale possono essere tagliati negli sfridi."},
    "parts.fill_no_target": {"de": "Kein anderes Projekt mit offenen Teilen braucht dieses Material.", "en": "No other project with open parts uses this material.", "fr": "Aucun autre projet avec des pièces ouvertes n’utilise ce matériau.", "it": "Nessun altro progetto con pezzi aperti usa questo materiale."},
    "jobs.title": {"de": "Sägeaufträge", "en": "Cut jobs", "fr": "Ordres de coupe", "it": "Ordini di taglio"},
    "jobs.progress": {"de": "{done} von {total} gesägt", "en": "{done} of {total} cut", "fr": "{done} sur {total} coupées", "it": "{done} di {total} tagliati"},
    "jobs.continue": {"de": "Weitersägen", "en": "Continue cutting", "fr": "Continuer", "it": "Continua"},
    "jobs.show": {"de": "Ansehen", "en": "View", "fr": "Voir", "it": "Vedi"},
    "jobs.delete_confirm": {
        "de": "Sägeauftrag „{name}“ löschen? Bereits Gesägtes bleibt bei den Projekten verbucht.",
        "en": "Delete cut job “{name}”? Anything already cut stays booked to the projects.",
        "fr": "Supprimer l’ordre de coupe « {name} » ? Ce qui est déjà coupé reste compté dans les projets.",
        "it": "Eliminare l’ordine di taglio «{name}»? Quanto già tagliato resta contato nei progetti.",
    },
    # Vorlagen (Reiter Teile)
    "tpl.title": {"de": "Vorlagen", "en": "Templates", "fr": "Modèles", "it": "Modelli"},
    "tpl.new": {"de": "Neue Vorlage", "en": "New template", "fr": "Nouveau modèle", "it": "Nuovo modello"},
    "tpl.hint": {"de": "Stücklisten, die du immer wieder sägst. Speichere einen Sägeauftrag als Vorlage oder lege eine neue an – mit „Sägen ×N“ entsteht daraus jedes Mal ein neuer Sägeauftrag, berechnet mit dem aktuellen Lager.", "en": "Parts lists you cut again and again. Save a cut job as a template or create a new one – “Cut ×N” turns it into a fresh cut job each time, calculated with your current stock.", "fr": "Listes de pièces que vous découpez régulièrement. Enregistrez un ordre de coupe comme modèle ou créez-en un – « Découper ×N » en fait à chaque fois un nouvel ordre de coupe, calculé avec le stock actuel.", "it": "Distinte che tagli più volte. Salva un ordine di taglio come modello o creane uno nuovo – «Taglia ×N» ne ricava ogni volta un nuovo ordine di taglio, calcolato con il magazzino attuale."},
    "tpl.back": {"de": "← Teile", "en": "← Parts", "fr": "← Pièces", "it": "← Pezzi"},
    "tpl.run": {"de": "Sägen ×N…", "en": "Cut ×N…", "fr": "Découper ×N…", "it": "Taglia ×N…"},
    "tpl.run_title": {"de": "„{name}“ sägen", "en": "Cut “{name}”", "fr": "Découper « {name} »", "it": "Taglia «{name}»"},
    "tpl.run_go": {"de": "Anlegen und sägen →", "en": "Create and cut →", "fr": "Créer et découper →", "it": "Crea e taglia →"},
    "tpl.run_name_auto": {"de": "leer = Vorlage und Datum", "en": "empty = template and date", "fr": "vide = modèle et date", "it": "vuoto = modello e data"},
    "tpl.run_preview": {"de": "Ergibt {n} Teile aus {materialien}.", "en": "Makes {n} parts from {materialien}.", "fr": "Donne {n} pièces en {materialien}.", "it": "Risultano {n} pezzi da {materialien}."},
    "tpl.already_running": {"de": "Läuft schon: {name} ({done} von {total} gesägt)", "en": "Already running: {name} ({done} of {total} cut)", "fr": "Déjà en cours : {name} ({done} sur {total} coupées)", "it": "Già in corso: {name} ({done} di {total} tagliati)"},
    "tpl.sets": {"de": "Sätze", "en": "Sets", "fr": "Jeux", "it": "Set"},
    "tpl.sets_hint": {"de": "Wie oft die ganze Stückliste gesägt wird.", "en": "How many times the whole parts list is cut.", "fr": "Combien de fois toute la liste est découpée.", "it": "Quante volte si taglia l’intera distinta."},
    "tpl.sets_n": {"de": "{n}× Satz", "en": "{n}× set", "fr": "{n}× jeu", "it": "{n}× set"},
    "tpl.rename": {"de": "Umbenennen", "en": "Rename", "fr": "Renommer", "it": "Rinomina"},
    "tpl.restart_tip": {"de": "Wird das öfter gesägt? Dann besser „Als Vorlage speichern“ – jeder Durchgang bekommt seinen eigenen Sägeauftrag und das Projekt bleibt, wie es ist.", "en": "Cut this regularly? Then “Save as template” works better – every run gets its own cut job and the project stays as it is.", "fr": "Vous le découpez régulièrement ? Mieux vaut « Enregistrer comme modèle » – chaque passage reçoit son propre ordre de coupe et le projet reste tel quel.", "it": "Lo tagli spesso? Meglio «Salva come modello» – ogni passaggio ha il suo ordine di taglio e il progetto resta com’è."},
    "tpl.material_delete": {"de": "- Auch aus diesen Vorlagen verschwinden die Teile: {namen}", "en": "- The parts also disappear from these templates: {namen}", "fr": "- Les pièces disparaissent aussi de ces modèles : {namen}", "it": "- I pezzi spariscono anche da questi modelli: {namen}"},
    "tpl.delete": {"de": "Vorlage löschen", "en": "Delete template", "fr": "Supprimer le modèle", "it": "Elimina modello"},
    "tpl.name": {"de": "Name", "en": "Name", "fr": "Nom", "it": "Nome"},
    "tpl.col_part": {"de": "Teil", "en": "Part", "fr": "Pièce", "it": "Pezzo"},
    "tpl.col_material": {"de": "Material", "en": "Material", "fr": "Matériau", "it": "Materiale"},
    "tpl.col_grain": {"de": "Maserung", "en": "Grain", "fr": "Fil", "it": "Venatura"},
    "tpl.dims": {"de": "Maße", "en": "Size", "fr": "Dimensions", "it": "Misure"},
    "tpl.per_set": {"de": "Stück je Satz", "en": "Qty per set", "fr": "Qté par jeu", "it": "Pz. per set"},
    "tpl.runs": {"de": "Verlauf", "en": "History", "fr": "Historique", "it": "Cronologia"},
    "tpl.no_runs": {"de": "Noch nie gesägt.", "en": "Never cut yet.", "fr": "Jamais découpé.", "it": "Mai tagliato."},
    "tpl.empty": {"de": "Noch keine Teile – lege welche an oder importiere eine CSV-Datei.", "en": "No parts yet – add some or import a CSV file.", "fr": "Pas encore de pièces – ajoutez-en ou importez un fichier CSV.", "it": "Ancora nessun pezzo – aggiungine o importa un file CSV."},
    "tpl.summary": {"de": "{n} Teile · {m} Material(ien)", "en": "{n} parts · {m} material(s)", "fr": "{n} pièces · {m} matériau(x)", "it": "{n} pezzi · {m} materiale/i"},
    "tpl.last_run": {"de": "zuletzt {datum} · {n}× gesägt", "en": "last {datum} · cut {n}×", "fr": "dernier {datum} · découpé {n}×", "it": "ultimo {datum} · tagliato {n}×"},
    "tpl.never": {"de": "noch nie gesägt", "en": "never cut", "fr": "jamais découpé", "it": "mai tagliato"},
    "tpl.running": {"de": "{n} läuft", "en": "{n} running", "fr": "{n} en cours", "it": "{n} in corso"},
    "tpl.run_done": {"de": "fertig am {datum}", "en": "done on {datum}", "fr": "terminé le {datum}", "it": "finito il {datum}"},
    "tpl.run_deleted": {"de": "gelöscht bei {done} von {total}", "en": "deleted at {done} of {total}", "fr": "supprimé à {done} sur {total}", "it": "eliminato a {done} di {total}"},
    "tpl.created": {"de": "Vorlage „{name}“ gespeichert", "en": "Template “{name}” saved", "fr": "Modèle « {name} » enregistré", "it": "Modello «{name}» salvato"},
    "tpl.save_as": {"de": "Als Vorlage speichern", "en": "Save as template", "fr": "Enregistrer comme modèle", "it": "Salva come modello"},
    "tpl.save_as_hint": {"de": "Die Vorlage übernimmt {n} Teile ({materialien}) mit Maßen und Stückzahl. Das Original bleibt unverändert.", "en": "The template takes {n} parts ({materialien}) with sizes and quantities. The original stays unchanged.", "fr": "Le modèle reprend {n} pièces ({materialien}) avec dimensions et quantités. L’original reste inchangé.", "it": "Il modello riprende {n} pezzi ({materialien}) con misure e quantità. L’originale resta invariato."},
    "tpl.delete_confirm": {"de": "Vorlage „{name}“ löschen? Bereits angelegte Sägeaufträge bleiben erhalten.", "en": "Delete template “{name}”? Cut jobs already created are kept.", "fr": "Supprimer le modèle « {name} » ? Les ordres de coupe déjà créés sont conservés.", "it": "Eliminare il modello «{name}»? Gli ordini di taglio già creati restano."},
    "tpl.select_part": {"de": "Bitte ein Teil auswählen.", "en": "Please select a part.", "fr": "Veuillez sélectionner une pièce.", "it": "Seleziona un pezzo."},
    "tpl.keep_as": {"de": "Vorher als Vorlage speichern (zum Wiederholen)", "en": "Save as template first (to repeat it)", "fr": "Enregistrer d’abord comme modèle (pour le refaire)", "it": "Salva prima come modello (per ripeterlo)"},
    "tpl.delete_job": {"de": "Auftrag löschen", "en": "Delete job", "fr": "Supprimer l’ordre", "it": "Elimina ordine"},
    "tpl.keep_job": {"de": "Behalten", "en": "Keep", "fr": "Conserver", "it": "Tieni"},
    "tpl.run_finished": {"de": "„{name}“ ist komplett gesägt. Der Durchgang steht im Verlauf der Vorlage „{vorlage}“.\n\nSägeauftrag jetzt löschen?", "en": "“{name}” is fully cut. The run is listed in the history of template “{vorlage}”.\n\nDelete the cut job now?", "fr": "« {name} » est entièrement découpé. Le passage figure dans l’historique du modèle « {vorlage} ».\n\nSupprimer l’ordre de coupe maintenant ?", "it": "«{name}» è tutto tagliato. Il passaggio è nella cronologia del modello «{vorlage}».\n\nEliminare ora l’ordine di taglio?"},
    "jobs.from_template": {"de": "aus Vorlage „{name}“", "en": "from template “{name}”", "fr": "du modèle « {name} »", "it": "dal modello «{name}»"},
    # Reiter Einstellungen: Gruppen und Erklärungen
    "set.g_general": {"de": "Allgemein", "en": "General", "fr": "Général", "it": "Generale"},
    "set.g_saw": {"de": "Sägen", "en": "Sawing", "fr": "Sciage", "it": "Taglio"},
    "set.g_stock": {"de": "Lager", "en": "Stock", "fr": "Stock", "it": "Magazzino"},
    "set.g_labels": {"de": "Etiketten & Drucker", "en": "Labels & printer", "fr": "Étiquettes et imprimante", "it": "Etichette e stampante"},
    "set.g_data": {"de": "Daten", "en": "Data", "fr": "Données", "it": "Dati"},
    "set.g_connect": {"de": "Verbindungen", "en": "Connections", "fr": "Connexions", "it": "Connessioni"},
    "set.g_keys": {"de": "Tastenkürzel", "en": "Keyboard shortcuts", "fr": "Raccourcis clavier", "it": "Scorciatoie"},
    "set.g_about": {"de": "Über & Lizenz", "en": "About & license", "fr": "À propos et licence", "it": "Info e licenza"},
    "set.h_language": {
        "de": "Sprache der Oberfläche, der PDFs und Etiketten.",
        "en": "Language of the interface, PDFs and labels.",
        "fr": "Langue de l’interface, des PDF et des étiquettes.",
        "it": "Lingua dell’interfaccia, dei PDF e delle etichette.",
    },
    "set.h_unit": {
        "de": "Wie Längen angezeigt und eingegeben werden. Gespeichert wird immer in Millimetern. In Zoll gehen auch Brüche und Fuß: 1 3/4, 1-3/4\", 2' 1/4\", 8ft. Brüche werden auf 1/16\" gerundet.",
        "en": "How lengths are shown and entered. Everything is stored in millimetres. In inches you can also type fractions and feet: 1 3/4, 1-3/4\", 2' 1/4\", 8ft. Fractions are rounded to 1/16\".",
        "fr": "Comment les longueurs sont affichées et saisies. Tout est enregistré en millimètres. En pouces, les fractions et les pieds sont acceptés : 1 3/4, 1-3/4\", 2' 1/4\", 8ft. Les fractions sont arrondies au 1/16\".",
        "it": "Come vengono mostrate e inserite le lunghezze. Tutto viene salvato in millimetri. In pollici si possono inserire anche frazioni e piedi: 1 3/4, 1-3/4\", 2' 1/4\", 8ft. Le frazioni sono arrotondate a 1/16\".",
    },
    "set.h_unit_feet": {
        "de": "Längen ab 12\" als Fuß und Zoll zeigen (2' 1/4\" statt 24 1/4\").",
        "en": "Show lengths from 12\" as feet and inches (2' 1/4\" instead of 24 1/4\").",
        "fr": "Afficher les longueurs à partir de 12\" en pieds et pouces (2' 1/4\" au lieu de 24 1/4\").",
        "it": "Mostra le lunghezze da 12\" in piedi e pollici (2' 1/4\" invece di 24 1/4\").",
    },
    "set.h_theme": {
        "de": "Hell, dunkel oder wie im Betriebssystem eingestellt.",
        "en": "Light, dark or as set in the operating system.",
        "fr": "Clair, sombre ou selon le système d’exploitation.",
        "it": "Chiaro, scuro o come impostato nel sistema operativo.",
    },
    "set.h_blades": {
        "de": "Die Schnittbreite (Fuge) wird bei jedem Schnitt eingerechnet. Welches Sägeblatt ein Material standardmäßig nimmt, steht am Material; die Optimierung merkt sich das zuletzt verwendete.",
        "en": "The kerf is added for every cut. Which saw blade a material uses by default is set on the material; the optimization remembers the last one used.",
        "fr": "La largeur de coupe est comptée à chaque coupe. La lame par défaut d’un matériau se règle sur le matériau ; l’optimisation retient la dernière utilisée.",
        "it": "La larghezza di taglio viene considerata a ogni taglio. La lama predefinita di un materiale si imposta sul materiale; l’ottimizzazione ricorda l’ultima usata.",
    },
    "set.h_reservation": {
        "de": "Stücke in einem gespeicherten Plan werden für andere Projekte nicht verplant, bis sie gesägt sind oder der Plan verworfen wird.",
        "en": "Pieces in a saved plan are not planned for other projects until they are cut or the plan is discarded.",
        "fr": "Les pièces d’un plan enregistré ne sont pas utilisées pour d’autres projets tant qu’elles ne sont pas coupées ou que le plan n’est pas abandonné.",
        "it": "I pezzi di un piano salvato non vengono pianificati per altri progetti finché non sono tagliati o il piano viene scartato.",
    },
    "set.h_waste_min": {
        "de": "Noch kleinere Abschnitte werden weggeworfen. Nur wirksam, wenn die Abfallkiste eingeschaltet ist.",
        "en": "Even smaller offcuts are thrown away. Only applies when the offcut bin is switched on.",
        "fr": "Les chutes encore plus petites sont jetées. Uniquement si le bac à chutes est activé.",
        "it": "I ritagli ancora più piccoli vengono buttati. Vale solo se la cassa dei ritagli è attiva.",
    },
    "set.h_label_format": {
        "de": "A4-Bögen druckt jeder Drucker; angebrochene Bögen nutzt das „Startfeld“ im Etiketten-Dialog. Rollen und Endlos-Band sind für Etikettendrucker (z. B. Brother QL, Dymo): ein Etikett je Seite, gedruckt über den Druckdialog des Treibers. Kleine Etiketten zeigen nur, was lesbar passt – zuerst Code bzw. Teil, dann das Maß.",
        "en": "Any printer prints A4 sheets; part-used sheets use the “start field” in the label dialog. Rolls and continuous tape are for label printers (e.g. Brother QL, Dymo): one label per page, printed via the driver’s print dialog. Small labels show only what fits legibly – code or part first, then the size.",
        "fr": "Toute imprimante imprime les planches A4 ; les planches entamées utilisent le « champ de départ » du dialogue d’étiquettes. Rouleaux et ruban continu sont pour les imprimantes d’étiquettes (p. ex. Brother QL, Dymo) : une étiquette par page, via la boîte d’impression du pilote. Les petites étiquettes n’affichent que ce qui reste lisible – d’abord le code ou la pièce, puis la cote.",
        "it": "Qualsiasi stampante stampa fogli A4; per i fogli iniziati c’è il «campo iniziale» nel dialogo etichette. Rotoli e nastro continuo sono per stampanti di etichette (es. Brother QL, Dymo): un’etichetta per pagina, stampata dal dialogo del driver. Le etichette piccole mostrano solo ciò che resta leggibile – prima il codice o il pezzo, poi la misura.",
    },
    "set.h_label_custom": {
        "de": "Nur bei „Benutzerdefiniert“: Breite × Höhe eines Etiketts, mindestens 15 × 10 mm.",
        "en": "Only with “Custom”: width × height of one label, at least 15 × 10 mm.",
        "fr": "Seulement avec « Personnalisé » : largeur × hauteur d’une étiquette, au moins 15 × 10 mm.",
        "it": "Solo con «Personalizzato»: larghezza × altezza di un’etichetta, almeno 15 × 10 mm.",
    },
    "set.h_backup": {
        "de": "Ein Backup ist eine ZIP-Datei mit allen Daten (Material, Lager, Projekte, Pläne, Einstellungen). Wiederherstellen ersetzt alle aktuellen Daten durch die aus dem Backup.",
        "en": "A backup is a ZIP file with all data (material, stock, projects, plans, settings). Restoring replaces all current data with the backup.",
        "fr": "Une sauvegarde est un fichier ZIP avec toutes les données (matériaux, stock, projets, plans, réglages). La restauration remplace toutes les données actuelles.",
        "it": "Un backup è un file ZIP con tutti i dati (materiali, magazzino, progetti, piani, impostazioni). Il ripristino sostituisce tutti i dati attuali.",
    },
    "set.h_api_enabled": {
        "de": "Erlaubt anderen Programmen (z. B. Skripten oder Home Assistant), CutStock über das Netzwerk zu steuern.",
        "en": "Lets other programs (e.g. scripts or Home Assistant) control CutStock over the network.",
        "fr": "Permet à d’autres programmes (scripts, Home Assistant…) de piloter CutStock via le réseau.",
        "it": "Permette ad altri programmi (script, Home Assistant…) di controllare CutStock via rete.",
    },
    "set.h_api_port": {
        "de": "Port der Desktop-App für die API. Wird nach einem Neustart wirksam.",
        "en": "Port of the desktop app for the API. Takes effect after a restart.",
        "fr": "Port de l’application de bureau pour l’API. Effectif après redémarrage.",
        "it": "Porta dell’app desktop per l’API. Attiva dopo un riavvio.",
    },
    "set.h_api_key": {
        "de": "Mit Key müssen andere Programme „Authorization: Bearer“ und den Key mitsenden. Ohne Key ist die API für jeden erreichbar, der CutStock im Netzwerk erreicht.",
        "en": "With a key, other programs must send “Authorization: Bearer” plus the key. Without a key, anyone who can reach CutStock on the network can use the API.",
        "fr": "Avec une clé, les autres programmes doivent envoyer « Authorization: Bearer » et la clé. Sans clé, l’API est accessible à quiconque atteint CutStock sur le réseau.",
        "it": "Con una chiave, gli altri programmi devono inviare «Authorization: Bearer» e la chiave. Senza chiave, l’API è raggiungibile da chiunque raggiunga CutStock in rete.",
    },
    "labels.custom_size": {"de": "Eigenes Maß (mm):", "en": "Custom size (mm):", "fr": "Taille personnalisée (mm) :", "it": "Misura personalizzata (mm):"},
    "labels.preview": {"de": "Vorschau:", "en": "Preview:", "fr": "Aperçu :", "it": "Anteprima:"},
    "labels.preview_info": {
        "de": "Musteretikett {mass}, so wie es gedruckt wird.",
        "en": "Sample label {mass}, as it will be printed.",
        "fr": "Étiquette exemple {mass}, telle qu’imprimée.",
        "it": "Etichetta di esempio {mass}, come verrà stampata.",
    },
    "labels.endless_hint": {
        "de": "Bei Endlos-Band richtet sich die Länge nach dem Inhalt.",
        "en": "With continuous tape the length follows the content.",
        "fr": "Avec le ruban continu, la longueur suit le contenu.",
        "it": "Con il nastro continuo la lunghezza segue il contenuto.",
    },
    "labels.endless": {"de": "{h} mm endlos", "en": "{h} mm continuous", "fr": "{h} mm continu", "it": "{h} mm continuo"},
    "labels.per_sheet": {"de": "{n} je Bogen", "en": "{n} per sheet", "fr": "{n} par planche", "it": "{n} per foglio"},
    "labels.g_bogen": {"de": "A4-Bögen", "en": "A4 sheets", "fr": "Planches A4", "it": "Fogli A4"},
    "labels.g_bogen_klein": {"de": "A4-Bögen, kleine Etiketten", "en": "A4 sheets, small labels", "fr": "Planches A4, petites étiquettes", "it": "Fogli A4, etichette piccole"},
    "labels.g_rolle": {"de": "Rollen (Etikettendrucker)", "en": "Rolls (label printer)", "fr": "Rouleaux (imprimante d’étiquettes)", "it": "Rotoli (stampante di etichette)"},
    "labels.g_rolle_klein": {"de": "Rollen, kleine Etiketten", "en": "Rolls, small labels", "fr": "Rouleaux, petites étiquettes", "it": "Rotoli, etichette piccole"},
    "labels.g_endlos": {"de": "Endlos-Band", "en": "Continuous tape", "fr": "Ruban continu", "it": "Nastro continuo"},
    # Reiter Optimierung: Arbeitsliste, Hauptaktion je Stand
    "mat.blade": {"de": "Sägeblatt", "en": "Saw blade", "fr": "Lame de scie", "it": "Lama"},
    "mat.blade_first": {"de": "– erstes Sägeblatt –", "en": "– first saw blade –", "fr": "– première lame –", "it": "– prima lama –"},
    "wl.title": {"de": "Was sägen?", "en": "What to cut?", "fr": "Que couper ?", "it": "Cosa tagliare?"},
    "wl.search": {"de": "Suchen…", "en": "Search…", "fr": "Rechercher…", "it": "Cerca…"},
    "wl.show_done": {"de": "auch fertige zeigen", "en": "show finished too", "fr": "afficher aussi les terminés", "it": "mostra anche i finiti"},
    "wl.group_sammel": {"de": "Sammelpläne", "en": "Combined plans", "fr": "Plans groupés", "it": "Piani combinati"},
    "wl.group_jobs": {"de": "Sägeaufträge", "en": "Cut jobs", "fr": "Ordres de coupe", "it": "Ordini di taglio"},
    "wl.group_projects": {"de": "Projekte", "en": "Projects", "fr": "Projets", "it": "Progetti"},
    "wl.empty": {
        "de": "Nichts zu sägen. Teile legst du im Reiter Projekte an.",
        "en": "Nothing to cut. Add parts in the Projects tab.",
        "fr": "Rien à couper. Ajoutez des pièces dans l’onglet Projets.",
        "it": "Niente da tagliare. Aggiungi pezzi nella scheda Progetti.",
    },
    "wl.n_materials": {"de": "{n} Materialien", "en": "{n} materials", "fr": "{n} matériaux", "it": "{n} materiali"},
    "wl.tag_job": {"de": "Sägeauftrag", "en": "Cut job", "fr": "Ordre de coupe", "it": "Ordine di taglio"},
    "wl.no_match": {"de": "Nichts gefunden.", "en": "Nothing found.", "fr": "Aucun résultat.", "it": "Nessun risultato."},
    "wl.pick": {
        "de": "Wähle links aus, was du sägen willst.",
        "en": "Pick on the left what you want to cut.",
        "fr": "Choisissez à gauche ce que vous voulez couper.",
        "it": "Scegli a sinistra cosa vuoi tagliare.",
    },
    "wl.st_kein_plan": {"de": "noch kein Plan", "en": "no plan yet", "fr": "pas encore de plan", "it": "nessun piano"},
    "wl.st_bereit": {"de": "Plan bereit · {done}/{total}", "en": "plan ready · {done}/{total}", "fr": "plan prêt · {done}/{total}", "it": "piano pronto · {done}/{total}"},
    "wl.st_in_arbeit": {"de": "in Arbeit · {done}/{total}", "en": "in progress · {done}/{total}", "fr": "en cours · {done}/{total}", "it": "in corso · {done}/{total}"},
    "wl.st_veraltet": {"de": "Plan veraltet", "en": "plan outdated", "fr": "plan obsolète", "it": "piano superato"},
    "wl.st_fertig": {"de": "fertig", "en": "finished", "fr": "terminé", "it": "finito"},
    "wl.st_sammel": {"de": "im Sammelplan", "en": "in combined plan", "fr": "dans le plan groupé", "it": "nel piano combinato"},
    "wl.resize": {"de": "Ziehen, um die Breite zu ändern", "en": "Drag to change the width", "fr": "Glisser pour changer la largeur", "it": "Trascina per cambiare la larghezza"},
    "wl.st_job": {"de": "im {name}", "en": "in {name}", "fr": "dans {name}", "it": "in {name}"},
    "wl.st_jobs": {"de": "in {n} Sägeaufträgen", "en": "in {n} cut jobs", "fr": "dans {n} ordres de coupe", "it": "in {n} ordini di taglio"},
    "wl.st_verplant": {"de": "anderswo verplant", "en": "planned elsewhere", "fr": "prévu ailleurs", "it": "pianificato altrove"},
    "wl.open_parts": {"de": "{teile} Teile · {n} Stück offen", "en": "{teile} parts · {n} pieces open", "fr": "{teile} pièces · {n} exemplaires à couper", "it": "{teile} pezzi · {n} da tagliare"},
    "wl.open_one": {"de": "1 Teil · {n} Stück offen", "en": "1 part · {n} pieces open", "fr": "1 pièce · {n} exemplaires à couper", "it": "1 pezzo · {n} da tagliare"},
    "wl.reason_teile": {"de": "Teile oder Material wurden geändert", "en": "parts or material changed", "fr": "pièces ou matériau modifiés", "it": "pezzi o materiale modificati"},
    "wl.reason_anderswo": {"de": "Teile wurden inzwischen anderswo gesägt", "en": "parts were cut elsewhere meanwhile", "fr": "des pièces ont été coupées ailleurs entre-temps", "it": "alcuni pezzi sono stati tagliati altrove"},
    "wl.reason_lager": {"de": "eingeplante Lagerstücke fehlen", "en": "planned stock pieces are missing", "fr": "des pièces de stock prévues manquent", "it": "mancano pezzi di magazzino pianificati"},
    "wl.outdated": {"de": "Plan veraltet: {reason}", "en": "Plan outdated: {reason}", "fr": "Plan obsolète : {reason}", "it": "Piano superato: {reason}"},
    "wl.together": {
        "de": "{material} wird auch in {names} gebraucht – zusammen sägen?",
        "en": "{material} is also needed in {names} – cut together?",
        "fr": "{material} sert aussi dans {names} – couper ensemble ?",
        "it": "{material} serve anche in {names} – tagliare insieme?",
    },
    "wl.together_go": {"de": "Sammelplan anlegen", "en": "Create combined plan", "fr": "Créer un plan groupé", "it": "Crea piano combinato"},
    "wl.verplant_jobs": {
        "de": "Alle offenen Teile stecken schon in: {names}.",
        "en": "All open parts are already in: {names}.",
        "fr": "Toutes les pièces à couper sont déjà dans : {names}.",
        "it": "Tutti i pezzi da tagliare sono già in: {names}.",
    },
    "wl.verplant_hint": {
        "de": "Alle offenen Teile stecken schon in einem Sägeauftrag oder einem anderen Plan.",
        "en": "All open parts are already in a cut job or another plan.",
        "fr": "Toutes les pièces à couper sont déjà dans un ordre de coupe ou un autre plan.",
        "it": "Tutti i pezzi da tagliare sono già in un ordine di taglio o in un altro piano.",
    },
    "wl.done_hint": {"de": "Fertig gesägt.", "en": "All cut.", "fr": "Tout est coupé.", "it": "Tutto tagliato."},
    "opt.calc": {"de": "Schnittplan berechnen", "en": "Calculate cutting plan", "fr": "Calculer le plan de coupe", "it": "Calcola piano di taglio"},
    "opt.to_saw": {"de": "An die Säge →", "en": "To the saw →", "fr": "À la scie →", "it": "Alla sega →"},
    "opt.recalc": {"de": "Neu berechnen", "en": "Recalculate", "fr": "Recalculer", "it": "Ricalcola"},
    "opt.more": {"de": "Mehr", "en": "More", "fr": "Plus", "it": "Altro"},
    "opt.mark_all": {"de": "Alles als gesägt markieren…", "en": "Mark everything as cut…", "fr": "Tout marquer comme coupé…", "it": "Segna tutto come tagliato…"},
    "opt.settings": {"de": "Einstellungen", "en": "Settings", "fr": "Réglages", "it": "Impostazioni"},
    "opt.rests_first_off": {"de": "Reste zuerst aus", "en": "remnants first off", "fr": "chutes d’abord désactivé", "it": "prima gli sfridi no"},
    "opt.max_short": {"de": "max. {n} je Stange", "en": "max. {n} per bar", "fr": "max. {n} par barre", "it": "max. {n} per barra"},
    "opt.algo_fast": {"de": "Schnell", "en": "Fast", "fr": "Rapide", "it": "Veloce"},
    "opt.algo_standard": {"de": "Standard", "en": "Standard", "fr": "Standard", "it": "Standard"},
    "opt.algo_thorough": {"de": "Gründlich", "en": "Thorough", "fr": "Approfondi", "it": "Accurato"},
    "opt.calc_mode": {"de": "Rechenart", "en": "Calculation", "fr": "Calcul", "it": "Calcolo"},
    "stat.line_parts": {"de": "{n} Teile", "en": "{n} parts", "fr": "{n} pièces", "it": "{n} pezzi"},
    "stat.line_used": {"de": "{p} % genutzt", "en": "{p} % used", "fr": "{p} % utilisé", "it": "{p} % usato"},
    "stat.line_waste": {"de": "Abfall {p} %", "en": "waste {p} %", "fr": "déchet {p} %", "it": "scarto {p} %"},
    "stat.missing_box": {
        "de": "Material reicht nicht – {n} Teile können nicht gesägt werden: {labels}",
        "en": "Not enough material – {n} parts can’t be cut: {labels}",
        "fr": "Matériau insuffisant – {n} pièces ne peuvent pas être découpées : {labels}",
        "it": "Materiale insufficiente – {n} pezzi non possono essere tagliati: {labels}",
    },
    "stat.missing_box_one": {
        "de": "Material reicht nicht – 1 Teil kann nicht gesägt werden: {labels}",
        "en": "Not enough material – 1 part can’t be cut: {labels}",
        "fr": "Matériau insuffisant – 1 pièce ne peut pas être découpée : {labels}",
        "it": "Materiale insufficiente – 1 pezzo non può essere tagliato: {labels}",
    },
    "stat.too_long": {
        "de": "Länger als jede Stange im Lager: {labels}",
        "en": "Longer than any bar in stock: {labels}",
        "fr": "Plus long que toute barre en stock : {labels}",
        "it": "Più lungo di ogni barra in magazzino: {labels}",
    },
    "stat.too_big": {
        "de": "Größer als jede Platte im Lager: {labels}",
        "en": "Larger than any panel in stock: {labels}",
        "fr": "Plus grand que tout panneau en stock : {labels}",
        "it": "Più grande di ogni pannello in magazzino: {labels}",
    },
    "stat.buy": {"de": "Nachkaufen: {list}", "en": "To buy: {list}", "fr": "À acheter : {list}", "it": "Da acquistare: {list}"},
    "opt.max_hint": {
        "de": "Max. je Stange: höchstens so viele Teile auf eine Stange, auch wenn mehr passen – lässt Platz für Füllteile. Leer = keine Grenze.",
        "en": "Max. per bar: at most this many parts per bar, even if more would fit – leaves room for filler parts. Empty = no limit.",
        "fr": "Max. par barre : au plus ce nombre de pièces par barre, même si davantage tiendrait – laisse de la place pour les pièces de remplissage. Vide = sans limite.",
        "it": "Max. per barra: al massimo questo numero di pezzi per barra, anche se ne entrerebbero di più – lascia spazio per i pezzi di riempimento. Vuoto = nessun limite.",
    },
    "proj.restart_hint": {
        "de": "Fortschritt auf 0 und Pläne löschen, um das Projekt noch einmal zu sägen",
        "en": "Reset progress and delete plans to cut the project once more",
        "fr": "Remettre la progression à 0 et supprimer les plans pour recouper le projet",
        "it": "Azzera l’avanzamento ed elimina i piani per tagliare di nuovo il progetto",
    },
    "sammel.badge": {"de": "Sammelplan", "en": "Combined plan", "fr": "Plan groupé", "it": "Piano combinato"},
    "sammel.open": {"de": "Sammelplan öffnen", "en": "Open combined plan", "fr": "Ouvrir le plan groupé", "it": "Apri piano combinato"},
    "sammel.list_title": {"de": "Sammelpläne", "en": "Combined plans", "fr": "Plans groupés", "it": "Piani combinati"},
    "sammel.list_empty": {
        "de": "Noch kein Sammelplan. Mit „Neu“ sägst du mehrere Projekte aus einem Material gemeinsam.",
        "en": "No combined plan yet. Use “New” to cut several projects from one material together.",
        "fr": "Aucun plan groupé. Avec « Nouveau », découpez plusieurs projets dans un même matériau.",
        "it": "Nessun piano combinato. Con «Nuovo» tagli insieme più progetti dallo stesso materiale.",
    },
    "sammel.new_title": {"de": "Neuer Sammelplan", "en": "New combined plan", "fr": "Nouveau plan groupé", "it": "Nuovo piano combinato"},
    "sammel.rename_title": {"de": "Sammelplan umbenennen", "en": "Rename combined plan", "fr": "Renommer le plan groupé", "it": "Rinomina piano combinato"},
    "sammel.select": {"de": "Bitte einen Sammelplan auswählen.", "en": "Please select a combined plan.", "fr": "Veuillez choisir un plan groupé.", "it": "Seleziona un piano combinato."},
    "sammel.no_material": {"de": "Kein Projekt hat offene Teile.", "en": "No project has open parts.", "fr": "Aucun projet n’a de pièces ouvertes.", "it": "Nessun progetto ha pezzi aperti."},
    "sammel.exists": {
        "de": "Für dieses Material gibt es schon „{name}“ – er wird geöffnet.",
        "en": "This material already has “{name}” – opening it.",
        "fr": "Ce matériau a déjà « {name} » – il est ouvert.",
        "it": "Questo materiale ha già «{name}» – viene aperto.",
    },
    "sammel.members": {"de": "Mitglieder", "en": "Members", "fr": "Membres", "it": "Membri"},
    "sammel.readonly": {
        "de": "Nur Ansicht – die Teile bearbeitest du im jeweiligen Projekt.",
        "en": "View only – edit the parts in their own project.",
        "fr": "Lecture seule – modifiez les pièces dans leur propre projet.",
        "it": "Sola lettura – modifica i pezzi nel loro progetto.",
    },
    "sammel.no_parts": {"de": "Keine Teile in diesem Material.", "en": "No parts in this material.", "fr": "Aucune pièce dans ce matériau.", "it": "Nessun pezzo in questo materiale."},
    "sammel.part_hint": {
        "de": "Wird im Sammelplan gesägt – klicken öffnet ihn",
        "en": "Cut in the combined plan – click to open it",
        "fr": "Découpée dans le plan groupé – cliquer pour l’ouvrir",
        "it": "Tagliato nel piano combinato – clic per aprirlo",
    },
    "sammel.icon_title": {"de": "Im Sammelplan: {names}", "en": "In combined plan: {names}", "fr": "Dans le plan groupé : {names}", "it": "Nel piano combinato: {names}"},
    "sammel.delete_confirm": {
        "de": "Sammelplan „{name}“ löschen?\n\nDie Projekte und ihre Teile bleiben erhalten.",
        "en": "Delete combined plan “{name}”?\n\nThe projects and their parts stay.",
        "fr": "Supprimer le plan groupé « {name} » ?\n\nLes projets et leurs pièces restent.",
        "it": "Eliminare il piano combinato «{name}»?\n\nI progetti e i loro pezzi restano.",
    },
    "sammel.delete_sawn": {
        "de": "Achtung: {done} von {total} Stück sind schon gesägt. Sie bleiben in den Projekten als gesägt; der Rest wird wieder offen, reservierte Lagerstücke werden frei.",
        "en": "Caution: {done} of {total} pieces are already cut. They stay cut in the projects; the rest becomes open again and reserved stock is released.",
        "fr": "Attention : {done} sur {total} pièces sont déjà découpées. Elles restent découpées dans les projets ; le reste redevient ouvert et le stock réservé est libéré.",
        "it": "Attenzione: {done} di {total} pezzi sono già tagliati. Restano tagliati nei progetti; il resto torna aperto e il magazzino riservato viene liberato.",
    },
    "sammel.delete_plan": {
        "de": "Der berechnete Schnittplan wird verworfen, reservierte Lagerstücke werden frei.",
        "en": "The calculated cutting plan is discarded and reserved stock is released.",
        "fr": "Le plan de coupe calculé est abandonné et le stock réservé est libéré.",
        "it": "Il piano di taglio calcolato viene scartato e il magazzino riservato viene liberato.",
    },
    # ---- Lager: Reiter, Lagerorte, Abfallkiste, Entnahme ----
    "tab.material": {"de": "Material", "en": "Material", "fr": "Matériau", "it": "Materiale"},
    "tab.stock": {"de": "Lager", "en": "Stock", "fr": "Stock", "it": "Magazzino"},
    "loc.title": {"de": "Lagerorte", "en": "Locations", "fr": "Emplacements", "it": "Ubicazioni"},
    "loc.name": {"de": "Name", "en": "Name", "fr": "Nom", "it": "Nome"},
    "loc.materials": {"de": "Materialien", "en": "Materials", "fr": "Matériaux", "it": "Materiali"},
    "loc.pieces": {"de": "Stücke", "en": "Pieces", "fr": "Pièces", "it": "Pezzi"},
    "loc.contents": {"de": "Inhalt", "en": "Contents", "fr": "Contenu", "it": "Contenuto"},
    "loc.rename_btn": {"de": "Umbenennen", "en": "Rename", "fr": "Renommer", "it": "Rinomina"},
    "loc.new": {"de": "Neuer Lagerort", "en": "New location", "fr": "Nouvel emplacement", "it": "Nuova ubicazione"},
    "loc.new_option": {"de": "+ Neuer Lagerort …", "en": "+ New location …", "fr": "+ Nouvel emplacement …", "it": "+ Nuova ubicazione …"},
    "loc.new_placeholder": {"de": "Name des neuen Lagerorts", "en": "Name of the new location", "fr": "Nom du nouvel emplacement", "it": "Nome della nuova ubicazione"},
    "loc.rename": {"de": "Lagerort umbenennen", "en": "Rename location", "fr": "Renommer l’emplacement", "it": "Rinomina ubicazione"},
    "loc.select": {"de": "Bitte einen Lagerort wählen.", "en": "Please select a location.", "fr": "Veuillez choisir un emplacement.", "it": "Seleziona un’ubicazione."},
    "loc.empty": {"de": "An diesem Lagerort liegt nichts.", "en": "Nothing is stored at this location.", "fr": "Rien n’est stocké à cet emplacement.", "it": "In questa ubicazione non c’è nulla."},
    "loc.rests_only": {"de": "nur Reste", "en": "offcuts only", "fr": "chutes seulement", "it": "solo ritagli"},
    "loc.to_material": {"de": "Zum Material", "en": "Go to material", "fr": "Vers le matériau", "it": "Al materiale"},
    "loc.piece_hint": {"de": "Klicken: Notiz oder entnehmen", "en": "Click: note or take out", "fr": "Cliquer : note ou retirer", "it": "Clic: nota o preleva"},
    "loc.delete_confirm": {"de": "Lagerort „{name}“ löschen?", "en": "Delete location “{name}”?", "fr": "Supprimer l’emplacement « {name} » ?", "it": "Eliminare l’ubicazione “{name}”?"},
    "loc.delete_title": {"de": "„{name}“ löschen", "en": "Delete “{name}”", "fr": "Supprimer « {name} »", "it": "Elimina “{name}”"},
    "loc.move_to": {"de": "Materialien verschieben nach", "en": "Move materials to", "fr": "Déplacer les matériaux vers", "it": "Sposta i materiali in"},
    "loc.in_use": {"de": "Hier liegt noch: {list}. Diese Materialien kommen an den gewählten Ort.", "en": "Still stored here: {list}. These materials move to the chosen location.", "fr": "Encore stocké ici : {list}. Ces matériaux vont à l’emplacement choisi.", "it": "Qui c’è ancora: {list}. Questi materiali vanno nell’ubicazione scelta."},
    "loc.waste_box": {"de": "Abfallkiste", "en": "Offcut bin", "fr": "Bac à chutes", "it": "Cassa sfridi"},
    "loc.waste_empty": {"de": "Die Abfallkiste ist leer.", "en": "The offcut bin is empty.", "fr": "Le bac à chutes est vide.", "it": "La cassa sfridi è vuota."},
    "loc.waste_off_hint": {"de": "Die Abfallkiste ist ausgeschaltet – neue Abschnitte werden weggeworfen (Einstellungen > Lager).", "en": "The offcut bin is switched off – new offcuts are thrown away (Settings > Stock).", "fr": "Le bac à chutes est désactivé – les nouvelles chutes sont jetées (Paramètres > Stock).", "it": "La cassa sfridi è disattivata – i nuovi ritagli vengono buttati (Impostazioni > Magazzino)."},
    "loc.waste_take": {"de": "1 entnehmen", "en": "Take 1", "fr": "En retirer 1", "it": "Preleva 1"},
    "loc.waste_clear": {"de": "Kiste leeren", "en": "Empty bin", "fr": "Vider le bac", "it": "Svuota cassa"},
    "loc.waste_clear_mat": {"de": "Wegwerfen", "en": "Throw away", "fr": "Jeter", "it": "Butta"},
    "loc.waste_clear_confirm": {"de": "Die ganze Abfallkiste leeren?", "en": "Empty the whole offcut bin?", "fr": "Vider tout le bac à chutes ?", "it": "Svuotare tutta la cassa sfridi?"},
    "loc.waste_clear_mat_confirm": {"de": "Alle Abschnitte von {name} wegwerfen?", "en": "Throw away all offcuts of {name}?", "fr": "Jeter toutes les chutes de {name} ?", "it": "Buttare tutti i ritagli di {name}?"},
    "stock.rests_at": {"de": "Reste: {ort}", "en": "Offcuts: {ort}", "fr": "Chutes : {ort}", "it": "Ritagli: {ort}"},
    "stock.waste_hint": {"de": "+ {n} in der Abfallkiste", "en": "+ {n} in the offcut bin", "fr": "+ {n} dans le bac à chutes", "it": "+ {n} nella cassa sfridi"},
    "mat.location_rest_same": {"de": "(gleicher Ort)", "en": "(same location)", "fr": "(même emplacement)", "it": "(stessa ubicazione)"},
    "lbl.title": {"de": "Etiketten drucken", "en": "Print labels", "fr": "Imprimer des étiquettes", "it": "Stampa etichette"},
    "lbl.all": {"de": "Alle", "en": "All", "fr": "Toutes", "it": "Tutte"},
    "lbl.none": {"de": "Keine", "en": "None", "fr": "Aucune", "it": "Nessuna"},
    "lbl.unprinted": {"de": "Noch nicht gedruckt", "en": "Not printed yet", "fr": "Pas encore imprimées", "it": "Non ancora stampate"},
    "lbl.rests": {"de": "Nur Reste", "en": "Offcuts only", "fr": "Chutes seulement", "it": "Solo ritagli"},
    "lbl.whole": {"de": "Nur ganze Stücke", "en": "Whole pieces only", "fr": "Pièces entières seulement", "it": "Solo pezzi interi"},
    "lbl.new_badge": {"de": "neu", "en": "new", "fr": "nouveau", "it": "nuovo"},
    "lbl.start": {"de": "Beginnen bei Feld", "en": "Start at field", "fr": "Commencer au champ", "it": "Inizia dal campo"},
    "lbl.start_hint": {"de": "Für angebrochene Bögen: 1 = oben links, dann zeilenweise bis {n}.", "en": "For partly used sheets: 1 = top left, then row by row up to {n}.", "fr": "Pour les planches entamées : 1 = en haut à gauche, puis ligne par ligne jusqu’à {n}.", "it": "Per fogli già usati: 1 = in alto a sinistra, poi riga per riga fino a {n}."},
    "lbl.print_n": {"de": "{n} drucken", "en": "Print {n}", "fr": "Imprimer {n}", "it": "Stampa {n}"},
    "lbl.piece": {"de": "Etikett drucken", "en": "Print label", "fr": "Imprimer l’étiquette", "it": "Stampa etichetta"},
    "lbl.printed_at": {"de": "Etikett zuletzt gedruckt am {datum}", "en": "Label last printed on {datum}", "fr": "Étiquette imprimée le {datum}", "it": "Etichetta stampata il {datum}"},
    "lbl.never": {"de": "Für dieses Stück wurde noch kein Etikett gedruckt.", "en": "No label has been printed for this piece yet.", "fr": "Aucune étiquette n’a encore été imprimée pour cette pièce.", "it": "Per questo pezzo non è ancora stata stampata un’etichetta."},
    "labels.button_dlg": {"de": "Etiketten …", "en": "Labels …", "fr": "Étiquettes …", "it": "Etichette …"},
    "piece.take": {"de": "Entnehmen …", "en": "Take out …", "fr": "Retirer …", "it": "Preleva …"},
    "piece.take_btn": {"de": "Entnehmen", "en": "Take out", "fr": "Retirer", "it": "Preleva"},
    "piece.take_hint": {"de": "Nimmt das Stück aus dem Lager (wird im Lagerjournal vermerkt).", "en": "Removes the piece from stock (recorded in the stock journal).", "fr": "Retire la pièce du stock (noté dans le journal).", "it": "Toglie il pezzo dal magazzino (registrato nel giornale)."},
    "piece.take_title": {"de": "{code} entnehmen", "en": "Take out {code}", "fr": "Retirer {code}", "it": "Preleva {code}"},
    "piece.take_reason": {"de": "Grund", "en": "Reason", "fr": "Motif", "it": "Motivo"},
    "piece.take_reserved": {
        "de": "{code} ist für „{projekt}“ reserviert.\nTrotzdem entnehmen? Der Plan von „{projekt}“ muss danach neu optimiert werden.",
        "en": "{code} is reserved for “{projekt}”.\nTake it out anyway? The plan of “{projekt}” will need to be optimized again.",
        "fr": "{code} est réservé pour « {projekt} ».\nLe retirer quand même ? Le plan de « {projekt} » devra être réoptimisé.",
        "it": "{code} è riservato per “{projekt}”.\nPrelevarlo comunque? Il piano di “{projekt}” andrà ottimizzato di nuovo.",
    },
    "piece.taken": {"de": "{code} entnommen", "en": "{code} taken out", "fr": "{code} retiré", "it": "{code} prelevato"},
    "piece.taken_box": {"de": "{code} liegt jetzt in der Abfallkiste", "en": "{code} is now in the offcut bin", "fr": "{code} est maintenant dans le bac à chutes", "it": "{code} ora è nella cassa sfridi"},
    "take.verbraucht": {"de": "Verbraucht", "en": "Used", "fr": "Utilisé", "it": "Usato"},
    "take.verkauft": {"de": "Verkauft / abgegeben", "en": "Sold / given away", "fr": "Vendu / donné", "it": "Venduto / ceduto"},
    "take.defekt": {"de": "Defekt, entsorgt", "en": "Defective, disposed of", "fr": "Défectueux, jeté", "it": "Difettoso, smaltito"},
    "take.abfall": {"de": "In die Abfallkiste", "en": "Into the offcut bin", "fr": "Dans le bac à chutes", "it": "Nella cassa sfridi"},
    "set.waste_keep": {"de": "Abfallstücke in der Abfallkiste aufheben:", "en": "Keep offcuts in the offcut bin:", "fr": "Garder les chutes dans le bac à chutes :", "it": "Conserva gli sfridi nella cassa:"},
    "set.waste_keep_hint": {
        "de": "Abschnitte unter dem Mindest-Restmaß werden nicht weggeworfen, sondern ohne Code in der Abfallkiste geführt (nur zur Übersicht, die Optimierung nutzt sie nicht).",
        "en": "Offcuts below the minimum remnant size are not thrown away but listed without a code in the offcut bin (overview only, optimization does not use them).",
        "fr": "Les chutes sous la taille minimale ne sont pas jetées mais listées sans code dans le bac à chutes (aperçu seulement, l’optimisation ne les utilise pas).",
        "it": "Gli sfridi sotto la misura minima non vengono buttati ma elencati senza codice nella cassa (solo panoramica, l’ottimizzazione non li usa).",
    },
    "set.waste_min": {"de": "Abfall erst ab ({unit}):", "en": "Only offcuts from ({unit}):", "fr": "Chutes seulement à partir de ({unit}) :", "it": "Sfridi solo da ({unit}):"},
    "plan.stock_missing_codes": {"de": "Nicht mehr im Lager: {codes} – ggf. neu optimieren", "en": "No longer in stock: {codes} – consider optimizing again", "fr": "Plus en stock : {codes} – réoptimiser si nécessaire", "it": "Non più in magazzino: {codes} – eventualmente ottimizzare di nuovo"},
    "err.lagerort_vorhanden": {"de": "Diesen Lagerort gibt es schon.", "en": "This location already exists.", "fr": "Cet emplacement existe déjà.", "it": "Questa ubicazione esiste già."},
    "err.letzter_lagerort": {"de": "Der letzte Lagerort kann nicht gelöscht werden.", "en": "The last location cannot be deleted.", "fr": "Le dernier emplacement ne peut pas être supprimé.", "it": "L’ultima ubicazione non può essere eliminata."},
    "err.sammel_nichts_offen": {"de": "In den Projekten dieses Sammelplans ist in diesem Material nichts mehr offen. Zum erneuten Sägen im Reiter Projekte im Kasten „Sammelpläne“ den Sammelplan auswählen und „Neu starten“.", "en": "Nothing is open in this material in the projects of this combined plan. To cut it again, select the combined plan in the “Combined plans” box of the Projects tab and use “Restart”.", "fr": "Plus rien n’est ouvert dans ce matériau dans les projets de ce plan groupé. Pour le découper à nouveau, sélectionnez le plan groupé dans la zone « Plans groupés » de l’onglet Projets et utilisez « Recommencer ».", "it": "Nei progetti di questo piano combinato non c’è più nulla di aperto in questo materiale. Per tagliarlo di nuovo seleziona il piano combinato nel riquadro «Piani combinati» della scheda Progetti e usa «Ricomincia»."},
    "sammel.restart_short": {"de": "Neu starten", "en": "Restart", "fr": "Recommencer", "it": "Ricomincia"},
    "sammel.restart_hint": {"de": "Teile dieses Materials in allen Mitgliedern wieder offen, um den Sammelplan noch einmal zu sägen", "en": "Open the parts of this material in all members again to cut the combined plan once more", "fr": "Rouvrir les pièces de ce matériau dans tous les membres pour découper à nouveau le plan groupé", "it": "Riapri i pezzi di questo materiale in tutti i membri per tagliare di nuovo il piano combinato"},
    "sammel.proj_buttons_hint": {"de": "Gilt für Projekte – den Sammelplan unten im Kasten „Sammelpläne“ bearbeiten", "en": "Applies to projects – edit the combined plan in the “Combined plans” box below", "fr": "S’applique aux projets – modifiez le plan groupé dans la zone « Plans groupés » ci-dessous", "it": "Vale per i progetti – modifica il piano combinato nel riquadro «Piani combinati» qui sotto"},
    "sammel.restart": {"de": "Sammelplan neu starten", "en": "Restart combined plan", "fr": "Recommencer le plan groupé", "it": "Ricomincia piano combinato"},
    "sammel.restart_confirm": {"de": "Sammelplan „{name}“ neu starten, um ihn noch einmal zu sägen?\n- In {projekte} geht der Fortschritt aller Teile aus {material} auf 0\n- Teile aus anderen Materialien bleiben, wie sie sind\n- Der gespeicherte Sammelplan wird gelöscht, das Lager bleibt unverändert\n\nDanach „Optimieren“ – gerechnet wird mit dem aktuellen Lager samt Resten.", "en": "Restart combined plan “{name}” to cut it again?\n- In {projekte}, progress of all parts made of {material} goes back to 0\n- Parts of other materials stay as they are\n- The saved combined plan is deleted, stock stays unchanged\n\nThen “Optimize” – it is calculated with the current stock including remnants.", "fr": "Recommencer le plan groupé « {name} » pour le découper à nouveau ?\n- Dans {projekte}, la progression de toutes les pièces en {material} revient à 0\n- Les pièces d’autres matériaux restent inchangées\n- Le plan groupé enregistré est supprimé, le stock reste inchangé\n\nEnsuite « Optimiser » – le calcul utilise le stock actuel, chutes comprises.", "it": "Ricominciare il piano combinato «{name}» per tagliarlo di nuovo?\n- In {projekte} l’avanzamento di tutti i pezzi in {material} torna a 0\n- I pezzi di altri materiali restano invariati\n- Il piano combinato salvato viene eliminato, il magazzino resta invariato\n\nPoi «Ottimizza» – si calcola con il magazzino attuale, sfridi compresi."},
    "sammel.restarted": {"de": "Sammelplan neu gestartet – jetzt optimieren", "en": "Combined plan restarted – optimize it now", "fr": "Plan groupé recommencé – optimisez-le maintenant", "it": "Piano combinato ricominciato – ora ottimizzalo"},
    "err.vorlage_unbekannt": {"de": "Vorlage nicht gefunden.", "en": "Template not found.", "fr": "Modèle introuvable.", "it": "Modello non trovato."},
    "err.vorlage_leer": {"de": "Die Vorlage enthält noch keine Teile.", "en": "The template has no parts yet.", "fr": "Le modèle ne contient encore aucune pièce.", "it": "Il modello non contiene ancora pezzi."},
    "err.vorlage_nicht_saegbar": {"de": "Eine Vorlage wird nicht selbst gesägt – starte einen Durchgang mit „Sägen ×N“.", "en": "A template is not cut itself – start a run with “Cut ×N”.", "fr": "Un modèle n’est pas découpé lui-même – lancez un passage avec « Découper ×N ».", "it": "Un modello non si taglia direttamente – avvia un passaggio con «Taglia ×N»."},
    "err.name_leer": {"de": "Bitte einen Namen eingeben.", "en": "Please enter a name.", "fr": "Veuillez saisir un nom.", "it": "Inserisci un nome."},
    "err.stueck_unbekannt": {"de": "Stück nicht gefunden.", "en": "Piece not found.", "fr": "Pièce introuvable.", "it": "Pezzo non trovato."},
    "err.abfall_zu_wenig": {"de": "Davon liegen nur {vorhanden} in der Abfallkiste.", "en": "Only {vorhanden} of these are in the offcut bin.", "fr": "Il n’y en a que {vorhanden} dans le bac à chutes.", "it": "Nella cassa ce ne sono solo {vorhanden}."},
    "upd.download": {"de": "Neue Version herunterladen", "en": "Download new version", "fr": "Télécharger la nouvelle version", "it": "Scarica la nuova versione"},
}


@app.get("/api/i18n/{lang}")
def get_translations(lang: str):
    if lang not in LANGUAGES:
        raise HTTPException(400, f"Unsupported language. Available: {list(LANGUAGES.keys())}")
    result = {}
    for key, translations in TRANSLATIONS.items():
        result[key] = translations.get(lang, translations.get("en", key))
    for key, translations in WEB_EXTRA_TRANSLATIONS.items():
        result[key] = translations.get(lang, translations.get("en", key))
    return result


# ---------------------------------------------------------------------------
# Seed data endpoint (for initial setup)
# ---------------------------------------------------------------------------


@app.post("/api/seed", status_code=201)
def seed_database():
    if get_db().list_materials():
        raise HTTPException(400, "Database already contains data")
    seed_data(get_db())
    return {"status": "ok", "message": "Example data created"}


# ---------------------------------------------------------------------------
# Desktop mode: shutdown endpoint
# ---------------------------------------------------------------------------


@app.get("/api/is-desktop")
def is_desktop():
    return {"desktop": IS_DESKTOP}


if IS_DESKTOP:
    @app.post("/api/shutdown", status_code=202)
    def shutdown_server():
        def _exit():
            import time
            time.sleep(0.5)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=_exit, daemon=True).start()
        return {"status": "shutting_down"}


# ---------------------------------------------------------------------------
# Static files & SPA fallback
# ---------------------------------------------------------------------------

if STATIC_DIR.is_dir():
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/")
    def serve_index():
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(str(index), headers=NO_CACHE)
        raise HTTPException(404, "index.html not found")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file_path = STATIC_DIR / path
        if file_path.is_file():
            return FileResponse(str(file_path), headers=NO_CACHE)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(str(index), headers=NO_CACHE)
        raise HTTPException(404, "Not found")
