"""FastAPI backend for CutStock – wraps core/ as a REST API."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
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


def get_db() -> Database:
    """Thread-local Database instance — SQLite connections can't cross threads."""
    if not hasattr(_db_local, "db"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db_local.db = Database(DB_PATH)
    return _db_local.db


# Eagerly create tables / seed on import (main thread)
_init_db = get_db()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="CutStock API", version="1.0.0")

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


class PdfRequest(BaseModel):
    ergebnis: OptimizeResult
    projekt_name: str = ""
    material_name: str = ""
    saegeblatt_name: str = ""
    is_1d: bool = False


class SettingsIn(BaseModel):
    language: Optional[str] = None
    unit: Optional[str] = None
    theme: Optional[str] = None


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
        teil_tuples = [(t.label, t.laenge, t.offen_anzahl) for t in teile]
        stock = [StangenVorrat(ls.id, ls.laenge, ls.stueckzahl) for ls in vorrat]

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
