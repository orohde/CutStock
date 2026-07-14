"""SQLite-Datenzugriffsschicht (Repository-Pattern).

Vergleichbar mit einem DAO/Repository in Java – alle SQL-Statements sind hier
gekapselt, der Rest der App arbeitet nur mit den Dataclasses aus models.py.
"""

from __future__ import annotations

import platform
import sqlite3
from pathlib import Path

from core.models import (
    Lagerstueck,
    Maserung,
    Material,
    MaterialTyp,
    Projekt,
    Saegeblatt,
    Teil,
    TeilStatus,
)


def _default_db_path() -> Path:
    if platform.system() == "Darwin":
        # macOS: iCloud Drive bevorzugen, damit die DB zwischen Macs synchronisiert
        icloud = (Path.home() / "Library" / "Mobile Documents"
                  / "com~apple~CloudDocs" / "CutStock")
        if icloud.parent.exists():
            icloud.mkdir(parents=True, exist_ok=True)
            return icloud / "cutstock.db"
    # Fallback (kein iCloud / Windows / Linux)
    if platform.system() == "Windows":
        import os
        app_dir = Path(os.environ.get("APPDATA", Path.home())) / "CutStock"
    else:
        app_dir = Path.home() / "Library" / "Application Support" / "CutStock"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "cutstock.db"


def _migrate_old_db(new_path: Path):
    """Verschiebt die DB vom alten Ort nach iCloud, falls vorhanden.

    Sucht in dieser Reihenfolge:
    1. Alter Name CutMaster in iCloud
    2. Alter Name CutMaster in Application Support
    3. Neuer Name CutStock in Application Support
    """
    if new_path.exists():
        return
    import shutil
    old_paths = [
        Path.home() / "Library" / "Mobile Documents"
        / "com~apple~CloudDocs" / "CutMaster" / "cutmaster.db",
        Path.home() / "Library" / "Application Support" / "CutMaster" / "cutmaster.db",
        Path.home() / "Library" / "Application Support" / "CutStock" / "cutstock.db",
    ]
    for old in old_paths:
        if old.exists():
            shutil.copy2(str(old), str(new_path))
            return


