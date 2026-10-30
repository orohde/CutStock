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

from core.db import Database, seed_data
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
    fuelle_rest_1d,
)
from core.pdf import export_pdf
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
        })
    return _lager_cache[1]


_lager_cache: tuple[float, dict] = (-1.0, {})


def get_db() -> Database:
    """Thread-local Database instance — SQLite connections can't cross threads."""
    db = getattr(_db_local, "db", None)
    if db is not None and getattr(_db_local, "gen", None) == _db_generation:
        db.nr_sperrfrist_tage = _lager_einstellungen()["nr_sperrfrist_tage"]
        return db
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db_local.db = Database(DB_PATH, app_version=APP_VERSION)
    _db_local.gen = _db_generation
    _db_local.db.nr_sperrfrist_tage = _lager_einstellungen()["nr_sperrfrist_tage"]
    return _db_local.db


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
    lagerort: str = ""
    lagerort_reste: str = ""


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


class StockIn(BaseModel):
    material_id: int
    laenge: float
    breite: float = 0.0
    stueckzahl: int = 1
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
    lagerort: str = ""           # eigener Lagerort (leer = Material)
    lagerort_effektiv: str = ""  # eigener oder der des Materials
    reserviert_fuer: str = ""    # Projekt, dessen gespeicherter Plan das Stück reserviert


class EinzelstueckIn(BaseModel):
    notiz: str = ""
    lagerort: str = ""


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
    reste_stuecke: list[RestStueckOut] = []   # eingebuchte Reste (nach dem Anfangen)


class MaterialBedarfOut(BaseModel):
    laenge: float
    breite: float
    anzahl: int


class OptimizeResult(BaseModel):
    schnittplaene: list[SchnittplanOut]
    fehlende_teile: list[str]
    gesamt_verschnitt_prozent: float
    materialbedarf: list[MaterialBedarfOut] = []
    # Gespeicherter Plan (0/leer bei reinen Berechnungsergebnissen, z.B. im PDF)
    plan_id: int = 0
    projekt_id: int = 0
    material_id: int = 0
    saegeblatt_id: Optional[int] = None
    algorithmus: str = ""
    erstellt: float = 0.0
    version: int = 0
    veraltet: bool = False      # Teile/Material/Sägeblatt seit der Berechnung geändert
    lager_fehlt: bool = False   # eingeplante, noch unbenutzte Lagerstücke fehlen
    fuellteile: list[dict] = []          # Auswahl [{teil_id, modus, menge}]
    fuell_alle_reste: bool = False
    vorrat_verfuegbar: list[dict] = []   # eigene Teile mit Vorrat: [{teil_id, label, anzahl}]


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
    schnittfolge_titel: str = "Schnittfolge"


class LabelIn(BaseModel):
    title: str = ""
    line1: str = ""
    line2: str = ""
    id_text: str = ""


class LabelsRequest(BaseModel):
    labels: list[LabelIn]
    filename: str = "Etiketten"


class SettingsIn(BaseModel):
    language: Optional[str] = None
    unit: Optional[str] = None
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
        lagerort=data.lagerort,
        lagerort_reste=data.lagerort_reste,
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
    )


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


def _berechne_materialbedarf(fehlende_labels, teile, vorrat, material, kerf):
    """Estimate additional stock needed for parts that couldn't be placed."""
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
        "unit": s.value("appearance/unit", "mm"),
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
    }


def _update_settings(data: SettingsIn):
    from core.settings import Settings

    settings_path = DB_PATH.parent / "settings.json"
    s = Settings(settings_path)
    if data.language is not None:
        s.setValue("appearance/language", data.language)
    if data.unit is not None:
        s.setValue("appearance/unit", data.unit)
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
    existing = get_db().get_material(mid)
    if not existing:
        raise HTTPException(404, "Material not found")
    m = _material_from_in(data, mid)
    try:
        m = get_db().save_material(m)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _material_to_out(m)


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


