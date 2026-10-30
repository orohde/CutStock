"""Tests für die FastAPI-Schicht (API-Key, Einstellungen, Plan-Markierung)."""

import json
import os
import tempfile
from pathlib import Path

# DB_PATH wird beim Import von web.app festgelegt – vorher auf eine Wegwerf-DB zeigen.
_TMP = Path(tempfile.mkdtemp(prefix="cutstock-test-"))
os.environ["CUTSTOCK_DB"] = str(_TMP / "cutstock.db")

import pytest
from fastapi.testclient import TestClient

from web import app as webapp

KEY = "geheim123"


@pytest.fixture
def client():
    webapp.SETTINGS_PATH.unlink(missing_ok=True)
    with TestClient(webapp.app, base_url="http://cutstock.test") as c:
        yield c
    webapp.SETTINGS_PATH.unlink(missing_ok=True)


def _set_key(key: str):
    webapp.SETTINGS_PATH.write_text(json.dumps({"api": {"key": key}}))


def _mark_plan(payload: dict) -> dict:
    """Lager-Abgleich eines Bretts direkt aufrufen (früher /api/optimize/mark-plan)."""
    return webapp._mark_plan_core(webapp.get_db(), webapp.MarkPlanRequest(**payload))


def _ui_cookie(c: TestClient):
    return c.cookies.get("cutstock_ui_default")


# =====================================================================
# API-Key-Middleware
# =====================================================================

