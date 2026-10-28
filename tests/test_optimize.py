"""Tests für die Optimierungsalgorithmen."""

import pytest

from core.models import Defekt
import core.optimize as optimize_mod
from core.optimize import (
    OptimierungsErgebnis,
    PlattenVorrat,
    StangenVorrat,
    optimize_1d,
    optimize_1d_ga,
    optimize_2d,
    optimize_2d_ga,
)


# =====================================================================
# 1D – Stangen
# =====================================================================

class TestOptimize1D:

    def test_ein_teil_passt(self):
        """Ein Teil, eine Stange – trivialster Fall."""
        erg = optimize_1d(
            teile=[("Strebe", 500.0, 1)],
            vorrat=[StangenVorrat(1, 2500.0, 1)],
            kerf=3.0,
        )
        assert len(erg.schnittplaene) == 1
        assert len(erg.fehlende_teile) == 0
        plan = erg.schnittplaene[0]
        assert len(plan.platzierungen) == 1
        assert plan.platzierungen[0].laenge == 500.0

    def test_mehrere_teile_eine_stange(self):
        """Mehrere Teile passen auf eine Stange, Kerf wird abgezogen."""
        erg = optimize_1d(
            teile=[("A", 400.0, 2), ("B", 300.0, 1)],
            vorrat=[StangenVorrat(1, 2500.0, 1)],
            kerf=3.0,
        )
        assert len(erg.schnittplaene) == 1
        assert len(erg.fehlende_teile) == 0
        plan = erg.schnittplaene[0]
        assert len(plan.platzierungen) == 3
        # 400 + 3 + 400 + 3 + 300 = 1106 -> Rest = 1394
        verbraucht = 400 + 3 + 400 + 3 + 300
        assert plan.lager_laenge - verbraucht == pytest.approx(1394.0)

    def test_kerf_beruecksichtigt(self):
        """Bei knappen Stangen macht die Kerf den Unterschied."""
        # Stange 1003mm, 2 Teile à 500mm, Kerf 3mm -> 500+3+500 = 1003 ✓
        erg = optimize_1d(
            teile=[("X", 500.0, 2)],
            vorrat=[StangenVorrat(1, 1003.0, 1)],
            kerf=3.0,
        )
        assert len(erg.fehlende_teile) == 0

        # Stange 1002mm -> 500+3+500 = 1003 > 1002 -> nur 1 passt
        erg2 = optimize_1d(
            teile=[("X", 500.0, 2)],
            vorrat=[StangenVorrat(1, 1002.0, 1)],
            kerf=3.0,
        )
        assert len(erg2.fehlende_teile) == 1

    def test_kleine_stangen_zuerst(self):
        """Kleine/Rest-Stangen werden bevorzugt verwendet."""
        erg = optimize_1d(
            teile=[("A", 300.0, 1)],
            vorrat=[
                StangenVorrat(1, 2500.0, 1),
                StangenVorrat(2, 400.0, 1),
            ],
            kerf=3.0,
        )
        assert len(erg.schnittplaene) == 1
        assert erg.schnittplaene[0].lagerstueck_id == 2

    def test_teil_zu_gross(self):
        """Teil passt auf keine Stange -> fehlend."""
        erg = optimize_1d(
            teile=[("Riese", 3000.0, 1)],
            vorrat=[StangenVorrat(1, 2500.0, 5)],
            kerf=3.0,
        )
        assert erg.fehlende_teile == ["Riese"]
        assert len(erg.schnittplaene) == 0

    def test_mehrere_stangen_noetig(self):
        """Teile brauchen mehr als eine Stange."""
        erg = optimize_1d(
            teile=[("A", 2000.0, 3)],
            vorrat=[StangenVorrat(1, 2500.0, 5)],
            kerf=3.0,
        )
        assert len(erg.schnittplaene) == 3
        assert len(erg.fehlende_teile) == 0

    def test_leerer_vorrat(self):
        erg = optimize_1d(
            teile=[("A", 100.0, 1)],
            vorrat=[],
            kerf=3.0,
        )
        assert erg.fehlende_teile == ["A"]

    def test_verschnitt_prozent(self):
        """Verschnitt wird korrekt berechnet."""
        erg = optimize_1d(
            teile=[("A", 1000.0, 1)],
            vorrat=[StangenVorrat(1, 2000.0, 1)],
            kerf=0.0,
        )
        assert erg.gesamt_verschnitt_prozent == pytest.approx(50.0)

    def test_defekt_teilt_stange(self):
        """Ein Defekt in der Mitte teilt die Stange in zwei Segmente."""
        defekte = {1: {1: [Defekt(einzelstueck_id=1,
                                   position=1000, laenge=100)]}}
        erg = optimize_1d(
            teile=[("A", 900.0, 1), ("B", 1300.0, 1)],
            vorrat=[StangenVorrat(1, 2500.0, 1)],
            kerf=3.0,
            defekte=defekte,
        )
        assert len(erg.fehlende_teile) == 0
        assert len(erg.schnittplaene) == 1

    def test_defekt_macht_teil_unmoeglich(self):
        """Defekt macht Stange zu kurz für ein langes Teil."""
        defekte = {1: {1: [Defekt(einzelstueck_id=1,
                                   position=500, laenge=100)]}}
        erg = optimize_1d(
            teile=[("A", 2000.0, 1)],
            vorrat=[StangenVorrat(1, 2500.0, 1)],
            kerf=3.0,
            defekte=defekte,
        )
        assert erg.fehlende_teile == ["A"]

    def test_rest_gebuendelt_wenige_muster(self):
        """ZMS: minimale Stangenzahl, Verschnitt auf einer Stange, wenige Muster."""
        teile = [("kurz", 291.3, 36), ("lang", 375.5, 72), ("mittel", 307.4, 72)]
        erg = optimize_1d(teile, [StangenVorrat(1, 2000.0, 31)], 3.2)
        assert not erg.fehlende_teile
        assert len(erg.schnittplaene) == 31
        anzahl = {}
        for p in erg.schnittplaene:
            for t in p.platzierungen:
                anzahl[t.teil_label] = anzahl.get(t.teil_label, 0) + 1
        assert anzahl == {"kurz": 36, "lang": 72, "mittel": 72}
        muster = {tuple(sorted(t.laenge for t in p.platzierungen))
                  for p in erg.schnittplaene}
        assert len(muster) <= 4
        assert max(x[0] for p in erg.schnittplaene for x in p.reste) > 860


