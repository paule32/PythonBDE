"""Early GUI exception reporting for pythonw.exe, Windows and Linux.

No Qt import at module import time: call install_exception_handler() before
importing PyQt5 or constructing QApplication. If Qt is absent/unusable under
Windows, show an actual native Win32 multiline EDIT window (not only a
MessageBox), including the complete traceback.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path

_LOG_LOCK = threading.RLock()
_DIALOG_LOCK = threading.Lock()
_INSTALLED = False
_APP_NAME = "PythonBDE"
_LOG_PATH = None
_ORIGINAL_STDERR = None
_ORIGINAL_EXCEP = None
_ORIGINAL_THREAD_EXCEP = None
_ORIGINAL_UNRAISABLE = None


def _default_log_path() -> Path:
    """Writable by the current user, even for installed/read-only software."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        xdg = os.environ.get("XDG_STATE_HOME", "")
        root = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local" / "state"
    return root / "PythonBDE" / "pythonbde_errors.log"


def log_path() -> Path:
    return Path(_LOG_PATH) if _LOG_PATH is not None else _default_log_path()


def append_error_log(text: str) -> Path | None:
    """Append with a temporary-directory fallback; never trigger recursion."""
    entry = str(text).replace("\r\n", "\n").replace("\r", "\n")
    with _LOG_LOCK:
        for target in (log_path(), Path(tempfile.gettempdir()) / "pythonbde_errors.log"):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Keep the extra diagnostic log bounded (the old part remains
                # available as .old until the next rotation).
                if target.exists() and target.stat().st_size >= 5 * 1024 * 1024:
                    target.replace(target.with_suffix(".log.old"))
                with target.open("a", encoding="utf-8", errors="replace") as handle:
                    handle.write(entry)
                    if not entry.endswith("\n"):
                        handle.write("\n")
                return target
            except (OSError, ValueError):
                continue
    return None


class _StderrToFile:
    """Keep third-party stderr output even with pythonw.exe (stderr=None)."""

    def __init__(self, original):
        self.original = original
        self.encoding = "utf-8"
        self.errors = "replace"
        self._partial = ""
        self._lock = threading.RLock()

    def write(self, text):
        text = str(text)
        if text:
            with self._lock:
                pending = (self._partial + text).replace("\r\n", "\n")
                lines = pending.split("\n")
                self._partial = lines.pop()
                for line in lines:
                    append_error_log(line + "\n")
                # Avoid unbounded buffering if stderr never writes a newline.
                if len(self._partial) > 8192:
                    append_error_log(self._partial)
                    self._partial = ""
                if self.original is not None:
                    try:
                        self.original.write(text)
                    except (OSError, ValueError):
                        pass
        return len(text)

    def flush(self):
        with self._lock:
            if self._partial:
                append_error_log(self._partial)
                self._partial = ""
            if self.original is not None:
                try:
                    self.original.flush()
                except (OSError, ValueError):
                    pass

    def isatty(self):
        return bool(self.original and getattr(self.original, "isatty", lambda: False)())

    def writable(self):
        return True


def _qt_trace_dialog(title: str, details: str, path: Path | None) -> bool:
    """Use Qt only on its GUI thread, *after* QApplication exists."""
    try:
        from PyQt5.QtCore import QThread, Qt
        from PyQt5.QtWidgets import (
            QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
            QPlainTextEdit, QPushButton, QVBoxLayout,
        )
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            return False

        dlg = QDialog(app.activeWindow())
        dlg.setWindowTitle(f"{_APP_NAME} – Fehler / Traceback")
        dlg.resize(900, 560)
        layout = QVBoxLayout(dlg)
        description = QLabel(title)
        description.setWordWrap(True)
        layout.addWidget(description)
        edit = QPlainTextEdit(dlg)
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        edit.setPlainText(details)
        layout.addWidget(edit, 1)
        if path is not None:
            location = QLabel(f"Fehlerprotokoll: {path}")
            location.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(location)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
        copy_button = QPushButton("Copy Traceback", dlg)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(details))
        buttons.addButton(copy_button, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec_()
        return True
    except Exception:
        # QApplication or Qt widget creation might be the actual failure.
        return False


def _win32_trace_editor(title: str, details: str) -> bool:
    """Native Win32 read-only EDIT window. No QApplication / Qt dependency.

    Has its own message loop, scrollbars and Copy/Close buttons. If Win32
    GUI creation fails, uses MessageBoxW as last-ditch fallback.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LONG_PTR = ctypes.c_ssize_t
        LRESULT = LONG_PTR
        HWND = wintypes.HWND
        WPARAM = wintypes.WPARAM
        LPARAM = wintypes.LPARAM
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, WPARAM, LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", HWND), ("message", wintypes.UINT),
                ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT),
            ]

        # Explicit return/argument types are essential on 64-bit Windows.
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = HWND
        user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.MoveWindow.argtypes = [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        user32.SendMessageW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.SendMessageW.restype = LRESULT
        user32.DestroyWindow.argtypes = [HWND]
        user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
        user32.UpdateWindow.argtypes = [HWND]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.SetWindowTextW.argtypes = [HWND, wintypes.LPCWSTR]
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        WS_OVERLAPPEDWINDOW = 0x00CF0000
        WS_CHILD = 0x40000000
        WS_VISIBLE = 0x10000000
        WS_VSCROLL = 0x00200000
        WS_HSCROLL = 0x00100000
        WS_TABSTOP = 0x00010000
        ES_MULTILINE = 0x0004
        ES_AUTOVSCROLL = 0x0040
        ES_AUTOHSCROLL = 0x0080
        ES_READONLY = 0x0800
        WS_EX_CLIENTEDGE = 0x00000200
        WM_SIZE, WM_COMMAND, WM_CLOSE, WM_DESTROY = 5, 0x0111, 0x0010, 2
        WM_SETFONT = 0x0030
        EM_SETSEL = 0x00B1
        EM_LIMITTEXT = 0x00C5
        WM_COPY = 0x0301
        SW_SHOW = 5
        BUTTON_COPY, BUTTON_CLOSE = 1001, 1002
        hinstance = kernel32.GetModuleHandleW(None)
        control = {"edit": None, "copy": None, "close": None}
        native_text = details.replace("\r\n", "\n").replace("\n", "\r\n")
        # Windows EDIT's historical text limit: still show a useful portion.
        native_text = native_text[-500_000:]
        title_text = title[:200]
        class_name = f"PythonBDE_Trace_{os.getpid()}_{threading.get_ident()}"
        destroyed = {"done": False}

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_SIZE:
                width, height = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
                if control["edit"]:
                    user32.MoveWindow(control["edit"], 10, 10, max(1, width - 20), max(1, height - 58), True)
                    user32.MoveWindow(control["copy"], max(10, width - 222), max(0, height - 39), 102, 29, True)
                    user32.MoveWindow(control["close"], max(10, width - 112), max(0, height - 39), 102, 29, True)
                return 0
            if msg == WM_COMMAND:
                command = int(wparam) & 0xFFFF
                if command == BUTTON_COPY and control["edit"]:
                    user32.SendMessageW(control["edit"], EM_SETSEL, 0, -1)
                    user32.SendMessageW(control["edit"], WM_COPY, 0, 0)
                    return 0
                if command == BUTTON_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                destroyed["done"] = True
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        callback = WNDPROC(wndproc)  # Hold the callback for the entire message loop.
        klass = WNDCLASSW()
        klass.lpfnWndProc = callback
        klass.hInstance = hinstance
        klass.lpszClassName = class_name
        klass.hbrBackground = wintypes.HBRUSH(6)  # COLOR_WINDOW + 1
        if not user32.RegisterClassW(ctypes.byref(klass)):
            raise OSError("RegisterClassW failed")
        try:
            window = user32.CreateWindowExW(
                0, class_name, f"{_APP_NAME} – Fehler: {title_text}",
                WS_VISIBLE | WS_OVERLAPPEDWINDOW,
                100, 100, 930, 620, None, None, hinstance, None,
            )
            if not window:
                raise OSError("CreateWindowExW failed")
            control["edit"] = user32.CreateWindowExW(
                WS_EX_CLIENTEDGE, "EDIT", "",
                WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_HSCROLL |
                ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | ES_AUTOHSCROLL,
                10, 10, 890, 535, window, None, hinstance, None,
            )
            control["copy"] = user32.CreateWindowExW(
                0, "BUTTON", "Copy Traceback",
                WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                688, 545, 110, 29, window, wintypes.HMENU(BUTTON_COPY), hinstance, None,
            )
            control["close"] = user32.CreateWindowExW(
                0, "BUTTON", "Close",
                WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                806, 545, 104, 29, window, wintypes.HMENU(BUTTON_CLOSE), hinstance, None,
            )
            if not all(control.values()):
                user32.DestroyWindow(window)
                raise OSError("Failed to create native edit/buttons")
            # Raise the edit control's text limit before assigning the traceback.
            user32.SendMessageW(control["edit"], EM_LIMITTEXT, 600000, 0)
            user32.SetWindowTextW(control["edit"], native_text)
            # Fixed-pitch font to keep tracebacks readable.
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            gdi32.GetStockObject.argtypes = [ctypes.c_int]
            gdi32.GetStockObject.restype = wintypes.HANDLE
            stock_font = gdi32.GetStockObject(10)  # OEM_FIXED_FONT
            if stock_font:
                user32.SendMessageW(control["edit"], WM_SETFONT, stock_font, 1)
            user32.ShowWindow(window, SW_SHOW)
            user32.UpdateWindow(window)
            msg = MSG()
            while not destroyed["done"]:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            return True
        finally:
            user32.UnregisterClassW(class_name, hinstance)
    except Exception:
        return _win32_messagebox(title, details)


def _win32_messagebox(title: str, details: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, str(details)[-3900:], f"{_APP_NAME} – {title}", 0x10 | 0x00010000
        )
        return True
    except Exception:
        return False


def show_traceback(title: str, details: str, *, save: bool = True) -> Path | None:
    """Present traceback in Qt, native Win32 EDIT, or stderr as last resort."""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    report = f"{stamp} | {_APP_NAME} | {title}\n{details.rstrip()}\n"
    saved = append_error_log(report) if save else log_path()
    # Never recurse when the error UI itself raises an exception.
    if not _DIALOG_LOCK.acquire(blocking=False):
        return saved
    try:
        if _qt_trace_dialog(title, report, saved):
            return saved
        if _win32_trace_editor(title, report):
            return saved
        if _ORIGINAL_STDERR is not None:
            try:
                _ORIGINAL_STDERR.write(report + "\n")
                _ORIGINAL_STDERR.flush()
            except Exception:
                pass
    finally:
        _DIALOG_LOCK.release()
    return saved


def report_exception(exc_type, exc_value, exc_traceback, *, title="Unbehandelte Ausnahme"):
    """Format the original Python traceback and display it once."""
    if exc_type in (KeyboardInterrupt, SystemExit):
        return None
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    return show_traceback(title, details)


def _main_hook(exc_type, exc_value, exc_traceback):
    report_exception(exc_type, exc_value, exc_traceback)


def _thread_hook(args):
    report_exception(args.exc_type, args.exc_value, args.exc_traceback,
                     title=f"Hintergrundthread: {getattr(args.thread, 'name', '?')}")


def _unraisable_hook(args):
    try:
        report_exception(args.exc_type, args.exc_value, args.exc_traceback,
                         title=f"Unraisable exception: {getattr(args, 'err_msg', '') or ''}")
    except Exception:
        pass


def install_exception_handler(*, app_name="PythonBDE", error_log=None, redirect_stderr=True):
    """Install early in both entry points, before Qt imports or QApplication."""
    global _INSTALLED, _APP_NAME, _LOG_PATH, _ORIGINAL_STDERR
    global _ORIGINAL_EXCEP, _ORIGINAL_THREAD_EXCEP, _ORIGINAL_UNRAISABLE
    _APP_NAME = str(app_name)
    if error_log is not None:
        _LOG_PATH = Path(error_log)
    if _INSTALLED:
        return
    _INSTALLED = True
    _ORIGINAL_STDERR = sys.stderr
    _ORIGINAL_EXCEP = sys.excepthook
    sys.excepthook = _main_hook
    if hasattr(threading, "excepthook"):
        _ORIGINAL_THREAD_EXCEP = threading.excepthook
        threading.excepthook = _thread_hook
    if hasattr(sys, "unraisablehook"):
        _ORIGINAL_UNRAISABLE = sys.unraisablehook
        sys.unraisablehook = _unraisable_hook
    if redirect_stderr:
        sys.stderr = _StderrToFile(sys.stderr)