class TestApiKey:

    def test_ohne_key_offen(self, client):
        assert client.get("/api/version").status_code == 200

    def test_mit_key_ohne_auth_abgelehnt(self, client):
        _set_key(KEY)
        assert client.get("/api/version").status_code == 401

    def test_gefaelschter_referer_reicht_nicht(self, client):
        _set_key(KEY)
        r = client.get("/api/version", headers={
            "Referer": "http://cutstock.test/", "Host": "cutstock.test"})
        assert r.status_code == 401

    def test_bearer_token(self, client):
        _set_key(KEY)
        ok = client.get("/api/version", headers={"Authorization": f"Bearer {KEY}"})
        falsch = client.get("/api/version", headers={"Authorization": "Bearer nein"})
        assert ok.status_code == 200
        assert falsch.status_code == 401

    def test_weboberflaeche_bekommt_cookie(self, client):
        _set_key(KEY)
        client.get("/")
        assert _ui_cookie(client)
        r = client.get("/api/version", headers={"Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 200

    def test_cookie_nicht_von_fremder_seite(self, client):
        _set_key(KEY)
        client.get("/")
        for site in ("same-site", "cross-site"):
            r = client.get("/api/version", headers={"Sec-Fetch-Site": site})
            assert r.status_code == 401

    def test_cookie_nach_keywechsel_ungueltig(self, client):
        _set_key(KEY)
        client.get("/")
        _set_key("anderer")
        r = client.get("/api/version", headers={"Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 401

    def test_keywechsel_ueber_oberflaeche_erneuert_cookie(self, client):
        _set_key(KEY)
        client.get("/")
        h = {"Sec-Fetch-Site": "same-origin"}
        assert client.put("/api/settings", json={"api_key": "neu"}, headers=h).status_code == 200
        assert client.get("/api/version", headers=h).status_code == 200

    def test_lokal_nur_ohne_proxy_header(self, client, monkeypatch):
        _set_key(KEY)

        class _Client:
            host = "127.0.0.1"

        monkeypatch.setattr(webapp.StarletteRequest, "client", property(lambda self: _Client))
        assert client.get("/api/version").status_code == 200
        r = client.get("/api/version", headers={"X-Forwarded-For": "203.0.113.5"})
        assert r.status_code == 401


# =====================================================================
# Einstellungen
# =====================================================================

class TestSettings:

    def test_theme_default_system(self, client):
        assert client.get("/api/settings").json()["theme"] == "system"

    def test_altes_auto_wird_system(self, client):
        webapp.SETTINGS_PATH.write_text(json.dumps({"appearance": {"theme": "auto"}}))
        assert client.get("/api/settings").json()["theme"] == "system"


# =====================================================================
# Plan-Markierung: Zurücknehmen bucht Originalmaße zurück
# =====================================================================

class TestMarkPlanUndo:

    def _material(self, client, typ, besaeumung):
        r = client.post("/api/materials", json={
            "name": f"Test {typ}", "typ": typ, "besaeumung": besaeumung})
        return r.json()["id"]

    def _stock(self, client, mid):
        return [(s["laenge"], s["breite"], s["stueckzahl"])
                for s in client.get(f"/api/stock?material_id={mid}").json()]

    def _mark(self, client, mid, sid, is_1d, l, b, marked, consumed, rest_ids=()):
        return _mark_plan({
            "material_id": mid, "lagerstueck_id": sid, "is_1d": is_1d,
            "lager_laenge": l, "lager_breite": b, "kerf": 3,
            "marked_laengen": marked, "prev_consumed": consumed,
            "prev_rest_ids": list(rest_ids)})

    @pytest.mark.parametrize("stueckzahl", [1, 2])
    def test_platte_mehrfach_markieren_und_zuruecknehmen(self, client, stueckzahl):
        mid = self._material(client, "Platte", 10)
        sid = client.post("/api/stock", json={
            "material_id": mid, "laenge": 2800, "breite": 2070,
            "stueckzahl": stueckzahl}).json()["id"]
        # Plan kennt die besäumten Maße
        l, b = 2780, 2050
        for _ in range(3):
            res = self._mark(client, mid, sid, False, l, b, [500], False)
            assert res["consumed"]
            res = self._mark(client, mid, sid, False, l, b, [], True, res["rest_ids"])
            assert not res["consumed"]
            sid = res["lagerstueck_id"]
            assert self._stock(client, mid) == [(2800, 2070, stueckzahl)]

    def test_stange_zuruecknehmen(self, client):
        mid = self._material(client, "Stange", 5)
        sid = client.post("/api/stock", json={
            "material_id": mid, "laenge": 3000, "stueckzahl": 1}).json()["id"]
        res = self._mark(client, mid, sid, True, 2990, 0, [800], False)
        res = self._mark(client, mid, sid, True, 2990, 0, [], True, res["rest_ids"])
        assert self._stock(client, mid) == [(3000, 0, 1)]

    def test_stange_mit_defekt_reste_ohne_defekt(self, client):
        """Defektzone wird herausgeschnitten, die Reste liegen links/rechts."""
        mid = self._material(client, "Stange", 0)
        sid = client.post("/api/stock", json={
            "material_id": mid, "laenge": 3000, "stueckzahl": 1}).json()["id"]
        res = _mark_plan({
            "material_id": mid, "lagerstueck_id": sid, "is_1d": True,
            "lager_laenge": 3000, "kerf": 3,
            "marked_laengen": [820, 820], "marked_x": [0, 1050],
            "defekte": [[1000, 50]], "prev_consumed": False})
        assert sorted(self._stock(client, mid)) == [(177, 0, 1), (1127, 0, 1)]
        self._mark(client, mid, res["lagerstueck_id"], True, 3000, 0, [], True,
                   res["rest_ids"])
        assert self._stock(client, mid) == [(3000, 0, 1)]


# =====================================================================
# Verbrauch trifft das Einzelstück aus dem Plan (nicht das mit der höchsten Nr.)
# =====================================================================

class TestEinzelstueckVerbrauch:

    def _setup(self, client, typ="Platte", stueckzahl=3):
        mid = client.post("/api/materials", json={
            "name": f"ES {typ}", "typ": typ}).json()["id"]
        sid = client.post("/api/stock", json={
            "material_id": mid, "laenge": 2000,
            "breite": 1000 if typ == "Platte" else 0,
            "stueckzahl": stueckzahl}).json()["id"]
        return mid, sid

    def _pieces(self, client, sid):
        return {p["nr"]: p for p in client.get(f"/api/stock/{sid}/pieces").json()}

    def _defect(self, client, sid, nr, pos=100, pos_y=100):
        eid = self._pieces(client, sid)[nr]["id"]
        client.post(f"/api/pieces/{eid}/defects",
                    json={"position": pos, "position_y": pos_y,
                          "laenge": 50, "breite": 50})

    def _mark(self, client, mid, sid, nr, marked, consumed=False, piece=None,
              rest_ids=()):
        return _mark_plan({
            "material_id": mid, "lagerstueck_id": sid, "is_1d": False,
            "lager_laenge": 2000, "lager_breite": 1000, "kerf": 3,
            "marked_laengen": marked, "prev_consumed": consumed,
            "prev_rest_ids": list(rest_ids), "stueck_nr": nr,
            "prev_consumed_piece": piece})

    def test_verbraucht_plan_stueck_und_nimmt_zurueck(self, client):
        mid, sid = self._setup(client)
        self._defect(client, sid, 1)
        client.put(f"/api/pieces/{self._pieces(client, sid)[1]['id']}",
                   json={"notiz": "Ast"})

        res = self._mark(client, mid, sid, 1, [500])
        assert sorted(self._pieces(client, sid)) == [2, 3]
        assert res["consumed_piece"]["nr"] == 1

        res = self._mark(client, mid, res["lagerstueck_id"], 1, [], True,
                         res["consumed_piece"], res["rest_ids"])
        pieces = self._pieces(client, sid)
        assert sorted(pieces) == [1, 2, 3]
        assert pieces[1]["notiz"] == "Ast"
        assert pieces[1]["defekt_count"] == 1
        assert res["consumed_piece"] is None

    @pytest.mark.parametrize("sperrfrist,erwartet", [(0, [1, 2, 3]), (1, [1, 3, 4])])
    def test_freie_nummer_nach_sperrfrist(self, client, sperrfrist, erwartet):
        client.put("/api/settings", json={"nr_lock_days": sperrfrist})
        mid, sid = self._setup(client)
        self._mark(client, mid, sid, 2, [500])
        assert sorted(self._pieces(client, sid)) == [1, 3]
        stock = client.get(f"/api/stock?material_id={mid}").json()
        ls = next(s for s in stock if s["id"] == sid)
        client.put(f"/api/stock/{sid}", json={**ls, "stueckzahl": 3})
        assert sorted(self._pieces(client, sid)) == erwartet

    def test_optimierung_nutzt_echte_nummern(self, client):
        mid, sid = self._setup(client, stueckzahl=3)
        self._defect(client, sid, 3, pos=1940, pos_y=940)   # Ecke, Teil passt
        self._mark(client, mid, sid, 1, [500])        # #1 weg, Rest: 2, 3
        pid = client.post("/api/projects", json={"name": "ES"}).json()["id"]
        client.post(f"/api/projects/{pid}/parts", json={
            "label": "A", "material_id": mid, "laenge": 1900,
            "breite": 900, "stueckzahl": 2})
        bid = client.post("/api/blades", json={"name": "B"}).json()["id"]
        res = client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid}).json()
        plaene = [p for p in res["schnittplaene"] if p["lagerstueck_id"] == sid]
        assert sorted(p["stueck_nr"] for p in plaene) == [2, 3]
        p3 = next(p for p in plaene if p["stueck_nr"] == 3)
        p2 = next(p for p in plaene if p["stueck_nr"] == 2)
        assert len(p3["defekte"]) == 1 and p2["defekte"] == []


# =====================================================================
# Gespeicherte Schnittpläne
# =====================================================================

class TestGespeichertePlaene:

    def _setup(self, client, typ="Platte", stock=None, teile=None):
        mid = client.post("/api/materials", json={
            "name": f"Plan {typ}", "typ": typ}).json()["id"]
        for laenge, breite, n in stock or [(2000, 1000, 3)]:
            client.post("/api/stock", json={"material_id": mid, "laenge": laenge,
                                            "breite": breite, "stueckzahl": n})
        pid = client.post("/api/projects", json={"name": "Plan"}).json()["id"]
        for label, laenge, breite, n in teile or [("A", 900, 900, 4)]:
            client.post(f"/api/projects/{pid}/parts", json={
                "label": label, "typ": typ, "material_id": mid,
                "laenge": laenge, "breite": breite, "stueckzahl": n})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        return mid, pid, bid

    def _optimize(self, client, mid, pid, bid):
        r = client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid,
            "algorithm": "nested"})
        assert r.status_code == 200, r.text
        return r.json()

    def _teile(self, client, pid):
        return {t["label"]: t for t in client.get(f"/api/projects/{pid}").json()["teile"]}

    def _stock_total(self, client, mid):
        return sum(s["stueckzahl"] for s in client.get(f"/api/stock?material_id={mid}").json())

    def test_berechnung_wird_gespeichert_und_geladen(self, client):
        mid, pid, bid = self._setup(client)
        plan = self._optimize(client, mid, pid, bid)
        assert plan["plan_id"] > 0
        geladen = client.get(f"/api/projects/{pid}/plans/{mid}").json()
        assert geladen["plan_id"] == plan["plan_id"]
        assert len(geladen["schnittplaene"]) == len(plan["schnittplaene"])
        assert all(p["id"] > 0 for sp in geladen["schnittplaene"] for p in sp["platzierungen"])
        assert not geladen["veraltet"] and not geladen["lager_fehlt"]
        assert client.get(f"/api/projects/{pid}").json()["plaene"][0]["gesamt"] == 4

    def test_ohne_plan_null(self, client):
        mid, pid, _ = self._setup(client)
        assert client.get(f"/api/projects/{pid}/plans/{mid}").json() is None

    def test_abhaken_idempotent_mit_fortschritt_und_lager(self, client):
        mid, pid, bid = self._setup(client)
        plan = self._optimize(client, mid, pid, bid)
        stueck = plan["schnittplaene"][0]["platzierungen"][0]
        vorher = self._stock_total(client, mid)
        for _ in range(2):   # zweimal „gesägt“ setzen zählt nur einmal
            res = client.post(f"/api/plan-pieces/{stueck['id']}", json={"gesaegt": True}).json()
        assert res["teil"]["gesaegt_anzahl"] == 1
        assert res["plan"]["schnittplaene"][0]["verbraucht"]
        voll = [s for s in client.get(f"/api/stock?material_id={mid}").json()
                if s["laenge"] == 2000 and s["breite"] == 1000]
        assert voll[0]["stueckzahl"] == 2                   # eine ganze Platte weniger
        # Stand überlebt das Neuladen
        geladen = client.get(f"/api/projects/{pid}/plans/{mid}").json()
        assert geladen["schnittplaene"][0]["platzierungen"][0]["gesaegt"]
        # Zurücknehmen stellt Fortschritt und Lager wieder her
        res = client.post(f"/api/plan-pieces/{stueck['id']}", json={"gesaegt": False}).json()
        assert res["teil"]["gesaegt_anzahl"] == 0
        assert not res["plan"]["schnittplaene"][0]["verbraucht"]
        assert self._stock_total(client, mid) == vorher

    def test_alle_bestaetigen(self, client):
        mid, pid, bid = self._setup(client)
        plan = self._optimize(client, mid, pid, bid)
        res = client.post(f"/api/plans/{plan['plan_id']}/confirm-all").json()
        assert all(p["gesaegt"] for sp in res["schnittplaene"] for p in sp["platzierungen"])
        assert self._teile(client, pid)["A"]["gesaegt_anzahl"] == 4

    def test_veraltet_nach_teil_aenderung(self, client):
        mid, pid, bid = self._setup(client)
        self._optimize(client, mid, pid, bid)
        teil = self._teile(client, pid)["A"]
        client.put(f"/api/parts/{teil['id']}", json={**teil, "stueckzahl": 5})
        assert client.get(f"/api/projects/{pid}/plans/{mid}").json()["veraltet"]

    def test_neu_berechnen_behaelt_angefangene_platte(self, client):
        mid, pid, bid = self._setup(client, stock=[(2000, 1000, 3)],
                                    teile=[("A", 900, 900, 4)])
        plan = self._optimize(client, mid, pid, bid)
        brett = plan["schnittplaene"][0]
        client.post(f"/api/plan-pieces/{brett['platzierungen'][0]['id']}",
                    json={"gesaegt": True})
        neu = self._optimize(client, mid, pid, bid)
        erstes = neu["schnittplaene"][0]
        assert erstes["verbraucht"]
        assert len(erstes["platzierungen"]) == len(brett["platzierungen"])
        # Insgesamt weiterhin genau 4 Teile A eingeplant, keines doppelt
        assert sum(len(sp["platzierungen"]) for sp in neu["schnittplaene"]) == 4
        assert neu["fehlende_teile"] == []

    def test_neu_berechnen_schliesst_angefangene_stange_ab(self, client):
        mid, pid, bid = self._setup(client, typ="Stange", stock=[(3000, 0, 2)],
                                    teile=[("S", 900, 0, 3)])
        plan = self._optimize(client, mid, pid, bid)
        stange = next(sp for sp in plan["schnittplaene"] if len(sp["platzierungen"]) == 3)
        client.post(f"/api/plan-pieces/{stange['platzierungen'][0]['id']}",
                    json={"gesaegt": True})
        neu = self._optimize(client, mid, pid, bid)
        alt = neu["schnittplaene"][0]
        assert alt["verbraucht"] and len(alt["platzierungen"]) == 1
        # Die zwei restlichen Teile werden neu verteilt – auch auf das Reststück
        assert sum(len(sp["platzierungen"]) for sp in neu["schnittplaene"]) == 3

    def test_projekt_neu_starten(self, client):
        mid, pid, bid = self._setup(client)
        plan = self._optimize(client, mid, pid, bid)
        client.post(f"/api/plans/{plan['plan_id']}/confirm-all")
        lager = self._stock_total(client, mid)
        res = client.post(f"/api/projects/{pid}/restart").json()
        assert res["plaene"] == []
        assert all(t["gesaegt_anzahl"] == 0 for t in res["teile"])
        assert self._stock_total(client, mid) == lager
        assert client.get(f"/api/projects/{pid}/plans/{mid}").json() is None

    def test_projekt_und_material_loeschen_mit_plan(self, client):
        mid, pid, bid = self._setup(client)
        self._optimize(client, mid, pid, bid)
        assert client.delete(f"/api/projects/{pid}").status_code == 204
        mid2, pid2, bid2 = self._setup(client)
        self._optimize(client, mid2, pid2, bid2)
        assert client.delete(f"/api/materials/{mid2}").status_code == 204


