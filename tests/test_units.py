"""Tests für die Maßeinheiten (core/units.py)."""

import pytest

from core import units

ZOLL = 25.4


@pytest.mark.parametrize("mm, text", [
    (0.75 * ZOLL, '3/4"'),
    (1.75 * ZOLL, '1 3/4"'),
    (30.5 * ZOLL, '2\' 6 1/2"'),
    (24.25 * ZOLL, '2\' 1/4"'),
    (96 * ZOLL, '8\' 0"'),
    (12 * ZOLL, '1\' 0"'),
    (ZOLL / 16, '1/16"'),
    (0.0, '0"'),
    (3.2, '1/8"'),                 # 3,2 mm Sägeblatt → nächstes 1/16"
    (11.99 * ZOLL, '1\' 0"'),      # rundet auf 12" und wird zu Fuß
])
def test_bruch_mit_fuss(mm, text):
    assert units.length(mm, "in_frac") == text


def test_bruch_ohne_fuss():
    assert units.length(30.5 * ZOLL, "in_frac", feet=False) == '30 1/2"'
    assert units.length(96 * ZOLL, "in_frac", feet=False) == '96"'


def test_dezimal_zoll():
    assert units.length(24.25 * ZOLL, "in") == '24.25"'
    assert units.length(ZOLL / 16, "in") == '0.062"'


def test_metrisch_unveraendert():
    assert units.length(375.5) == "375.5 mm"
    assert units.length(375.5, "cm") == "37.55 cm"
    assert units.dimensions(800, 600) == "800 × 600 mm"
    assert units.dimensions(640, 0) == "640 mm"


def test_masse_zoll_je_wert_mit_zeichen():
    assert units.dimensions(48 * ZOLL, 23.625 * ZOLL, "in") == '48" × 23.625"'
    assert units.dimensions(31.5 * ZOLL, 23.625 * ZOLL, "in_frac") == '2\' 7 1/2" × 1\' 11 5/8"'


def test_unbekannte_einheit_wird_mm():
    assert units.normalize_unit("yard") == "mm"
    assert units.length(100, "yard") == "100 mm"
