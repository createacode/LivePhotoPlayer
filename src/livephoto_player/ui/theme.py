"""视觉规范：配色、间距与全局样式表。

统一在这里定义，禁止在控件里散落颜色字面量。
"""

from __future__ import annotations

from typing import Final

COLOR_WINDOW: Final = "#1a1d21"
COLOR_PANEL: Final = "#22262b"
COLOR_PANEL_ALT: Final = "#282d33"
COLOR_CANVAS: Final = "#0e1013"
COLOR_BORDER: Final = "#333941"
COLOR_TEXT: Final = "#e6e9ef"
COLOR_TEXT_MUTED: Final = "#98a2b1"
COLOR_ACCENT: Final = "#4c8dff"
COLOR_ACCENT_SOFT: Final = "#2f5fb8"
COLOR_SUCCESS: Final = "#37c98b"
COLOR_WARNING: Final = "#f0b429"
COLOR_DANGER: Final = "#f2555a"

RADIUS: Final = 8
SPACING: Final = 8

FONT_STACK: Final = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'

STYLE_SHEET: Final = f"""
QWidget {{
    background-color: {COLOR_WINDOW};
    color: {COLOR_TEXT};
    font-family: {FONT_STACK};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {COLOR_WINDOW};
}}
QToolBar {{
    background-color: {COLOR_PANEL};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 6px 8px;
    spacing: 6px;
}}
QToolBar QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
    padding: 6px 10px;
    color: {COLOR_TEXT};
}}
QToolBar QToolButton:hover {{
    background-color: {COLOR_PANEL_ALT};
    border-color: {COLOR_BORDER};
}}
QToolBar QToolButton:pressed {{
    background-color: {COLOR_ACCENT_SOFT};
}}
QToolBar QToolButton:disabled {{
    color: {COLOR_TEXT_MUTED};
}}
QStatusBar {{
    background-color: {COLOR_PANEL};
    border-top: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_MUTED};
    min-height: 40px;
}}
QStatusBar::item {{
    border: none;
}}
QPushButton {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS}px;
    padding: 7px 14px;
    color: {COLOR_TEXT};
    min-height: 20px;
}}
QPushButton:hover {{
    border-color: {COLOR_ACCENT};
    background-color: #2f353d;
}}
QPushButton:pressed {{
    background-color: {COLOR_ACCENT_SOFT};
}}
QPushButton:disabled {{
    color: {COLOR_TEXT_MUTED};
    border-color: {COLOR_BORDER};
    background-color: {COLOR_PANEL};
}}
QPushButton:checked {{
    background-color: {COLOR_ACCENT_SOFT};
    border-color: {COLOR_ACCENT};
}}
QComboBox {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS}px;
    padding: 4px 10px;
    min-width: 64px;
}}
QComboBox:hover {{
    border-color: {COLOR_ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_ACCENT_SOFT};
    outline: none;
}}
QListView {{
    background-color: {COLOR_PANEL};
    border: none;
    border-right: 1px solid {COLOR_BORDER};
    outline: none;
    padding: 4px;
}}
QListView::item {{
    padding: 6px 8px;
    border-radius: 6px;
    color: {COLOR_TEXT};
}}
QListView::item:hover {{
    background-color: {COLOR_PANEL_ALT};
}}
QListView::item:selected {{
    background-color: {COLOR_ACCENT_SOFT};
    color: #ffffff;
}}
QMenu {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 24px 6px 16px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {COLOR_ACCENT_SOFT};
}}
QMenu::separator {{
    height: 1px;
    background-color: {COLOR_BORDER};
    margin: 4px 8px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #3d444d;
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: #4d5560;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #3d444d;
    border-radius: 5px;
    min-width: 32px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QProgressBar {{
    background-color: {COLOR_PANEL_ALT};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 3px;
}}
QToolTip {{
    background-color: {COLOR_PANEL_ALT};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    padding: 4px 8px;
}}
QSplitter::handle {{
    background-color: {COLOR_BORDER};
    width: 1px;
}}
"""
