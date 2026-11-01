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

    def test_lagerort_kommt_vom_material(self, client):
        mid = self._mat(client, kuerzel="LO", lagerort="Regal 2")["id"]
        sid = self._stock(client, mid, 3000, n=2)
        p1, p2 = client.get(f"/api/stock/{sid}/pieces").json()
        assert p1["lagerort"] == p1["lagerort_effektiv"] == "Regal 2"
        # Ein eigener Ort am Stück wird nicht mehr übernommen
        r = client.put(f"/api/pieces/{p2['id']}", json={"notiz": "x", "lagerort": "Kiste"}).json()
        assert r["lagerort"] == "Regal 2" and r["notiz"] == "x"

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

    def test_gesaegtes_fuellteil_zaehlt_erst_beim_projekt_dann_fertigteile(self, client):
        mid, bid, haupt, anderes, fid = self._setup(client)
        plan = self._opt(client, haupt, mid, bid,
                         fuellteile=[{"teil_id": fid, "modus": "auffuellen", "menge": 3}])
        st = self._fuell(plan)
        assert len(st) == 3                                       # 2 offen + 1 Überschuss
        stand = []
        for s in st:
            t = client.post(f"/api/plan-pieces/{s['id']}", json={"gesaegt": True}).json()["teil"]
            stand.append((t["gesaegt_anzahl"], t["vorrat"]))
        assert stand == [(1, 0), (2, 0), (2, 1)]
        haupt_teil = client.get(f"/api/projects/{haupt}").json()["teile"][0]
        assert haupt_teil["gesaegt_anzahl"] == 0                  # Hauptprojekt unberührt
        # Zurücknehmen bucht genau das zurück, was beim Sägen passiert ist
        t = client.post(f"/api/plan-pieces/{st[0]['id']}", json={"gesaegt": False}).json()["teil"]
        assert (t["gesaegt_anzahl"], t["vorrat"]) == (1, 1)
        t = client.post(f"/api/plan-pieces/{st[2]['id']}", json={"gesaegt": False}).json()["teil"]
        assert (t["gesaegt_anzahl"], t["vorrat"]) == (1, 0)

    def test_fertigteile_uebernehmen(self, client):
        mid, bid, haupt, anderes, fid = self._setup(client)
        r = client.put(f"/api/parts/{fid}", json={"label": "K200", "typ": "Stange",
                                                  "material_id": mid, "laenge": 200,
                                                  "stueckzahl": 2, "vorrat": 1})
        assert r.status_code == 200, r.text
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

    def _zweites_fuellteil(self, client, mid):
        pid = client.post("/api/projects", json={"name": "Drittes"}).json()["id"]
        return client.post(f"/api/projects/{pid}/parts", json={
            "label": "K100", "typ": "Stange", "material_id": mid, "laenge": 100,
            "stueckzahl": 1}).json()["id"]

    def test_max_teile_je_stange(self, client):
        mid, bid, haupt, _, fid = self._setup(client)
        plan = self._opt(client, haupt, mid, bid, max_pro_stange=4)
        assert len(plan["schnittplaene"]) == 7                    # 28 Teile / 4
        assert {len(sp["platzierungen"]) for sp in plan["schnittplaene"]} == {4}
        assert plan["max_pro_stange"] == 4
        # bleibt beim Neuberechnen erhalten, auch mit dem genetischen Algorithmus
        plan = self._opt(client, haupt, mid, bid, algorithm="ga")
        assert len(plan["schnittplaene"]) == 7
        plan = self._opt(client, haupt, mid, bid, max_pro_stange=0)
        assert len(plan["schnittplaene"]) == 4

    def test_vorschlaege_und_wahl(self, client):
        mid, bid, haupt, _, fid = self._setup(client)
        f100 = self._zweites_fuellteil(client, mid)
        # 208 mm frei hinter der Fuge: K200 allein ist am besten, K100 nur als Alternative
        plan = self._opt(client, haupt, mid, bid, fuellteile=[
            {"teil_id": fid, "modus": "auffuellen", "menge": 0},
            {"teil_id": f100, "modus": "auffuellen", "menge": 0}])
        [g] = plan["fuell_vorschlaege"]
        assert (g["gruppe"], g["stangen"], g["gewaehlt"], g["manuell"]) == ("208.0", 4, 0, False)
        assert [[(t["teil_id"], t["anzahl"]) for t in v["teile"]] for v in g["vorschlaege"]] == [
            [(fid, 1)], [(f100, 2)]]
        assert g["vorschlaege"][0]["rest"] == 5
        # K100 wählen: Hauptteile bleiben, alle vier Stangen bekommen 2 × K100
        alt = [[p["laenge"] for p in sp["platzierungen"] if not p["ist_fuellteil"]]
               for sp in plan["schnittplaene"]]
        plan = client.post(f"/api/plans/{plan['plan_id']}/fill-choice", json={
            "gruppe": "208.0", "wahl": [{"teil_id": f100, "anzahl": 2}]}).json()
        assert [[p["laenge"] for p in sp["platzierungen"] if not p["ist_fuellteil"]]
                for sp in plan["schnittplaene"]] == alt
        assert [p["teil_label"] for p in self._fuell(plan)] == ["K100 → Drittes"] * 8
        g = plan["fuell_vorschlaege"][0]
        assert (g["gewaehlt"], g["manuell"], g["automatisch"]) == (1, True, 0)
        # Wahl bleibt beim Neuberechnen, "nichts" und zurück zur Automatik
        plan = self._opt(client, haupt, mid, bid)
        assert len(self._fuell(plan)) == 8
        plan = client.post(f"/api/plans/{plan['plan_id']}/fill-choice",
                           json={"gruppe": "208.0", "wahl": []}).json()
        assert self._fuell(plan) == [] and plan["fuell_vorschlaege"][0]["gewaehlt"] == -1
        plan = client.post(f"/api/plans/{plan['plan_id']}/fill-choice",
                           json={"gruppe": "208.0", "wahl": None}).json()
        assert [p["teil_label"] for p in self._fuell(plan)] == ["K200 → Anderes"] * 4

    def test_wahl_mit_menge_faellt_auf_automatik_zurueck(self, client):
        mid, bid, haupt, _, fid = self._setup(client)
        f100 = self._zweites_fuellteil(client, mid)
        plan = self._opt(client, haupt, mid, bid, fuellteile=[
            {"teil_id": fid, "modus": "auffuellen", "menge": 0},
            {"teil_id": f100, "modus": "auffuellen", "menge": 3}])
        plan = client.post(f"/api/plans/{plan['plan_id']}/fill-choice", json={
            "gruppe": "208.0", "wahl": [{"teil_id": f100, "anzahl": 2}]}).json()
        # nur 3 × K100: eine Stange mit 2, eine mit dem bevorzugten Rest-K100, dann K200
        labels = [[p["teil_label"].split(" ")[0] for p in sp["platzierungen"] if p["ist_fuellteil"]]
                  for sp in plan["schnittplaene"]]
        assert labels == [["K100", "K100"], ["K200"], ["K200"], ["K200"]]
        assert plan["fuell_vorschlaege"][0]["automatisch"] == 3


