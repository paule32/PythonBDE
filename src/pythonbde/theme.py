"""Plattformübergreifende Qt5 Light-/Dark-Themes für PythonBDE.

Toolbar-Icons werden mit QPainter zur Laufzeit erzeugt. Die kleinen PNG-Pfeile
für Qt Style-Sheet-Scrollbars liegen als Projektressourcen neben diesem Modul.
"""
from __future__ import annotations

import math
from pathlib import Path

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import QApplication


ARROWS = Path(__file__).resolve().parent / "assets"


def theme_icon(dark: bool) -> QIcon:
    """Im Light-Mode Mond (Umschalten zu Dark), im Dark-Mode Sonne."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if dark:
            # Gelbe Sonne für aktiven dunklen Modus.
            color = QColor("#ffcc3d")
            painter.setPen(QPen(color, 2.3, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(color)
            painter.drawEllipse(QRectF(11.0, 11.0, 10.0, 10.0))
            for step in range(8):
                angle = math.pi * step / 4
                x, y = math.cos(angle), math.sin(angle)
                painter.drawLine(QPointF(16 + 9 * x, 16 + 9 * y),
                                 QPointF(16 + 13 * x, 16 + 13 * y))
        else:
            # Gut sichtbarer marineblauer Sichelmond für den hellen Modus.
            outside = QPainterPath()
            outside.addEllipse(QRectF(5, 4, 22, 22))
            cutout = QPainterPath()
            cutout.addEllipse(QRectF(12, 0, 20, 20))
            painter.fillPath(outside.subtracted(cutout), QColor("#263d78"))
    finally:
        painter.end()
    return QIcon(pixmap)


def theme_palette(dark: bool) -> QPalette:
    palette = QPalette()
    if dark:
        colors = {
            QPalette.Window: "#151b26",
            QPalette.WindowText: "#eef2fa",
            QPalette.Base: "#1e2838",
            QPalette.AlternateBase: "#27334a",
            QPalette.Text: "#eef2fa",
            QPalette.Button: "#293951",
            QPalette.ButtonText: "#eef2fa",
            QPalette.Highlight: "#37649a",
            QPalette.HighlightedText: "#ffffff",
            QPalette.ToolTipBase: "#263650",
            QPalette.ToolTipText: "#ffffff",
            QPalette.Link: "#84b7ff",
        }
    else:
        colors = {
            QPalette.Window: "#f1f4f9",
            QPalette.WindowText: "#202b3c",
            QPalette.Base: "#ffffff",
            QPalette.AlternateBase: "#eaf0f8",
            QPalette.Text: "#202b3c",
            QPalette.Button: "#e7edf5",
            QPalette.ButtonText: "#202b3c",
            QPalette.Highlight: "#3976bc",
            QPalette.HighlightedText: "#ffffff",
            QPalette.ToolTipBase: "#ffffff",
            QPalette.ToolTipText: "#202b3c",
            QPalette.Link: "#245da2",
        }
    for role, value in colors.items():
        palette.setColor(QPalette.Active, role, QColor(value))
        palette.setColor(QPalette.Inactive, role, QColor(value))
        palette.setColor(QPalette.Disabled, role, QColor(value))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#8994a6" if dark else "#87919e"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8994a6" if dark else "#87919e"))
    return palette


def theme_stylesheet(dark: bool) -> str:
    """Style für die ganze QApplication, einschließlich später geöffneter Dialoge.

    Der rot/grün/gelbe 3px-Kontostatusrahmen ist nicht Bestandteil dieses
    Style-Sheets und bleibt als lokaler Style von UserManagerDock erhalten.
    """
    if dark:
        window, base, surface = "#151b26", "#1e2838", "#253146"
        text, border, button, hover = "#eef2fa", "#475771", "#2b3c56", "#38516f"
        selected, disabled = "#37649a", "#8994a6"
    else:
        window, base, surface = "#f1f4f9", "#ffffff", "#eaf0f8"
        text, border, button, hover = "#202b3c", "#adbad0", "#e7edf5", "#d5e2f2"
        selected, disabled = "#3976bc", "#87919e"

    def image(filename: str) -> str:
        # Durchgehende Vorwärtsstriche sind auch bei Windows-Pfaden gültig.
        # PNG vermeidet eine QtSvg-Abhängigkeit für die gelben Pfeile.
        return (ARROWS / filename).as_posix()

    qss = r"""
    QWidget { color: @TEXT@; }
    QMainWindow, QDialog, QDockWidget, QStatusBar, QMenuBar, QToolBar {
        background-color: @WINDOW@; color: @TEXT@;
    }
    QDockWidget::title { background-color: @SURFACE@; color: @TEXT@;
        padding: 5px; text-align: left; }
    QMenu { background-color: @BASE@; color: @TEXT@; border: 1px solid @BORDER@; }
    QMenu::item { padding: 5px 24px; }
    QMenu::item:selected, QMenuBar::item:selected { background-color: @HOVER@; }
    QMenuBar::item { background: transparent; padding: 4px 8px; }
    QToolBar { border-bottom: 1px solid @BORDER@; spacing: 4px; padding: 3px; }
    QToolButton { background-color: @BUTTON@; color: @TEXT@;
        border: 1px solid @BORDER@; border-radius: 4px; padding: 3px; }
    QToolButton:hover { background-color: @HOVER@; }
    QToolButton:pressed { background-color: @SELECTED@; }
    QStatusBar { border-top: 1px solid @BORDER@; }
    QStatusBar::item { border: none; }
    QGroupBox { border: 1px solid @BORDER@; border-radius: 5px;
        margin-top: 12px; padding-top: 8px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
    QLineEdit, QSpinBox, QDateTimeEdit, QComboBox, QPlainTextEdit, QTextEdit,
    QTreeWidget, QTableWidget, QListWidget {
        background-color: @BASE@; color: @TEXT@;
        border: 1px solid @BORDER@; border-radius: 3px;
        selection-background-color: @SELECTED@; selection-color: #ffffff;
    }
    QLineEdit, QSpinBox, QDateTimeEdit, QComboBox { padding: 3px; }
    QTreeWidget::item:selected, QTableWidget::item:selected {
        background-color: @SELECTED@; color: #ffffff;
    }
    QHeaderView::section { background-color: @SURFACE@; color: @TEXT@;
        border: 1px solid @BORDER@; padding: 4px; }
    QPushButton { background-color: @BUTTON@; color: @TEXT@;
        border: 1px solid @BORDER@; border-radius: 4px;
        padding: 5px 10px; min-height: 18px; }
    QPushButton:hover { background-color: @HOVER@; }
    QPushButton:pressed { background-color: @SELECTED@; color: white; }
    QPushButton:disabled, QToolButton:disabled { color: @DISABLED@; }
    QCheckBox, QRadioButton { spacing: 5px; }
    QCheckBox::indicator, QRadioButton::indicator {
        width: 15px; height: 15px;
        border: 2px solid @INDICATOR@;
        background-color: @BASE@;
    }
    QCheckBox::indicator { border-radius: 3px; }
    QRadioButton::indicator { border-radius: 9px; }
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {
        background-color: @SELECTED@; border-color: @INDICATOR@;
    }
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
        border-color: @BORDER@;
    }
    QSplitter::handle { background-color: @BORDER@; }
    QSplitter::handle:horizontal { width: 3px; }
    QSplitter::handle:vertical { height: 3px; }

    /* Navyblaue Scrollbars mit gelben, expliziten Pfeil-Bilddateien. */
    QScrollBar:vertical { background: #081b3d; border: 1px solid #173462;
        width: 17px; margin: 17px 0 17px 0; }
    QScrollBar::handle:vertical { background: #315c99; border: 1px solid #496fb0;
        min-height: 25px; border-radius: 4px; margin: 1px; }
    QScrollBar::handle:vertical:hover { background: #4475b6; }
    QScrollBar::add-line:vertical { background: #112c59; height: 17px;
        subcontrol-position: bottom; subcontrol-origin: margin; }
    QScrollBar::sub-line:vertical { background: #112c59; height: 17px;
        subcontrol-position: top; subcontrol-origin: margin; }
    QScrollBar::up-arrow:vertical { image: url("@UP@"); width: 12px; height: 12px; }
    QScrollBar::down-arrow:vertical { image: url("@DOWN@"); width: 12px; height: 12px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #081b3d; }

    QScrollBar:horizontal { background: #081b3d; border: 1px solid #173462;
        height: 17px; margin: 0 17px 0 17px; }
    QScrollBar::handle:horizontal { background: #315c99; border: 1px solid #496fb0;
        min-width: 25px; border-radius: 4px; margin: 1px; }
    QScrollBar::handle:horizontal:hover { background: #4475b6; }
    QScrollBar::add-line:horizontal { background: #112c59; width: 17px;
        subcontrol-position: right; subcontrol-origin: margin; }
    QScrollBar::sub-line:horizontal { background: #112c59; width: 17px;
        subcontrol-position: left; subcontrol-origin: margin; }
    QScrollBar::left-arrow:horizontal { image: url("@LEFT@"); width: 12px; height: 12px; }
    QScrollBar::right-arrow:horizontal { image: url("@RIGHT@"); width: 12px; height: 12px; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: #081b3d; }
    """
    for key, value in {
        "WINDOW": window, "BASE": base, "SURFACE": surface,
        "TEXT": text, "BORDER": border, "BUTTON": button,
        "HOVER": hover, "SELECTED": selected, "DISABLED": disabled,
        "UP": image("scroll_up.png"), "DOWN": image("scroll_down.png"),
        "LEFT": image("scroll_left.png"), "RIGHT": image("scroll_right.png"),
    }.items():
        qss = qss.replace("@" + key + "@", value)
    return qss.replace("@INDICATOR@", "#D7E7FF" if dark else "#46576F")


def apply_application_theme(dark: bool) -> None:
    """Anwendung weit umstellen: Docks, Menüs, Statusbar und modale Dialoge."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must exist before setting the theme")
    app.setStyle("Fusion")
    app.setPalette(theme_palette(dark))
    app.setStyleSheet(theme_stylesheet(dark))
