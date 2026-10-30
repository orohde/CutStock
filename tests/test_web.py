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
        return client.post("/api/optimize/mark-plan", json={
            "material_id": mid, "lagerstueck_id": sid, "is_1d": is_1d,
            "lager_laenge": l, "lager_breite": b, "kerf": 3,
            "marked_laengen": marked, "prev_consumed": consumed,
            "prev_rest_ids": list(rest_ids)}).json()

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
        res = client.post("/api/optimize/mark-plan", json={
            "material_id": mid, "lagerstueck_id": sid, "is_1d": True,
            "lager_laenge": 3000, "kerf": 3,
            "marked_laengen": [820, 820], "marked_x": [0, 1050],
            "defekte": [[1000, 50]], "prev_consumed": False}).json()
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
        return client.post("/api/optimize/mark-plan", json={
            "material_id": mid, "lagerstueck_id": sid, "is_1d": False,
            "lager_laenge": 2000, "lager_breite": 1000, "kerf": 3,
            "marked_laengen": marked, "prev_consumed": consumed,
            "prev_rest_ids": list(rest_ids), "stueck_nr": nr,
            "prev_consumed_piece": piece}).json()

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

    def test_neue_stuecke_hinter_luecke(self, client):
        mid, sid = self._setup(client)
        self._mark(client, mid, sid, 2, [500])
        assert sorted(self._pieces(client, sid)) == [1, 3]
        stock = client.get(f"/api/stock?material_id={mid}").json()
        ls = next(s for s in stock if s["id"] == sid)
        client.put(f"/api/stock/{sid}", json={**ls, "stueckzahl": 3})
        assert sorted(self._pieces(client, sid)) == [1, 3, 4]

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