# =====================================================================
# Sammelplan: ein Material, mehrere Projekte gemeinsam
# =====================================================================

class TestFuellteile2D:

    def test_platten_auffuellen_nur_abfall(self, client):
        mid = client.post("/api/materials", json={
            "name": "MDF", "typ": "Platte", "rest_min_laenge": 300,
            "rest_min_breite": 300}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 1000, "breite": 500,
                                        "stueckzahl": 5})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        haupt = client.post("/api/projects", json={"name": "Haupt"}).json()["id"]
        # 800 × 500: rechts bleibt ein 197 mm breiter Streifen = Abfall
        client.post(f"/api/projects/{haupt}/parts", json={
            "label": "Boden", "typ": "Platte", "material_id": mid,
            "laenge": 800, "breite": 500, "stueckzahl": 1})
        anderes = client.post("/api/projects", json={"name": "Anderes"}).json()["id"]
        fid = client.post(f"/api/projects/{anderes}/parts", json={
            "label": "Leiste", "typ": "Platte", "material_id": mid,
            "laenge": 150, "breite": 100, "stueckzahl": 1}).json()["id"]
        plan = client.post("/api/optimize", json={
            "project_id": haupt, "material_id": mid, "blade_id": bid,
            "fuellteile": [{"teil_id": fid, "modus": "auffuellen", "menge": 0}]}).json()
        assert len(plan["schnittplaene"]) == 1
        fuell = [p for p in plan["schnittplaene"][0]["platzierungen"] if p["ist_fuellteil"]]
        assert len(fuell) == 4                                   # 4 × 100 in 197 × 500
        assert all(p["x"] >= 803 for p in fuell)
        assert fuell[0]["teil_label"] == "Leiste → Anderes"


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


