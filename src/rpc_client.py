"""PythonBDE JSONL RPC Client – Qt5 GUI for Windows/Linux.

RPC GUI commands use a strict dispatcher. Signed .cpy packages are the one
exception: after explicit publisher-key pinning they execute trusted Python
bytecode locally with the user's full process permissions.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import deque
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QTcpSocket
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget, QToolBar,
    QTabWidget, QSpinBox, QButtonGroup, QGridLayout, QMenu,
    QMdiArea, QMdiSubWindow, QFrame,
)
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QFontMetrics, QIcon, QPixmap, QPainterPath
from PyQt5.QtCore import QSize, QRect

from pythonbde.theme import theme_icon, apply_application_theme
from pythonbde.windows_secrets import ENVELOPE_ALGORITHM, encrypt_password, trusted_fingerprint, save_trusted_fingerprint

from pythonbde.rpc import (
    ERR_CREATE_WINDOW, ERR_UNKNOWN_FUNCTION, ERR_WINDOW_NOT_VISIBLE, result_message,
)
from pythonbde.emulation import GUI_SIZES, TUI_SIZES, validate_client_display
from pythonbde.start_menu import validate_menu
from pythonbde.cpy_modules import verify_and_load, MODULE_IDS

MAX_LINE = 64 * 1024
MAX_BUFFER = 128 * 1024
MAX_LOG_LINES = 500
WINDOW_SIZES = (
    (640, 480), (800, 600), (1024, 768), (1280, 720),
    (1280, 768), (1280, 800), (1280, 1024),
)
TUI_WINDOW_SIZES = ((80, 25), (80, 50))
# Originaler Standard-Desktopfarbton von Windows 95 (Teal / Petrolgrün).
# Absichtlich unabhängig vom Light-/Dark-Theme des RPC-Clients.
WIN95_DESKTOP_COLOR = "#008080"
XP_SKY_COLOR = "#4EAAF0"
DESKTOP_GRID = 48
DESKTOP_ICON_SIZE = 48


def log_line(code: int, message: str, when=None) -> str:
    """A single, injection-safe local-time log record for both Qt editors."""
    when = when or datetime.now().astimezone()
    clean = " ".join(str(message).split())[:600]
    return f"{when:%Y-%m-%d %H:%M:%S} | {int(code)} | {clean}"


def snapped_to_grid(x: int, y: int, width: int, height: int,
                    grid: int = DESKTOP_GRID) -> tuple[int, int]:
    """Snap top-left corner of an icon to 48-pixel desktop cells."""
    max_x = max(0, width - DESKTOP_ICON_SIZE)
    max_y = max(0, height - DESKTOP_ICON_SIZE)
    return (max(0, min(round(x / grid) * grid, max_x)),
            max(0, min(round(y / grid) * grid, max_y)))


class DesktopGridOverlay(QWidget):
    """Visible 48x48 snap cells ONLY while dragging an icon."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setPen(QPen(QColor(255, 245, 100, 125), 1, Qt.DashLine))
            for x in range(0, self.width(), DESKTOP_GRID):
                p.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), DESKTOP_GRID):
                p.drawLine(0, y, self.width(), y)
        finally:
            p.end()


