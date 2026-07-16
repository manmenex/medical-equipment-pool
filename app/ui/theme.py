"""
Modern hospital-themed Qt stylesheets (dark / light).

Kept as plain Qt Style Sheet (QSS) strings rather than per-widget
`setStyleSheet` calls scattered across the codebase, so switching themes
is a single `QApplication.setStyleSheet(...)` call from Settings.
"""

from __future__ import annotations

# Clinical blue/teal palette - calm, high-contrast, accessible.
PRIMARY = "#1F6FEB"
PRIMARY_DARK = "#154C9E"
ACCENT_TEAL = "#0FB5AE"
DANGER = "#E5484D"
WARNING = "#F5A524"
SUCCESS = "#12B76A"

DARK_QSS = f"""
QWidget {{
    background-color: #10151C;
    color: #E6EDF3;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QMainWindow, #NavPanel {{
    background-color: #0B0F14;
}}
#NavPanel QPushButton {{
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    color: #C9D1D9;
    background: transparent;
}}
#NavPanel QPushButton:hover {{
    background-color: #1B2430;
}}
#NavPanel QPushButton:checked {{
    background-color: {PRIMARY};
    color: white;
    font-weight: 600;
}}
QFrame#StatCard {{
    background-color: #161B22;
    border: 1px solid #262E38;
    border-radius: 10px;
}}
QLabel#StatValue {{
    font-size: 26px;
    font-weight: 700;
    color: {ACCENT_TEAL};
}}
QLabel#StatLabel {{
    color: #9AA7B2;
    font-size: 12px;
}}
QPushButton {{
    background-color: {PRIMARY};
    color: white;
    border-radius: 6px;
    padding: 8px 16px;
    border: none;
}}
QPushButton:hover {{ background-color: {PRIMARY_DARK}; }}
QPushButton:disabled {{ background-color: #33404D; color: #7A8794; }}
QTableWidget, QTableView {{
    background-color: #161B22;
    gridline-color: #262E38;
    border: 1px solid #262E38;
    selection-background-color: {PRIMARY};
}}
QHeaderView::section {{
    background-color: #1B2430;
    color: #E6EDF3;
    padding: 6px;
    border: none;
}}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background-color: #161B22;
    border: 1px solid #30363D;
    border-radius: 4px;
    padding: 5px;
    color: #E6EDF3;
}}
QProgressBar {{
    border: 1px solid #30363D;
    border-radius: 4px;
    text-align: center;
    background-color: #161B22;
}}
QProgressBar::chunk {{ background-color: {ACCENT_TEAL}; }}
QStatusBar {{ background-color: #0B0F14; color: #9AA7B2; }}
QTabBar::tab {{ padding: 8px 14px; }}
"""

LIGHT_QSS = f"""
QWidget {{
    background-color: #F4F7FA;
    color: #1B2430;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QMainWindow, #NavPanel {{
    background-color: #FFFFFF;
}}
#NavPanel QPushButton {{
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    color: #33404D;
    background: transparent;
}}
#NavPanel QPushButton:hover {{
    background-color: #E7EEF7;
}}
#NavPanel QPushButton:checked {{
    background-color: {PRIMARY};
    color: white;
    font-weight: 600;
}}
QFrame#StatCard {{
    background-color: #FFFFFF;
    border: 1px solid #DCE4EC;
    border-radius: 10px;
}}
QLabel#StatValue {{
    font-size: 26px;
    font-weight: 700;
    color: {PRIMARY_DARK};
}}
QLabel#StatLabel {{
    color: #5B6B7A;
    font-size: 12px;
}}
QPushButton {{
    background-color: {PRIMARY};
    color: white;
    border-radius: 6px;
    padding: 8px 16px;
    border: none;
}}
QPushButton:hover {{ background-color: {PRIMARY_DARK}; }}
QPushButton:disabled {{ background-color: #C7D0DA; color: #8B97A3; }}
QTableWidget, QTableView {{
    background-color: #FFFFFF;
    gridline-color: #E1E8EF;
    border: 1px solid #DCE4EC;
    selection-background-color: {PRIMARY};
    selection-color: white;
}}
QHeaderView::section {{
    background-color: #EDF2F7;
    color: #1B2430;
    padding: 6px;
    border: none;
}}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid #C7D0DA;
    border-radius: 4px;
    padding: 5px;
}}
QProgressBar {{
    border: 1px solid #C7D0DA;
    border-radius: 4px;
    text-align: center;
    background-color: #FFFFFF;
}}
QProgressBar::chunk {{ background-color: {ACCENT_TEAL}; }}
QStatusBar {{ background-color: #FFFFFF; color: #5B6B7A; }}
"""


def stylesheet_for(theme: str) -> str:
    return DARK_QSS if theme.lower() == "dark" else LIGHT_QSS


STATUS_COLORS = {
    "Matched": SUCCESS,
    "Possible Match": WARNING,
    "Not Matched": DANGER,
}
