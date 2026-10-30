"""SQLite-Datenzugriffsschicht (Repository-Pattern).

Vergleichbar mit einem DAO/Repository in Java – alle SQL-Statements sind hier
gekapselt, der Rest der App arbeitet nur mit den Dataclasses aus models.py.
"""

from __future__ import annotations

import platform
import sqlite3
from pathlib import Path

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
    kuerzel_vorschlag,
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
    rest_min_breite REAL    NOT NULL DEFAULT 0,
    bild            BLOB    DEFAULT NULL,
    kuerzel         TEXT    NOT NULL DEFAULT '',
    lagerort        TEXT    NOT NULL DEFAULT '',
    lagerort_reste  TEXT    NOT NULL DEFAULT ''
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
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT    NOT NULL,
    anzahl INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS einzelstueck (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lagerstueck_id  INTEGER NOT NULL REFERENCES lagerstueck(id) ON DELETE CASCADE,
    nr              INTEGER NOT NULL,
    notiz           TEXT    NOT NULL DEFAULT '',
    lagerort        TEXT    NOT NULL DEFAULT '',
    UNIQUE(lagerstueck_id, nr)
);

CREATE TABLE IF NOT EXISTS defekt (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    einzelstueck_id INTEGER NOT NULL REFERENCES einzelstueck(id) ON DELETE CASCADE,
    position        REAL    NOT NULL DEFAULT 0,
    position_y      REAL    NOT NULL DEFAULT 0,
    laenge          REAL    NOT NULL,
    breite          REAL    NOT NULL DEFAULT 0
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

-- Gespeicherte Schnittpläne (ein Plan je Projekt + Material).
-- Fremdschlüssel bewusst mit CASCADE/SET NULL: Auch eine ältere CutStock-Version,
-- die diese Tabellen nicht kennt, kann Projekte, Materialien, Teile und
-- Sägeblätter weiterhin löschen (gleiche DB über iCloud auf mehreren Macs).
CREATE TABLE IF NOT EXISTS schnittplan (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    projekt_id     INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    material_id    INTEGER NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    saegeblatt_id  INTEGER REFERENCES saegeblatt(id) ON DELETE SET NULL,
    kerf           REAL    NOT NULL DEFAULT 0,
    algorithmus    TEXT    NOT NULL DEFAULT '',
    eingabe_hash   TEXT    NOT NULL DEFAULT '',
    fehlende_json  TEXT    NOT NULL DEFAULT '[]',
    bedarf_json    TEXT    NOT NULL DEFAULT '[]',
    erstellt       REAL    NOT NULL DEFAULT 0,
    geaendert      REAL    NOT NULL DEFAULT 0,
    version        INTEGER NOT NULL DEFAULT 1,
    UNIQUE(projekt_id, material_id)
);

CREATE TABLE IF NOT EXISTS schnittplan_brett (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    schnittplan_id   INTEGER NOT NULL REFERENCES schnittplan(id) ON DELETE CASCADE,
    pos              INTEGER NOT NULL DEFAULT 0,
    lagerstueck_id   INTEGER NOT NULL DEFAULT 0,   -- kein FK: Zeile verschwindet beim Verbrauch
    stueck_nr        INTEGER NOT NULL DEFAULT 0,
    lager_laenge     REAL    NOT NULL DEFAULT 0,
    lager_breite     REAL    NOT NULL DEFAULT 0,
    reste_json       TEXT    NOT NULL DEFAULT '[]',
    defekte_json     TEXT    NOT NULL DEFAULT '[]',
    verschnitt_mm    REAL    NOT NULL DEFAULT 0,
    verschnitt_prozent REAL  NOT NULL DEFAULT 0,
    verbraucht       INTEGER NOT NULL DEFAULT 0,
    rest_ids_json    TEXT    NOT NULL DEFAULT '[]',
    stueck_json      TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schnittplan_stueck (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    brett_id   INTEGER NOT NULL REFERENCES schnittplan_brett(id) ON DELETE CASCADE,
    teil_id    INTEGER REFERENCES teil(id) ON DELETE SET NULL,
    teil_label TEXT    NOT NULL DEFAULT '',
    laenge     REAL    NOT NULL DEFAULT 0,
    breite     REAL    NOT NULL DEFAULT 0,
    x          REAL    NOT NULL DEFAULT 0,
    y          REAL    NOT NULL DEFAULT 0,
    gedreht    INTEGER NOT NULL DEFAULT 0,
    gesaegt    INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    """Zentrale Datenbankklasse – öffnet/erstellt die SQLite-Datei."""

    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self._sicherung_vor_migration()
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        # DELETE-Modus statt WAL: alle Daten landen direkt in der .db-Datei.
        # Wichtig für iCloud-Sync – WAL erzeugt .db-wal/.db-shm die nicht synchronisiert werden.
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    # Spalten, die per Migration nachgerüstet werden (für die Sicherung vor dem Update)
    PFLICHT_SPALTEN = {
        "projekt": {"anzahl"},
        "material": {"kuerzel", "lagerort", "lagerort_reste"},
        "einzelstueck": {"lagerort"},
    }

    @staticmethod
    def _spalten_vorhanden(path: Path, tabelle: str) -> set[str]:
        conn = sqlite3.connect(str(path))
        try:
            return {r[1] for r in conn.execute(f"PRAGMA table_info({tabelle})")}
        finally:
            conn.close()

    def _sicherung_vor_migration(self):
        """Vor einer Schema-Änderung eine Kopie der DB anlegen (neben der DB).

        Die Migrationen legen nur Tabellen/Spalten an und ändern keine bestehenden
        Daten – die Kopie ist reine Vorsicht. Sie entsteht nur, wenn wirklich etwas
        fehlt, also einmal pro Update: <name>-vor-update-JJJJMMTT-HHMMSS.db
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        try:
            conn = sqlite3.connect(str(self.path))
            try:
                tabellen = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            if "projekt" not in tabellen:
                return  # leere/neue DB, nichts zu sichern
            if "schnittplan" in tabellen and all(
                    spalten <= self._spalten_vorhanden(self.path, tabelle)
                    for tabelle, spalten in self.PFLICHT_SPALTEN.items()):
                return  # Schema aktuell
            import shutil
            import time
            sicherung = self.path.with_name(
                f"{self.path.stem}-vor-update-{time.strftime('%Y%m%d-%H%M%S')}"
                f"{self.path.suffix}")
            if not sicherung.exists():
                shutil.copy2(str(self.path), str(sicherung))
        except (sqlite3.Error, OSError):
            pass  # Sicherung ist optional, der Start darf daran nicht scheitern

    def _create_tables(self):
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Spalten nachrüsten die in älteren DB-Versionen fehlen."""
        mat_cols = {row[1] for row in
                    self.conn.execute("PRAGMA table_info(material)").fetchall()}
        for spalte in ("kuerzel", "lagerort", "lagerort_reste"):
            if spalte not in mat_cols:
                self.conn.execute(
                    f"ALTER TABLE material ADD COLUMN {spalte} TEXT NOT NULL DEFAULT ''")
        if "bild" not in mat_cols:
            self.conn.execute(
                "ALTER TABLE material ADD COLUMN bild BLOB DEFAULT NULL")
        if "besaeumung" not in mat_cols:
            self.conn.execute(
                "ALTER TABLE material ADD COLUMN besaeumung REAL NOT NULL DEFAULT 0")
        if "maserung" not in mat_cols:
            self.conn.execute(
                "ALTER TABLE material ADD COLUMN maserung TEXT NOT NULL DEFAULT 'keine'")
            self.conn.execute(
                "UPDATE material SET maserung='längs' WHERE drehung_erlaubt=0")
        proj_cols = {row[1] for row in
                     self.conn.execute("PRAGMA table_info(projekt)").fetchall()}
        if "anzahl" not in proj_cols:
            # Default 1: bestehende Projekte bleiben unverändert; ältere Versionen
            # ignorieren die Spalte einfach (INSERT ohne anzahl → 1).
            self.conn.execute(
                "ALTER TABLE projekt ADD COLUMN anzahl INTEGER NOT NULL DEFAULT 1")
        teil_cols = {row[1] for row in
                     self.conn.execute("PRAGMA table_info(teil)").fetchall()}
        if "maserung" not in teil_cols:
            self.conn.execute(
                "ALTER TABLE teil ADD COLUMN maserung TEXT NOT NULL DEFAULT 'egal'")
        if "gesaegt_anzahl" not in teil_cols:
            self.conn.execute(
                "ALTER TABLE teil ADD COLUMN gesaegt_anzahl INTEGER NOT NULL DEFAULT 0")
            self.conn.execute(
                "UPDATE teil SET gesaegt_anzahl = stueckzahl WHERE status = 'gesägt'")
        self._migrate_einzelstuecke()
        es_cols = {row[1] for row in
                   self.conn.execute("PRAGMA table_info(einzelstueck)").fetchall()}
        if "lagerort" not in es_cols:
            self.conn.execute(
                "ALTER TABLE einzelstueck ADD COLUMN lagerort TEXT NOT NULL DEFAULT ''")
        self._migrate_kuerzel()
        self._migrate_stueck_nummern()

    def _migrate_kuerzel(self):
        """Materialien ohne Kürzel bekommen einen Vorschlag aus dem Namen."""
        vergeben = {r[0] for r in self.conn.execute(
            "SELECT kuerzel FROM material WHERE kuerzel != ''")}
        for r in self.conn.execute(
                "SELECT id, name FROM material WHERE kuerzel = '' ORDER BY id").fetchall():
            k = kuerzel_vorschlag(r["name"], vergeben)
            vergeben.add(k)
            self.conn.execute("UPDATE material SET kuerzel=? WHERE id=?", (k, r["id"]))

    def _migrate_stueck_nummern(self):
        """Stücknummern je Material eindeutig machen (früher: je Lagerzeile).

        Nur doppelte Nummern werden geändert: Das erste Stück (große/lange
        zuerst) behält seine Nummer, weitere bekommen die kleinsten freien
        Nummern des Materials. So bleiben möglichst viele Aufschriften gültig –
        auch wenn eine ältere CutStock-Version zwischendurch wieder pro
        Lagerzeile nummeriert hat. Noch nicht angefangene Bretter gespeicherter
        Pläne werden auf die neuen Nummern umgestellt.
        """
        doppelt = [r[0] for r in self.conn.execute(
            """SELECT DISTINCT l.material_id FROM einzelstueck e
               JOIN lagerstueck l ON l.id = e.lagerstueck_id
               GROUP BY l.material_id, e.nr HAVING COUNT(*) > 1""")]
        for mid in doppelt:
            stuecke = self.conn.execute(
                """SELECT e.id, e.lagerstueck_id, e.nr FROM einzelstueck e
                   JOIN lagerstueck l ON l.id = e.lagerstueck_id
                   WHERE l.material_id=?
                   ORDER BY l.laenge DESC, l.breite DESC, l.id, e.nr""", (mid,)).fetchall()
            belegt = {s["nr"] for s in stuecke}
            gesehen: set[int] = set()
            naechste = 1
            for st in stuecke:
                if st["nr"] not in gesehen:
                    gesehen.add(st["nr"])
                    continue
                while naechste in belegt:
                    naechste += 1
                belegt.add(naechste)
                gesehen.add(naechste)
                self.conn.execute("UPDATE einzelstueck SET nr=? WHERE id=?",
                                  (naechste, st["id"]))
                self.conn.execute(
                    """UPDATE schnittplan_brett SET stueck_nr=?
                       WHERE lagerstueck_id=? AND stueck_nr=? AND verbraucht=0""",
                    (naechste, st["lagerstueck_id"], st["nr"]))

    def _migrate_einzelstuecke(self):
        """Einzelstück-Tabelle befüllen, Defekt-FK migrieren."""
        defekt_cols = {row[1] for row in
                       self.conn.execute("PRAGMA table_info(defekt)").fetchall()}
        if "lagerstueck_id" not in defekt_cols:
            self._ensure_einzelstuecke_exist()
            return
        # Alte defekt-Tabelle hat lagerstueck_id → migrieren
        self._ensure_einzelstuecke_exist()
        old_defekte = self.conn.execute("SELECT * FROM defekt").fetchall()
        self.conn.execute("DROP TABLE defekt")
        self.conn.execute("""
            CREATE TABLE defekt (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                einzelstueck_id INTEGER NOT NULL REFERENCES einzelstueck(id)
                                ON DELETE CASCADE,
                position        REAL NOT NULL DEFAULT 0,
                position_y      REAL NOT NULL DEFAULT 0,
                laenge          REAL NOT NULL,
                breite          REAL NOT NULL DEFAULT 0
            )""")
        for od in old_defekte:
            es = self.conn.execute(
                "SELECT id FROM einzelstueck WHERE lagerstueck_id=? AND nr=1",
                (od["lagerstueck_id"],),
            ).fetchone()
            if es:
                self.conn.execute(
                    """INSERT INTO defekt (einzelstueck_id, position,
                       position_y, laenge, breite) VALUES (?,?,?,?,?)""",
                    (es["id"], od["position"], od["position_y"],
                     od["laenge"], od["breite"]),
                )

    def _ensure_einzelstuecke_exist(self):
        """Für alle Lagerstücke ohne Einzelstücke welche anlegen."""
        rows = self.conn.execute(
            """SELECT l.id, l.stueckzahl FROM lagerstueck l
               WHERE NOT EXISTS (
                   SELECT 1 FROM einzelstueck e WHERE e.lagerstueck_id = l.id
               )"""
        ).fetchall()
        for r in rows:
            for nr in range(1, r["stueckzahl"] + 1):
                self.conn.execute(
                    "INSERT INTO einzelstueck (lagerstueck_id, nr) VALUES (?,?)",
                    (r["id"], nr),
                )

    def close(self):
        self.conn.commit()
        self.conn.close()

    # ------------------------------------------------------------------
    # Material
    # ------------------------------------------------------------------

    def save_material(self, m: Material) -> Material:
        """Material speichern. Leeres Kürzel → Vorschlag aus dem Namen.

        Raises ValueError, wenn das Kürzel schon ein anderes Material hat.
        """
        import re
        m.kuerzel = re.sub(r"[^A-Z0-9ÄÖÜ]", "", (m.kuerzel or "").upper())[:10]
        andere = {r[0] for r in self.conn.execute(
            "SELECT kuerzel FROM material WHERE kuerzel != '' AND id != ?", (m.id or 0,))}
        if not m.kuerzel:
            m.kuerzel = kuerzel_vorschlag(m.name, andere)
        elif m.kuerzel in andere:
            raise ValueError(f"Kürzel {m.kuerzel} ist schon vergeben")
        m.lagerort = (m.lagerort or "").strip()
        m.lagerort_reste = (m.lagerort_reste or "").strip()
        if m.id is None:
            cur = self.conn.execute(
                """INSERT INTO material
                   (name, typ, dicke, querschnitt_breite, querschnitt_tiefe,
                    drehung_erlaubt, maserung, besaeumung,
                    rest_min_laenge, rest_min_breite, kuerzel, lagerort, lagerort_reste)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (m.name, m.typ.value, m.dicke, m.querschnitt_breite,
                 m.querschnitt_tiefe, int(m.maserung == Maserung.KEINE),
                 m.maserung.value, m.besaeumung,
                 m.rest_min_laenge, m.rest_min_breite,
                 m.kuerzel, m.lagerort, m.lagerort_reste),
            )
            m.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE material SET name=?, typ=?, dicke=?,
                   querschnitt_breite=?, querschnitt_tiefe=?,
                   drehung_erlaubt=?, maserung=?, besaeumung=?,
                   rest_min_laenge=?, rest_min_breite=?,
                   kuerzel=?, lagerort=?, lagerort_reste=?
                   WHERE id=?""",
                (m.name, m.typ.value, m.dicke, m.querschnitt_breite,
                 m.querschnitt_tiefe, int(m.maserung == Maserung.KEINE),
                 m.maserung.value, m.besaeumung,
                 m.rest_min_laenge, m.rest_min_breite,
                 m.kuerzel, m.lagerort, m.lagerort_reste, m.id),
            )
        self.conn.commit()
        return m

    def save_material_image(self, mid: int, image: bytes | None):
        self.conn.execute(
            "UPDATE material SET bild=? WHERE id=?", (image, mid))
        self.conn.commit()

    def get_material_image(self, mid: int) -> bytes | None:
        row = self.conn.execute(
            "SELECT bild FROM material WHERE id=?", (mid,)).fetchone()
        return row["bild"] if row else None

    def get_material(self, mid: int) -> Material | None:
        row = self.conn.execute(
            "SELECT * FROM material WHERE id=?", (mid,)
        ).fetchone()
        return self._row_to_material(row) if row else None

    def list_materials(self) -> list[Material]:
        rows = self.conn.execute(
            "SELECT id, name, typ, dicke, querschnitt_breite, querschnitt_tiefe,"
            " drehung_erlaubt, maserung, besaeumung, rest_min_laenge, rest_min_breite,"
            " kuerzel, lagerort, lagerort_reste,"
            " (bild IS NOT NULL AND length(bild) > 0) AS hat_bild"
            " FROM material ORDER BY name").fetchall()
        return [self._row_to_material(r, hat_bild_col=True) for r in rows]

    def delete_material(self, mid: int):
        self.conn.execute("DELETE FROM schnittplan WHERE material_id=?", (mid,))
        self.conn.execute("DELETE FROM teil WHERE material_id=?", (mid,))
        self.conn.execute("DELETE FROM lagerstueck WHERE material_id=?", (mid,))
        self.conn.execute("DELETE FROM material WHERE id=?", (mid,))
        self.conn.commit()

    @staticmethod
    def _row_to_material(row: sqlite3.Row, hat_bild_col: bool = False) -> Material:
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
            bild=b"\x01" if (hat_bild_col and row["hat_bild"]) else b"",
            kuerzel=row["kuerzel"], lagerort=row["lagerort"],
            lagerort_reste=row["lagerort_reste"],
        )

    # ------------------------------------------------------------------
    # Lagerstück
    # ------------------------------------------------------------------

    def save_lagerstueck(self, l: Lagerstueck, wunsch_nr: int = 0) -> Lagerstueck:
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
        self._sync_einzelstuecke(l.id, l.stueckzahl, wunsch_nr)
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
    # Einzelstück
    # ------------------------------------------------------------------

    def _sync_einzelstuecke(self, lagerstueck_id: int, stueckzahl: int,
                            wunsch_nr: int = 0):
        """Einzelstücke an Stückzahl anpassen (anlegen/löschen).

        Nummern sind je Material eindeutig, haben aber Lücken: Ein verbrauchtes
        Stück gibt seine Nummer frei, die übrigen behalten ihre (sie stehen ja
        auf dem Material). Neue Stücke bekommen die kleinsten freien Nummern des
        Materials, beim Verringern fallen die höchsten dieser Lagerzeile weg.
        """
        nrs = self.einzelstueck_nrs_for_lagerstueck(lagerstueck_id)
        if stueckzahl > len(nrs):
            for nr in self.freie_stueck_nrs(lagerstueck_id, stueckzahl - len(nrs), wunsch_nr):
                self.conn.execute(
                    "INSERT INTO einzelstueck (lagerstueck_id, nr) VALUES (?,?)",
                    (lagerstueck_id, nr),
                )
        for nr in nrs[stueckzahl:] if stueckzahl < len(nrs) else []:
            self.conn.execute(
                """DELETE FROM einzelstueck
                   WHERE lagerstueck_id=? AND nr=?""",
                (lagerstueck_id, nr),
            )

    def freie_stueck_nrs(self, lagerstueck_id: int, anzahl: int,
                         wunsch_nr: int = 0) -> list[int]:
        """Die kleinsten freien Stücknummern im Material dieser Lagerzeile.

        Ist wunsch_nr frei, kommt sie zuerst (Rest erbt den Code seines Bretts).
        """
        belegt = {r[0] for r in self.conn.execute(
            """SELECT e.nr FROM einzelstueck e
               JOIN lagerstueck l ON l.id = e.lagerstueck_id
               WHERE l.material_id = (SELECT material_id FROM lagerstueck WHERE id=?)""",
            (lagerstueck_id,))}
        frei, nr = [], 1
        if wunsch_nr > 0 and wunsch_nr not in belegt and anzahl > 0:
            frei.append(wunsch_nr)
            belegt.add(wunsch_nr)
        while len(frei) < anzahl:
            if nr not in belegt:
                frei.append(nr)
            nr += 1
        return frei

    def einzelstueck_nrs_for_material(self, material_id: int) -> dict[int, list[int]]:
        """Vorhandene Stücknummern je Lagerstück: {lagerstueck_id: [nr, ...]}."""
        rows = self.conn.execute(
            """SELECT e.lagerstueck_id, e.nr FROM einzelstueck e
               JOIN lagerstueck l ON e.lagerstueck_id = l.id
               WHERE l.material_id = ?
               ORDER BY e.lagerstueck_id, e.nr""",
            (material_id,),
        ).fetchall()
        result: dict[int, list[int]] = {}
        for r in rows:
            result.setdefault(r["lagerstueck_id"], []).append(r["nr"])
        return result

    def list_einzelstuecke(self, lagerstueck_id: int) -> list[Einzelstueck]:
        rows = self.conn.execute(
            "SELECT * FROM einzelstueck WHERE lagerstueck_id=? ORDER BY nr",
            (lagerstueck_id,),
        ).fetchall()
        return [Einzelstueck(id=r["id"], lagerstueck_id=r["lagerstueck_id"],
                             nr=r["nr"], notiz=r["notiz"], lagerort=r["lagerort"])
                for r in rows]

    def get_einzelstueck(self, eid: int) -> Einzelstueck | None:
        row = self.conn.execute(
            "SELECT * FROM einzelstueck WHERE id=?", (eid,)
        ).fetchone()
        if not row:
            return None
        return Einzelstueck(id=row["id"], lagerstueck_id=row["lagerstueck_id"],
                            nr=row["nr"], notiz=row["notiz"], lagerort=row["lagerort"])

    def save_einzelstueck(self, e: Einzelstueck) -> Einzelstueck:
        self.conn.execute(
            "UPDATE einzelstueck SET notiz=?, lagerort=? WHERE id=?",
            (e.notiz, (e.lagerort or "").strip(), e.id),
        )
        self.conn.commit()
        return e

    # ------------------------------------------------------------------
    # Defekt
    # ------------------------------------------------------------------

    def save_defekt(self, d: Defekt) -> Defekt:
        if d.id is None:
            cur = self.conn.execute(
                """INSERT INTO defekt (einzelstueck_id, position, position_y,
                   laenge, breite) VALUES (?,?,?,?,?)""",
                (d.einzelstueck_id, d.position, d.position_y,
                 d.laenge, d.breite),
            )
            d.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE defekt SET einzelstueck_id=?, position=?,
                   position_y=?, laenge=?, breite=? WHERE id=?""",
                (d.einzelstueck_id, d.position, d.position_y,
                 d.laenge, d.breite, d.id),
            )
        self.conn.commit()
        return d

    def list_defekte(self, einzelstueck_id: int) -> list[Defekt]:
        rows = self.conn.execute(
            "SELECT * FROM defekt WHERE einzelstueck_id=? ORDER BY position",
            (einzelstueck_id,),
        ).fetchall()
        return [self._row_to_defekt(r) for r in rows]

    def list_defekte_for_lagerstueck(self, lagerstueck_id: int
                                     ) -> dict[int, list[Defekt]]:
        """Defekte gruppiert nach Stücknummer für ein Lagerstück."""
        rows = self.conn.execute(
            """SELECT d.*, e.nr FROM defekt d
               JOIN einzelstueck e ON d.einzelstueck_id = e.id
               WHERE e.lagerstueck_id = ?
               ORDER BY e.nr, d.position""",
            (lagerstueck_id,),
        ).fetchall()
        result: dict[int, list[Defekt]] = {}
        for r in rows:
            result.setdefault(r["nr"], []).append(self._row_to_defekt(r))
        return result

    def list_defekte_for_material(
        self, material_id: int,
    ) -> dict[int, dict[int, list[Defekt]]]:
        """Defekte für den Optimizer: {lagerstueck_id: {stueck_nr: [Defekt]}}."""
        rows = self.conn.execute(
            """SELECT d.*, e.nr, e.lagerstueck_id FROM defekt d
               JOIN einzelstueck e ON d.einzelstueck_id = e.id
               JOIN lagerstueck l ON e.lagerstueck_id = l.id
               WHERE l.material_id = ?
               ORDER BY e.lagerstueck_id, e.nr, d.position""",
            (material_id,),
        ).fetchall()
        result: dict[int, dict[int, list[Defekt]]] = {}
        for r in rows:
            lid = r["lagerstueck_id"]
            nr = r["nr"]
            result.setdefault(lid, {}).setdefault(nr, []).append(
                self._row_to_defekt(r))
        return result

    def get_defekt(self, did: int) -> Defekt | None:
        row = self.conn.execute(
            "SELECT * FROM defekt WHERE id=?", (did,)
        ).fetchone()
        return self._row_to_defekt(row) if row else None

    def delete_defekt(self, did: int):
        self.conn.execute("DELETE FROM defekt WHERE id=?", (did,))
        self.conn.commit()

    @staticmethod
    def _row_to_defekt(row: sqlite3.Row) -> Defekt:
        return Defekt(
            id=row["id"],
            einzelstueck_id=row["einzelstueck_id"],
            position=row["position"],
            position_y=row["position_y"],
            laenge=row["laenge"],
            breite=row["breite"],
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
        p.anzahl = max(1, int(p.anzahl or 1))
        if p.id is None:
            cur = self.conn.execute(
                "INSERT INTO projekt (name, anzahl) VALUES (?,?)", (p.name, p.anzahl)
            )
            p.id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE projekt SET name=?, anzahl=? WHERE id=?", (p.name, p.anzahl, p.id)
            )
            # Weniger Exemplare: Fortschritt darf die neue Gesamtmenge nicht übersteigen
            self.conn.execute(
                """UPDATE teil SET gesaegt_anzahl = MIN(gesaegt_anzahl, stueckzahl * ?),
                   status = CASE WHEN MIN(gesaegt_anzahl, stueckzahl * ?) >= stueckzahl * ?
                   THEN 'gesägt' ELSE 'offen' END WHERE projekt_id=?""",
                (p.anzahl, p.anzahl, p.anzahl, p.id))
        self.conn.commit()
        return p

    def list_projekte(self) -> list[Projekt]:
        rows = self.conn.execute("SELECT * FROM projekt ORDER BY name").fetchall()
        projekte = []
        for r in rows:
            p = Projekt(id=r["id"], name=r["name"], anzahl=r["anzahl"])
            p.teile = self.list_teile(p.id)
            projekte.append(p)
        return projekte

    def get_projekt(self, pid: int) -> Projekt | None:
        row = self.conn.execute(
            "SELECT * FROM projekt WHERE id=?", (pid,)
        ).fetchone()
        if not row:
            return None
        p = Projekt(id=row["id"], name=row["name"], anzahl=row["anzahl"])
        p.teile = self.list_teile(p.id)
        return p

    def delete_projekt(self, pid: int):
        self.conn.execute("DELETE FROM schnittplan WHERE projekt_id=?", (pid,))
        self.conn.execute("DELETE FROM teil WHERE projekt_id=?", (pid,))
        self.conn.execute("DELETE FROM projekt WHERE id=?", (pid,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Teil
    # ------------------------------------------------------------------

    def save_teil(self, t: Teil) -> Teil:
        row = self.conn.execute(
            "SELECT anzahl FROM projekt WHERE id=?", (t.projekt_id,)).fetchone()
        t.exemplare = row["anzahl"] if row else 1
        # Status aus gesaegt_anzahl ableiten (über alle Exemplare)
        if t.ist_komplett:
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
            """SELECT t.*, p.anzahl AS exemplare FROM teil t
               JOIN projekt p ON p.id = t.projekt_id
               WHERE t.projekt_id=? ORDER BY t.label""",
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
            exemplare=row["exemplare"] if "exemplare" in row.keys() else 1,
        )

    # ------------------------------------------------------------------
    # Gespeicherte Schnittpläne
    # ------------------------------------------------------------------

    def save_plan(self, plan: GespeicherterPlan) -> GespeicherterPlan:
        """Plan für (Projekt, Material) anlegen bzw. komplett ersetzen."""
        import json
        import time
        jetzt = time.time()
        alt = self.conn.execute(
            "SELECT id, erstellt, version FROM schnittplan WHERE projekt_id=? AND material_id=?",
            (plan.projekt_id, plan.material_id),
        ).fetchone()
        if alt:
            self.conn.execute("DELETE FROM schnittplan WHERE id=?", (alt["id"],))
            plan.version = alt["version"] + 1
        plan.erstellt = plan.erstellt or jetzt
        plan.geaendert = jetzt
        cur = self.conn.execute(
            """INSERT INTO schnittplan (projekt_id, material_id, saegeblatt_id, kerf,
               algorithmus, eingabe_hash, fehlende_json, bedarf_json, erstellt,
               geaendert, version) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (plan.projekt_id, plan.material_id, plan.saegeblatt_id, plan.kerf,
             plan.algorithmus, plan.eingabe_hash, json.dumps(plan.fehlende_teile),
             json.dumps(plan.materialbedarf), plan.erstellt, plan.geaendert,
             plan.version),
        )
        plan.id = cur.lastrowid
        for pos, b in enumerate(plan.bretter):
            b.schnittplan_id = plan.id
            b.pos = pos
            cur = self.conn.execute(
                """INSERT INTO schnittplan_brett (schnittplan_id, pos, lagerstueck_id,
                   stueck_nr, lager_laenge, lager_breite, reste_json, defekte_json,
                   verschnitt_mm, verschnitt_prozent, verbraucht, rest_ids_json,
                   stueck_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (b.schnittplan_id, b.pos, b.lagerstueck_id, b.stueck_nr,
                 b.lager_laenge, b.lager_breite, json.dumps(b.reste),
                 json.dumps(b.defekte), b.verschnitt_mm, b.verschnitt_prozent,
                 int(b.verbraucht), json.dumps(b.rest_ids),
                 json.dumps(b.verbrauchtes_stueck) if b.verbrauchtes_stueck else ""),
            )
            b.id = cur.lastrowid
            for st in b.stuecke:
                st.brett_id = b.id
                cur = self.conn.execute(
                    """INSERT INTO schnittplan_stueck (brett_id, teil_id, teil_label,
                       laenge, breite, x, y, gedreht, gesaegt)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (st.brett_id, st.teil_id, st.teil_label, st.laenge, st.breite,
                     st.x, st.y, int(st.gedreht), int(st.gesaegt)),
                )
                st.id = cur.lastrowid
        self.conn.commit()
        return plan

    def get_plan(self, projekt_id: int, material_id: int) -> GespeicherterPlan | None:
        row = self.conn.execute(
            "SELECT * FROM schnittplan WHERE projekt_id=? AND material_id=?",
            (projekt_id, material_id),
        ).fetchone()
        return self._row_to_plan(row) if row else None

    def get_plan_by_id(self, plan_id: int) -> GespeicherterPlan | None:
        row = self.conn.execute(
            "SELECT * FROM schnittplan WHERE id=?", (plan_id,)).fetchone()
        return self._row_to_plan(row) if row else None

    def get_plan_for_stueck(self, stueck_id: int) -> GespeicherterPlan | None:
        row = self.conn.execute(
            """SELECT p.* FROM schnittplan p
               JOIN schnittplan_brett b ON b.schnittplan_id = p.id
               JOIN schnittplan_stueck s ON s.brett_id = b.id
               WHERE s.id=?""", (stueck_id,)).fetchone()
        return self._row_to_plan(row) if row else None

    def _row_to_plan(self, row: sqlite3.Row) -> GespeicherterPlan:
        import json
        plan = GespeicherterPlan(
            id=row["id"], projekt_id=row["projekt_id"], material_id=row["material_id"],
            saegeblatt_id=row["saegeblatt_id"], kerf=row["kerf"],
            algorithmus=row["algorithmus"], eingabe_hash=row["eingabe_hash"],
            fehlende_teile=json.loads(row["fehlende_json"] or "[]"),
            materialbedarf=json.loads(row["bedarf_json"] or "[]"),
            erstellt=row["erstellt"], geaendert=row["geaendert"],
            version=row["version"],
        )
        bretter = self.conn.execute(
            "SELECT * FROM schnittplan_brett WHERE schnittplan_id=? ORDER BY pos",
            (plan.id,)).fetchall()
        for b in bretter:
            brett = PlanBrett(
                id=b["id"], schnittplan_id=plan.id, pos=b["pos"],
                lagerstueck_id=b["lagerstueck_id"], stueck_nr=b["stueck_nr"],
                lager_laenge=b["lager_laenge"], lager_breite=b["lager_breite"],
                reste=json.loads(b["reste_json"] or "[]"),
                defekte=json.loads(b["defekte_json"] or "[]"),
                verschnitt_mm=b["verschnitt_mm"],
                verschnitt_prozent=b["verschnitt_prozent"],
                verbraucht=bool(b["verbraucht"]),
                # [[lagerstueck_id, stück_nr], ...]; bis 2026.10.62 nur IDs
                rest_ids=[r if isinstance(r, list) else [r, 0]
                          for r in json.loads(b["rest_ids_json"] or "[]")],
                verbrauchtes_stueck=json.loads(b["stueck_json"]) if b["stueck_json"] else None,
            )
            brett.stuecke = [
                PlanStueck(id=s["id"], brett_id=brett.id, teil_id=s["teil_id"],
                           teil_label=s["teil_label"], laenge=s["laenge"],
                           breite=s["breite"], x=s["x"], y=s["y"],
                           gedreht=bool(s["gedreht"]), gesaegt=bool(s["gesaegt"]))
                for s in self.conn.execute(
                    "SELECT * FROM schnittplan_stueck WHERE brett_id=? ORDER BY id",
                    (brett.id,)).fetchall()
            ]
            plan.bretter.append(brett)
        return plan

    def list_plan_status(self, projekt_id: int) -> list[dict]:
        """Kurzstatus aller Pläne eines Projekts (für Projektliste/Dropdowns)."""
        rows = self.conn.execute(
            """SELECT p.id, p.material_id, p.erstellt,
                      COUNT(s.id) AS gesamt,
                      COALESCE(SUM(s.gesaegt), 0) AS gesaegt,
                      COALESCE(MAX(b.verbraucht), 0) AS angefangen
               FROM schnittplan p
               LEFT JOIN schnittplan_brett b ON b.schnittplan_id = p.id
               LEFT JOIN schnittplan_stueck s ON s.brett_id = b.id
               WHERE p.projekt_id=? GROUP BY p.id ORDER BY p.id""",
            (projekt_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_stueck_gesaegt(self, stueck_id: int, gesaegt: bool):
        self.conn.execute("UPDATE schnittplan_stueck SET gesaegt=? WHERE id=?",
                          (int(gesaegt), stueck_id))
        self.conn.commit()

    def save_brett_zustand(self, b: PlanBrett):
        import json
        self.conn.execute(
            """UPDATE schnittplan_brett SET lagerstueck_id=?, verbraucht=?,
               rest_ids_json=?, stueck_json=? WHERE id=?""",
            (b.lagerstueck_id, int(b.verbraucht), json.dumps(b.rest_ids),
             json.dumps(b.verbrauchtes_stueck) if b.verbrauchtes_stueck else "",
             b.id))
        self.conn.commit()

    def plan_geaendert(self, plan_id: int):
        """Version hochzählen (Grundlage für spätere Mehrbenutzer-Erkennung)."""
        import time
        self.conn.execute(
            "UPDATE schnittplan SET version = version + 1, geaendert=? WHERE id=?",
            (time.time(), plan_id))
        self.conn.commit()

    def teil_gesaegt_aendern(self, teil_id: int, delta: int):
        """Fortschritt relativ ändern (nie unter 0, nie über die Stückzahl)."""
        self.conn.execute(
            """UPDATE teil SET gesaegt_anzahl = MAX(0, MIN(
                   stueckzahl * (SELECT anzahl FROM projekt WHERE id = teil.projekt_id),
                   gesaegt_anzahl + ?))
               WHERE id=?""", (delta, teil_id))
        self.conn.execute(
            """UPDATE teil SET status = CASE WHEN gesaegt_anzahl >=
                   stueckzahl * (SELECT anzahl FROM projekt WHERE id = teil.projekt_id)
               THEN 'gesägt' ELSE 'offen' END WHERE id=?""", (teil_id,))
        self.conn.commit()

    def projekt_neu_starten(self, projekt_id: int):
        """Fortschritt aller Teile zurücksetzen und Pläne löschen (Lager bleibt)."""
        self.conn.execute(
            "UPDATE teil SET gesaegt_anzahl=0, status='offen' WHERE projekt_id=?",
            (projekt_id,))
        self.conn.execute("DELETE FROM schnittplan WHERE projekt_id=?", (projekt_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Lager-Operationen für den Optimierungslauf
    # ------------------------------------------------------------------

    def lager_verbrauchen(self, lagerstueck_id: int, anzahl: int = 1,
                          stueck_nr: int = 0) -> dict | None:
        """Stückzahl reduzieren, bei 0 löschen.

        Mit stueck_nr wird genau dieses Einzelstück verbraucht (samt Defekten),
        sonst das mit der höchsten Nummer. Liefert dann einen Schnappschuss
        {nr, notiz, defekte}, mit dem einzelstueck_wiederherstellen es beim
        Zurücknehmen wieder anlegt.
        """
        ls = self.get_lagerstueck(lagerstueck_id)
        if not ls:
            return None
        snapshot = None
        if stueck_nr:
            row = self.conn.execute(
                "SELECT * FROM einzelstueck WHERE lagerstueck_id=? AND nr=?",
                (lagerstueck_id, stueck_nr),
            ).fetchone()
            if row:
                snapshot = {
                    "nr": row["nr"], "notiz": row["notiz"], "lagerort": row["lagerort"],
                    "defekte": [
                        {"position": d.position, "position_y": d.position_y,
                         "laenge": d.laenge, "breite": d.breite}
                        for d in self.list_defekte(row["id"])],
                }
                self.conn.execute("DELETE FROM einzelstueck WHERE id=?", (row["id"],))
                anzahl = 1
        ls.stueckzahl -= anzahl
        if ls.stueckzahl <= 0:
            self.delete_lagerstueck(lagerstueck_id)
        else:
            self.save_lagerstueck(ls)
        return snapshot

    def stueck_hinzufuegen(self, ls: Lagerstueck,
                           wunsch_nr: int = 0) -> tuple[Lagerstueck, int]:
        """Stückzahl um 1 erhöhen; liefert die Nummer des neu angelegten Stücks."""
        vorher = set(self.einzelstueck_nrs_for_lagerstueck(ls.id)) if ls.id else set()
        ls.stueckzahl += 1
        ls = self.save_lagerstueck(ls, wunsch_nr)
        neu = [n for n in self.einzelstueck_nrs_for_lagerstueck(ls.id) if n not in vorher]
        return ls, (neu[0] if neu else 0)

    def einzelstueck_wiederherstellen(self, lagerstueck_id: int, neue_nr: int,
                                      snapshot: dict):
        """Ein per lager_verbrauchen verbrauchtes Stück wieder anlegen.

        Das gerade per stueck_hinzufuegen angelegte Stück (neue_nr) bekommt
        seine alte Nummer (falls im Material frei), Notiz, Lagerort und Defekte zurück.
        """
        neu = self.conn.execute(
            "SELECT id FROM einzelstueck WHERE lagerstueck_id=? AND nr=?",
            (lagerstueck_id, neue_nr),
        ).fetchone()
        if not neu:
            return
        nr = snapshot.get("nr", 0)
        frei = nr and not self.conn.execute(
            """SELECT 1 FROM einzelstueck e JOIN lagerstueck l ON l.id = e.lagerstueck_id
               WHERE e.nr=? AND e.id != ? AND l.material_id =
                     (SELECT material_id FROM lagerstueck WHERE id=?)""",
            (nr, neu["id"], lagerstueck_id)).fetchone()
        if frei:
            self.conn.execute("UPDATE einzelstueck SET nr=? WHERE id=?",
                              (nr, neu["id"]))
        self.conn.execute("UPDATE einzelstueck SET notiz=?, lagerort=? WHERE id=?",
                          (snapshot.get("notiz", ""), snapshot.get("lagerort", ""),
                           neu["id"]))
        for d in snapshot.get("defekte", []):
            self.conn.execute(
                """INSERT INTO defekt (einzelstueck_id, position, position_y,
                   laenge, breite) VALUES (?,?,?,?,?)""",
                (neu["id"], d.get("position", 0), d.get("position_y", 0),
                 d.get("laenge", 0), d.get("breite", 0)),
            )
        self.conn.commit()

    def einzelstueck_nrs_for_lagerstueck(self, lagerstueck_id: int) -> list[int]:
        return [r["nr"] for r in self.conn.execute(
            "SELECT nr FROM einzelstueck WHERE lagerstueck_id=? ORDER BY nr",
            (lagerstueck_id,),
        ).fetchall()]

    def rest_einbuchen(self, material_id: int, laenge: float, breite: float = 0.0,
                       wunsch_nr: int = 0) -> tuple[Lagerstueck, int] | None:
        """Rest als Lagerstück einbuchen. Gleiche Maße werden zusammengefasst.

        Liefert (Lagerzeile, Stücknummer des neuen Rests) oder None, wenn der
        Rest unter dem Mindestmaß liegt (= Abfall). Der Rest bekommt den
        Reste-Lagerort des Materials und, falls frei, die Nummer wunsch_nr.
        """
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
        ls = next((e for e in self.list_lagerstuecke(material_id)
                   if abs(e.laenge - laenge) < 0.1 and abs(e.breite - breite) < 0.1),
                  None) or Lagerstueck(material_id=material_id, laenge=laenge,
                                       breite=breite, stueckzahl=0)
        ls, nr = self.stueck_hinzufuegen(ls, wunsch_nr)
        if mat.lagerort_reste and nr:
            self.conn.execute(
                "UPDATE einzelstueck SET lagerort=? WHERE lagerstueck_id=? AND nr=?",
                (mat.lagerort_reste, ls.id, nr))
            self.conn.commit()
        return ls, nr


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
