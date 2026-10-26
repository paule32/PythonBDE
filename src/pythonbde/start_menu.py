"""Ephemeral, validated Start-menu JSON exchanged after successful login.

Only UI descriptions are transferred, NEVER arbitrary commands or executable paths.
Each response is serialized to a short-lived private JSON file on the SERVER;
that file is read once, removed in finally, and never written on the client.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import tempfile

MAX_MENU_BYTES = 32 * 1024
MAX_NODES = 90
MAX_DEPTH = 4
ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")

# A functional approximation of the original Windows 95 Start menu.
# Server administrators can customize this Python template in a later release.
DEFAULT_MENU = [
    {"id": "programs", "label": "Programs", "icon": "programs", "children": [
        {"id": "accessories", "label": "Accessories", "icon": "folder", "children": [
            {"id": "notepad", "label": "Notepad", "icon": "document"},
            {"id": "calculator", "label": "Calculator", "icon": "program"},
        ]},
        {"id": "startup", "label": "StartUp", "icon": "folder", "children": [
            {"id": "startup-empty", "label": "(Empty)", "icon": "document", "disabled": True},
        ]},
        {"id": "msdos", "label": "MS-DOS Prompt", "icon": "console"},
        {"id": "explorer", "label": "Windows Explorer", "icon": "folder"},
    ]},
    {"id": "documents", "label": "Documents", "icon": "documents", "children": [
        {"id": "documents-empty", "label": "(No recent documents)", "icon": "document", "disabled": True},
    ]},
    {"id": "settings", "label": "Settings", "icon": "settings", "children": [
        {"id": "control-panel", "label": "Control Panel", "icon": "settings"},
        {"id": "printers", "label": "Printers", "icon": "program"},
    ]},
    {"id": "find", "label": "Find", "icon": "find", "children": [
        {"id": "find-files", "label": "Files or Folders...", "icon": "find"},
    ]},
    {"id": "help", "label": "Help", "icon": "help"},
    {"id": "run", "label": "Run...", "icon": "program"},
    {"id": "shutdown", "label": "Shut Down...", "icon": "shutdown", "separatorBefore": True},
]

ICONS = {"programs", "folder", "documents", "document", "settings", "find",
         "help", "shutdown", "program", "console"}


def validate_menu(items):
    """Validate untrusted server JSON before passing it to Qt widgets."""
    if not isinstance(items, list) or not items:
        raise ValueError("Start menu requires a nonempty list")
    visited = set()
    count = 0

    def walk(nodes, depth):
        nonlocal count
        if depth > MAX_DEPTH:
            raise ValueError("Start menu nesting too deep")
        if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
            raise ValueError("Invalid Start menu children")
        for item in nodes:
            count += 1
            if count > MAX_NODES or not isinstance(item, dict):
                raise ValueError("Invalid Start menu item")
            if set(item) - {"id", "label", "icon", "children", "disabled", "separatorBefore"}:
                raise ValueError("Unsupported Start menu item property")
            key = item.get("id")
            label = item.get("label")
            if not isinstance(key, str) or not ID_RE.fullmatch(key) or key in visited:
                raise ValueError("Invalid or duplicate Start menu item ID")
            if not isinstance(label, str) or not 1 <= len(label) <= 70 or any(ord(c) < 32 for c in label):
                raise ValueError("Invalid Start menu text")
            if item.get("icon", "program") not in ICONS:
                raise ValueError("Unsupported Start menu icon")
            if type(item.get("disabled", False)) is not bool or type(item.get("separatorBefore", False)) is not bool:
                raise ValueError("Invalid Start menu flag")
            visited.add(key)
            if "children" in item:
                walk(item["children"], depth + 1)

    walk(items, 1)
    if len(json.dumps(items, ensure_ascii=False).encode("utf-8")) > MAX_MENU_BYTES:
        raise ValueError("Start menu JSON too large")
    return items


def menu_payload(mode: str, session_id: str) -> dict:
    if mode not in ("win95", "winXP"):
        raise ValueError("Start menu is only available in a graphical session")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Missing server session ID")
    return {"event": "menu_config", "menuVersion": 1, "client": session_id,
            "systemMode": mode, "items": copy.deepcopy(validate_menu(DEFAULT_MENU))}


def _restrict_windows_acl(path: Path, *, directory: bool):
    """Fail-closed DACL: current Windows account + SYSTEM, protected inheritance.

    Uses Win32 APIs directly: no PowerShell/ICACLS subprocess and no broad
    Everyone/Users/Administrators ACE. Existing administrator backup privileges
    and the creating account's access are Windows security model properties.
    """
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("Advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("Kernel32", use_last_error=True)
    TOKEN_QUERY = 0x0008
    TOKEN_USER = 1
    DACL_SECURITY_INFORMATION = 4
    SD_REVISION = 1
    token = wintypes.HANDLE()
    adv.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    adv.OpenProcessToken.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.LocalFree.argtypes = (wintypes.HLOCAL,)
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        adv.GetTokenInformation.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
        adv.GetTokenInformation.restype = wintypes.BOOL
        size = wintypes.DWORD()
        adv.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, TOKEN_USER, buf, size.value, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]
        sid = ctypes.cast(buf, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents.Sid
        sid_string = wintypes.LPWSTR()
        adv.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            user_sid = sid_string.value
        finally:
            kernel.LocalFree(sid_string)
    finally:
        kernel.CloseHandle(token)

    inheritable = "OICI" if directory else ""
    sddl = f"D:P(A;{inheritable};FA;;;SY)(A;{inheritable};FA;;;{user_sid})"
    descriptor = ctypes.c_void_p()
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, SD_REVISION,
                                                                      ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        adv.SetFileSecurityW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
        adv.SetFileSecurityW.restype = wintypes.BOOL
        if not adv.SetFileSecurityW(str(path), DACL_SECURITY_INFORMATION, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def serialized_temporary_menu(mode: str, session_id: str, *, parent=None):
    """Return JSON-decoded payload, deleting temporary file/dir before return.

    Directory is access-controlled before sensitive files are created.
    Windows failure to apply DACL aborts the transfer rather than falling back
    to a world-readable temp file. POSIX uses directory 0700, file 0600.
    """
    import platform
    import shutil
    folder = Path(tempfile.mkdtemp(prefix="pythonbde_menu_", dir=parent))
    filename = folder / "start_menu.json"
    try:
        if platform.system() == "Windows":
            _restrict_windows_acl(folder, directory=True)
        else:
            folder.chmod(0o700)
        payload = menu_payload(mode, session_id)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_MENU_BYTES:
            raise ValueError("Start menu transfer too large")
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if platform.system() == "Windows":
                _restrict_windows_acl(filename, directory=False)
            with os.fdopen(fd, "wb") as f:
                fd = -1
                f.write(raw)
        finally:
            if fd >= 0:
                os.close(fd)
        with filename.open("rb") as f:
            return json.loads(f.read().decode("utf-8"))
    finally:
        try:
            filename.unlink(missing_ok=True)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