# =====================================================================
# Update von einer DB ohne Plan-Tabellen: keine Daten verloren
# =====================================================================

class TestMigrationSchnittplaene:

    def test_alte_db_bleibt_erhalten_und_wird_gesichert(self, tmp_path):
        import sqlite3
        from core.db import Database
        path = tmp_path / "cutstock.db"
        db = Database(path)
        mid = db.conn.execute(
            "INSERT INTO material (name, typ) VALUES ('Alt', 'Platte')").lastrowid
        db.conn.execute("INSERT INTO projekt (name) VALUES ('P')")
        db.conn.execute(
            "INSERT INTO lagerstueck (material_id, laenge, breite, stueckzahl) VALUES (?,1,1,2)",
            (mid,))
        db.conn.commit()
        # Stand einer älteren Version simulieren: Plan-Tabellen gibt es noch nicht
        for t in ("schnittplan_stueck", "schnittplan_brett", "schnittplan"):
            db.conn.execute(f"DROP TABLE {t}")
        db.conn.execute("ALTER TABLE projekt DROP COLUMN anzahl")
        db.conn.commit()
        db.close()

        db = Database(path)
        tabellen = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"schnittplan", "schnittplan_brett", "schnittplan_stueck"} <= tabellen
        assert db.conn.execute("SELECT COUNT(*) FROM material").fetchone()[0] == 1
        assert [tuple(r) for r in db.conn.execute("SELECT name, anzahl FROM projekt")] == [("P", 1)]
        assert db.conn.execute("SELECT SUM(stueckzahl) FROM lagerstueck").fetchone()[0] == 2
        db.close()

        sicherungen = list(tmp_path.glob("cutstock-vor-update-*.db"))
        assert len(sicherungen) == 1
        sicherung = sicherungen[0]
        Database(path).close()        # aktuelles Schema → keine weitere Sicherung
        assert len(list(tmp_path.glob("cutstock-vor-update-*.db"))) == 1
        conn = sqlite3.connect(str(sicherung))
        assert conn.execute("SELECT name FROM material").fetchone()[0] == "Alt"
        conn.close()

    def test_versionswechsel_sichert_einmal(self, tmp_path):
        from core.db import Database
        path = tmp_path / "cutstock.db"
        db = Database(path, app_version="2026.10.1")
        db.conn.execute("INSERT INTO projekt (name) VALUES ('P')")
        db.conn.commit()
        db.close()
        Database(path, app_version="2026.10.1").close()   # gleiche Version
        assert list(tmp_path.glob("cutstock-vor-update-*.db")) == []

        Database(path, app_version="2026.10.2").close()   # Update
        assert len(list(tmp_path.glob("cutstock-vor-update-*.db"))) == 1
        Database(path, app_version="2026.10.2").close()   # zweiter Start
        assert len(list(tmp_path.glob("cutstock-vor-update-*.db"))) == 1

    def test_nur_letzte_sicherungen_bleiben(self, tmp_path):
        from core.db import Database
        path = tmp_path / "cutstock.db"
        db = Database(path, app_version="1")
        db.conn.execute("INSERT INTO projekt (name) VALUES ('P')")
        db.conn.commit()
        db.close()
        for i in range(7):
            (tmp_path / f"cutstock-vor-update-2020010{i}-000000.db").write_bytes(b"")
        Database(path, app_version="2").close()
        rest = sorted(p.name for p in tmp_path.glob("cutstock-vor-update-*.db"))
        assert len(rest) == Database.MAX_SICHERUNGEN
        assert "cutstock-vor-update-20200100-000000.db" not in rest
        assert not rest[-1].startswith("cutstock-vor-update-2020")   # neue bleibt



