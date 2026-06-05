"""Maßeinheiten-Handling für die GUI.

Intern speichert die DB alles in mm. Die GUI kann in mm oder cm anzeigen.
"""

from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QHBoxLayout, QWidget

UNITS = {
    "mm": {"label": "mm", "factor": 1.0, "decimals": 1},
    "cm": {"label": "cm", "factor": 10.0, "decimals": 2},
}


def current_unit() -> str:
    from core.settings import get_settings
    return get_settings().value("appearance/unit", "mm")


def unit_label() -> str:
    return UNITS[current_unit()]["label"]


def factor() -> float:
    return UNITS[current_unit()]["factor"]


def decimals() -> int:
    return UNITS[current_unit()]["decimals"]


def to_display(mm_value: float) -> float:
    return mm_value / factor()


def to_mm(display_value: float) -> float:
    return display_value * factor()


def create_length_input(max_val: float = 99999) -> tuple[QDoubleSpinBox, QLabel]:
    spin = QDoubleSpinBox()
    spin.setRange(0, to_display(max_val))
    spin.setDecimals(decimals())
    label = QLabel(unit_label())
    return spin, label


def length_row(max_val: float = 99999) -> tuple[QDoubleSpinBox, QWidget]:
    spin, ulabel = create_length_input(max_val)
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(spin)
    layout.addWidget(ulabel)
    layout.addStretch()
    return spin, container
