"""Tests für den PDF-Export."""

from core.models import Defekt
from core.optimize import OptimierungsErgebnis, Platzierung, Schnittplan
from core.pdf import _muster_bilden, _schnittliste_zeilen, export_pdf


def _stange(*laengen, defekte=None, stueck_nr=0):
    pl, x = [], 0.0
    for l in laengen:
        pl.append(Platzierung(f"Teil {l}", l, x=x))
        x += l + 3
    return Schnittplan(1, 2000, stueck_nr=stueck_nr, platzierungen=pl,
                       reste=[(2000 - x,)], defekte=defekte or [])


class TestMuster:

    def test_gleiche_stangen_zusammengefasst(self):
        plaene = [_stange(375.5, 307.4)] * 3 + [_stange(291.3)]
        muster = _muster_bilden(plaene, [], is_1d=True)
        assert [m.anzahl for m in muster] == [3, 1]

    def test_reihenfolge_egal_bei_stangen(self):
        muster = _muster_bilden([_stange(375.5, 307.4), _stange(307.4, 375.5)],
                                [], is_1d=True)
        assert len(muster) == 1 and muster[0].anzahl == 2

    def test_stange_mit_defekt_bleibt_einzeln(self):
        defekt = Defekt(position=900, laenge=60)
        plaene = [_stange(375.5), _stange(375.5, defekte=[defekt], stueck_nr=3),
                  _stange(375.5)]
        muster = _muster_bilden(plaene, [], is_1d=True)
        assert [m.anzahl for m in muster] == [2, 1]
        assert muster[1].plan.stueck_nr == 3

    def test_platten_mit_anderer_schnittfolge_getrennt(self):
        platte = Schnittplan(1, 2800, 2070, platzierungen=[
            Platzierung("Boden", 800, 300)])
        muster = _muster_bilden([platte, platte, platte],
                                [["a"], ["a"], ["b"]], is_1d=False)
        assert [m.anzahl for m in muster] == [2, 1]


class TestSchnittliste:

    def test_zaehlt_teile_und_rest(self):
        zeilen = _schnittliste_zeilen(_stange(375.5, 375.5, 307.4), 1000)
        assert zeilen == ["2 × Teil 375.5 (375.5 mm)   ·   "
                          "1 × Teil 307.4 (307.4 mm)   ·   Rest 932.6 mm"]

    def test_bricht_um(self):
        zeilen = _schnittliste_zeilen(_stange(100, 200, 300, 400), 150)
        assert zeilen[0] == "1 × Teil 100 (100 mm)"
        assert zeilen[-1] == "1 × Teil 400 (400 mm)   ·   Rest 988 mm"


def test_export_erzeugt_pdf(tmp_path):
    erg = OptimierungsErgebnis([_stange(375.5, 307.4)] * 10 + [_stange(20, 45)])
    pfad = tmp_path / "plan.pdf"
    export_pdf(erg, pfad, "Test", is_1d=True)
    assert pfad.read_bytes().startswith(b"%PDF")


def test_export_mit_materialbild(tmp_path):
    from io import BytesIO
    from PIL import Image
    png = BytesIO()
    Image.new("RGB", (40, 30), "grey").save(png, "PNG")
    erg = OptimierungsErgebnis([_stange(375.5)] * 2)
    for bild in (png.getvalue(), b"kein bild"):  # unlesbares Bild wird übersprungen
        pfad = tmp_path / "plan.pdf"
        export_pdf(erg, pfad, "Test", material_name="Profil", is_1d=True,
                   material_bild=bild)
        assert pfad.read_bytes().startswith(b"%PDF")