# =====================================================================
# Projekt mehrfach bauen (Anzahl Exemplare)
# =====================================================================

class TestProjektAnzahl:

    def _setup(self, client, anzahl=3):
        mid = client.post("/api/materials", json={"name": "Anz", "typ": "Stange"}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 3000, "stueckzahl": 10})
        pid = client.post("/api/projects", json={"name": "Hocker", "anzahl": anzahl}).json()["id"]
        tid = client.post(f"/api/projects/{pid}/parts", json={
            "label": "Bein", "typ": "Stange", "material_id": mid,
            "laenge": 450, "stueckzahl": 4}).json()["id"]
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        return mid, pid, tid, bid

    def _teil(self, client, pid):
        return client.get(f"/api/projects/{pid}").json()["teile"][0]

    def test_mengen_mal_anzahl(self, client):
        mid, pid, _, bid = self._setup(client, anzahl=3)
        teil = self._teil(client, pid)
        assert (teil["stueckzahl"], teil["gesamt_anzahl"], teil["offen_anzahl"]) == (4, 12, 12)
        plan = client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid}).json()
        assert sum(len(sp["platzierungen"]) for sp in plan["schnittplaene"]) == 12

    def test_fortschritt_ueber_alle_exemplare(self, client):
        mid, pid, _, bid = self._setup(client, anzahl=2)
        plan = client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid}).json()
        res = client.post(f"/api/plans/{plan['plan_id']}/confirm-all").json()
        assert all(p["gesaegt"] for sp in res["schnittplaene"] for p in sp["platzierungen"])
        teil = self._teil(client, pid)
        assert teil["gesaegt_anzahl"] == 8 and teil["status"] == "gesägt"

    def test_anzahl_aendern_macht_plan_veraltet(self, client):
        mid, pid, _, bid = self._setup(client, anzahl=2)
        client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid})
        client.put(f"/api/projects/{pid}", json={"name": "Hocker", "anzahl": 5})
        assert client.get(f"/api/projects/{pid}/plans/{mid}").json()["veraltet"]
        assert self._teil(client, pid)["offen_anzahl"] == 20

    def test_weniger_exemplare_kappt_fortschritt(self, client):
        mid, pid, tid, bid = self._setup(client, anzahl=3)
        teil = self._teil(client, pid)
        client.put(f"/api/parts/{tid}", json={**teil, "gesaegt_anzahl": 10})
        client.put(f"/api/projects/{pid}", json={"name": "Hocker", "anzahl": 2})
        teil = self._teil(client, pid)
        assert teil["gesaegt_anzahl"] == 8 and teil["status"] == "gesägt"

    def test_kopie_uebernimmt_anzahl(self, client):
        _, pid, _, _ = self._setup(client, anzahl=4)
        assert client.post(f"/api/projects/{pid}/clone").json()["anzahl"] == 4