class TestSammelplanImReiterProjekte:
    """Sammelpläne als eigene Einträge: Liste, Anlegen, Mitglieder, Umbenennen, Löschen."""

    _setup = TestSammelplan._setup
    _req = TestSammelplan._req
    _sammel = TestSammelplan._sammel

    def test_liste_nur_mit_art(self, client):
        mid, bid, a, _ = self._setup(client)
        self._sammel(client, mid, bid, [a])
        assert all(p["art"] != "sammel" for p in client.get("/api/projects").json())
        sammel = client.get("/api/projects?art=sammel").json()
        s = next(p for p in sammel if p["sammel_material_id"] == mid)
        assert (s["art"], s["mitglieder"], s["teile"]) == ("sammel", [a], [])
        alle = client.get("/api/projects?art=alle").json()
        assert {p["art"] for p in alle} >= {"", "sammel"} and alle[-1]["art"] == "sammel"
        assert client.get("/api/projects?art=quatsch").status_code == 400

    def test_anlegen_mit_kuerzel_und_namen(self, client):
        mid, bid, a, b = self._setup(client)
        kuerzel = next(m["kuerzel"] for m in client.get("/api/materials").json()
                       if m["id"] == mid)
        name_b = client.put(f"/api/projects/{b}", json={"name": "Sammel-B-Name"}).json()["name"]
        r = client.post("/api/sammel", json={"material": kuerzel.lower(), "projekte": [str(a), name_b]})
        assert r.status_code == 201, r.text
        s = r.json()
        assert (s["name"], s["mitglieder"], s["plaene"]) == ("Sammelplan Alu 40x40", [a, b], [])
        assert client.get(f"/api/projects/{a}").json()["sammel"] == {str(mid): s["name"]}
        # Je Material nur einer – der bestehende wird genannt
        r = client.post("/api/sammel", json={"material": str(mid), "projekte": [str(a)]})
        assert r.status_code == 409 and r.json()["detail"]["sammel_id"] == s["id"]
        # Danach rechnet die Optimierung mit diesen Mitgliedern
        plan = self._sammel(client, mid, bid, [a, b])
        assert plan["projekt_id"] == s["id"]

    def test_anlegen_fehler(self, client):
        mid, _, a, _ = self._setup(client)
        assert client.post("/api/sammel", json={"material": "XX-unbekannt", "projekte": [str(a)]}
                           ).json()["detail"]["code"] == "material_unbekannt"
        r = client.post("/api/sammel", json={"material": str(mid), "projekte": ["gibt es nicht"]})
        assert r.status_code == 404 and r.json()["detail"]["code"] == "projekt_unbekannt"
        assert client.post("/api/sammel", json={"material": str(mid), "projekte": []}
                           ).status_code == 422

    def test_mitglieder_aendern_macht_plan_veraltet(self, client):
        mid, bid, a, b = self._setup(client)
        plan = self._sammel(client, mid, bid, [a, b])
        r = client.put(f"/api/sammel/{mid}/members", json={"projekte": [str(a)]})
        assert r.status_code == 200 and r.json()["mitglieder"] == [a]
        assert client.get(f"/api/projects/{b}").json()["sammel"] == {}
        neu = client.get(f"/api/projects/{plan['projekt_id']}/plans/{mid}").json()
        assert neu["veraltet"]
        andere = client.post("/api/materials", json={"name": "Ohne", "typ": "Stange"}).json()["id"]
        r = client.put(f"/api/sammel/{andere}/members", json={"projekte": [str(a)]})
        assert r.status_code == 404 and r.json()["detail"]["code"] == "sammel_unbekannt"
        # Ein Sammelplan ist selbst kein Mitglied
        r = client.put(f"/api/sammel/{mid}/members", json={"projekte": [str(plan["projekt_id"])]})
        assert r.json()["detail"]["code"] == "projekt_unbekannt"

    def test_umbenennen_und_keine_eigenen_teile(self, client):
        mid, bid, a, _ = self._setup(client)
        sid = self._sammel(client, mid, bid, [a])["projekt_id"]
        r = client.put(f"/api/projects/{sid}", json={"name": "Alu-Runde", "anzahl": 5})
        assert (r.json()["name"], r.json()["anzahl"]) == ("Alu-Runde", 1)
        assert client.get(f"/api/projects/{a}").json()["sammel"] == {str(mid): "Alu-Runde"}
        teil = {"label": "X", "typ": "Stange", "material_id": mid, "laenge": 100, "stueckzahl": 1}
        assert client.post(f"/api/projects/{sid}/parts", json=teil
                           ).json()["detail"]["code"] == "sammel_ohne_teile"
        assert client.post(f"/api/projects/{sid}/clone").status_code == 400
        assert client.post(f"/api/projects/{sid}/copy-parts",
                           json={"part_ids": [1]}).status_code == 400

    def test_loeschen_uebernimmt_gesaegtes(self, client):
        mid, bid, a, b = self._setup(client)
        plan = self._sammel(client, mid, bid, [a, b])
        sid = plan["projekt_id"]
        # Erste Stange ganz sägen: Teile beider Projekte gesägt, Stange verbraucht
        for st in plan["schnittplaene"][0]["platzierungen"]:
            client.post(f"/api/plan-pieces/{st['id']}", json={"gesaegt": True})
        vorher = {pid: client.get(f"/api/projects/{pid}").json()["teile"][0]["gesaegt_anzahl"]
                  for pid in (a, b)}
        assert sum(vorher.values()) == len(plan["schnittplaene"][0]["platzierungen"])
        assert client.delete(f"/api/projects/{sid}").status_code == 204
        assert client.get(f"/api/projects/{sid}").status_code == 404
        assert client.get(f"/api/sammel/{mid}").json()["sammel_id"] == 0
        for pid in (a, b):
            p = client.get(f"/api/projects/{pid}").json()
            assert p["sammel"] == {} and p["teile"][0]["gesaegt_anzahl"] == vorher[pid]
        # Der Rest ist wieder offen: das Projekt lässt sich einzeln optimieren
        r = client.post("/api/optimize", json={"project_id": a, "material_id": mid, "blade_id": bid})
        assert r.status_code == 200, r.text
        n = sum(len(sp["platzierungen"]) for sp in r.json()["schnittplaene"])
        assert n == 4 - vorher[a]
        # Reservierte, ungesägte Stangen des Sammelplans sind wieder frei
        frei = client.get("/api/stock", params={"material_id": mid}).json()
        assert sum(s["stueckzahl"] for s in frei if s["laenge"] == 2000) == 9