@pytest.mark.parametrize("optimize", [optimize_1d, optimize_1d_ga])
class TestDefekt1DPositionen:
    """Teile liegen neben dem Defekt, nicht darüber (Schnell und Gründlich)."""

    @pytest.fixture(autouse=True)
    def _schnell(self, monkeypatch):
        monkeypatch.setattr(optimize_mod, "_GA_GENERATIONS", 20)

    def _pruefe_plan(self, plan, defekte, kerf):
        belegt = sorted((p.x, p.x + p.laenge) for p in plan.platzierungen)
        for d in defekte:
            for x0, x1 in belegt:
                assert x1 <= d.position or x0 >= d.position + d.laenge, \
                    f"Teil {x0}–{x1} überlappt Defekt bei {d.position}"
        for (_, a1), (b0, _) in zip(belegt, belegt[1:]):
            assert b0 >= a1 + kerf - 1e-6 or any(
                a1 <= d.position and b0 >= d.position + d.laenge for d in defekte)
        assert belegt[0][0] >= 0 and belegt[-1][1] <= plan.lager_laenge
        # Reste liegen in freien Bereichen
        for rest_l, rest_x in plan.reste:
            for x0, x1 in belegt:
                assert rest_x + rest_l <= x0 + 1e-6 or rest_x >= x1 - 1e-6
            for d in defekte:
                assert (rest_x + rest_l <= d.position + 1e-6
                        or rest_x >= d.position + d.laenge - 1e-6)

    def test_kein_teil_ueber_defekt(self, optimize):
        defekt = Defekt(einzelstueck_id=1, position=1000, laenge=50)
        erg = optimize([("a", 820.0, 4), ("b", 455.0, 6)],
                       [StangenVorrat(1, 2000.0, 2), StangenVorrat(2, 3000.0, 2)],
                       3.0, {2: {1: [defekt]}})
        assert not erg.fehlende_teile
        plaene = [sp for sp in erg.schnittplaene
                  if sp.lagerstueck_id == 2 and sp.stueck_nr == 1]
        assert len(plaene) == 1
        plan = plaene[0]
        assert plan.lager_laenge == 3000.0
        self._pruefe_plan(plan, [defekt], 3.0)
        # Teile + Fugen + Reste + Defekt ergeben die ganze Stange;
        # Fugen nur zwischen Teilen desselben Segments
        segmente = {p.x < defekt.position for p in plan.platzierungen}
        fugen = 3.0 * (len(plan.platzierungen) - len(segmente))
        genutzt = sum(p.laenge for p in plan.platzierungen)
        assert plan.verschnitt_mm == pytest.approx(
            plan.lager_laenge - genutzt - fugen)
        assert sum(r[0] for r in plan.reste) == pytest.approx(
            plan.verschnitt_mm - defekt.laenge)

    def test_ungenutztes_segment_wird_rest(self, optimize):
        """Ein Segment ohne Teile bleibt als eigener Rest erhalten."""
        defekt = Defekt(einzelstueck_id=1, position=400, laenge=50)
        erg = optimize([("A", 2000.0, 1), ("B", 2000.0, 1)],
                       [StangenVorrat(1, 3000.0, 2)], 3.0,
                       {1: {1: [defekt], 2: [defekt]}})
        assert not erg.fehlende_teile
        for plan in erg.schnittplaene:
            assert plan.platzierungen[0].x == 450
            self._pruefe_plan(plan, [defekt], 3.0)
            assert sorted(plan.reste) == [(400.0, 0.0), (550.0, 2450.0)]

    def test_mehrere_defekte(self, optimize):
        defekte = [Defekt(einzelstueck_id=1, position=700, laenge=30),
                   Defekt(einzelstueck_id=1, position=1500, laenge=80)]
        erg = optimize([("A", 600.0, 6), ("B", 250.0, 6)],
                       [StangenVorrat(1, 2400.0, 3)], 4.0, {1: {1: defekte}})
        plaene = [sp for sp in erg.schnittplaene if sp.stueck_nr == 1]
        assert plaene
        self._pruefe_plan(plaene[0], defekte, 4.0)


