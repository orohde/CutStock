"""FastAPI backend for CutStock – wraps core/ as a REST API."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import asdict
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
    Lagerstueck,
    Maserung,
    Material,
    MaterialTyp,
    Projekt,
    Saegeblatt,
    Teil,
    TeilStatus,
    drehung_fuer_teil,
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
)
from core.pdf import export_pdf
from ui.i18n import LANGUAGES, TRANSLATIONS

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = Path(os.environ.get("CUTSTOCK_DB", "/data/cutstock.db"))

import threading

_db_local = threading.local()
# Wird bei einem Restore hochgezählt, damit alle Threads ihre veralteten
# SQLite-Verbindungen schließen und die neue Datei öffnen.
_db_generation = 0

SETTINGS_PATH = DB_PATH.parent / "settings.json"


def get_db() -> Database:
    """Thread-local Database instance — SQLite connections can't cross threads."""
    db = getattr(_db_local, "db", None)
    if db is not None and getattr(_db_local, "gen", None) == _db_generation:
        return db
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db_local.db = Database(DB_PATH)
    _db_local.gen = _db_generation
    return _db_local.db


# Eagerly create tables / seed on import (main thread)
_init_db = get_db()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="CutStock API", version="1.0.0")

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


class StockIn(BaseModel):
    material_id: int
    laenge: float
    breite: float = 0.0
    stueckzahl: int = 1


class StockOut(BaseModel):
    id: int
    material_id: int
    laenge: float
    breite: float
    stueckzahl: int


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


class ProjectIn(BaseModel):
    name: str


class ProjectOut(BaseModel):
    id: int
    name: str
    teile: list[PartOut]


class OptimizeRequest(BaseModel):
    project_id: int
    material_id: int
    blade_id: int
    algorithm: str = "greedy"


class PlatzierungOut(BaseModel):
    teil_label: str
    laenge: float
    breite: float
    x: float
    y: float
    gedreht: bool


class SchnittplanOut(BaseModel):
    lagerstueck_id: int
    lager_laenge: float
    lager_breite: float
    platzierungen: list[PlatzierungOut]
    reste: list[list[float]]
    verschnitt_mm: float
    verschnitt_prozent: float


class OptimizeResult(BaseModel):
    schnittplaene: list[SchnittplanOut]
    fehlende_teile: list[str]
    gesamt_verschnitt_prozent: float


class ConfirmRequest(BaseModel):
    project_id: int
    material_id: int
    schnittplaene: list[SchnittplanOut]


class MarkPlanRequest(BaseModel):
    material_id: int
    lagerstueck_id: int
    is_1d: bool
    lager_laenge: float
    lager_breite: float = 0.0
    kerf: float = 0.0
    marked_laengen: list[float] = []
    total_pieces: int = 0
    reste: list[list[float]] = []
    prev_consumed: bool = False
    prev_rest_ids: list[int] = []


class PdfRequest(BaseModel):
    ergebnis: OptimizeResult
    projekt_name: str = ""
    material_name: str = ""
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
    )


def _stock_to_out(ls: Lagerstueck) -> StockOut:
    return StockOut(
        id=ls.id,
        material_id=ls.material_id,
        laenge=ls.laenge,
        breite=ls.breite,
        stueckzahl=ls.stueckzahl,
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
    )


def _projekt_to_out(p: Projekt) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        teile=[_teil_to_out(t) for t in p.teile],
    )