class TestRegalKorrektur:
    """Teil-Dialog: Regal-Bestand von Hand setzen (Inventur)."""

    def test_vorrat_setzen_und_behalten(self, client):
        mid = client.post("/api/materials", json={"name": "Kiefer", "typ": "Stange"}).json()["id"]
        pid = client.post("/api/projects", json={"name": "Regal"}).json()["id"]
        teil = client.post(f"/api/projects/{pid}/parts", json={
            "label": "Latte", "typ": "Stange", "material_id": mid,
            "laenge": 500, "stueckzahl": 6}).json()
        felder = {k: teil[k] for k in ("label", "typ", "material_id", "laenge",
                                       "breite", "stueckzahl", "gesaegt_anzahl", "maserung")}
        r = client.put(f"/api/parts/{teil['id']}", json={**felder, "vorrat": 3})
        assert r.status_code == 200 and r.json()["vorrat"] == 3
        # Ohne Feld bleibt der Bestand unverändert
        r = client.put(f"/api/parts/{teil['id']}", json={**felder, "label": "Latte 2"})
        assert r.json()["vorrat"] == 3 and r.json()["label"] == "Latte 2"
        r = client.put(f"/api/parts/{teil['id']}", json={**felder, "vorrat": 0})
        assert r.json()["vorrat"] == 0
        assert client.put(f"/api/parts/{teil['id']}",
                          json={**felder, "vorrat": -1}).status_code == 422