# =====================================================================
# Stück-Codes je Material, Lagerorte, Reste beschriften
# =====================================================================

class TestStueckCodes:

    def _mat(self, client, name="Alu Profil 40x40 Nut 8", typ="Stange", **kw):
        r = client.post("/api/materials", json={"name": name, "typ": typ, **kw})
        assert r.status_code == 201, r.text
        return r.json()

    def _stock(self, client, mid, laenge, breite=0, n=1):
        return client.post("/api/stock", json={"material_id": mid, "laenge": laenge,
                                               "breite": breite, "stueckzahl": n}).json()["id"]

    def _codes(self, client, sid):
        return [p["code"] for p in client.get(f"/api/stock/{sid}/pieces").json()]

    def test_kuerzel_vorschlag_und_eindeutig(self, client):
        m = self._mat(client, kuerzel="")
        assert m["kuerzel"]
        dup = client.post("/api/materials", json={"name": "Anderes", "typ": "Stange",
                                                  "kuerzel": m["kuerzel"].lower()})
        assert dup.status_code == 409

    def test_nummern_je_material_ueber_alle_laengen(self, client):
        mid = self._mat(client, kuerzel="T40")["id"]
        a = self._stock(client, mid, 6000, n=2)
        b = self._stock(client, mid, 800, n=2)
        assert self._codes(client, a) == ["T40-01", "T40-02"]
        assert self._codes(client, b) == ["T40-03", "T40-04"]
        # anderes Material zählt eigenständig
        mid2 = self._mat(client, name="Zweites", kuerzel="Z2")["id"]
        assert self._codes(client, self._stock(client, mid2, 1000)) == ["Z2-01"]

    def test_lagerort_vom_material_und_eigener(self, client):
        mid = self._mat(client, kuerzel="LO", lagerort="Regal 2")["id"]
        sid = self._stock(client, mid, 3000, n=2)
        p1, p2 = client.get(f"/api/stock/{sid}/pieces").json()
        assert p1["lagerort_effektiv"] == "Regal 2"
        r = client.put(f"/api/pieces/{p2['id']}", json={"notiz": "", "lagerort": "Kiste"}).json()
        assert r["lagerort"] == "Kiste" and r["lagerort_effektiv"] == "Kiste"

    def test_plan_zeigt_code_und_rest_mit_freier_nummer(self, client):
        mat = self._mat(client, kuerzel="RS", lagerort="Wand", lagerort_reste="Restekiste",
                        rest_min_laenge=100)
        mid = mat["id"]
        sid = self._stock(client, mid, 3000, n=2)      # RS-01, RS-02
        pid = client.post("/api/projects", json={"name": "R"}).json()["id"]
        client.post(f"/api/projects/{pid}/parts", json={
            "label": "A", "typ": "Stange", "material_id": mid, "laenge": 1000, "stueckzahl": 1})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        plan = client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid}).json()
        brett = plan["schnittplaene"][0]
        assert brett["stueck_code"] in ("RS-01", "RS-02") and brett["lagerort"] == "Wand"
        res = client.post(f"/api/plan-pieces/{brett['platzierungen'][0]['id']}",
                          json={"gesaegt": True}).json()
        rest = res["plan"]["schnittplaene"][0]["reste_stuecke"]
        # verbrauchtes Stück gibt seine Nummer frei → der Rest bekommt sie
        assert [r["code"] for r in rest] == [brett["stueck_code"]]
        assert rest[0]["lagerort"] == "Restekiste" and rest[0]["laenge"] == 1997
        # Zurücknehmen: Rest weg, Original wieder mit alter Nummer
        client.post(f"/api/plan-pieces/{brett['platzierungen'][0]['id']}", json={"gesaegt": False})
        assert sorted(self._codes(client, sid)) == ["RS-01", "RS-02"]
        assert len(client.get(f"/api/stock?material_id={mid}").json()) == 1


class TestMigrationStueckNummern:

    def test_doppelte_nummern_werden_je_material_eindeutig(self, tmp_path):
        from core.db import Database
        from core.models import GespeicherterPlan, Lagerstueck, Material, MaterialTyp, PlanBrett
        db = Database(tmp_path / "cutstock.db")
        mid = db.save_material(Material(name="Alt 40x40", typ=MaterialTyp.STANGE)).id
        lang = db.save_lagerstueck(Lagerstueck(material_id=mid, laenge=6000, stueckzahl=2))
        kurz = db.save_lagerstueck(Lagerstueck(material_id=mid, laenge=500, stueckzahl=2))
        pid = db.conn.execute("INSERT INTO projekt (name) VALUES ('P')").lastrowid
        db.save_plan(GespeicherterPlan(projekt_id=pid, material_id=mid, bretter=[
            PlanBrett(lagerstueck_id=kurz.id, stueck_nr=3)]))
        # Zustand bis 2026.10.62: Nummern je Lagerzeile (1, 2 | 1, 2), kein Kürzel
        db.conn.execute("UPDATE einzelstueck SET nr = nr - 2 WHERE lagerstueck_id=?", (kurz.id,))
        db.conn.execute("UPDATE schnittplan_brett SET stueck_nr=1")
        db.conn.execute("UPDATE material SET kuerzel=''")
        db.conn.commit()
        db.close()

        db = Database(tmp_path / "cutstock.db")
        assert db.einzelstueck_nrs_for_lagerstueck(lang.id) == [1, 2]
        assert db.einzelstueck_nrs_for_lagerstueck(kurz.id) == [3, 4]
        assert db.get_material(mid).kuerzel == "A4040"
        # Plan zeigt weiter auf dasselbe physische Stück (früher #1 der kurzen Zeile)
        assert db.get_plan(pid, mid).bretter[0].stueck_nr == 3
        db.close()


