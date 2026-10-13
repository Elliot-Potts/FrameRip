from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

BG = "#141518"
SURFACE = "#1c1d21"
RAISED = "#25272c"
BORDER = "#2e3036"
TEXT = "#dcdee3"
MUTED = "#8a8f99"
ACCENT = "#4cc2ff"
SUGGESTED = "#b58cff"
VIEWER_BG = "#0e0f11"

# Sharpness ramp: soft -> ok -> crisp
HEAT_LOW = (196, 71, 58)
HEAT_MID = (217, 164, 58)
HEAT_HIGH = (79, 180, 119)
HEAT_NONE = (44, 46, 52)


def heat_lut() -> np.ndarray:
    """256x3 uint8 colour ramp for normalised sharpness."""
    t = np.linspace(0, 1, 256)[:, None]
    low, mid, high = (np.array(c, dtype=np.float32) for c in (HEAT_LOW, HEAT_MID, HEAT_HIGH))
    first = low + (mid - low) * np.clip(t * 2, 0, 1)
    second = mid + (high - mid) * np.clip(t * 2 - 1, 0, 1)
    return np.where(t < 0.5, first, second).astype(np.uint8)


HEAT = heat_lut()


def heat_color(v: float | None) -> QColor:
    if v is None or np.isnan(v):
        return QColor(*HEAT_NONE)
    r, g, b = HEAT[int(np.clip(v, 0, 1) * 255)]
    return QColor(int(r), int(g), int(b))


STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 9.5pt; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
QMenuBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {RAISED}; border-radius: 4px; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {RAISED}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 6px; }}
QStatusBar::item {{ border: none; }}
#TransportBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
#BottomPanel {{ background: {SURFACE}; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {RAISED}; }}
QToolButton:pressed {{ background: {BORDER}; }}
QToolButton:checked {{ background: {RAISED}; }}
QToolButton#PlayButton {{ background: {RAISED}; border-radius: 16px; }}
QToolButton#PlayButton:hover {{ background: {BORDER}; }}
QDockWidget {{ titlebar-close-icon: none; color: {MUTED}; }}
QDockWidget::title {{ background: {SURFACE}; padding: 6px 8px; border-bottom: 1px solid {BORDER}; }}
QListWidget {{ background: {SURFACE}; border: none; outline: none; }}
QListWidget::item {{ padding: 4px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {RAISED}; color: {TEXT}; }}
QListWidget::item:hover {{ background: #212327; }}
QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 6px;
               padding: 5px 12px; }}
QPushButton:hover {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #0b1a24; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #6fd0ff; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {BG}; border: 1px solid {BORDER};
               border-radius: 6px; padding: 4px 6px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER};
               selection-background-color: {RAISED}; }}
QProgressBar {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 4px; height: 8px;
               text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; border-radius: 7px;
                              background: {ACCENT}; }}
QSlider::handle:horizontal:disabled {{ background: {MUTED}; }}
QRadioButton, QCheckBox {{ spacing: 8px; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 14px; height: 14px;
               border: 1px solid #4a4d55; background: {BG}; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{ border-color: {ACCENT};
               background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
               stop:0 {ACCENT}, stop:0.5 {ACCENT}, stop:0.6 {BG}, stop:1 {BG}); }}
QCheckBox::indicator:checked {{ border-color: {ACCENT}; background: {ACCENT}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Heading {{ font-size: 11pt; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BG))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(RAISED))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#0b1a24"))
    pal.setColor(QPalette.ToolTipBase, QColor(RAISED))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