class TestSchnittliste:
    """Reiter „Teile“: Schnittliste aus einzelnen Teilen, gesägt → Regal."""

    def _setup(self, client):
        mid = client.post("/api/materials", json={"name": "Alu", "typ": "Stange"}).json()["id"]
        client.post("/api/stock", json={"material_id": mid, "laenge": 2000, "stueckzahl": 10})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        teile = {}
        for name, laenge in (("A", 695), ("B", 600)):
            pid = client.post("/api/projects", json={"name": name}).json()["id"]
            teile[name] = client.post(f"/api/projects/{pid}/parts", json={
                "label": "Schiene", "typ": "Stange", "material_id": mid,
                "laenge": laenge, "stueckzahl": 4}).json()
        return mid, bid, teile

    def _liste(self, client, eintraege, name="Liste 1"):
        r = client.post("/api/cut-lists", json={"name": name, "eintraege": eintraege})
        assert r.status_code == 201, r.text
        return r.json()

    def test_alle_teile_ohne_listen(self, client):
        _, _, teile = self._setup(client)
        self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 2}])
        ids = {t["id"] for t in teile.values()}
        alle = client.get("/api/parts").json()
        assert ids <= {x["teil_id"] for x in alle}
        assert not any(x["projekt"] == "Liste 1" for x in alle)   # Liste selbst fehlt

    def test_liste_kopiert_teile_mit_herkunft(self, client):
        _, _, teile = self._setup(client)
        liste = self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 2},
                                     {"teil_id": teile["B"]["id"], "menge": 3}])
        assert liste["art"] == "liste"
        kopien = sorted((t["label"], t["stueckzahl"], t["herkunft_teil_id"])
                        for t in liste["teile"])
        assert kopien == [("Schiene (A)", 2, teile["A"]["id"]),
                          ("Schiene (B)", 3, teile["B"]["id"])]
        assert any(p["art"] == "liste" for p in client.get("/api/projects").json())

    def test_unbekanntes_teil(self, client):
        r = client.post("/api/cut-lists", json={"name": "X",
                                                "eintraege": [{"teil_id": 999, "menge": 1}]})
        assert r.status_code == 404

    def test_gesaegt_zaehlt_beim_herkunftsprojekt(self, client):
        mid, bid, teile = self._setup(client)
        liste = self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 2}])
        plan = client.post("/api/optimize", json={
            "project_id": liste["id"], "material_id": mid, "blade_id": bid}).json()
        stueck = plan["schnittplaene"][0]["platzierungen"][0]
        client.post(f"/api/plan-pieces/{stueck['id']}", json={"gesaegt": True})
        a = client.get(f"/api/projects/{teile['A']['projekt_id']}").json()["teile"][0]
        kopie = client.get(f"/api/projects/{liste['id']}").json()["teile"][0]
        assert (a["vorrat"], a["gesaegt_anzahl"]) == (0, 1)   # direkt beim Projekt
        assert kopie["gesaegt_anzahl"] == 1
        client.post(f"/api/plan-pieces/{stueck['id']}", json={"gesaegt": False})
        a = client.get(f"/api/projects/{teile['A']['projekt_id']}").json()["teile"][0]
        assert (a["vorrat"], a["gesaegt_anzahl"]) == (0, 0)

    def test_ueberschuss_geht_zu_den_fertigteilen(self, client):
        mid, bid, teile = self._setup(client)
        liste = self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 6}])  # 4 offen
        plan = client.post("/api/optimize", json={
            "project_id": liste["id"], "material_id": mid, "blade_id": bid}).json()
        client.post(f"/api/plans/{plan['plan_id']}/confirm-all")
        a = client.get(f"/api/projects/{teile['A']['projekt_id']}").json()["teile"][0]
        assert (a["gesaegt_anzahl"], a["vorrat"]) == (4, 2)

    def test_plan_des_herkunftsprojekts_wird_veraltet(self, client):
        mid, bid, teile = self._setup(client)
        pid_a = teile["A"]["projekt_id"]
        plan_a = client.post("/api/optimize", json={
            "project_id": pid_a, "material_id": mid, "blade_id": bid}).json()
        assert not plan_a["veraltet"]
        # Danach im Sägeauftrag gesägt → der Plan von A enthält jetzt zu viele Stücke
        liste = self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 1}])
        plan = client.post("/api/optimize", json={
            "project_id": liste["id"], "material_id": mid, "blade_id": bid}).json()
        client.post(f"/api/plans/{plan['plan_id']}/confirm-all")
        assert client.get(f"/api/projects/{pid_a}/plans/{mid}").json()["veraltet"]

    def test_herkunftsprojekt_plant_listenteile_nicht_doppelt(self, client):
        mid, bid, teile = self._setup(client)
        liste = self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 3}])
        client.post("/api/optimize", json={
            "project_id": liste["id"], "material_id": mid, "blade_id": bid})
        plan = client.post("/api/optimize", json={
            "project_id": teile["A"]["projekt_id"], "material_id": mid, "blade_id": bid}).json()
        n = sum(len(sp["platzierungen"]) for sp in plan["schnittplaene"])
        assert n == 1   # 4 offen − 3 ungesägt in der Schnittliste

    def test_beauftragt_zaehlt_schon_ohne_plan(self, client):
        mid, bid, teile = self._setup(client)
        self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 3}])
        plan = client.post("/api/optimize", json={
            "project_id": teile["A"]["projekt_id"], "material_id": mid, "blade_id": bid}).json()
        assert sum(len(sp["platzierungen"]) for sp in plan["schnittplaene"]) == 1

    def test_duplizieren_bleibt_schnittliste(self, client):
        _, _, teile = self._setup(client)
        liste = self._liste(client, [{"teil_id": teile["A"]["id"], "menge": 2}])
        kopie = client.post(f"/api/projects/{liste['id']}/clone").json()
        assert kopie["art"] == "liste"
        assert kopie["teile"][0]["herkunft_teil_id"] == teile["A"]["id"]