@app.post("/api/stock", response_model=StockOut, status_code=201)
def create_stock(data: StockIn):
    ls = Lagerstueck(
        material_id=data.material_id,
        laenge=data.laenge,
        breite=data.breite,
        stueckzahl=data.stueckzahl,
        ist_rest=data.ist_rest,
    )
    ls = get_db().save_lagerstueck(ls)
    return _stock_to_out(ls)


@app.put("/api/stock/{sid}", response_model=StockOut)
def update_stock(sid: int, data: StockIn):
    existing = get_db().get_lagerstueck(sid)
    if not existing:
        raise HTTPException(404, "Stock piece not found")
    ls = Lagerstueck(
        id=sid,
        material_id=data.material_id,
        laenge=data.laenge,
        breite=data.breite,
        stueckzahl=data.stueckzahl,
        ist_rest=data.ist_rest,
    )
    ls = get_db().save_lagerstueck(ls)
    return _stock_to_out(ls)


@app.delete("/api/stock/{sid}", status_code=204)
def delete_stock(sid: int):
    existing = get_db().get_lagerstueck(sid)
    if not existing:
        raise HTTPException(404, "Stock piece not found")
    get_db().delete_lagerstueck(sid)


# ---------------------------------------------------------------------------
# Einzelstücke (individual pieces)
# ---------------------------------------------------------------------------


def _piece_out(db: Database, e: Einzelstueck, material: Material | None,
               reserviert: dict | None = None) -> EinzelstueckOut:
    return EinzelstueckOut(
        reserviert_fuer=(reserviert or {}).get((e.lagerstueck_id, e.nr), ""),
        id=e.id, lagerstueck_id=e.lagerstueck_id, nr=e.nr, notiz=e.notiz,
        defekt_count=len(db.list_defekte(e.id)),
        code=stueck_code(material.kuerzel if material else "", e.nr),
        lagerort=e.lagerort,
        lagerort_effektiv=e.lagerort or (material.lagerort if material else ""))


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


@app.put("/api/pieces/{eid}", response_model=EinzelstueckOut)
def update_piece(eid: int, data: EinzelstueckIn):
    db = get_db()
    e = db.get_einzelstueck(eid)
    if not e:
        raise HTTPException(404, "Piece not found")
    e.notiz = data.notiz
    e.lagerort = data.lagerort
    e = db.save_einzelstueck(e)
    return _piece_out(db, db.get_einzelstueck(eid), _material_of_stock(db, e.lagerstueck_id))


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
def list_projects():
    return [_projekt_to_out(p) for p in get_db().list_projekte()]


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
    existing.anzahl = data.anzahl
    get_db().save_projekt(existing)
    return _projekt_to_out(get_db().get_projekt(pid))


@app.post("/api/projects/{pid}/clone", response_model=ProjectOut, status_code=201)
def clone_project(pid: int):
    db = get_db()
    existing = db.get_projekt(pid)
    if not existing:
        raise HTTPException(404, "Project not found")
    clone = Projekt(name=f"{existing.name} (Kopie)", anzahl=existing.anzahl)
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


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: int):
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
    t = get_db().save_teil(t)
    return _teil_to_out(t)


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
    vorrat_alle = db.list_lagerstuecke(material_id)
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