DEFAULT_DB = _default_db_path()
if platform.system() == "Darwin" and "Mobile Documents" in str(DEFAULT_DB):
    _migrate_old_db(DEFAULT_DB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS material (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    typ             TEXT    NOT NULL CHECK(typ IN ('Platte','Stange')),
    dicke           REAL    NOT NULL DEFAULT 0,
    querschnitt_breite REAL NOT NULL DEFAULT 0,
    querschnitt_tiefe  REAL NOT NULL DEFAULT 0,
    drehung_erlaubt INTEGER NOT NULL DEFAULT 1,
    maserung        TEXT    NOT NULL DEFAULT 'keine',
    besaeumung      REAL    NOT NULL DEFAULT 0,
    rest_min_laenge REAL    NOT NULL DEFAULT 0,
    rest_min_breite REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lagerstueck (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES material(id),
    laenge      REAL    NOT NULL,
    breite      REAL    NOT NULL DEFAULT 0,
    stueckzahl  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS app_lock (
    id          INTEGER PRIMARY KEY CHECK(id = 1),
    hostname    TEXT    NOT NULL DEFAULT '',
    heartbeat   REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS saegeblatt (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    schnittbreite  REAL    NOT NULL DEFAULT 3.0
);

CREATE TABLE IF NOT EXISTS projekt (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS teil (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    projekt_id  INTEGER NOT NULL REFERENCES projekt(id),
    label       TEXT    NOT NULL DEFAULT '',
    typ         TEXT    NOT NULL CHECK(typ IN ('Platte','Stange')),
    material_id INTEGER NOT NULL REFERENCES material(id),
    laenge      REAL    NOT NULL,
    breite      REAL    NOT NULL DEFAULT 0,
    stueckzahl  INTEGER NOT NULL DEFAULT 1,
    gesaegt_anzahl INTEGER NOT NULL DEFAULT 0,
    maserung    TEXT    NOT NULL DEFAULT 'egal',
    status      TEXT    NOT NULL DEFAULT 'offen' CHECK(status IN ('offen','gesägt'))
);
"""


class Database:
    """Zentrale Datenbankklasse – öffnet/erstellt die SQLite-Datei."""

    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        # DELETE-Modus statt WAL: alle Daten landen direkt in der .db-Datei.
        # Wichtig für iCloud-Sync – WAL erzeugt .db-wal/.db-shm die nicht synchronisiert werden.
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Spalten nachrüsten die in älteren DB-Versionen fehlen."""
        mat_cols = {row[1] for row in
                    self.conn.execute("PRAGMA table_info(material)").fetchall()}
        if "besaeumung" not in mat_cols:
            self.conn.execute(
                "ALTER TABLE material ADD COLUMN besaeumung REAL NOT NULL DEFAULT 0")
        if "maserung" not in mat_cols:
            self.conn.execute(
                "ALTER TABLE material ADD COLUMN maserung TEXT NOT NULL DEFAULT 'keine'")
            # Bestehende Materialien migrieren: drehung_erlaubt=False → maserung=längs
            self.conn.execute(
                "UPDATE material SET maserung='längs' WHERE drehung_erlaubt=0")
        teil_cols = {row[1] for row in
                     self.conn.execute("PRAGMA table_info(teil)").fetchall()}
        if "maserung" not in teil_cols:
            self.conn.execute(
                "ALTER TABLE teil ADD COLUMN maserung TEXT NOT NULL DEFAULT 'egal'")
        if "gesaegt_anzahl" not in teil_cols:
            self.conn.execute(
                "ALTER TABLE teil ADD COLUMN gesaegt_anzahl INTEGER NOT NULL DEFAULT 0")
            # Bestehende gesägte Teile migrieren
            self.conn.execute(
                "UPDATE teil SET gesaegt_anzahl = stueckzahl WHERE status = 'gesägt'")

    def close(self):
        self.conn.commit()
        self.conn.close()

    # ------------------------------------------------------------------
    # Material
    # ------------------------------------------------------------------

    def save_material(self, m: Material) -> Material:
        if m.id is None:
            cur = self.conn.execute(
                """INSERT INTO material
                   (name, typ, dicke, querschnitt_breite, querschnitt_tiefe,
                    drehung_erlaubt, maserung, besaeumung,
                    rest_min_laenge, rest_min_breite)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (m.name, m.typ.value, m.dicke, m.querschnitt_breite,
                 m.querschnitt_tiefe, int(m.maserung == Maserung.KEINE),
                 m.maserung.value, m.besaeumung,
                 m.rest_min_laenge, m.rest_min_breite),
            )
            m.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE material SET name=?, typ=?, dicke=?,
                   querschnitt_breite=?, querschnitt_tiefe=?,
                   drehung_erlaubt=?, maserung=?, besaeumung=?,
                   rest_min_laenge=?, rest_min_breite=?
                   WHERE id=?""",
                (m.name, m.typ.value, m.dicke, m.querschnitt_breite,
                 m.querschnitt_tiefe, int(m.maserung == Maserung.KEINE),
                 m.maserung.value, m.besaeumung,
                 m.rest_min_laenge, m.rest_min_breite, m.id),
            )
        self.conn.commit()
        return m

    def get_material(self, mid: int) -> Material | None:
        row = self.conn.execute(
            "SELECT * FROM material WHERE id=?", (mid,)
        ).fetchone()
        return self._row_to_material(row) if row else None

    def list_materials(self) -> list[Material]:
        rows = self.conn.execute("SELECT * FROM material ORDER BY name").fetchall()
        return [self._row_to_material(r) for r in rows]

    def delete_material(self, mid: int):
        self.conn.execute("DELETE FROM teil WHERE material_id=?", (mid,))
        self.conn.execute("DELETE FROM lagerstueck WHERE material_id=?", (mid,))
        self.conn.execute("DELETE FROM material WHERE id=?", (mid,))
        self.conn.commit()

    @staticmethod
    def _row_to_material(row: sqlite3.Row) -> Material:
        maserung = Maserung(row["maserung"]) if row["maserung"] else Maserung.KEINE
        return Material(
            id=row["id"], name=row["name"],
            typ=MaterialTyp(row["typ"]), dicke=row["dicke"],
            querschnitt_breite=row["querschnitt_breite"],
            querschnitt_tiefe=row["querschnitt_tiefe"],
            maserung=maserung,
            drehung_erlaubt=(maserung == Maserung.KEINE),
            besaeumung=row["besaeumung"],
            rest_min_laenge=row["rest_min_laenge"],
            rest_min_breite=row["rest_min_breite"],
        )

    # ------------------------------------------------------------------
    # Lagerstück
    # ------------------------------------------------------------------

    def save_lagerstueck(self, l: Lagerstueck) -> Lagerstueck:
        if l.id is None:
            cur = self.conn.execute(
                """INSERT INTO lagerstueck (material_id, laenge, breite, stueckzahl)
                   VALUES (?,?,?,?)""",
                (l.material_id, l.laenge, l.breite, l.stueckzahl),
            )
            l.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE lagerstueck SET material_id=?, laenge=?, breite=?,
                   stueckzahl=? WHERE id=?""",
                (l.material_id, l.laenge, l.breite, l.stueckzahl, l.id),
            )
        self.conn.commit()
        return l

    def list_lagerstuecke(self, material_id: int | None = None) -> list[Lagerstueck]:
        if material_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM lagerstueck WHERE material_id=? ORDER BY laenge DESC",
                (material_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM lagerstueck ORDER BY material_id, laenge DESC"
            ).fetchall()
        return [self._row_to_lagerstueck(r) for r in rows]

    def get_lagerstueck(self, lid: int) -> Lagerstueck | None:
        row = self.conn.execute(
            "SELECT * FROM lagerstueck WHERE id=?", (lid,)
        ).fetchone()
        return self._row_to_lagerstueck(row) if row else None

    def delete_lagerstueck(self, lid: int):
        self.conn.execute("DELETE FROM lagerstueck WHERE id=?", (lid,))
        self.conn.commit()

    @staticmethod
    def _row_to_lagerstueck(row: sqlite3.Row) -> Lagerstueck:
        return Lagerstueck(
            id=row["id"], material_id=row["material_id"],
            laenge=row["laenge"], breite=row["breite"],
            stueckzahl=row["stueckzahl"],
        )

    # ------------------------------------------------------------------
    # Sägeblatt
    # ------------------------------------------------------------------

    def save_saegeblatt(self, s: Saegeblatt) -> Saegeblatt:
        if s.id is None:
            cur = self.conn.execute(
                "INSERT INTO saegeblatt (name, schnittbreite) VALUES (?,?)",
                (s.name, s.schnittbreite),
            )
            s.id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE saegeblatt SET name=?, schnittbreite=? WHERE id=?",
                (s.name, s.schnittbreite, s.id),
            )
        self.conn.commit()
        return s

    def list_saegeblaetter(self) -> list[Saegeblatt]:
        rows = self.conn.execute(
            "SELECT * FROM saegeblatt ORDER BY name"
        ).fetchall()
        return [Saegeblatt(id=r["id"], name=r["name"],
                           schnittbreite=r["schnittbreite"]) for r in rows]

    def delete_saegeblatt(self, sid: int):
        self.conn.execute("DELETE FROM saegeblatt WHERE id=?", (sid,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Projekt
    # ------------------------------------------------------------------

    def save_projekt(self, p: Projekt) -> Projekt:
        if p.id is None:
            cur = self.conn.execute(
                "INSERT INTO projekt (name) VALUES (?)", (p.name,)
            )
            p.id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE projekt SET name=? WHERE id=?", (p.name, p.id)
            )
        self.conn.commit()
        return p

    def list_projekte(self) -> list[Projekt]:
        rows = self.conn.execute("SELECT * FROM projekt ORDER BY name").fetchall()
        projekte = []
        for r in rows:
            p = Projekt(id=r["id"], name=r["name"])
            p.teile = self.list_teile(p.id)
            projekte.append(p)
        return projekte

    def get_projekt(self, pid: int) -> Projekt | None:
        row = self.conn.execute(
            "SELECT * FROM projekt WHERE id=?", (pid,)
        ).fetchone()
        if not row:
            return None
        p = Projekt(id=row["id"], name=row["name"])
        p.teile = self.list_teile(p.id)
        return p

    def delete_projekt(self, pid: int):
        self.conn.execute("DELETE FROM teil WHERE projekt_id=?", (pid,))
        self.conn.execute("DELETE FROM projekt WHERE id=?", (pid,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Teil
    # ------------------------------------------------------------------

    def save_teil(self, t: Teil) -> Teil:
        # Status aus gesaegt_anzahl ableiten
        if t.gesaegt_anzahl >= t.stueckzahl:
            t.status = TeilStatus.GESAEGT
        elif t.gesaegt_anzahl > 0:
            t.status = TeilStatus.OFFEN  # teilweise
        else:
            t.status = TeilStatus.OFFEN

        if t.id is None:
            cur = self.conn.execute(
                """INSERT INTO teil
                   (projekt_id, label, typ, material_id, laenge, breite,
                    stueckzahl, gesaegt_anzahl, maserung, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (t.projekt_id, t.label, t.typ.value, t.material_id,
                 t.laenge, t.breite, t.stueckzahl, t.gesaegt_anzahl,
                 t.maserung.value, t.status.value),
            )
            t.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE teil SET projekt_id=?, label=?, typ=?, material_id=?,
                   laenge=?, breite=?, stueckzahl=?, gesaegt_anzahl=?,
                   maserung=?, status=? WHERE id=?""",
                (t.projekt_id, t.label, t.typ.value, t.material_id,
                 t.laenge, t.breite, t.stueckzahl, t.gesaegt_anzahl,
                 t.maserung.value, t.status.value, t.id),
            )
        self.conn.commit()
        return t

    def list_teile(self, projekt_id: int) -> list[Teil]:
        rows = self.conn.execute(
            "SELECT * FROM teil WHERE projekt_id=? ORDER BY label",
            (projekt_id,),
        ).fetchall()
        return [self._row_to_teil(r) for r in rows]

    def delete_teil(self, tid: int):
        self.conn.execute("DELETE FROM teil WHERE id=?", (tid,))
        self.conn.commit()

    @staticmethod
    def _row_to_teil(row: sqlite3.Row) -> Teil:
        mas = Maserung(row["maserung"]) if row["maserung"] else Maserung.EGAL
        return Teil(
            id=row["id"], projekt_id=row["projekt_id"],
            label=row["label"], typ=MaterialTyp(row["typ"]),
            material_id=row["material_id"], laenge=row["laenge"],
            breite=row["breite"], stueckzahl=row["stueckzahl"],
            gesaegt_anzahl=row["gesaegt_anzahl"],
            maserung=mas,
            status=TeilStatus(row["status"]),
        )

    # ------------------------------------------------------------------
    # Lager-Operationen für den Optimierungslauf
    # ------------------------------------------------------------------

    def lager_verbrauchen(self, lagerstueck_id: int, anzahl: int = 1):
        """Stückzahl reduzieren, bei 0 löschen."""
        ls = self.get_lagerstueck(lagerstueck_id)
        if not ls:
            return
        ls.stueckzahl -= anzahl
        if ls.stueckzahl <= 0:
            self.delete_lagerstueck(lagerstueck_id)
        else:
            self.save_lagerstueck(ls)

    def rest_einbuchen(self, material_id: int, laenge: float,
                       breite: float = 0.0) -> Lagerstueck | None:
        """Rest als Lagerstück einbuchen. Gleiche Maße werden zusammengefasst."""
        mat = self.get_material(material_id)
        if not mat:
            return None
        if mat.typ == MaterialTyp.STANGE:
            if laenge < mat.rest_min_laenge:
                return None
        else:
            if laenge < mat.rest_min_laenge or breite < mat.rest_min_breite:
                return None
        # Bestehendes Lagerstück mit gleichen Maßen suchen
        for existing in self.list_lagerstuecke(material_id):
            if (abs(existing.laenge - laenge) < 0.1 and
                    abs(existing.breite - breite) < 0.1):
                existing.stueckzahl += 1
                return self.save_lagerstueck(existing)
        ls = Lagerstueck(material_id=material_id, laenge=laenge,
                         breite=breite, stueckzahl=1)
        return self.save_lagerstueck(ls)


def seed_data(db: Database):
    """Beispieldaten einfügen, damit die App sofort etwas zeigt."""
    # Materialien
    fichte = db.save_material(Material(
        name="Fichtenleiste 20x40", typ=MaterialTyp.STANGE,
        querschnitt_breite=20.0, querschnitt_tiefe=40.0,
        rest_min_laenge=100.0,
    ))
    mdf = db.save_material(Material(
        name="MDF 19mm", typ=MaterialTyp.PLATTE,
        dicke=19.0, drehung_erlaubt=True,
        rest_min_laenge=200.0, rest_min_breite=200.0,
    ))
    eiche = db.save_material(Material(
        name="Eiche Massiv 26mm", typ=MaterialTyp.PLATTE,
        dicke=26.0, drehung_erlaubt=False,
        rest_min_laenge=150.0, rest_min_breite=100.0,
    ))

    # Lagerbestände
    db.save_lagerstueck(Lagerstueck(material_id=fichte.id, laenge=2500.0, stueckzahl=10))
    db.save_lagerstueck(Lagerstueck(material_id=fichte.id, laenge=1200.0, stueckzahl=3))
    db.save_lagerstueck(Lagerstueck(
        material_id=mdf.id, laenge=2800.0, breite=2070.0, stueckzahl=5,
    ))
    db.save_lagerstueck(Lagerstueck(
        material_id=eiche.id, laenge=2000.0, breite=600.0, stueckzahl=2,
    ))

    # Sägeblätter
    db.save_saegeblatt(Saegeblatt(name="Standard 3mm", schnittbreite=3.0))
    db.save_saegeblatt(Saegeblatt(name="Fein 2.5mm", schnittbreite=2.5))

    # Beispielprojekt
    proj = db.save_projekt(Projekt(name="Regal Wohnzimmer"))
    db.save_teil(Teil(
        projekt_id=proj.id, label="Seitenwand links",
        typ=MaterialTyp.PLATTE, material_id=mdf.id,
        laenge=1800.0, breite=300.0, stueckzahl=1,
    ))
    db.save_teil(Teil(
        projekt_id=proj.id, label="Seitenwand rechts",
        typ=MaterialTyp.PLATTE, material_id=mdf.id,
        laenge=1800.0, breite=300.0, stueckzahl=1,
    ))
    db.save_teil(Teil(
        projekt_id=proj.id, label="Regalboden",
        typ=MaterialTyp.PLATTE, material_id=mdf.id,
        laenge=800.0, breite=300.0, stueckzahl=4,
    ))
    db.save_teil(Teil(
        projekt_id=proj.id, label="Rückwand",
        typ=MaterialTyp.PLATTE, material_id=mdf.id,
        laenge=1800.0, breite=862.0, stueckzahl=1,
    ))
    db.save_teil(Teil(
        projekt_id=proj.id, label="Querstrebe",
        typ=MaterialTyp.STANGE, material_id=fichte.id,
        laenge=800.0, stueckzahl=4,
    ))