def _ergebnis_to_out(erg: OptimierungsErgebnis) -> OptimizeResult:
    return OptimizeResult(
        schnittplaene=[
            SchnittplanOut(
                lagerstueck_id=sp.lagerstueck_id,
                lager_laenge=sp.lager_laenge,
                lager_breite=sp.lager_breite,
                platzierungen=[
                    PlatzierungOut(
                        teil_label=p.teil_label,
                        laenge=p.laenge,
                        breite=p.breite,
                        x=p.x,
                        y=p.y,
                        gedreht=p.gedreht,
                    )
                    for p in sp.platzierungen
                ],
                reste=[list(r) for r in sp.reste],
                verschnitt_mm=sp.verschnitt_mm,
                verschnitt_prozent=sp.verschnitt_prozent,
            )
            for sp in erg.schnittplaene
        ],
        fehlende_teile=erg.fehlende_teile,
        gesamt_verschnitt_prozent=erg.gesamt_verschnitt_prozent,
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
            )
            for sp in data.schnittplaene
        ],
        fehlende_teile=data.fehlende_teile,
        gesamt_verschnitt_prozent=data.gesamt_verschnitt_prozent,
    )


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _get_settings_dict() -> dict:
    from core.settings import Settings

    settings_path = DB_PATH.parent / "settings.json"
    s = Settings(settings_path)
    return {
        "language": s.value("appearance/language", "en"),
        "unit": s.value("appearance/unit", "mm"),
        "theme": s.value("appearance/theme", "system"),
        "hotkeys": s.value("web/hotkeys", {}),
        "label_format": s.value("labels/format", "a4_3x8"),
        "label_custom_w": s.value("labels/custom_w", 89),
        "label_custom_h": s.value("labels/custom_h", 36),
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
    m = get_db().save_material(m)
    return _material_to_out(m)


@app.put("/api/materials/{mid}", response_model=MaterialOut)
def update_material(mid: int, data: MaterialIn):
    existing = get_db().get_material(mid)
    if not existing:
        raise HTTPException(404, "Material not found")
    m = _material_from_in(data, mid)
    m = get_db().save_material(m)
    return _material_to_out(m)


@app.delete("/api/materials/{mid}", status_code=204)
def delete_material(mid: int):
    existing = get_db().get_material(mid)
    if not existing:
        raise HTTPException(404, "Material not found")
    get_db().delete_material(mid)


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
    p = Projekt(name=data.name)
    p = get_db().save_projekt(p)
    p.teile = []
    return _projekt_to_out(p)


@app.put("/api/projects/{pid}", response_model=ProjectOut)
def update_project(pid: int, data: ProjectIn):
    existing = get_db().get_projekt(pid)
    if not existing:
        raise HTTPException(404, "Project not found")
    existing.name = data.name
    get_db().save_projekt(existing)
    return _projekt_to_out(existing)


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


@app.post("/api/optimize", response_model=OptimizeResult)
def run_optimization(req: OptimizeRequest):
    projekt = get_db().get_projekt(req.project_id)
    if not projekt:
        raise HTTPException(404, "Project not found")

    material = get_db().get_material(req.material_id)
    if not material:
        raise HTTPException(404, "Material not found")

    blades = get_db().list_saegeblaetter()
    blade = next((b for b in blades if b.id == req.blade_id), None)
    if not blade:
        raise HTTPException(404, "Saw blade not found")

    # Filter parts for this material that are not fully cut
    teile = [t for t in projekt.teile
             if t.material_id == req.material_id and t.offen_anzahl > 0]
    if not teile:
        raise HTTPException(400, "No open parts for this material")

    vorrat = get_db().list_lagerstuecke(req.material_id)
    if not vorrat:
        raise HTTPException(400, "No stock available for this material")

    kerf = blade.schnittbreite
    is_1d = material.typ == MaterialTyp.STANGE

    if is_1d:
        # Apply trim (Besaeumung): subtract 2*trim from bar length, drop too-short pieces
        besaeumung = material.besaeumung
        teil_tuples = [(t.label, t.laenge, t.offen_anzahl) for t in teile]
        stock = [
            StangenVorrat(ls.id, ls.laenge - 2 * besaeumung, ls.stueckzahl)
            for ls in vorrat
            if ls.laenge - 2 * besaeumung > 0
        ]
        if not stock:
            raise HTTPException(400, "No stock available for this material")

        if req.algorithm == "ga":
            ergebnis = optimize_1d_ga(teil_tuples, stock, kerf)
        else:
            ergebnis = optimize_1d(teil_tuples, stock, kerf)
    else:
        # Apply trim (Besaeumung) to stock dimensions
        besaeumung = material.besaeumung
        teil_tuples = [(t.label, t.laenge, t.breite, t.offen_anzahl) for t in teile]
        stock = [
            PlattenVorrat(
                ls.id,
                ls.laenge - 2 * besaeumung,
                ls.breite - 2 * besaeumung,
                ls.stueckzahl,
            )
            for ls in vorrat
        ]

        # Build per-part rotation rules from grain directions
        teil_drehung: dict[str, tuple[bool, bool]] = {}
        for t in teile:
            normal_ok, gedreht_ok = drehung_fuer_teil(material.maserung, t.maserung)
            teil_drehung[t.label] = (normal_ok, gedreht_ok)

        drehung_erlaubt = material.maserung == Maserung.KEINE

        if req.algorithm == "ga":
            ergebnis = optimize_2d_ga(teil_tuples, stock, kerf, drehung_erlaubt, teil_drehung)
        elif req.algorithm == "nested":
            ergebnis = optimize_2d_nested(teil_tuples, stock, kerf, drehung_erlaubt, teil_drehung)
        else:
            ergebnis = optimize_2d(teil_tuples, stock, kerf, drehung_erlaubt, teil_drehung)

    return _ergebnis_to_out(ergebnis)


# ---------------------------------------------------------------------------
# Confirm (apply cutting plan)
# ---------------------------------------------------------------------------


@app.post("/api/optimize/confirm")
def confirm_optimization(req: ConfirmRequest):
    material = get_db().get_material(req.material_id)
    if not material:
        raise HTTPException(404, "Material not found")

    projekt = get_db().get_projekt(req.project_id)
    if not projekt:
        raise HTTPException(404, "Project not found")

    is_1d = material.typ == MaterialTyp.STANGE

    # Count how many times each label was placed
    label_counts: dict[str, int] = {}
    for sp in req.schnittplaene:
        # Consume the stock piece
        get_db().lager_verbrauchen(sp.lagerstueck_id)

        for rest in sp.reste:
            if is_1d:
                if len(rest) >= 1 and rest[0] > 0:
                    get_db().rest_einbuchen(req.material_id, rest[0])
            else:
                if len(rest) >= 2 and rest[0] > 0 and rest[1] > 0:
                    get_db().rest_einbuchen(req.material_id, rest[0], rest[1])

        for p in sp.platzierungen:
            label_counts[p.teil_label] = label_counts.get(p.teil_label, 0) + 1

    # Update teil.gesaegt_anzahl
    for teil in projekt.teile:
        if teil.material_id != req.material_id:
            continue
        placed = label_counts.get(teil.label, 0)
        if placed > 0:
            teil.gesaegt_anzahl = min(teil.stueckzahl, teil.gesaegt_anzahl + placed)
            get_db().save_teil(teil)

    return {"status": "ok", "message": "Cutting plan confirmed. Stock updated."}


@app.post("/api/optimize/mark-plan")
def mark_plan(req: MarkPlanRequest):
    """Lagerbestand für EINEN Schnittplan live anpassen (wie Desktop _on_teil_cut).

    Beim ersten markierten Stück wird das Lagerstück verbraucht; der tatsächliche
    Rest (1D: Länge − Σ markiert − Kerf·Anzahl; 2D: plan.reste nur wenn komplett)
    wird eingebucht. Vorher gebuchte Reste werden zuerst entfernt (idempotent).
    Ohne Markierungen wird der Verbrauch rückgängig gemacht.
    """
    db = get_db()
    consumed = req.prev_consumed
    # Zuvor gebuchte Reste immer entfernen und ggf. neu buchen
    for rid in req.prev_rest_ids:
        db.lager_verbrauchen(rid)
    rest_ids: list[int] = []

    n_marked = len(req.marked_laengen)
    if n_marked > 0:
        if not consumed:
            db.lager_verbrauchen(req.lagerstueck_id)
            consumed = True
        if req.is_1d:
            rest_val = req.lager_laenge - sum(req.marked_laengen) - req.kerf * n_marked
            if rest_val > 0:
                r = db.rest_einbuchen(req.material_id, rest_val)
                if r:
                    rest_ids.append(r.id)
        else:
            # 2D: Sobald das Brett angesägt wird, die Reststücke des Plans
            # einbuchen (durchgängige Schnitte). Beim Zurücknehmen aller
            # Markierungen werden sie über prev_rest_ids wieder entfernt.
            for rest in req.reste:
                if len(rest) >= 2 and rest[0] > 0 and rest[1] > 0:
                    r = db.rest_einbuchen(req.material_id, rest[0], rest[1])
                    if r:
                        rest_ids.append(r.id)
    elif consumed:
        # Alle Markierungen entfernt → Original-Lagerstück zurückbuchen
        db.rest_einbuchen(req.material_id, req.lager_laenge, req.lager_breite)
        consumed = False

    return {"consumed": consumed, "rest_ids": rest_ids}


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


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def _read_version() -> str:
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            vf = Path(sys._MEIPASS) / "VERSION"
        else:
            vf = PROJECT_ROOT / "VERSION"
        return vf.read_text().strip()
    except Exception:
        return "0.0.0"


APP_VERSION = _read_version()
GITHUB_REPO = "orohde/CutStock"


@app.get("/api/version")
def get_version():
    return {
        "version": APP_VERSION,
        "repo": GITHUB_REPO,
        "github_url": f"https://github.com/{GITHUB_REPO}",
        "website_url": "https://worldgate.de/cutstock/",
        "releases_api": f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
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