# =====================================================================
# 2D – Platten
# =====================================================================

class TestOptimize2D:

    def test_ein_teil_passt(self):
        """Ein Teil auf eine Platte."""
        erg = optimize_2d(
            teile=[("Boden", 800.0, 300.0, 1)],
            vorrat=[PlattenVorrat(1, 2800.0, 2070.0, 1)],
            kerf=3.0,
        )
        assert len(erg.schnittplaene) == 1
        assert len(erg.fehlende_teile) == 0

    def test_mehrere_teile_eine_platte(self):
        """Mehrere Teile werden auf eine Platte gepackt."""
        erg = optimize_2d(
            teile=[("A", 500.0, 400.0, 3)],
            vorrat=[PlattenVorrat(1, 2000.0, 1000.0, 1)],
            kerf=3.0,
        )
        assert len(erg.fehlende_teile) == 0
        assert len(erg.schnittplaene) == 1

    def test_kerf_bei_platten(self):
        """Kerf wird bei Platzierung berücksichtigt."""
        # Platte 1003 x 500, 2 Teile à 500 x 500, Kerf 3 -> 500+3+500 = 1003 ✓
        erg = optimize_2d(
            teile=[("X", 500.0, 500.0, 2)],
            vorrat=[PlattenVorrat(1, 1003.0, 500.0, 1)],
            kerf=3.0,
            drehung_erlaubt=False,
        )
        assert len(erg.fehlende_teile) == 0

    def test_drehung(self):
        """Teil wird gedreht, wenn es sonst nicht passt."""
        # Platte 1000x400, Teil 300x900 -> passt nicht, gedreht 900x300 -> passt
        erg = optimize_2d(
            teile=[("D", 300.0, 900.0, 1)],
            vorrat=[PlattenVorrat(1, 1000.0, 400.0, 1)],
            kerf=3.0,
            drehung_erlaubt=True,
        )
        assert len(erg.fehlende_teile) == 0
        assert erg.schnittplaene[0].platzierungen[0].gedreht is True

    def test_drehung_verboten(self):
        """Ohne Drehung passt das Teil nicht."""
        erg = optimize_2d(
            teile=[("D", 300.0, 900.0, 1)],
            vorrat=[PlattenVorrat(1, 1000.0, 400.0, 1)],
            kerf=3.0,
            drehung_erlaubt=False,
        )
        assert len(erg.fehlende_teile) == 1

    def test_teil_zu_gross(self):
        erg = optimize_2d(
            teile=[("Riese", 3000.0, 3000.0, 1)],
            vorrat=[PlattenVorrat(1, 2800.0, 2070.0, 2)],
            kerf=3.0,
        )
        assert erg.fehlende_teile == ["Riese"]

    def test_kleine_platten_zuerst(self):
        """Kleine Platten werden bevorzugt (Reste zuerst)."""
        erg = optimize_2d(
            teile=[("A", 200.0, 200.0, 1)],
            vorrat=[
                PlattenVorrat(1, 2800.0, 2070.0, 1),
                PlattenVorrat(2, 300.0, 300.0, 1),
            ],
            kerf=3.0,
        )
        assert erg.schnittplaene[0].lagerstueck_id == 2

    def test_verschnitt_prozent(self):
        erg = optimize_2d(
            teile=[("A", 500.0, 500.0, 1)],
            vorrat=[PlattenVorrat(1, 1000.0, 1000.0, 1)],
            kerf=0.0,
            drehung_erlaubt=False,
        )
        assert erg.gesamt_verschnitt_prozent == pytest.approx(75.0)

    def test_defekt_blockiert_platte(self):
        """Defekt blockiert Fläche — Teil wird daneben platziert."""
        defekte = {1: {1: [Defekt(einzelstueck_id=1,
                                   position=0, position_y=0,
                                   laenge=400, breite=500)]}}
        erg = optimize_2d(
            teile=[("A", 500.0, 400.0, 1)],
            vorrat=[PlattenVorrat(1, 1000.0, 500.0, 1)],
            kerf=3.0,
            drehung_erlaubt=False,
            defekte=defekte,
        )
        assert len(erg.fehlende_teile) == 0
        p = erg.schnittplaene[0].platzierungen[0]
        assert p.x >= 403

    def test_defekt_zu_gross_kein_platz(self):
        """Defekt lässt nicht genug Platz — Teil passt nicht."""
        defekte = {1: {1: [Defekt(einzelstueck_id=1,
                                   position=0, position_y=0,
                                   laenge=600, breite=500)]}}
        erg = optimize_2d(
            teile=[("A", 500.0, 400.0, 1)],
            vorrat=[PlattenVorrat(1, 1000.0, 500.0, 1)],
            kerf=3.0,
            drehung_erlaubt=False,
            defekte=defekte,
        )
        assert len(erg.fehlende_teile) == 1

    def test_guillotine_reste_sind_rechtecke(self):
        """Alle Reste müssen Rechtecke sein (Guillotine-Constraint)."""
        erg = optimize_2d(
            teile=[("A", 600.0, 400.0, 2)],
            vorrat=[PlattenVorrat(1, 2000.0, 1000.0, 1)],
            kerf=3.0,
        )
        for plan in erg.schnittplaene:
            for rest_l, rest_b in plan.reste:
                assert rest_l > 0
                assert rest_b > 0


