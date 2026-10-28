"""Start Windows console utilities invisibly from pythonw.exe / a Qt GUI.

A GUI application must not briefly create a console for compiler probes,
MinGW builds or Windows ``icacls`` calls. On Linux do not pass Windows-only
Popen flags. For a GUI-subsystem EXE use ``gui_executable=True``: only set
CREATE_NO_WINDOW and do not impose SW_HIDE on its first ShowWindow call,
otherwise the independent crash-dialog window could be suppressed.
"""
from __future__ import annotations

import os
import subprocess


def hidden_process_kwargs(*, gui_executable: bool = False) -> dict:
    if os.name != "nt":
        return {}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW}
    if not gui_executable:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE for CLI utilities only
        options["startupinfo"] = startupinfo
    return options