def _berechnen(material: Material, kerf: float, algorithm: str, reste_zuerst: bool,
               teile: list[Teil], mengen: dict[int, int], lage: _Lagerlage
               ) -> OptimierungsErgebnis:
    """Teile (Mengen je ID) auf das freie Lager verteilen, ohne zu speichern."""
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
            if algorithm == "ga":
                return optimize_1d_ga(teil_tuples, stock, kerf, lage.defekte_lauf)
            return optimize_1d(teil_tuples, stock, kerf, lage.defekte_lauf)
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

    material = get_db().get_material(req.material_id)
    if not material:
        raise HTTPException(404, "Material not found")

    blades = get_db().list_saegeblaetter()
    blade = next((b for b in blades if b.id == req.blade_id), None)
    if not blade:
        raise HTTPException(404, "Saw blade not found")

    db = get_db()
    is_1d = material.typ == MaterialTyp.STANGE
    alt = db.get_plan(req.project_id, req.material_id)
    fuell_auswahl = ([f.model_dump() for f in req.fuellteile] if req.fuellteile is not None
                     else (alt.fuellteile if alt else []))
    fuell_alle = (req.fuell_alle_reste if req.fuell_alle_reste is not None
                  else (alt.fuell_alle_reste if alt else False))
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
                                   [], [], fuell_auswahl, fuell_alle)
        if any(anderswo.get(t.id) for t in projekt.teile if t.material_id == material.id):
            sammel = db.sammel_von_projekt(projekt.id).get(material.id)
            raise HTTPException(409, f"All open parts are already in “{sammel}”."
                                if sammel else "All open parts are already in another plan")
        raise HTTPException(400, "No open parts for this material")

    # Füllteile: Teile anderer Projekte desselben Materials. Im Plan heißen sie
    # "Label → Projekt", damit sie unterscheidbar sind (der Optimizer kennt nur Labels).
    fuell_fest: list[Teil] = []
    fuell_auf: list[tuple[Teil, int]] = []
    for f in fuell_auswahl:
        t = db.get_teil(f["teil_id"])
        if not t or t.material_id != material.id or t.projekt_id == projekt.id:
            continue
        herkunft = db.get_projekt(t.projekt_id)
        ft = replace(t, label=f"{t.label} → {herkunft.name if herkunft else '?'}")
        if f.get("modus") == "fest":
            if int(f.get("menge") or 0) > 0:
                fuell_fest.append(ft)
                offen[ft.id] = int(f["menge"])
        elif is_1d:
            fuell_auf.append((ft, int(f.get("menge") or 0)))
    teile = teile + fuell_fest
    fuell_ids = {t.id for t in fuell_fest} | {t.id for t, _ in fuell_auf}

    kerf = blade.schnittbreite
    lage = _lagerlage(db, req.material_id, ausser_projekt=req.project_id)
    ergebnis = _berechnen(material, kerf, req.algorithm, req.reste_zuerst, teile,
                          {t.id: offen[t.id] for t in teile}, lage)

    neue = _ergebnis_to_bretter(ergebnis, lage.defekte_map, teile, offen)
    for b in neue:
        for st in b.stuecke:
            st.ist_fuellteil = st.teil_id in fuell_ids
    if fuell_auf:
        _reste_auffuellen(neue, fuell_auf, kerf, material, fuell_alle)
    bedarf = []
    if ergebnis.fehlende_teile:
        bedarf = [m.model_dump() for m in _berechne_materialbedarf(
            ergebnis.fehlende_teile, teile, lage.vorrat_alle, material, kerf)]
    return _plan_speichern(projekt, material, blade, req.algorithm, behalten + neue,
                           ergebnis.fehlende_teile, bedarf, fuell_auswahl, fuell_alle)


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
        if not pr or pr.art == "sammel":
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
                   if (pr := db.get_projekt(pid)) and pr.art != "sammel"]
    if not projekt_ids:
        raise HTTPException(400, "No projects selected")

    is_1d = material.typ == MaterialTyp.STANGE
    sammel = db.get_sammel(material.id) or db.sammel_anlegen(
        material.id, f"Sammelplan {material.name}")
    for pid in projekt_ids:
        if einzel := _offener_einzelplan(db, pid, material.id):
            db.delete_plan(einzel.id)

    alt = db.get_plan(sammel.id, material.id)
    if alt and all(st.gesaegt for b in alt.bretter for st in b.stuecke):
        db.delete_plan(alt.id)
        alt = None
    behalten = _angefangene_bretter(alt, is_1d)
    db.sammel_mitglieder_setzen(sammel.id, projekt_ids)
    teile, offen = _sammel_teile(db, material, projekt_ids, sammel.id,
                                 _schon_geplant(behalten))
    sammel = db.get_projekt(sammel.id)
    if not teile:
        if behalten:
            return _plan_speichern(sammel, material, blade, req.algorithm, behalten, [], [])
        raise HTTPException(400, "No open parts for this material")

    kerf = blade.schnittbreite
    lage = _lagerlage(db, material.id, ausser_projekt=sammel.id)
    ergebnis = _berechnen(material, kerf, req.algorithm, req.reste_zuerst, teile,
                          dict(offen), lage)
    neue = _ergebnis_to_bretter(ergebnis, lage.defekte_map, teile, offen)
    bedarf = []
    if ergebnis.fehlende_teile:
        bedarf = [m.model_dump() for m in _berechne_materialbedarf(
            ergebnis.fehlende_teile, teile, lage.vorrat_alle, material, kerf)]
    return _plan_speichern(sammel, material, blade, req.algorithm, behalten + neue,
                           ergebnis.fehlende_teile, bedarf)