class TestRestErbtCode:

    def test_stange_behaelt_code_ueber_mehrere_schnitte(self, client):
        mid = client.post("/api/materials", json={"name": "Erbe", "typ": "Stange",
                                                  "kuerzel": "ER", "rest_min_laenge": 50}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 900, "stueckzahl": 1})   # ER-01
        client.post("/api/stock", json={"material_id": mid, "laenge": 3000, "stueckzahl": 1})  # ER-02
        pid = client.post("/api/projects", json={"name": "E"}).json()["id"]
        client.post(f"/api/projects/{pid}/parts", json={
            "label": "A", "typ": "Stange", "material_id": mid, "laenge": 1000, "stueckzahl": 2})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        plan = client.post("/api/optimize", json={
            "project_id": pid, "material_id": mid, "blade_id": bid}).json()
        brett = next(sp for sp in plan["schnittplaene"] if len(sp["platzierungen"]) == 2)
        assert brett["stueck_code"] == "ER-02"
        codes = []
        for st in brett["platzierungen"]:
            res = client.post(f"/api/plan-pieces/{st['id']}", json={"gesaegt": True}).json()
            rest = next(sp for sp in res["plan"]["schnittplaene"] if sp["id"] == brett["id"])
            codes.append([(r["code"], r["laenge"]) for r in rest["reste_stuecke"]])
        assert codes == [[("ER-02", 1997)], [("ER-02", 994)]]


# =====================================================================
# Reservierung, Plan verwerfen, Reste zuerst
# =====================================================================

class TestReservierungUndResteZuerst:

    def _setup(self, client, lager, kuerzel):
        mid = client.post("/api/materials", json={"name": f"Res {kuerzel}", "typ": "Stange",
                                                  "kuerzel": kuerzel, "rest_min_laenge": 50}).json()["id"]
        sids = [client.post("/api/stock", json={"material_id": mid, "laenge": l,
                                                "stueckzahl": n, "ist_rest": rest}).json()["id"]
                for l, n, rest in lager]
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        return mid, sids, bid

    def _projekt(self, client, mid, name, laenge, n):
        pid = client.post("/api/projects", json={"name": name}).json()["id"]
        client.post(f"/api/projects/{pid}/parts", json={
            "label": "A", "typ": "Stange", "material_id": mid, "laenge": laenge, "stueckzahl": n})
        return pid

    def _opt(self, client, pid, mid, bid, **kw):
        r = client.post("/api/optimize", json={"project_id": pid, "material_id": mid,
                                               "blade_id": bid, **kw})
        assert r.status_code == 200, r.text
        return r.json()

    def test_andere_projekte_nutzen_reservierte_stuecke_nicht(self, client):
        mid, sids, bid = self._setup(client, [(3000, 2, False)], "RV")
        p1 = self._projekt(client, mid, "Eins", 2500, 1)
        p2 = self._projekt(client, mid, "Zwei", 2500, 2)
        plan1 = self._opt(client, p1, mid, bid)
        code1 = plan1["schnittplaene"][0]["stueck_code"]
        plan2 = self._opt(client, p2, mid, bid)
        assert [sp["stueck_code"] for sp in plan2["schnittplaene"]] != [code1]
        assert code1 not in [sp["stueck_code"] for sp in plan2["schnittplaene"]]
        assert len(plan2["fehlende_teile"]) == 1
        pieces = client.get(f"/api/stock/{sids[0]}/pieces").json()
        assert {p["code"]: p["reserviert_fuer"] for p in pieces}[code1] == "Eins"
        # Plan verwerfen gibt das Stück frei
        assert client.delete(f"/api/plans/{plan1['plan_id']}").status_code == 204
        plan2 = self._opt(client, p2, mid, bid)
        assert plan2["fehlende_teile"] == []

    def test_reservierung_abschaltbar(self, client):
        client.put("/api/settings", json={"reservation": False})
        mid, _, bid = self._setup(client, [(3000, 1, False)], "RA")
        p1 = self._projekt(client, mid, "Eins", 2500, 1)
        p2 = self._projekt(client, mid, "Zwei", 2500, 1)
        self._opt(client, p1, mid, bid)
        assert self._opt(client, p2, mid, bid)["fehlende_teile"] == []

    def test_reste_zuerst(self, client):
        # Ganze 3000er und zwei 1000er-Reste; Teile 900 mm passen in beide
        mid, sids, bid = self._setup(client, [(3000, 2, False), (1000, 2, True)], "RZ")
        pid = self._projekt(client, mid, "Reste", 900, 3)
        normal = self._opt(client, pid, mid, bid)
        zuerst = self._opt(client, pid, mid, bid, reste_zuerst=True)
        laengen = sorted(sp["lager_laenge"] for sp in zuerst["schnittplaene"])
        assert laengen[:2] == [1000, 1000]           # beide Reste werden verbraucht
        assert sum(len(sp["platzierungen"]) for sp in zuerst["schnittplaene"]) == 3
        assert zuerst["fehlende_teile"] == [] and normal["fehlende_teile"] == []
        # ohne Option passt alles material-sparend auf eine 3000er-Stange
        assert [sp["lager_laenge"] for sp in normal["schnittplaene"]] == [3000]

    def test_eingebuchter_rest_ist_markiert(self, client):
        mid, sids, bid = self._setup(client, [(3000, 1, False)], "RM")
        pid = self._projekt(client, mid, "M", 1000, 1)
        plan = self._opt(client, pid, mid, bid)
        client.post(f"/api/plan-pieces/{plan['schnittplaene'][0]['platzierungen'][0]['id']}",
                    json={"gesaegt": True})
        stock = client.get(f"/api/stock?material_id={mid}").json()
        assert [(s["laenge"], s["ist_rest"]) for s in stock] == [(1997, True)]