# =====================================================================
# Gründlich (genetischer Algorithmus)
# =====================================================================

def _plaene(erg):
    return [(p.lagerstueck_id, p.stueck_nr,
             [(z.teil_label, z.x, z.y, z.gedreht) for z in p.platzierungen])
            for p in erg.schnittplaene]


class TestGenetisch:

    @pytest.fixture(autouse=True)
    def _schnell(self, monkeypatch):
        monkeypatch.setattr(optimize_mod, "_GA_GENERATIONS", 20)

    def test_1d_unabhaengig_von_lagermenge(self):
        """Zusätzliche gleiche Stangen im Lager ändern den Plan nicht."""
        teile = [("lang", 375.5, 30), ("kurz", 291.3, 30)]
        wenig = optimize_1d_ga(teile, [StangenVorrat(1, 1200.0, 20)], 4.0)
        viel = optimize_1d_ga(teile, [StangenVorrat(1, 1200.0, 2000)], 4.0)
        assert not wenig.fehlende_teile
        assert _plaene(wenig) == _plaene(viel)

    def test_1d_nie_schlechter_als_schnell_reste_gebuendelt(self):
        """Bei viel Lager keine Extra-Stangen; Reste auf wenige Stangen gebündelt."""
        teile = [("kurz", 291.3, 36), ("lang", 375.5, 72), ("mittel", 307.4, 72)]
        vorrat = [StangenVorrat(1, 2000.0, 200)]
        schnell = optimize_1d(teile, vorrat, 3.2)
        ga = optimize_1d_ga(teile, vorrat, 3.2)
        assert not ga.fehlende_teile
        assert len(ga.schnittplaene) <= len(schnell.schnittplaene)
        laengster = lambda r: max((x[0] for p in r.schnittplaene for x in p.reste if x),
                                  default=0)
        assert laengster(ga) >= laengster(schnell)

    def test_1d_defekt_macht_teil_unmoeglich(self):
        """Ein Defekt teilt die Stange auch im genetischen Algorithmus."""
        defekte = {1: {1: [Defekt(einzelstueck_id=1, position=500, laenge=100)]}}
        erg = optimize_1d_ga([("A", 2000.0, 1)],
                             [StangenVorrat(1, 2500.0, 1)], 3.0, defekte)
        assert erg.fehlende_teile == ["A"]

    def test_2d_unabhaengig_von_lagermenge(self):
        """Zusätzliche gleiche Platten im Lager ändern den Plan nicht."""
        teile = [("A", 600.0, 400.0, 10), ("B", 350.0, 350.0, 10)]
        wenig = optimize_2d_ga(teile, [PlattenVorrat(1, 2800.0, 2070.0, 5)], 4.0)
        viel = optimize_2d_ga(teile, [PlattenVorrat(1, 2800.0, 2070.0, 500)], 4.0)
        assert not wenig.fehlende_teile
        assert _plaene(wenig) == _plaene(viel)

    def test_zeitlimit_liefert_startloesung(self, monkeypatch):
        """Bei abgelaufenem Zeitlimit kommt mindestens die Startlösung zurück."""
        monkeypatch.setattr(optimize_mod, "_GA_TIME_LIMIT", 0.0)
        teile = [("lang", 375.5, 30), ("kurz", 291.3, 30)]
        vorrat = [StangenVorrat(1, 1200.0, 50)]
        ga = optimize_1d_ga(teile, vorrat, 4.0)
        assert not ga.fehlende_teile
        assert len(ga.schnittplaene) <= len(optimize_1d(teile, vorrat, 4.0).schnittplaene) + 1

    def test_ein_einzelnes_teil(self):
        """Mit nur einem offenen Teil darf „Gründlich“ nicht abstürzen."""
        erg1 = optimize_1d_ga([("A", 500.0, 1)], [StangenVorrat(1, 2500.0, 3)], 3.0)
        erg2 = optimize_2d_ga([("A", 500.0, 400.0, 1)],
                              [PlattenVorrat(1, 2000.0, 1000.0, 3)], 3.0)
        assert not erg1.fehlende_teile and len(erg1.schnittplaene) == 1
        assert not erg2.fehlende_teile and len(erg2.schnittplaene) == 1
