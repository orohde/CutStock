"""Tests für die Optimierungsalgorithmen."""

import pytest

from core.optimize import (
    OptimierungsErgebnis,
    PlattenVorrat,
    StangenVorrat,
    optimize_1d,
    optimize_2d,
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
