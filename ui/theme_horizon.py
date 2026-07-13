"""SAP Horizon Theme als Qt-Stylesheet.

Die Farbwerte stammen aus dem offiziellen SAP-Paket
@sap-theming/theming-base-content (sap_horizon / sap_horizon_dark,
Apache-2.0-Lizenz) und sind identisch mit den Horizon-Themes der
Web-Oberflaeche (web/static/vendor/theme_horizon*.css).
"""

# Token-Sets: (hell, dunkel) — Schluessel wie in theming-base-content
_LIGHT = {
    "background": "#f5f6f7",
    "text": "#131e29",
    "label": "#556b82",
    "card": "#ffffff",
    "list_border": "#e5e5e5",
    "list_selection": "#ebf8ff",
    "list_hover": "#eaecee",
    "list_alternating": "#f5f6f7",
    "button_bg": "#ffffff",
    "button_border": "#bcc3ca",
    "button_text": "#0064d9",
    "button_hover_bg": "#eaecee",
    "emphasized_bg": "#0070f2",
    "emphasized_text": "#ffffff",
    "emphasized_hover_bg": "#0064d9",
    "field_bg": "#ffffff",
    "field_border": "#556b81",
    "field_text": "#131e29",
    "field_hover_border": "#0064d9",
    "field_focus_border": "#0032a5",
    "selected": "#0064d9",
    "header_bg": "#ffffff",
    "shell_bg": "#eff1f2",
    "scrollbar_face": "#7b91a8",
    "negative": "#aa0808",
    "neutral_bg": "#eff1f2",
}

_DARK = {
    "background": "#12171c",
    "text": "#f5f6f7",
    "label": "#8396a8",
    "card": "#1d232a",
    "list_border": "#2e3742",
    "list_selection": "#1d2d3e",
    "list_hover": "#222b35",
    "list_alternating": "#12171c",
    "button_bg": "#1c242c",
    "button_border": "#3a4a5a",
    "button_text": "#4db1ff",
    "button_hover_bg": "#222b35",
    "emphasized_bg": "#0070f2",
    "emphasized_text": "#ffffff",
    "emphasized_hover_bg": "#0064d9",
    "field_bg": "#161c22",
    "field_border": "#a9b4be",
    "field_text": "#ffffff",
    "field_hover_border": "#4db1ff",
    "field_focus_border": "#9ad3ff",
    "selected": "#4db1ff",
    "header_bg": "#1d232a",
    "shell_bg": "#12171c",
    "scrollbar_face": "#647891",
    "negative": "#fa6161",
    "neutral_bg": "#242e38",
}


def _build_qss(c: dict) -> str:
    return f"""
        QWidget {{
            background-color: {c['background']};
            color: {c['text']};
            font-family: "72", "Segoe UI", "SF Pro Text", sans-serif;
            font-size: 13px;
        }}

        QLabel {{ background: transparent; }}

        /* ----- Tabs (Fiori Icon Tab Bar: transparent, blauer Unterstrich) ----- */
        QTabWidget::pane {{ border: none; }}
        QTabWidget::tab-bar {{ alignment: left; }}
        QTabBar {{ background: {c['header_bg']}; }}
        QTabBar::tab {{
            background: {c['header_bg']};
            color: {c['label']};
            padding: 10px 16px;
            border: none;
            border-bottom: 3px solid transparent;
            margin-right: 4px;
        }}
        QTabBar::tab:selected {{
            color: {c['selected']};
            border-bottom: 3px solid {c['selected']};
        }}
        QTabBar::tab:hover:!selected {{ color: {c['text']}; }}

        /* ----- Buttons (Fiori Standard) ----- */
        QPushButton {{
            background-color: {c['button_bg']};
            color: {c['button_text']};
            border: 1px solid {c['button_border']};
            border-radius: 8px;
            padding: 6px 14px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {c['button_hover_bg']}; }}
        QPushButton:pressed {{
            background-color: {c['emphasized_bg']};
            color: {c['emphasized_text']};
        }}
        QPushButton:disabled {{
            color: {c['label']};
            border-color: {c['list_border']};
        }}
        QPushButton:default {{
            background-color: {c['emphasized_bg']};
            color: {c['emphasized_text']};
            border-color: {c['emphasized_bg']};
        }}
        QPushButton:default:hover {{ background-color: {c['emphasized_hover_bg']}; }}

        /* ----- Eingabefelder ----- */
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
            background-color: {c['field_bg']};
            color: {c['field_text']};
            border: 1px solid {c['field_border']};
            border-radius: 6px;
            padding: 5px 8px;
            selection-background-color: {c['selected']};
            selection-color: {c['emphasized_text']};
        }}
        QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
            border-color: {c['field_hover_border']};
        }}
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
            border: 2px solid {c['field_focus_border']};
            padding: 4px 7px;
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background-color: {c['card']};
            color: {c['text']};
            border: 1px solid {c['list_border']};
            selection-background-color: {c['list_selection']};
            selection-color: {c['text']};
        }}

        /* ----- Tabellen (Fiori Responsive Table) ----- */
        QTableWidget, QTableView {{
            background-color: {c['card']};
            alternate-background-color: {c['list_alternating']};
            gridline-color: {c['list_border']};
            border: 1px solid {c['list_border']};
            border-radius: 8px;
            selection-background-color: {c['list_selection']};
            selection-color: {c['text']};
        }}
        QTableWidget::item, QTableView::item {{ padding: 4px; }}
        QHeaderView {{ background-color: {c['card']}; border: none; }}
        QHeaderView::section {{
            background-color: {c['card']};
            color: {c['label']};
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid {c['list_border']};
            font-weight: 600;
        }}
        QTableCornerButton::section {{
            background-color: {c['card']};
            border: none;
            border-bottom: 1px solid {c['list_border']};
        }}

        /* ----- Gruppen als Fiori-Karten ----- */
        QGroupBox {{
            background-color: {c['card']};
            border: 1px solid {c['list_border']};
            border-radius: 12px;
            margin-top: 12px;
            padding-top: 20px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
            color: {c['text']};
            background: transparent;
        }}

        /* ----- Scrollbars (schlank) ----- */
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {c['scrollbar_face']};
            border-radius: 5px;
            min-height: 24px;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
            margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: {c['scrollbar_face']};
            border-radius: 5px;
            min-width: 24px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        /* ----- Sonstiges ----- */
        QCheckBox {{ background: transparent; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1px solid {c['field_border']};
            border-radius: 4px;
            background: {c['field_bg']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {c['emphasized_bg']};
            border-color: {c['emphasized_bg']};
        }}
        QMenu {{
            background-color: {c['card']};
            color: {c['text']};
            border: 1px solid {c['list_border']};
            border-radius: 8px;
        }}
        QMenu::item:selected {{ background-color: {c['list_hover']}; }}
        QToolTip {{
            background-color: {c['card']};
            color: {c['text']};
            border: 1px solid {c['list_border']};
        }}
        QMessageBox, QDialog {{ background-color: {c['background']}; }}
        QStatusBar {{
            background: {c['shell_bg']};
            color: {c['label']};
        }}
    """


HORIZON_LIGHT_QSS = _build_qss(_LIGHT)
HORIZON_DARK_QSS = _build_qss(_DARK)