class DraggableCloseIcon(QWidget):
    """48x48 desktop icon + centered title; pressed overlay and grid snapping.

    Mouse release with no drag closes the window. Other icons can reuse this
    pattern when more desktop shortcuts are added.
    """

    SIZE = DESKTOP_ICON_SIZE
    CELL = DESKTOP_GRID

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(96, 78)  # 48x48 graphic, plus two-line centered caption.
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Disconnect / Close – drag to move")
        self._press_global = None
        self._start_pos = None
        self._dragging = False
        self._pressed = False

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            center_x = (self.width() - self.SIZE) // 2
            dark = getattr(self.window(), '_dark_theme', False)
            pen = QPen(QColor('#ffcc3d' if dark else '#eef5ff'), 2.5)
            p.setPen(pen)
            p.setBrush(QColor('#263e54'))
            p.drawRoundedRect(center_x, 0, self.SIZE, self.SIZE, 7, 7)
            p.drawLine(center_x+14, 14, center_x+34, 34)
            p.drawLine(center_x+34, 14, center_x+14, 34)
            if self._pressed:
                # Pressed overlay lasts exactly as long as the mouse is down.
                p.fillRect(QRect(center_x, 0, self.SIZE, self.SIZE), QColor(50, 130, 255, 115))
            p.setPen(QColor('#ffffff'))
            p.setFont(QFont('Sans Serif', 9))
            p.drawText(QRect(0, 49, self.width(), 27),
                       Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, 'Disconnect')
        finally:
            p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPos()
            self._start_pos = self.pos()
            self._dragging = False
            self._pressed = True
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._press_global is None or not event.buttons() & Qt.LeftButton:
            return
        delta = event.globalPos() - self._press_global
        if delta.manhattanLength() >= 5:
            self._dragging = True
        if self._dragging:
            parent = self.parentWidget()
            # The title footprint is wider than the 48x48 icon grid cell.
            # Snapping is based on the 48-pixel glyph top-left.
            self.move(max(0, min(parent.width()-self.width(), self._start_pos.x() + delta.x())),
                      max(0, min(parent.height()-self.height(), self._start_pos.y() + delta.y())))
            owner = self.window()
            if hasattr(owner, 'show_icon_grid'):
                owner.show_icon_grid(True)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press_global is not None:
            clicked = not self._dragging
            self._pressed = False
            self._press_global = None
            self.setCursor(Qt.OpenHandCursor)
            owner = self.window()
            if hasattr(owner, 'show_icon_grid'):
                owner.show_icon_grid(False)
            if not clicked:
                parent = self.parentWidget()
                glyph_x = self.x() + (self.width()-self.SIZE)//2
                x, y = snapped_to_grid(glyph_x, self.y(), parent.width(), parent.height())
                self.move(max(0, min(parent.width()-self.width(), x-(self.width()-self.SIZE)//2)), y)
            self.update()
            event.accept()
            if clicked:
                self.window().close()



class RemoteDesktopHeader(QWidget):
    """Blue-to-white header with an original Qt-painted remote-desktop glyph.

    The icon is painted with vector shapes and requires no Windows-only
    resources, so the client starts unchanged on Windows and Linux.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(106)
        self.setMaximumHeight(106)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, QColor("#2472BF"))
            gradient.setColorAt(0.55, QColor("#A7CCE9"))
            gradient.setColorAt(1.0, QColor("#FFFFFF"))
            p.fillRect(self.rect(), QBrush(gradient))

            # Two stylized, overlapping displays with a connection arrow.
            # (A platform-neutral visual reference to Remote Desktop.)
            p.setPen(QPen(QColor("#1C3B67"), 2))
            p.setBrush(QColor("#EAF5FE"))
            p.drawRoundedRect(20, 23, 48, 39, 3, 3)
            p.setBrush(QColor("#4997D1"))
            p.drawRect(24, 27, 40, 30)
            p.setPen(QPen(QColor("#19385B"), 2))
            p.drawLine(42, 63, 42, 68)
            p.drawLine(33, 69, 52, 69)

            p.setPen(QPen(QColor("#1C3B67"), 2))
            p.setBrush(QColor("#EAF5FE"))
            p.drawRoundedRect(52, 42, 47, 34, 3, 3)
            p.setBrush(QColor("#8FC4E9"))
            p.drawRect(56, 46, 39, 26)
            p.setPen(QPen(QColor("#FFE266"), 4))
            p.drawLine(41, 39, 80, 61)
            p.drawLine(69, 62, 80, 61)
            p.drawLine(79, 50, 80, 61)

            p.setPen(QColor("#152E55"))
            font = QFont(self.font())
            font.setBold(True)
            font.setPointSize(17)
            p.setFont(font)
            p.drawText(QRect(114, 21, max(0, self.width()-120), 36),
                       Qt.AlignLeft | Qt.AlignVCenter, "Remotedesktop")
            font.setPointSize(11)
            font.setBold(False)
            p.setFont(font)
            p.drawText(QRect(116, 59, max(0, self.width()-120), 29),
                       Qt.AlignLeft | Qt.AlignVCenter, "Connection")
        finally:
            p.end()

class ClassicStartMenu(QMenu):
    """Qt-native Start popup with a blue Windows-95-style vertical sidebar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(29, 0, 0, 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.fillRect(QRect(0, 0, 28, self.height()), QColor("#101080"))
            p.setPen(QColor("#eeeeee"))
            p.setFont(QFont("Sans Serif", 11, QFont.Bold))
            p.translate(0, self.height())
            p.rotate(-90)
            p.drawText(QRect(9, 0, max(1, self.height()-14), 28),
                       Qt.AlignLeft | Qt.AlignVCenter, "Windows 95")
        finally:
            p.end()


def start_menu_icon(name: str) -> QIcon:
    """Small original Qt-drawn folder/document/control icon."""
    pix = QPixmap(20, 20)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    try:
        p.setPen(QPen(QColor("#484848"), 1))
        if name in ("programs", "folder", "documents"):
            p.setBrush(QColor("#ffda57"))
            p.drawRect(2, 6, 16, 11)
            p.fillRect(QRect(3, 3, 8, 5), QColor("#f7e48a"))
        elif name in ("settings", "shutdown"):
            p.setBrush(QColor("#afbaca"))
            p.drawEllipse(3, 3, 14, 14)
            p.fillRect(QRect(8, 6, 4, 8), QColor("#485e8b"))
        elif name in ("find", "help"):
            p.setBrush(QColor("#d8f0ff"))
            p.drawEllipse(3, 2, 10, 10)
            p.drawLine(12, 12, 17, 18)
        elif name == "console":
            p.setBrush(QColor("#111111"))
            p.drawRect(2, 3, 16, 14)
            p.setPen(QColor("#e9e9e9"))
            p.drawText(QRect(4, 4, 12, 11), Qt.AlignCenter, ">_")
        else:
            p.setBrush(QColor("#ffffff"))
            p.drawRect(4, 2, 12, 16)
            p.setPen(QColor("#2768bc"))
            p.drawLine(6, 8, 14, 8)
            p.drawLine(6, 11, 13, 11)
    finally:
        p.end()
    return QIcon(pix)


class EmulatedTaskbar(QWidget):
    """Frontmost child-widget taskbar, with a clickable Start button.

    Only the application's work area is affected; no global always-on-top
    window flag is used. Start items are descriptions supplied over JSON,
    never executable paths/commands.
    """

    start_clicked = pyqtSignal()

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        if mode not in ("win95", "winXP"):
            raise ValueError("Taskbar requires win95/winXP mode")
        self.mode = mode
        self.setFixedHeight(32 if mode == "win95" else 40)
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("Start")
        self._application_buttons = {}
        timer = QTimer(self)
        timer.setInterval(30_000)
        timer.timeout.connect(self.update)
        timer.start()
        self._timer = timer

    def _start_rect(self):
        return QRect(4, 4, 84 if self.mode == "win95" else 107, self.height() - 8)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._start_rect().contains(event.pos()):
            self.start_clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def set_app(self, key: str, title: str, callback):
        """Task button exists immediately on launch and remains on minimize."""
        if key in self._application_buttons:
            self._application_buttons[key].setText(title)
            return
        button = QPushButton(title, self)
        button.setObjectName('TaskbarApp_' + key)
        button.setToolTip(title)
        button.setFixedHeight(self.height() - 7)
        button.setStyleSheet('QPushButton { background:#c0c0c0; color:#151515; '
                             'border:2px outset #eeeeee; padding:2px 5px; } '
                             'QPushButton:pressed { border:2px inset #909090; }'
                             if self.mode == 'win95' else
                             'QPushButton { background:#397bd1; color:white; '
                             'border:1px solid #8cbaff; border-radius:4px; padding:2px 5px; }')
        button.clicked.connect(callback)
        self._application_buttons[key] = button
        self.layout_apps()

    def remove_app(self, key: str):
        button = self._application_buttons.pop(key, None)
        if button is not None:
            button.deleteLater()
        self.layout_apps()

    def layout_apps(self):
        x = 96 if self.mode == 'win95' else 115
        for button in self._application_buttons.values():
            width = max(75, min(158, (self.width()-x-105)//max(1, len(self._application_buttons))))
            button.setGeometry(x, 3, width, self.height()-6)
            button.show()
            x += width + 3

    @staticmethod
    def _windows_flag(p, x, y, scale=1):
        """Original miniature four-colour icon resembling the classic flag."""
        width = max(3, int(scale * 5))
        for dx, dy, color in ((0, 0, "#e23237"), (1, 0, "#32a459"),
                              (0, 1, "#2676da"), (1, 1, "#ffd335")):
            p.fillRect(x + dx * (width+1), y + dy * (width+1), width, width,
                       QColor(color))

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()
            if self.mode == "win95":
                p.fillRect(self.rect(), QColor("#c0c0c0"))
                p.setPen(QColor("#ffffff"))
                p.drawLine(0, 0, w, 0)
                p.drawLine(0, 1, w, 1)
                p.setPen(QColor("#808080"))
                p.drawRect(4, 5, 84, h - 10)
                p.setPen(QColor("#ffffff"))
                p.drawLine(5, 6, 86, 6)
                p.drawLine(5, 6, 5, h - 6)
                self._windows_flag(p, 12, 9)
                p.setPen(QColor("#101010"))
                p.setFont(QFont("Sans Serif", 10, QFont.Bold))
                p.drawText(QRect(35, 7, 51, h - 13), Qt.AlignVCenter, "Start")
                p.setPen(QColor("#666666"))
                p.drawRect(max(95, w - 91), 5, 85, h - 10)
                p.setPen(QColor("#151515"))
                p.setFont(QFont("Sans Serif", 9))
                p.drawText(QRect(max(95, w - 90), 5, 82, h - 10),
                           Qt.AlignCenter, datetime.now().strftime("%H:%M"))
            else:
                background = QLinearGradient(0, 0, 0, h)
                background.setColorAt(0, QColor("#3273e6"))
                background.setColorAt(0.18, QColor("#2355c3"))
                background.setColorAt(1, QColor("#143d9d"))
                p.fillRect(self.rect(), background)
                start = QLinearGradient(0, 0, 0, h)
                start.setColorAt(0, QColor("#66c743"))
                start.setColorAt(1, QColor("#21851f"))
                p.setBrush(QBrush(start))
                p.setPen(QPen(QColor("#b4e897"), 1))
                p.drawRoundedRect(-7, 3, 111, h - 6, 16, 16)
                self._windows_flag(p, 8, 11)
                p.setPen(QColor("#ffffff"))
                p.setFont(QFont("Sans Serif", 11, QFont.Bold))
                p.drawText(QRect(35, 5, 62, h - 10), Qt.AlignCenter, "start")
                tray = QRect(max(110, w - 98), 1, 98, h - 2)
                p.fillRect(tray, QColor("#177ebd"))
                p.setFont(QFont("Sans Serif", 9))
                p.drawText(tray, Qt.AlignCenter, datetime.now().strftime("%H:%M"))
        finally:
            p.end()




class CreatedWindow(QWidget):
    """Communication work area styled as Win95, WinXP or character console."""

    closed = pyqtSignal()

    def __init__(self, client_id: str, server_name: str, geometry=WINDOW_SIZES[0],
                 *, mode="winXP", tui_geometry=TUI_WINDOW_SIZES[0]):
        super().__init__(None, Qt.Window)
        if mode not in ("win95", "winXP", "con"):
            raise ValueError("Unsupported system emulation")
        self.setWindowTitle("PythonBDE – RPC Client Window")
        self.client_id = client_id
        self.mode = mode
        self.display = ({"unit": "cells", "width": tui_geometry[0], "height": tui_geometry[1]}
                        if mode == "con" else
                        {"unit": "pixels", "width": geometry[0], "height": geometry[1]})
        self._dark_theme = False
        self.taskbar = None
        self.workspace = None
        self.grid_overlay = None
        self._mdi_windows = {}
        self._tearing_down = False
        self.start_menu = None
        self._menu_data = None
        self._menu_log_callback = None
        self.terminal_view = None
        # Compatibility: log is mirrored but is never visibly shown in the work area.
        self.log = QPlainTextEdit(self)
        self.log.hide()
        if mode == "con":
            if tuple(tui_geometry) not in TUI_WINDOW_SIZES:
                raise ValueError("Unsupported TUI geometry")
            columns, rows = tui_geometry
            terminal = QPlainTextEdit(self)
            terminal.setObjectName("RpcConsoleArea")
            terminal.setReadOnly(True)
            terminal.setFont(QFont("Consolas", 10))
            terminal.setLineWrapMode(QPlainTextEdit.NoWrap)
            terminal.setStyleSheet(
                "QPlainTextEdit { background: #07151e; color: #c8f7e8; "
                "border: 0; padding: 4px; selection-background-color: #255f7b; }"
            )
            terminal.setPlainText(f"PythonBDE Console ({columns} x {rows})\nConnected: {server_name}")
            self.terminal_view = terminal
            self.terminal_columns, self.terminal_rows = columns, rows
            self.terminal_view.setMaximumBlockCount(1000)
            metrics = QFontMetrics(terminal.font())
            cell_width = metrics.horizontalAdvance("W")
            cell_height = metrics.lineSpacing()
            geometry = (columns * cell_width + 24, rows * cell_height + 24)
            self.setWindowTitle(f"PythonBDE Console – {columns} x {rows}")
        else:
            if tuple(geometry) not in WINDOW_SIZES:
                raise ValueError("Unsupported GUI geometry")
            self.workspace = QMdiArea(self)
            self.workspace.setObjectName('RemoteMdiDesktop')
            self.workspace.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.workspace.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.grid_overlay = DesktopGridOverlay(self.workspace.viewport())
            self._refresh_desktop_brush()
            self.taskbar = EmulatedTaskbar(mode, self)
            self.taskbar.start_clicked.connect(self.show_start_menu)
        self.close_icon = DraggableCloseIcon(self)
        # Desktop icons must be behind newly opened MDI windows, but above
        # the desktop background; the taskbar remains a separate top layer.
        if self.workspace is not None:
            self.close_icon.setParent(self.workspace.viewport())
        self.close_icon.move(24, 0)
        self.close_icon.show()
        self.close_icon.raise_()
        # Existing v0.4.9 behaviour: window can shrink, but not exceed preset.
        self.setMinimumSize(120, 90)
        self.setMaximumSize(*geometry)
        self.resize(*geometry)

    def paintEvent(self, event):
        """Windows 95 paints a classic teal desktop regardless of Qt theme.

        This is the workspace BACKGROUND, not the grey Win95 taskbar,
        the grey Start menu, or the other two emulation modes.
        """
        if self.mode != "win95":
            super().paintEvent(event)
            return
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(WIN95_DESKTOP_COLOR))
        finally:
            painter.end()

    def _refresh_desktop_brush(self):
        """Original XP-inspired sky/clouds/green rolling hills (not a wallpaper copy)."""
        if self.workspace is None:
            return
        w = max(1, self.workspace.width())
        h = max(1, self.workspace.height())
        if self.mode == 'win95':
            self.workspace.setBackground(QBrush(QColor(WIN95_DESKTOP_COLOR)))
            return
        picture = QPixmap(w, h)
        painter = QPainter(picture)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            sky = QLinearGradient(0, 0, 0, h)
            sky.setColorAt(0, QColor('#126ac2'))
            sky.setColorAt(.72, QColor(XP_SKY_COLOR))
            sky.setColorAt(1, QColor('#b6e6ff'))
            painter.fillRect(QRect(0, 0, w, h), QBrush(sky))
            # Soft clouds are simple vector shapes, not rasterized Microsoft artwork.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(245, 250, 255, 195))
            for ax, ay, scale in [(int(w*.20), int(h*.18), 1),
                                  (int(w*.73), int(h*.27), .7)]:
                painter.drawEllipse(ax, ay, int(110*scale), int(25*scale))
                painter.drawEllipse(ax+20, ay-int(11*scale), int(77*scale), int(39*scale))
            hill = QPainterPath()
            hill.moveTo(0, int(h*.78))
            hill.cubicTo(w*.25, h*.56, w*.55, h*.81, w, h*.62)
            hill.lineTo(w, h)
            hill.lineTo(0, h)
            hill.closeSubpath()
            green = QLinearGradient(0, h*.58, 0, h)
            green.setColorAt(0, QColor('#8ed143'))
            green.setColorAt(1, QColor('#27812b'))
            painter.fillPath(hill, QBrush(green))
        finally:
            painter.end()
        self.workspace.setBackground(QBrush(picture))

    def show_icon_grid(self, enabled: bool):
        if self.grid_overlay is None:
            return
        if enabled:
            self.grid_overlay.setGeometry(self.workspace.viewport().rect())
            self.grid_overlay.show()
            self.grid_overlay.raise_()
            self.close_icon.raise_()
        else:
            self.grid_overlay.hide()

    def launch_module_widget(self, module_id: str, title: str, widget):
        """Put trusted signed Python module inside moveable Qt MDI subwindow."""
        if self.workspace is None or self.taskbar is None:
            raise ValueError('Modules require Windows 95/XP GUI mode')
        if module_id in self._mdi_windows:
            previous = self._mdi_windows[module_id]
            if previous.isMinimized():
                previous.showNormal()
            self.workspace.setActiveSubWindow(previous)
            return previous
        sub = QMdiSubWindow(self.workspace)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title)
        sub.setWidget(widget)
        sub.resize(min(450, max(220, self.workspace.width()-40)),
                   min(320, max(150, self.workspace.height()-40)))
        self.workspace.addSubWindow(sub)
        self._mdi_windows[module_id] = sub
        self.taskbar.set_app(module_id, title, lambda key=module_id: self.toggle_module(key))
        sub.destroyed.connect(lambda _obj=None, key=module_id: self._forget_module(key))
        sub.show()
        self.workspace.setActiveSubWindow(sub)
        self.taskbar.raise_()
        return sub

    def toggle_module(self, module_id: str):
        sub = self._mdi_windows.get(module_id)
        if sub is None:
            return
        if sub.isMinimized():
            sub.showNormal()
            self.workspace.setActiveSubWindow(sub)
        elif self.workspace.activeSubWindow() is sub:
            sub.showMinimized()
        else:
            self.workspace.setActiveSubWindow(sub)
            sub.raise_()
        if self.taskbar is not None:
            self.taskbar.raise_()

    def _forget_module(self, module_id: str):
        self._mdi_windows.pop(module_id, None)
        if self.taskbar is not None and not self._tearing_down:
            self.taskbar.remove_app(module_id)

    def set_theme(self, dark: bool):
        self._dark_theme = bool(dark)
        self.close_icon.update()
        self.update()  # Repaint the workspace after a theme switch.

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.workspace is not None:
            bottom = self.taskbar.height() if self.taskbar is not None else 0
            self.workspace.setGeometry(0, 0, self.width(), max(1, self.height()-bottom))
            self._refresh_desktop_brush()
            self.grid_overlay.setGeometry(self.workspace.viewport().rect())
        if self.taskbar is not None:
            self.taskbar.setGeometry(0, self.height() - self.taskbar.height(),
                                    self.width(), self.taskbar.height())
            self.taskbar.layout_apps()
            self.taskbar.raise_()  # Always above all work-area child widgets.
        if self.terminal_view is not None:
            self.terminal_view.setGeometry(0, 0, self.width(), self.height())
            self.terminal_view.lower()
        icon = self.close_icon
        parent = icon.parentWidget()
        icon.move(max(0, min(icon.x(), parent.width()-icon.width())),
                  max(0, min(icon.y(), parent.height()-icon.height())))

    def configure_start_menu(self, packet: dict, on_select=None):
        """Rebuild the Win95/XP Qt menu from a *validated* server JSON tree."""
        if self.taskbar is None or packet.get("systemMode") != self.mode:
            raise ValueError("Start menu does not match the active GUI mode")
        if packet.get("menuVersion") != 1 or packet.get("event") != "menu_config":
            raise ValueError("Unsupported Start menu configuration")
        if packet.get("client") != self.server_session_id:
            raise ValueError("Start menu client session does not match")
        nodes = validate_menu(packet.get("items"))
        if self.start_menu is not None:
            self.start_menu.close()
            self.start_menu.deleteLater()
        menu = ClassicStartMenu(self) if self.mode == "win95" else QMenu(self)
        menu.setObjectName("PythonBDEStartMenu")
        # Qt draws the menu; no hard-coded screenshot or pixel-perfect cloning.
        if self.mode == "win95":
            menu.setStyleSheet('''
                QMenu {background: #c0c0c0; color: #111; border: 2px outset #f4f4f4;}
                QMenu::item {padding: 5px 26px 5px 14px;}
                QMenu::item:selected {background: #000080; color: white;}
                QMenu::separator {height: 2px; background: #858585; margin: 4px;}
            ''')
        else:
            menu.setStyleSheet('''
                QMenu {background: #eef4ff; color: #162a4c; border: 2px solid #326dd0;}
                QMenu::item {padding: 6px 30px 6px 14px;}
                QMenu::item:selected {background: #285bb7; color: white;}
                QMenu::separator {height: 1px; background: #a4bce7; margin: 4px;}
            ''')
        def populate(parent, items):
            for node in items:
                if node.get("separatorBefore"):
                    parent.addSeparator()
                if "children" in node:
                    sub = parent.addMenu(start_menu_icon(node.get("icon", "folder")), node["label"])
                    sub.setEnabled(not node.get("disabled", False))
                    populate(sub, node["children"])
                else:
                    action = parent.addAction(start_menu_icon(node.get("icon", "document")), node["label"])
                    action.setEnabled(not node.get("disabled", False))
                    # No remote shell execution. Selecting a menu entry only
                    # emits a local notice until a specific RPC is implemented.
                    if on_select is not None:
                        action.triggered.connect(
                            lambda _checked=False, key=node["id"], title=node["label"]:
                            on_select(key, title))
        populate(menu, nodes)
        self.start_menu = menu
        self._menu_data = packet
        self._menu_log_callback = on_select
        self.taskbar.raise_()

    def show_start_menu(self):
        if self.start_menu is None or self.taskbar is None:
            return
        menu = self.start_menu
        menu.adjustSize()
        desktop = QApplication.desktop().availableGeometry(self)
        anchor = self.taskbar.mapToGlobal(QPoint(4, 0))
        size = menu.sizeHint()
        x = max(desktop.left(), min(anchor.x(), desktop.right() - size.width() + 1))
        y = max(desktop.top(), min(anchor.y() - size.height(), desktop.bottom() - size.height() + 1))
        menu.popup(QPoint(x, y))
        menu.raise_()

    def append_console_message(self, message: str):
        """Render text-only server events in the selected 80-column TUI."""
        if self.terminal_view is None:
            return
        sanitized = " ".join(str(message).split())
        for i in range(0, len(sanitized), self.terminal_columns):
            self.terminal_view.appendPlainText(sanitized[i:i + self.terminal_columns])

    def set_rpc(self, packet):
        """CreateWindow targets existing work area; no additional window."""
        if packet.get("setFunc") != "CreateWindow":
            raise ValueError("Unsupported RPC function")
        # Do not process instructions sent for a different emulation session.
        if packet.get("systemMode", "winXP") != self.mode:
            raise ValueError("RPC emulation mode does not match client session")
        if packet.get("display") is not None:
            _, offered = validate_client_display(self.mode, packet["display"])
            if offered != self.display:
                raise ValueError("RPC geometry does not match client session")
        self.show()
        self.raise_()
        self.activateWindow()
        if self.taskbar is not None:
            self.taskbar.raise_()
        if self.mode == "con":
            self.append_console_message("RPC: CreateWindow")

    def closeEvent(self, event):
        self._tearing_down = True
        self.closed.emit()
        super().closeEvent(event)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About RPC Client")
        self.setModal(True)
        layout = QVBoxLayout(self)
        label = QLabel(
            "RPC Client v.0.5.3\n"
            "(c) 2026 by Jens Kallup - paule32\n"
            "all rights reserved.\n\n"
            "PythonBDE JSON RPC client for Windows and Linux."
        )
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignHCenter)
        self.resize(390, 180)
        # No hard-coded label colors: inherits native light/dark QPalette.


class RpcTestClient(QMainWindow):
    def __init__(self, host: str, port: int):
        super().__init__()
        self.setWindowTitle("PythonBDE – JSON RPC Client (c) 2026 by Jens Kallup - paule32")
        self.resize(700, 590)
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(self._connected)
        self.sock.readyRead.connect(self._read)
        self.sock.disconnected.connect(self._disconnected)
        self.sock.errorOccurred.connect(self._socket_error)
        self._buffer = bytearray()
        self._pending = deque()
        self._log_lines = deque(maxlen=MAX_LOG_LINES)
        self._logged_in = False
        self._server_session_id = None
        self._cached_menu_config = None
        self._handled_rpc_ids = set()
        self._module_requests = {}
        self._next_module_request = 0
        self._client_window = None
        self._closing_program = False
        self._window_teardown = False
        self._server_name = f"{host}:{port}"
        self._requested_mode = "winXP"
        self._requested_display = {"unit": "pixels", "width": 640, "height": 480}
        self._last_gui_mode = "winXP"
        self._dark_theme = False
        self._init_menu()
        self._init_theme_toolbar()

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 0, 12, 10)
        layout.setSpacing(8)

        # Header remains above the tabs and is entirely Qt-painted.
        self.connection_header = RemoteDesktopHeader(central)
        layout.addWidget(self.connection_header)

        # Main screen: tabbed login credentials and display configuration.
        self.tabs = QTabWidget(central)
        self.tabs.setObjectName("RPCClientTabs")
        self.common_tab = QWidget()
        self.display_tab = QWidget()
        self.tabs.addTab(self.common_tab, "Common")
        self.tabs.addTab(self.display_tab, "Display")
        layout.addWidget(self.tabs)

        common_layout = QVBoxLayout(self.common_tab)
        common_panels = QHBoxLayout()
        # Left panel: all eight original credentials labels/fields.
        connection_panel = QGroupBox("Connection")
        form = QFormLayout(connection_panel)
        self.host = QLineEdit(host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(port if 1 <= port <= 65535 else 43650)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Server IP / host", self.host)
        form.addRow("TCP Port", self.port)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        common_panels.addWidget(connection_panel, 3)

        # Right panel: explicit UI/protocol mode, not actual OS emulation.
        emulation_panel = QGroupBox("System Emulation")
        emulation_layout = QVBoxLayout(emulation_panel)
        self.win95_radio = QRadioButton("Windows 95")
        self.winxp_radio = QRadioButton("Windows XP")
        self.console_radio = QRadioButton("Console")
        self.winxp_radio.setChecked(True)
        self.system_mode_group = QButtonGroup(self)
        for radio in (self.win95_radio, self.winxp_radio, self.console_radio):
            self.system_mode_group.addButton(radio)
            emulation_layout.addWidget(radio)
        emulation_layout.addStretch(1)
        common_panels.addWidget(emulation_panel, 2)
        common_layout.addLayout(common_panels)

        buttons = QHBoxLayout()
        self.login_button = QPushButton("Connect / Login")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        self.login_button.clicked.connect(self.connect_login)
        self.disconnect_button.clicked.connect(self.disconnect_client)
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.disconnect_button)
        common_layout.addLayout(buttons)
        common_layout.addStretch(1)

        display_tab_layout = QVBoxLayout(self.display_tab)
        display_box = QGroupBox("Display:")
        display_layout = QHBoxLayout(display_box)
        modes_layout = QVBoxLayout()
        geometry_layout = QGridLayout()
        self.windowed_radio = QRadioButton("Windowed")
        self.windowed_radio.setChecked(True)
        self.fullscreen_radio = QRadioButton("Full Screen")
        self.fullscreen_radio.setEnabled(False)  # reserved for a later stage
        self.fullscreen_radio.setToolTip("Full Screen will be implemented later")
        self.display_mode_group = QButtonGroup(self)
        self.display_mode_group.addButton(self.windowed_radio)
        self.display_mode_group.addButton(self.fullscreen_radio)
        modes_layout.addWidget(self.windowed_radio)
        modes_layout.addWidget(self.fullscreen_radio)
        modes_layout.addStretch(1)
        display_layout.addLayout(modes_layout, 1)

        self.gui_geometry_radio = QRadioButton("GUI Geometry")
        self.tui_geometry_radio = QRadioButton("TUI Geometry")
        self.geometry_mode_group = QButtonGroup(self)
        self.geometry_mode_group.addButton(self.gui_geometry_radio)
        self.geometry_mode_group.addButton(self.tui_geometry_radio)
        self.gui_geometry_radio.setChecked(True)
        self.geometry_combo = QComboBox()
        for width, height in WINDOW_SIZES:
            self.geometry_combo.addItem(f"{width} x {height}", (width, height))
        self.tui_geometry_combo = QComboBox()
        for columns, rows in TUI_WINDOW_SIZES:
            self.tui_geometry_combo.addItem(f"{columns} x {rows}", (columns, rows))
        geometry_layout.addWidget(self.gui_geometry_radio, 0, 0)
        geometry_layout.addWidget(self.geometry_combo, 0, 1)
        geometry_layout.addWidget(self.tui_geometry_radio, 1, 0)
        geometry_layout.addWidget(self.tui_geometry_combo, 1, 1)
        geometry_layout.setColumnStretch(1, 1)
        display_layout.addLayout(geometry_layout, 2)
        display_tab_layout.addWidget(display_box)
        display_tab_layout.addStretch(1)

        self.win95_radio.toggled.connect(lambda checked: checked and self._select_system_mode("win95"))
        self.winxp_radio.toggled.connect(lambda checked: checked and self._select_system_mode("winXP"))
        self.console_radio.toggled.connect(lambda checked: checked and self._select_system_mode("con"))
        self.gui_geometry_radio.toggled.connect(lambda checked: checked and self._select_geometry_mode("gui"))
        self.tui_geometry_radio.toggled.connect(lambda checked: checked and self._select_geometry_mode("tui"))
        self._select_system_mode("winXP")

        # Server connection indicator belongs to QMainWindow's status bar,
        # never to the tabs or the log-editor's vertical layout.
        self.status = QLabel("Disconnected")
        self.status.setObjectName("RPCConnectionStatus")
        self.statusBar().addPermanentWidget(self.status)
        self.statusBar().showMessage("Ready")

        layout.addWidget(QLabel("Client Logging"))
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        layout.addWidget(self.log, stretch=1)
        self._log("RPC Client GUI started")

    def _init_menu(self):
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction("Close", self.close)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("About ...", self.show_about)

    def _init_theme_toolbar(self):
        toolbar = QToolBar("Display Theme", self)
        toolbar.setObjectName("RPCClientThemeToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        self.theme_action = toolbar.addAction(theme_icon(False), "Dark Mode")
        self.theme_action.triggered.connect(self.toggle_theme)
        apply_application_theme(False)

    def toggle_theme(self):
        self._dark_theme = not self._dark_theme
        apply_application_theme(self._dark_theme)
        self.theme_action.setIcon(theme_icon(self._dark_theme))
        self.theme_action.setToolTip("Light Mode" if self._dark_theme else "Dark Mode")
        if self._client_window is not None:
            self._client_window.set_theme(self._dark_theme)
        self._log("Dark Mode enabled" if self._dark_theme else "Light Mode enabled")

    def show_about(self):
        AboutDialog(self).exec_()

    def _log(self, message: str, code: int = 200):
        row = log_line(code, message)
        self._log_lines.appendleft(row)
        self.log.setPlainText("\n".join(self._log_lines))
        if self._client_window is not None:
            self._client_window.log.setPlainText("\n".join(self._log_lines))

    def _select_system_mode(self, mode: str):
        """Switch GUI/TUI size choice to match the selected wire mode."""
        if mode != "con":
            self._last_gui_mode = mode
        for widget in (self.gui_geometry_radio, self.tui_geometry_radio):
            widget.blockSignals(True)
        try:
            self.gui_geometry_radio.setChecked(mode != "con")
            self.tui_geometry_radio.setChecked(mode == "con")
        finally:
            for widget in (self.gui_geometry_radio, self.tui_geometry_radio):
                widget.blockSignals(False)
        self.geometry_combo.setEnabled(mode != "con")
        self.tui_geometry_combo.setEnabled(mode == "con")

    def _select_geometry_mode(self, geometry_mode: str):
        """Choosing TUI also selects Console; GUI restores the prior skin."""
        if geometry_mode == "tui":
            self.console_radio.setChecked(True)
        elif self.console_radio.isChecked():
            (self.win95_radio if self._last_gui_mode == "win95" else self.winxp_radio).setChecked(True)

    def _display_selection(self):
        if self.console_radio.isChecked():
            columns, rows = tuple(self.tui_geometry_combo.currentData() or TUI_WINDOW_SIZES[0])
            mode = "con"
            display = {"unit": "cells", "width": columns, "height": rows}
        else:
            mode = "win95" if self.win95_radio.isChecked() else "winXP"
            width, height = tuple(self.geometry_combo.currentData() or WINDOW_SIZES[0])
            display = {"unit": "pixels", "width": width, "height": height}
        return validate_client_display(mode, display)

    def connect_login(self):
        if self.sock.state() != QAbstractSocket.UnconnectedState:
            return
        port = self.port.value()
        if not self.username.text().strip() or not self.password.text():
            QMessageBox.warning(self, "Login", "Benutzername und Passwort eingeben")
            return
        if not self.windowed_radio.isChecked():
            QMessageBox.information(self, "Display", "Full Screen is not yet available")
            return
        try:
            self._requested_mode, self._requested_display = self._display_selection()
        except ValueError as exc:
            QMessageBox.warning(self, "Display", str(exc))
            return
        self._server_name = f"{self.host.text().strip()}:{port}"
        self._pending.clear()
        self._buffer.clear()
        self._handled_rpc_ids.clear()
        self._logged_in = False
        self.login_button.setEnabled(False)
        self.status.setText("Connecting ...")
        self._log(f"Connecting to {self._server_name}")
        self.sock.connectToHost(self.host.text().strip(), port)

    def _connected(self):
        # NEVER send credentials until platform preflight is complete.
        self._log("TCP connected; checking server capabilities")
        self._send("hello", clientPlatform=platform.system())
        self.disconnect_button.setEnabled(True)

    def _handle_hello(self, packet):
        if not packet.get("ok") or not isinstance(packet.get("data"), dict):
            self._log("Server platform handshake failed", 400)
            self.disconnect_client()
            return
        info = packet["data"]
        is_both_windows = platform.system() == "Windows" and info.get("platform") == "Windows"
        fingerprint = str(info.get("serverFingerprint", ""))
        try:
            pinned = trusted_fingerprint(self._server_name) if platform.system() == "Windows" else None
        except (OSError, ValueError) as exc:
            self._log(f"Server trust store error: {exc}", 400)
            self.disconnect_client()
            return
        if pinned and (not is_both_windows or pinned != fingerprint):
            self._log("Trusted server changed or encryption downgraded; connection refused", 400)
            QMessageBox.critical(self, "Server Identity",
                                 "Serverkennung geändert oder Verschlüsselung herabgestuft! Verbindung verweigert.")
            self.disconnect_client()
            return
        if is_both_windows:
            if (info.get("passwordTransport") != ENVELOPE_ALGORITHM
                    or not info.get("serverPublicKey") or not fingerprint or not info.get("nonce")):
                self._log("Windows server offers no valid Windows Secrets transport", 400)
                self.disconnect_client()
                return
            if not pinned:
                result = QMessageBox.question(
                    self, "Trust Windows Server",
                    "Erste Verbindung zum Windows-Server.\n"
                    "Bitte diesen SHA-256 Fingerprint unabhängig prüfen:\n\n"
                    + fingerprint + "\n\nServer dauerhaft vertrauen?",
                    QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
                if result != QMessageBox.Ok:
                    self.disconnect_client()
                    return
            try:
                envelope = encrypt_password(info["serverPublicKey"], fingerprint,
                                            info["nonce"], self.password.text())
                if not pinned:
                    save_trusted_fingerprint(self._server_name, fingerprint)
            except (ValueError, OSError, RuntimeError) as exc:
                self._log(f"Windows Secrets failed: {exc}", 400)
                self.disconnect_client()
                return
            self._log("Windows Secrets credential envelope prepared")
            self._send("login", clientPlatform="Windows", username=self.username.text(),
                       passwordSecret=envelope, systemMode=self._requested_mode,
                       display=self._requested_display)
        else:
            confirm = QMessageBox.question(
                self, "Connection Security",
                "Warning: Plain Password connection !\nWould you connect ?",
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            if confirm != QMessageBox.Ok:
                self._log("Plaintext login cancelled by user")
                self.disconnect_client()
                return
            self._log("WARNING: Using plaintext password (no TLS)", 400)
            self._send("login", clientPlatform=platform.system(), allowPlaintext=True,
                       username=self.username.text(), password=self.password.text(),
                       systemMode=self._requested_mode, display=self._requested_display)
        self.password.clear()

    def _send(self, action: str, **values):
        if self.sock.state() != QAbstractSocket.ConnectedState:
            return False
        payload = json.dumps({"action": action, **values}, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8") + b"\n"
        self._pending.append(action)
        self.sock.write(payload)
        return True

    def _read(self):
        self._buffer.extend(bytes(self.sock.readAll()))
        if len(self._buffer) > MAX_BUFFER:
            self._log("Incoming data exceeded maximum; disconnecting", 400)
            self.disconnect_client()
            return
        while b"\n" in self._buffer:
            pos = self._buffer.index(10)
            line = bytes(self._buffer[:pos])
            del self._buffer[:pos + 1]
            if len(line) > MAX_LINE:
                self._log("RPC message too large", 400)
                self.disconnect_client()
                return
            try:
                packet = json.loads(line.decode("utf-8"))
                if not isinstance(packet, dict):
                    raise ValueError("JSON object expected")
            except (UnicodeError, ValueError) as exc:
                self._log(f"Invalid server JSON: {exc}", 400)
                self.disconnect_client()
                return
            if packet.get("event") == "rpc_request":
                self._handle_rpc(packet)
            elif "event" in packet:
                self._handle_event(packet)
            else:
                self._handle_reply(packet)

    def _show_client_window(self):
        if self._client_window is not None:
            return self._client_window
        mode, display = validate_client_display(self._requested_mode, self._requested_display)
        size = (display["width"], display["height"])
        # In Console mode these are columns/rows, never raw window pixels.
        window = CreatedWindow(self.username.text().strip(), self._server_name,
                               size if mode != "con" else WINDOW_SIZES[0],
                               mode=mode, tui_geometry=size if mode == "con" else TUI_WINDOW_SIZES[0])
        window.closed.connect(self._on_client_window_closed)
        window.server_session_id = self._server_session_id
        self._client_window = window
        if self._cached_menu_config is not None:
            try:
                window.configure_start_menu(self._cached_menu_config, self._on_start_menu_selected)
            except ValueError as exc:
                self._log(f"Start menu configuration rejected: {exc}", 400)
        window.set_theme(self._dark_theme)
        self.hide()
        window.log.setPlainText("\n".join(self._log_lines))
        window.show()
        window.raise_()
        window.activateWindow()
        self._log(f"Client Window opened: {mode}, {size[0]} x {size[1]} ({display['unit']})")
        return window

    def _handle_reply(self, packet):
        action = self._pending.popleft() if self._pending else "unexpected"
        if action == "hello":
            self._handle_hello(packet)
        elif action == "login":
            self._logged_in = bool(packet.get("ok"))
            if self._logged_in:
                data = packet.get("data")
                if isinstance(data, dict) and data.get("systemMode"):
                    if data["systemMode"] != self._requested_mode:
                        self._log("Login emulation response mismatch", 400)
                        self.disconnect_client()
                        return
                self.status.setText("Logged in – waiting for RPC requests")
                self._log(f"Login successful: {self.username.text()}")
                try:
                    self._show_client_window()
                except Exception as exc:
                    self._log(f"Could not open Client Window: {exc}", 400)
                    self.disconnect_client()
            else:
                reason = str(packet.get("error", "unknown"))
                retry = packet.get("retryAfterSeconds", 0)
                if type(retry) is int and retry > 0:
                    reason += f"\nBitte mindestens {retry} Sekunden warten."
                self.status.setText("Login failed")
                code = packet.get("errorCode", 400)
                self._log("Login rejected: " + reason, code if type(code) is int else 400)
                self.disconnect_client()
                if code in (403, 409, 429):
                    QMessageBox.warning(self, "Login blocked", reason)
        elif action == "rpc_result":
            accepted = bool(packet.get("ok") and packet.get("data", {}).get("rpc_ack"))
            self._log("RPC confirmation accepted" if accepted else
                      "RPC confirmation rejected: " + str(packet.get("error", "unknown")),
                      200 if accepted else 400)
        elif action != "unexpected":
            self._log(f"Reply {action}: {packet.get('ok')}", 200 if packet.get("ok") else 400)
        else:
            self._log("Unexpected server response", 400)

    def _handle_event(self, packet):
        event = packet["event"]
        if event == "menu_config":
            if not self._logged_in:
                self._log("Start menu received before login", 400)
                return
            try:
                window = self._client_window
                if window is None or window.taskbar is None:
                    raise ValueError("Start menu received without graphical workspace")
                if (packet.get("client") != self._server_session_id and
                        self._server_session_id is not None):
                    raise ValueError("Start menu session mismatch")
                if self._server_session_id is None:
                    # The RPC CreateWindow packet is guaranteed to precede the menu.
                    raise ValueError("Start menu without authenticated RPC session")
                window.configure_start_menu(packet, self._on_start_menu_selected)
                self._cached_menu_config = packet
                self._log(f"Server Start menu loaded ({len(packet['items'])} entries)")
            except (ValueError, TypeError, KeyError) as exc:
                self._log(f"Invalid Start menu rejected: {exc}", 400)
        elif event == "module_package":
            self._handle_module_package(packet)
        elif event == "module_error":
            self._module_requests.pop(packet.get('requestId'), None)
            self._log('Server .cpy error: ' + str(packet.get('message','unknown')), 400)
        elif event == "server_message":
            message = str(packet.get("text", ""))
            self._log("SERVER MESSAGE: " + message)
            if self._client_window is not None:
                self._client_window.append_console_message("SERVER: " + message)
        elif event == "kicked":
            self._log("Kicked: " + str(packet.get("reason", "")), 400)
            self.disconnect_client()
        else:
            self._log(f"Server event: {event}")

    def _on_start_menu_selected(self, menu_id: str, title: str):
        # Request only a fixed, published server module; never interpret menu labels
        # as filesystem paths or arbitrary shell commands.
        if menu_id not in MODULE_IDS or not self._logged_in:
            self._log(f"Start Menu: {title} [{menu_id}] – no approved module")
            return
        self._next_module_request += 1
        request_id = f"m{self._next_module_request}"
        self._module_requests[request_id] = menu_id
        if not self._send("load_module", moduleId=menu_id, requestId=request_id):
            self._module_requests.pop(request_id, None)
        else:
            self._log(f"Requested signed .cpy module: {title}")

    def _handle_module_package(self, packet):
        if not self._logged_in or self._client_window is None:
            self._log("Module without active login rejected", 400)
            return
        key = packet.get('requestId')
        expected = self._module_requests.pop(key, None)
        if (expected is None or packet.get('moduleId') != expected or
                packet.get('client') != self._server_session_id):
            self._log("Mismatched/unsolicited .cpy module refused", 400)
            return
        # Pin must be distributed separately from the untrusted TCP session.
        from pathlib import Path
        import os
        trusted_path = Path(os.environ.get('PYTHONBDE_TRUSTED_MODULE_KEY') or
                            Path(__file__).resolve().with_name('module_signing_public.pem'))
        try:
            manifest, module = verify_and_load(packet, trusted_path)
            widget = module.create_widget(self._client_window.workspace)
            if not isinstance(widget, QWidget):
                raise ValueError('Signed module entrypoint must return a QWidget')
            self._client_window.launch_module_widget(expected, manifest['title'], widget)
            self._log(f"Remote .cpy module started: {manifest['title']}")
        except Exception as exc:
            self._log(f"Remote module rejected/failed: {exc}", 400)
            QMessageBox.warning(self._client_window, 'Module Loader', str(exc))

    def _handle_rpc(self, packet):
        if not self._logged_in:
            self._log("Ignoring RPC before successful login", 400)
            return
        if not packet.get("client") or not isinstance(packet.get("client"), str) or not isinstance(packet.get("rpcId"), str) or not packet.get("rpcId"):
            self._log("Invalid RPC: missing client or rpcId", 400)
            return
        if packet["rpcId"] in self._handled_rpc_ids:
            self._ack_rpc(packet, ERR_CREATE_WINDOW, "Duplicate RPC ID")
            self._log("Duplicate RPC ID refused", ERR_CREATE_WINDOW)
            return
        self._handled_rpc_ids.add(packet["rpcId"])
        self._server_session_id = packet["client"]
        if self._client_window is not None:
            self._client_window.server_session_id = self._server_session_id
        if packet.get("setFunc") != "CreateWindow":
            self._ack_rpc(packet, ERR_UNKNOWN_FUNCTION, "Unknown RPC function")
            self._log("Unknown RPC function", ERR_UNKNOWN_FUNCTION)
            return
        try:
            window = self._client_window
            if window is None:
                raise RuntimeError("Client Window is not active")
            window.set_rpc(packet)  # ALWAYS dispatch RPC to existing Client Window
            self._log(f"CreateWindow received for {packet['client']}")
        except Exception as exc:
            self._ack_rpc(packet, ERR_CREATE_WINDOW, str(exc))
            self._log(f"CreateWindow failed: {exc}", ERR_CREATE_WINDOW)
            return
        # Acknowledge only after Qt has processed window show events.
        QTimer.singleShot(0, lambda p=packet, w=window: self._ack_created_window(p, w))

    def _ack_created_window(self, packet, window):
        if window is self._client_window and window.isVisible() and self._logged_in:
            self._ack_rpc(packet, 0)
            self._log("CreateWindow successful; lastErrorCode=0")
        else:
            self._ack_rpc(packet, ERR_WINDOW_NOT_VISIBLE, "Window not visible")
            self._log("CreateWindow failed: Window not visible", ERR_WINDOW_NOT_VISIBLE)

    def _ack_rpc(self, packet, code, error=""):
        result = result_message(packet, code, error)
        self._send(result.pop("action"), **result)

    def _socket_error(self, error):
        self._log("TCP error: " + self.sock.errorString(), 400)
        self.status.setText("Connection error")

    def _close_client_window(self):
        window = self._client_window
        if window is None:
            return
        self._client_window = None
        self._window_teardown = True
        try:
            window.close()
            window.deleteLater()
        finally:
            self._window_teardown = False

    def _on_client_window_closed(self):
        if self._window_teardown or self._closing_program:
            return
        self._log("Client Window closed; disconnecting")
        window = self._client_window
        self._client_window = None
        if window is not None:
            window.deleteLater()
        self.show()
        self.raise_()
        self.activateWindow()
        self.disconnect_client()

    def _disconnected(self):
        self._logged_in = False
        self._pending.clear()
        self._buffer.clear()
        self._handled_rpc_ids.clear()
        self._server_session_id = None
        self._cached_menu_config = None
        if hasattr(self, '_module_requests'):
            self._module_requests.clear()
        self._close_client_window()
        if not self._closing_program:
            self.show()
        self.login_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.status.setText("Disconnected")
        self._log("TCP disconnected")

    def disconnect_client(self):
        self._close_client_window()
        if not self._closing_program:
            self.show()
        if self.sock.state() == QAbstractSocket.ConnectedState:
            if self._logged_in:
                self._send("logout")
            self.sock.disconnectFromHost()
        elif self.sock.state() != QAbstractSocket.UnconnectedState:
            self.sock.abort()
        self._logged_in = False
        self.login_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)

    def closeEvent(self, event):
        self._closing_program = True
        self._log("RPC Client GUI closed")
        self.disconnect_client()
        if self.sock.state() != QAbstractSocket.UnconnectedState:
            self.sock.waitForDisconnected(350)
            if self.sock.state() != QAbstractSocket.UnconnectedState:
                self.sock.abort()
        super().closeEvent(event)
        # quitOnLastWindowClosed(False) keeps the event loop alive during the
        # communication-window -> login-screen transition. File/Close must
        # explicitly exit it.
        QTimer.singleShot(0, QApplication.instance().quit)


def main():
    parser = argparse.ArgumentParser(description="PythonBDE JSON RPC Qt5 client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=43650)
    options = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # window switch must not kill Qt event loop
    window = RpcTestClient(options.host, options.port)
    window.show()
    code = app.exec_()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