# =====================================================================
# Füllteile aus anderen Projekten + Teile-Vorrat
# =====================================================================

class TestFuellteile:

    def _setup(self, client, rest_min=0):
        mid = client.post("/api/materials", json={"name": "Schiene", "typ": "Stange",
                                                  "rest_min_laenge": rest_min}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 2000, "stueckzahl": 10})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        haupt = client.post("/api/projects", json={"name": "Haupt"}).json()["id"]
        # 7 × 253 + 6 Fugen = 1789 → 211 mm Rest je Stange; 4 Stangen
        client.post(f"/api/projects/{haupt}/parts", json={
            "label": "S253", "typ": "Stange", "material_id": mid, "laenge": 253, "stueckzahl": 28})
        anderes = client.post("/api/projects", json={"name": "Anderes"}).json()["id"]
        fid = client.post(f"/api/projects/{anderes}/parts", json={
            "label": "K200", "typ": "Stange", "material_id": mid, "laenge": 200, "stueckzahl": 2}).json()["id"]
        return mid, bid, haupt, anderes, fid

    def _opt(self, client, pid, mid, bid, **kw):
        r = client.post("/api/optimize", json={"project_id": pid, "material_id": mid,
                                               "blade_id": bid, **kw})
        assert r.status_code == 200, r.text
        return r.json()

    def _fuell(self, plan):
        return [p for sp in plan["schnittplaene"] for p in sp["platzierungen"] if p["ist_fuellteil"]]

    def test_kandidaten_aus_anderen_projekten(self, client):
        mid, _, haupt, _, fid = self._setup(client)
        k = client.get(f"/api/projects/{haupt}/fill-candidates/{mid}").json()
        assert [(x["teil_id"], x["projekt"]) for x in k] == [(fid, "Anderes")]

    def test_auffuellen_braucht_kein_zusaetzliches_material(self, client):
        mid, bid, haupt, _, fid = self._setup(client)
        ohne = self._opt(client, haupt, mid, bid)
        mit = self._opt(client, haupt, mid, bid,
                        fuellteile=[{"teil_id": fid, "modus": "auffuellen", "menge": 0}])
        assert len(mit["schnittplaene"]) == len(ohne["schnittplaene"])
        fuell = self._fuell(mit)
        assert len(fuell) == len(mit["schnittplaene"])          # je Stange ein 200er
        assert fuell[0]["teil_label"] == "K200 → Anderes"
        # Obergrenze wird eingehalten, Auswahl bleibt beim Neuberechnen erhalten
        mit = self._opt(client, haupt, mid, bid,
                        fuellteile=[{"teil_id": fid, "modus": "auffuellen", "menge": 2}])
        assert len(self._fuell(mit)) == 2
        assert len(self._fuell(self._opt(client, haupt, mid, bid))) == 2
        assert mit["fuellteile"][0]["teil_id"] == fid

    def test_nur_abfall_laesst_verwertbare_reste_in_ruhe(self, client):
        mid, bid, haupt, _, fid = self._setup(client, rest_min=200)   # 211 mm Rest = verwertbar
        f = [{"teil_id": fid, "modus": "auffuellen", "menge": 0}]
        assert self._fuell(self._opt(client, haupt, mid, bid, fuellteile=f)) == []
        assert self._fuell(self._opt(client, haupt, mid, bid, fuellteile=f,
                                     fuell_alle_reste=True))

    def test_gesaegtes_fuellteil_geht_in_vorrat_und_wird_uebernommen(self, client):
        mid, bid, haupt, anderes, fid = self._setup(client)
        plan = self._opt(client, haupt, mid, bid,
                         fuellteile=[{"teil_id": fid, "modus": "auffuellen", "menge": 1}])
        st = self._fuell(plan)[0]
        res = client.post(f"/api/plan-pieces/{st['id']}", json={"gesaegt": True}).json()
        assert res["teil"]["vorrat"] == 1 and res["teil"]["gesaegt_anzahl"] == 0
        haupt_teil = client.get(f"/api/projects/{haupt}").json()["teile"][0]
        assert haupt_teil["gesaegt_anzahl"] == 0                  # Hauptprojekt unberührt
        # Das andere Projekt sieht den Vorrat im Plan und übernimmt ihn
        plan_b = self._opt(client, anderes, mid, bid)
        assert plan_b["vorrat_verfuegbar"] == [{"teil_id": fid, "label": "K200", "anzahl": 1}]
        teil = client.post(f"/api/projects/{anderes}/take-stock/{mid}").json()["teile"][0]
        assert (teil["gesaegt_anzahl"], teil["vorrat"]) == (1, 0)

    def test_feste_menge(self, client):
        mid, bid, haupt, _, fid = self._setup(client)
        plan = self._opt(client, haupt, mid, bid,
                         fuellteile=[{"teil_id": fid, "modus": "fest", "menge": 5}])
        assert len(self._fuell(plan)) == 5
        assert plan["fehlende_teile"] == []


# =====================================================================
# Sammelplan: ein Material, mehrere Projekte gemeinsam
# =====================================================================

