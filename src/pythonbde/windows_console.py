"""Best-effort early hiding of a *private* console for .pyw entry points.

Do not hide an existing command prompt: only hide when GetConsoleProcessList
returns this Python process alone. Using pythonw.exe remains preferred.
"""
from __future__ import annotations

import os


def hide_private_console() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetConsoleWindow.argtypes = ()
        kernel.GetConsoleWindow.restype = wintypes.HWND
        kernel.GetConsoleProcessList.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)
        kernel.GetConsoleProcessList.restype = wintypes.DWORD
        console = kernel.GetConsoleWindow()
        if not console:
            return False
        pids = (wintypes.DWORD * 2)()
        count = kernel.GetConsoleProcessList(pids, 2)
        if count != 1 or pids[0] != os.getpid():
            return False
        kernel.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        kernel.ShowWindow.restype = wintypes.BOOL
        kernel.ShowWindow(console, 0)  # SW_HIDE; private console only
        return True
    except (OSError, AttributeError, ValueError):
        return False