# =====================================================================
# Lager: Lagerorte, Zugang/Entnahme per Code, Abfallkiste, Journal
# =====================================================================

class TestLager:

    def _mat(self, client, kuerzel, typ="Stange", **kw):
        r = client.post("/api/materials", json={"name": f"Mat {kuerzel}", "typ": typ,
                                                "kuerzel": kuerzel, **kw})
        assert r.status_code == 201, r.text
        return r.json()

    def test_material_hat_immer_einen_lagerort(self, client):
        m = self._mat(client, "LG1")
        namen = [o["name"] for o in client.get("/api/locations").json()]
        assert m["lagerort"] in namen

    def test_unbekannter_ort_wird_angelegt_schreibweise_angeglichen(self, client):
        self._mat(client, "LG2", lagerort="Wandregal Neu")
        m = self._mat(client, "LG3", lagerort="  wandregal neu ")
        assert m["lagerort"] == "Wandregal Neu"
        namen = [o["name"].lower() for o in client.get("/api/locations").json()]
        assert namen.count("wandregal neu") == 1

    def test_aendern_ohne_lagerort_behaelt_ihn(self, client):
        m = self._mat(client, "LG4", lagerort="Halle", lagerort_reste="Kiste A")
        r = client.put(f"/api/materials/{m['id']}", json={"name": "Neu", "typ": "Stange",
                                                         "kuerzel": "LG4"}).json()
        assert (r["lagerort"], r["lagerort_reste"]) == ("Halle", "Kiste A")

    def test_umbenennen_wirkt_auf_materialien(self, client):
        m = self._mat(client, "LG5", lagerort="Ort Alt")
        ort = next(o for o in client.get("/api/locations").json() if o["name"] == "Ort Alt")
        assert client.put(f"/api/locations/{ort['id']}", json={"name": "Ort Neu"}).status_code == 200
        assert client.get("/api/materials").json()[0]["lagerort"] != "Ort Alt"
        mat = next(x for x in client.get("/api/materials").json() if x["id"] == m["id"])
        assert mat["lagerort"] == "Ort Neu"

    def test_loeschen_braucht_ziel_wenn_genutzt(self, client):
        self._mat(client, "LG6", lagerort="Weg damit")
        client.post("/api/locations", json={"name": "Ziel"})
        r = client.delete("/api/locations/Weg damit")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "lagerort_in_benutzung"
        assert client.delete("/api/locations/Weg damit?ziel=Ziel").status_code == 204
        m = next(x for x in client.get("/api/materials").json() if x["kuerzel"] == "LG6")
        assert m["lagerort"] == "Ziel"

    def test_zugang_und_entnahme_per_code(self, client):
        self._mat(client, "LG7", lagerort="R1", lagerort_reste="Restkiste")
        r = client.post("/api/stock/receive", json={"material": "lg7", "laenge": 800,
                                                    "anzahl": 2, "ist_rest": True}).json()
        assert r["codes"] == ["LG7-01", "LG7-02"] and r["lagerort"] == "Restkiste"
        assert client.get("/api/pieces/lg7-02").json()["laenge"] == 800
        inhalt = client.get("/api/locations/Restkiste/contents").json()
        assert inhalt[0]["rolle"] == "reste" and inhalt[0]["bestand"][0]["stueckzahl"] == 2
        t = client.post("/api/pieces/LG7-01/take", json={"grund": "verbraucht"}).json()
        assert t["code"] == "LG7-01"
        assert client.get("/api/pieces/LG7-01").status_code == 404
        arten = [j["art"] for j in client.get("/api/journal?material=LG7").json()]
        assert arten.count("zugang") == 2 and "entnahme" in arten

    def test_reserviertes_stueck_nur_mit_trotzdem(self, client):
        m = self._mat(client, "LG8")
        client.post("/api/stock/receive", json={"material": "LG8", "laenge": 3000})
        pid = client.post("/api/projects", json={"name": "Res"}).json()["id"]
        client.post(f"/api/projects/{pid}/parts", json={
            "label": "A", "typ": "Stange", "material_id": m["id"], "laenge": 1000})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        client.post("/api/optimize", json={"project_id": pid, "material_id": m["id"],
                                           "blade_id": bid})
        r = client.post("/api/pieces/LG8-01/take", json={})
        assert r.status_code == 409 and r.json()["detail"]["projekt"] == "Res"
        assert client.post("/api/pieces/LG8-01/take",
                           json={"trotzdem": True}).json()["reserviert_fuer"] == "Res"
        plan = client.get(f"/api/projects/{pid}/plans/{m['id']}").json()
        assert plan["lager_fehlt"] and plan["fehlende_stuecke"] == ["LG8-01"]

    def test_abfall_beim_saegen_in_die_kiste(self, client):
        client.put("/api/settings", json={"waste_keep": True, "waste_min": 50})
        m = self._mat(client, "LG9", rest_min_laenge=500)
        client.post("/api/stock/receive", json={"material": "LG9", "laenge": 1000})
        pid = client.post("/api/projects", json={"name": "Abf"}).json()["id"]
        client.post(f"/api/projects/{pid}/parts", json={
            "label": "A", "typ": "Stange", "material_id": m["id"], "laenge": 897})
        bid = client.post("/api/blades", json={"name": "B", "schnittbreite": 3}).json()["id"]
        plan = client.post("/api/optimize", json={"project_id": pid, "material_id": m["id"],
                                                  "blade_id": bid}).json()
        brett = plan["schnittplaene"][0]
        assert brett["reste_ziel"] == ["abfallkiste"]          # 100 mm Rest
        st = brett["platzierungen"][0]["id"]
        client.post(f"/api/plan-pieces/{st}", json={"gesaegt": True})
        assert client.get("/api/waste?material=LG9").json()[0]["anzahl"] == 1
        # Zurücknehmen nimmt den Abschnitt wieder aus der Kiste
        client.post(f"/api/plan-pieces/{st}", json={"gesaegt": False})
        assert client.get("/api/waste?material=LG9").json() == []

    def test_untergrenze_und_ausgeschaltet(self, client):
        m = self._mat(client, "LGA", rest_min_laenge=500)
        mat = webapp.get_db().get_material(m["id"])
        assert webapp._rest_ziel(mat, 100) == "weg"            # Kiste aus
        client.put("/api/settings", json={"waste_keep": True, "waste_min": 150})
        assert webapp._rest_ziel(mat, 100) == "weg"            # unter der Untergrenze
        assert webapp._rest_ziel(mat, 200) == "abfallkiste"
        assert webapp._rest_ziel(mat, 600) == "lager"

    def test_abfallkiste_entnehmen_und_leeren(self, client):
        self._mat(client, "LGB")
        client.post("/api/waste", json={"material": "LGB", "laenge": 120, "anzahl": 2})
        r = client.post("/api/waste/take", json={"material": "LGB", "laenge": 120, "anzahl": 3})
        assert r.status_code == 409 and r.json()["detail"]["vorhanden"] == 2
        assert client.post("/api/waste/take",
                           json={"material": "LGB", "laenge": 120}).json()[0]["anzahl"] == 1
        assert client.delete("/api/waste?material=LGB").status_code == 204
        assert client.get("/api/waste?material=LGB").json() == []