@app.post("/api/sammel/compare", response_model=VergleichOut)
def compare_sammel(req: SammelRequest):
    """Was spart der Sammelplan? Jedes Projekt einzeln gegen alle gemeinsam rechnen.

    Nichts wird gespeichert. Beide Varianten sehen dasselbe freie Lager; die
    getrennte Rechnung ist eine Schätzung, weil sich echte Einzelpläne das Lager teilen.
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

    def rechne(pids: list[int]) -> OptimierungsErgebnis:
        teile, offen = _sammel_teile(db, material, pids, ausser)
        if not teile:
            return OptimierungsErgebnis()
        return _berechnen(material, kerf, req.algorithm, req.reste_zuerst, teile, offen, lage)

    getrennt = [rechne([pid]) for pid in req.projekt_ids]
    gemeinsam = rechne(req.projekt_ids)
    return VergleichOut(
        getrennt_bretter=sum(len(e.schnittplaene) for e in getrennt),
        gemeinsam_bretter=len(gemeinsam.schnittplaene),
        getrennt_menge=sum(_verbrauch(e, is_1d) for e in getrennt),
        gemeinsam_menge=_verbrauch(gemeinsam, is_1d),
        fehlende_getrennt=sum(len(e.fehlende_teile) for e in getrennt),
        fehlende_gemeinsam=len(gemeinsam.fehlende_teile),
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
                    fuellteile=(), fuell_alle_reste=False) -> OptimizeResult:
    db = get_db()
    plan = GespeicherterPlan(
        projekt_id=projekt.id, material_id=material.id, saegeblatt_id=blade.id,
        kerf=blade.schnittbreite, algorithmus=algorithmus,
        eingabe_hash=_eingabe_hash(projekt, material, blade.schnittbreite),
        fehlende_teile=list(fehlende), materialbedarf=list(bedarf), bretter=bretter,
        fuellteile=list(fuellteile), fuell_alle_reste=bool(fuell_alle_reste),
    )
    return _plan_to_out(db.save_plan(plan))


def _reste_auffuellen(bretter: list[PlanBrett], auffuellen: list[tuple[Teil, int]],
                      kerf: float, material: Material, alle_reste: bool):
    """Den Rest am Ende jeder Stange mit Füllteilen belegen (Durchgang 2, nur 1D).

    Standard: nur echter Abfall, also Reste unter dem Mindest-Restmaß. Hat das
    Material kein Mindest-Restmaß, gilt jeder Rest als auffüllbar. Stangen mit
    Defekten bleiben außen vor (ihre freien Stücke liegen nicht am Ende).
    """
    rest_min = material.rest_min_laenge
    vorrat = {t.id: (m if m > 0 else 10 ** 6) for t, m in auffuellen}
    nach_id = {t.id: t for t, _ in auffuellen}
    for b in bretter:
        if b.defekte or not b.stuecke:
            continue
        ende = max(st.x + st.laenge for st in b.stuecke)
        start = ende + kerf
        rest = b.lager_laenge - start
        if rest <= 0 or not (alle_reste or rest_min <= 0 or rest < rest_min):
            continue
        kandidaten = [(tid, nach_id[tid].laenge, n) for tid, n in vorrat.items() if n > 0]
        pos = start
        for tid in fuelle_rest_1d(rest, kerf, kandidaten):
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


def _plan_to_out(plan: GespeicherterPlan) -> OptimizeResult:
    db = get_db()
    material = db.get_material(plan.material_id)
    projekt = db.get_projekt(plan.projekt_id)
    is_1d = material is not None and material.typ == MaterialTyp.STANGE

    # Noch nicht angefangene Bretter: gibt es genau diese Stücke noch im Lager?
    nrs_map = db.einzelstueck_nrs_for_material(plan.material_id)
    lager_fehlt = False
    for b in plan.bretter:
        if b.verbraucht:
            continue
        nrs = nrs_map.get(b.lagerstueck_id)
        if not nrs or (b.stueck_nr and b.stueck_nr not in nrs):
            lager_fehlt = True

    kuerzel = material.kuerzel if material else ""
    mat_ort = material.lagerort if material else ""

    def stueck_ort(lagerstueck_id: int, nr: int) -> str:
        row = db.conn.execute(
            "SELECT lagerort FROM einzelstueck WHERE lagerstueck_id=? AND nr=?",
            (lagerstueck_id, nr)).fetchone()
        return (row["lagerort"] if row else "") or mat_ort

    def brett_ort(b: PlanBrett) -> str:
        if b.verbraucht:
            return (b.verbrauchtes_stueck or {}).get("lagerort") or mat_ort
        return stueck_ort(b.lagerstueck_id, b.stueck_nr)

    def reste(b: PlanBrett) -> list[RestStueckOut]:
        out = []
        for lid, nr in b.rest_ids:
            ls = db.get_lagerstueck(lid)
            if ls and nr:
                out.append(RestStueckOut(code=stueck_code(kuerzel, nr), laenge=ls.laenge,
                                         breite=ls.breite, lagerort=stueck_ort(lid, nr)))
        return out

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
                reste_stuecke=reste(b),
            )
            for b in plan.bretter],
        fehlende_teile=plan.fehlende_teile,
        gesamt_verschnitt_prozent=round((1 - genutzt / gesamt) * 100, 1) if gesamt else 0.0,
        materialbedarf=[MaterialBedarfOut(**m) for m in plan.materialbedarf],
        plan_id=plan.id, projekt_id=plan.projekt_id, material_id=plan.material_id,
        saegeblatt_id=plan.saegeblatt_id, algorithmus=plan.algorithmus,
        erstellt=plan.erstellt, version=plan.version,
        veraltet=(projekt is None or material is None or
                  _eingabe_hash(projekt, material, plan.kerf) != plan.eingabe_hash),
        lager_fehlt=lager_fehlt,
        fuellteile=plan.fuellteile,
        fuell_alle_reste=plan.fuell_alle_reste,
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
    ))
    alte_id = brett.lagerstueck_id
    brett.verbraucht = res["consumed"]
    brett.rest_ids = [[rid, nr] for rid, nr in zip(res["rest_ids"], res["rest_nrs"])]
    brett.lagerstueck_id = res["lagerstueck_id"]
    brett.verbrauchtes_stueck = res["consumed_piece"]
    db.save_brett_zustand(brett)
    if brett.lagerstueck_id != alte_id:
        # Zurückgebucht in eine neue Lagerzeile: unbenutzte Bretter aller Pläne mitziehen
        db.conn.execute(
            """UPDATE schnittplan_brett SET lagerstueck_id=?
               WHERE lagerstueck_id=? AND verbraucht=0""",
            (brett.lagerstueck_id, alte_id))
        db.conn.commit()


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
        db.set_stueck_gesaegt(sid, data.gesaegt)
        if stueck.teil_id:
            _gesaegt_buchen(db, stueck, 1 if data.gesaegt else -1)
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
    """Gesägtes Stück verbuchen: Füllteile gehen in den Vorrat ihres Teils ("Regal"),
    alle anderen zählen als Fortschritt des Projekts."""
    if st.ist_fuellteil:
        db.teil_vorrat_aendern(st.teil_id, delta)
    else:
        db.teil_gesaegt_aendern(st.teil_id, delta)


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
    if not db.get_projekt(pid):
        raise HTTPException(404, "Project not found")
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
            db.set_stueck_gesaegt(st.id, True)
            if st.teil_id:
                _gesaegt_buchen(db, st, 1)
        _brett_abgleichen(db, plan, brett, is_1d)
    db.plan_geaendert(plan.id)
    return _plan_to_out(db.get_plan_by_id(plan.id))


@app.post("/api/projects/{pid}/restart", response_model=ProjectOut)
def restart_project(pid: int):
    """Projekt nochmal sägen: Fortschritt auf 0, Pläne weg, Lager bleibt wie es ist."""
    db = get_db()
    if not db.get_projekt(pid):
        raise HTTPException(404, "Project not found")
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
    # Zuvor gebuchte Reste immer entfernen und ggf. neu buchen
    for i, rid in enumerate(req.prev_rest_ids):
        nr = req.prev_rest_nrs[i] if i < len(req.prev_rest_nrs) else 0
        db.lager_verbrauchen(rid, stueck_nr=nr)
    rest_ids: list[int] = []
    rest_nrs: list[int] = []

    n_marked = len(req.marked_laengen)
    if n_marked > 0:
        if not consumed:
            consumed_piece = db.lager_verbrauchen(req.lagerstueck_id,
                                                  stueck_nr=req.stueck_nr)
            consumed = True
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
                if r[1] == erbe_nr:
                    erbe_nr = 0
    elif consumed:
        # Alle Markierungen entfernt → Original-Lagerstück zurückbuchen
        lagerstueck_id = _lagerstueck_zurueckbuchen(db, req)
        consumed = False
        consumed_piece = None

    return {"consumed": consumed, "rest_ids": rest_ids, "rest_nrs": rest_nrs,
            "lagerstueck_id": lagerstueck_id, "consumed_piece": consumed_piece}


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


@app.post("/api/pdf")
def generate_pdf(req: PdfRequest):
    ergebnis = _out_to_ergebnis(req.ergebnis)

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
            material_bild=(get_db().get_material_image(req.material_id) or b""
                           if req.material_id else b""),
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


@app.post("/api/labels")
def generate_labels(req: LabelsRequest):
    from core.labels import export_labels

    if not req.labels:
        raise HTTPException(400, "No labels")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cfg = _get_settings_dict()
        export_labels([l.model_dump() for l in req.labels], tmp_path,
                      title=req.filename,
                      fmt=str(cfg.get("label_format") or "a4_3x8"),
                      custom_w=float(cfg.get("label_custom_w") or 0),
                      custom_h=float(cfg.get("label_custom_h") or 0))
        fname = f"CutStock-{req.filename}.pdf"
        return FileResponse(
            tmp_path,
            media_type="application/pdf",
            filename=fname,
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(500, f"Label generation failed: {e}")


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
        "website_url": "https://worldgate.de/cutstock/",
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
    "mat.empty": {"de": "Keine Materialien vorhanden.", "en": "No materials.", "fr": "Aucun matériau.", "it": "Nessun materiale."},
    "stock.empty": {"de": "Kein Lagerbestand.", "en": "No stock.", "fr": "Pas de stock.", "it": "Nessuna scorta."},
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
    "sammel.saved": {"de": "{menge} gespart ({pct} %)", "en": "{menge} saved ({pct} %)", "fr": "{menge} économisés ({pct} %)", "it": "{menge} risparmiati ({pct} %)"},
    "sammel.no_saving": {"de": "keine Ersparnis", "en": "no saving", "fr": "aucune économie", "it": "nessun risparmio"},
    "sammel.compare_missing": {
        "de": "Es fehlt Material – der Vergleich ist nur bedingt aussagekräftig.",
        "en": "Material is missing – the comparison is only indicative.",
        "fr": "Il manque du matériau – la comparaison n’est qu’indicative.",
        "it": "Manca materiale – il confronto è solo indicativo.",
    },
    "sammel.bars": {"de": "{n} Stangen", "en": "{n} bars", "fr": "{n} barres", "it": "{n} barre"},
    "sammel.boards": {"de": "{n} Platten", "en": "{n} boards", "fr": "{n} panneaux", "it": "{n} pannelli"},
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
    "sammel.open": {"de": "Sammelplan öffnen", "en": "Open combined plan", "fr": "Ouvrir le plan groupé", "it": "Apri piano combinato"},
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