class TestSammelplan:

    def _setup(self, client):
        """Beispiel aus dem Design: A 4×695, B 4×600 auf 2000er Stangen, Fuge 3."""
        mid = client.post("/api/materials", json={"name": "Alu 40x40", "typ": "Stange"}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 2000, "stueckzahl": 10})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        ids = {}
        for name, laenge in (("A", 695), ("B", 600)):
            pid = client.post("/api/projects", json={"name": name}).json()["id"]
            client.post(f"/api/projects/{pid}/parts", json={
                "label": "Seite", "typ": "Stange", "material_id": mid,
                "laenge": laenge, "stueckzahl": 4})
            ids[name] = pid
        return mid, bid, ids["A"], ids["B"]

    def _req(self, mid, bid, pids, **kw):
        return {"material_id": mid, "blade_id": bid, "projekt_ids": pids,
                "algorithm": "greedy", **kw}

    def _sammel(self, client, mid, bid, pids):
        r = client.post("/api/sammel/optimize", json=self._req(mid, bid, pids))
        assert r.status_code == 200, r.text
        return r.json()

    def _stuecke(self, plan):
        return [p for sp in plan["schnittplaene"] for p in sp["platzierungen"]]

    def test_gemeinsam_spart_eine_stange(self, client):
        mid, bid, a, b = self._setup(client)
        v = client.post("/api/sammel/compare", json=self._req(mid, bid, [a, b])).json()
        assert (v["getrennt_bretter"], v["gemeinsam_bretter"]) == (4, 3)
        plan = self._sammel(client, mid, bid, [a, b])
        assert len(plan["schnittplaene"]) == 3
        labels = sorted(p["teil_label"] for p in self._stuecke(plan))
        assert labels == ["Seite → A"] * 4 + ["Seite → B"] * 4   # gleiche Labels getrennt

    def test_vergleich_getrennt_teilt_sich_das_lager(self, client):
        """Getrennt darf nicht jedes Projekt denselben Rest verplanen."""
        mid = client.post("/api/materials", json={"name": "Alu", "typ": "Stange"}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 2000, "stueckzahl": 5})
        client.post("/api/stock", json={"material_id": mid, "laenge": 1400, "ist_rest": True})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        pids = []
        for name in ("A", "B"):
            pid = client.post("/api/projects", json={"name": name}).json()["id"]
            client.post(f"/api/projects/{pid}/parts", json={
                "label": "Seite", "typ": "Stange", "material_id": mid,
                "laenge": 695, "stueckzahl": 2})
            pids.append(pid)
        v = client.post("/api/sammel/compare",
                        json=self._req(mid, bid, pids, reste_zuerst=True)).json()
        # A nimmt den Rest (1400), B muss eine ganze Stange anbrechen
        assert (v["getrennt_bretter"], v["getrennt_menge"]) == (2, 3400)
        assert v["getrennt_reste"] == 1

    def test_sammel_projekt_unsichtbar_mitglieder_kennen_es(self, client):
        mid, bid, a, _ = self._setup(client)
        self._sammel(client, mid, bid, [a])
        namen = [p["name"] for p in client.get("/api/projects").json()]
        assert "Sammelplan Alu 40x40" not in namen
        assert client.get(f"/api/projects/{a}").json()["sammel"] == {str(mid): "Sammelplan Alu 40x40"}
        s = client.get(f"/api/sammel/{mid}").json()
        assert s["sammel_id"] and [k["mitglied"] for k in s["kandidaten"]] == [True, False]

    def test_abhaken_bucht_ins_eigene_projekt(self, client):
        mid, bid, a, b = self._setup(client)
        plan = self._sammel(client, mid, bid, [a, b])
        st = next(p for p in self._stuecke(plan) if p["teil_label"] == "Seite → B")
        teil = client.post(f"/api/plan-pieces/{st['id']}", json={"gesaegt": True}).json()["teil"]
        assert (teil["projekt_id"], teil["gesaegt_anzahl"], teil["vorrat"]) == (b, 1, 0)

    def test_offener_einzelplan_wird_ersetzt(self, client):
        mid, bid, a, b = self._setup(client)
        client.post("/api/optimize", json={"project_id": a, "material_id": mid, "blade_id": bid})
        assert client.get(f"/api/projects/{a}/plans/{mid}").json()
        plan = self._sammel(client, mid, bid, [a, b])
        assert len(self._stuecke(plan)) == 8
        assert client.get(f"/api/projects/{a}/plans/{mid}").json() is None

    def test_angefangener_einzelplan_sperrt_nur_seine_teile(self, client):
        mid, bid, a, b = self._setup(client)
        # A hat 2 Exemplare = 8 Teile; der Einzelplan von A deckt nur 4 davon ab
        client.put(f"/api/projects/{a}", json={"name": "A", "anzahl": 1})
        einzel = client.post("/api/optimize", json={
            "project_id": a, "material_id": mid, "blade_id": bid}).json()
        client.post(f"/api/plan-pieces/{self._stuecke(einzel)[0]['id']}", json={"gesaegt": True})
        client.put(f"/api/projects/{a}", json={"name": "A", "anzahl": 2})
        k = {x["projekt_id"]: x for x in client.get(f"/api/sammel/{mid}").json()["kandidaten"]}
        assert (k[a]["einzelplan"], k[a]["gesperrt"], k[a]["offen"]) == ("angefangen", 3, 4)
        plan = self._sammel(client, mid, bid, [a, b])
        n_a = sum(p["teil_label"] == "Seite → A" for p in self._stuecke(plan))
        assert n_a == 4                                       # nur das zweite Exemplar
        assert client.get(f"/api/projects/{a}/plans/{mid}").json()   # Einzelplan bleibt

    def test_einzelplan_nach_sammelplan_nicht_doppelt(self, client):
        mid, bid, a, b = self._setup(client)
        self._sammel(client, mid, bid, [a, b])
        r = client.post("/api/optimize", json={"project_id": a, "material_id": mid, "blade_id": bid})
        assert r.status_code == 409 and "Sammelplan" in r.json()["detail"]

    def test_verwerfen_loescht_sammelplan(self, client):
        mid, bid, a, b = self._setup(client)
        plan = self._sammel(client, mid, bid, [a, b])
        assert client.delete(f"/api/plans/{plan['plan_id']}").status_code == 204
        assert client.get(f"/api/sammel/{mid}").json()["sammel_id"] == 0
        assert client.get(f"/api/projects/{a}").json()["sammel"] == {}

    def test_feste_fuellteile_sperren_sie_im_eigenen_plan(self, client):
        mid, bid, a, b = self._setup(client)
        fid = client.get(f"/api/projects/{b}").json()["teile"][0]["id"]
        client.post("/api/optimize", json={
            "project_id": a, "material_id": mid, "blade_id": bid,
            "fuellteile": [{"teil_id": fid, "modus": "fest", "menge": 3}]})
        plan_b = client.post("/api/optimize", json={
            "project_id": b, "material_id": mid, "blade_id": bid}).json()
        assert len(self._stuecke(plan_b)) == 1                  # 3 liegen schon bei A