class TestStueckEtiketten:

    def _lager(self, client, kuerzel, ort):
        r = client.post("/api/materials", json={"name": f"Mat {kuerzel}", "typ": "Stange",
                                                "kuerzel": kuerzel, "lagerort": ort})
        assert r.status_code == 201, r.text
        client.post("/api/stock/receive", json={"material": kuerzel, "laenge": 3000, "anzahl": 2})
        client.post("/api/stock/receive", json={"material": kuerzel, "laenge": 640,
                                                "ist_rest": True})

    def _drucken(self, client, **body):
        r = client.post("/api/labels/pieces", json=body)
        return r.status_code, int(r.headers.get("X-Label-Count", 0))

    def test_filter_und_gedruckt_vermerk(self, client):
        self._lager(client, "ET1", "Etiketten-Regal")
        self._lager(client, "ET2", "Etiketten-Regal")
        assert client.get("/api/pieces/ET1-01").json()["etikett_gedruckt"] == 0
        assert self._drucken(client, lagerort="Etiketten-Regal", nur_reste=True,
                             markieren=False) == (200, 2)
        assert self._drucken(client, lagerort="Etiketten-Regal", material="ET1",
                             nur_ganze=True) == (200, 2)
        assert client.get("/api/pieces/ET1-01").json()["etikett_gedruckt"] > 0
        assert client.get("/api/pieces/ET1-03").json()["etikett_gedruckt"] == 0
        # Nur noch nicht gedruckte: ET1-03 (Rest) und die drei von ET2
        assert self._drucken(client, lagerort="Etiketten-Regal", nur_ungedruckt=True) == (200, 4)
        assert self._drucken(client, lagerort="Etiketten-Regal", nur_ungedruckt=True)[0] == 404

    def test_einzelne_codes_und_fehler(self, client):
        self._lager(client, "ET3", "Etiketten-Ecke")
        r = client.post("/api/labels/pieces", json={"codes": ["et3-02"], "startfeld": 5})
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        assert "ET3-02" in r.headers["content-disposition"]
        assert client.post("/api/labels/pieces", json={}).json()["detail"]["code"] == "auswahl_fehlt"
        r = client.post("/api/labels/pieces", json={"codes": ["ET3-99"]})
        assert r.status_code == 404 and r.json()["detail"]["code"] == "stueck_unbekannt"

    def test_entnahme_rueckgaengig_behaelt_vermerk(self, tmp_path):
        from core.db import Database
        from core.models import Lagerstueck, Material, MaterialTyp
        db = Database(tmp_path / "cutstock.db")
        mid = db.save_material(Material(name="Rück 20x20", typ=MaterialTyp.STANGE)).id
        ls = db.save_lagerstueck(Lagerstueck(material_id=mid, laenge=1000, stueckzahl=1))
        db.etiketten_gedruckt([db.list_einzelstuecke(ls.id)[0].id])
        snap = db.lager_verbrauchen(ls.id, stueck_nr=1)
        ls2, nr = db.stueck_hinzufuegen(Lagerstueck(material_id=mid, laenge=1000, stueckzahl=0))
        db.einzelstueck_wiederherstellen(ls2.id, nr, snap)
        assert db.list_einzelstuecke(ls2.id)[0].etikett_gedruckt > 0
        db.close()

    def test_migration_bestand_gilt_als_gedruckt(self, tmp_path):
        from core.db import Database
        from core.models import Lagerstueck, Material, MaterialTyp
        db = Database(tmp_path / "cutstock.db")
        mid = db.save_material(Material(name="Alt 30x30", typ=MaterialTyp.STANGE)).id
        ls = db.save_lagerstueck(Lagerstueck(material_id=mid, laenge=2000, stueckzahl=1))
        db.conn.execute("ALTER TABLE einzelstueck DROP COLUMN etikett_gedruckt")
        db.conn.commit()
        db.close()
        db = Database(tmp_path / "cutstock.db")
        assert db.list_einzelstuecke(ls.id)[0].etikett_gedruckt == 1
        db.close()


class TestEtikettenStartfeld:

    def test_startfeld_verschiebt_auf_dem_bogen(self, tmp_path):
        import re
        from core.labels import export_labels, sheet_fields
        seiten = lambda f: len(re.findall(rb"/Type /Page\b(?!s)", f.read_bytes()))
        assert sheet_fields("a4_3x8") == 24 and sheet_fields("roll_89x36") == 0
        lab = [{"title": "T", "line1": "1", "line2": "", "id_text": str(i)} for i in range(3)]
        export_labels(lab, tmp_path / "a.pdf", start=23)
        assert seiten(tmp_path / "a.pdf") == 2   # Felder 23, 24 | 1
        export_labels(lab, tmp_path / "b.pdf", start=1)
        assert seiten(tmp_path / "b.pdf") == 1
