"""Zentrale Betriebssystem-Auswahl für eine gemeinsame Windows-/Linux-Codebasis."""
from __future__ import annotations

import os
import platform
from pathlib import Path

SUPPORTED_SYSTEMS = ("Windows", "Linux")


def operating_system() -> str:
    """Explizit unterstützt: Windows und Linux; unbekannte Systeme nicht still emulieren."""
    system = platform.system()
    if system not in SUPPORTED_SYSTEMS:
        raise RuntimeError(f"PythonBDE unterstützt derzeit Windows und Linux, nicht {system!r}.")
    return system


def default_dbf_path() -> Path:
    """Pro Benutzer nutzbarer OS-Standardpfad; Konfiguration --dbf bleibt möglich."""
    system = operating_system()
    if system == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", "")
        root = Path(xdg_data) if xdg_data and Path(xdg_data).is_absolute() else Path.home() / ".local" / "share"
    return root / "PythonBDE" / "users.dbf"


def password_backend() -> str:
    return "Windows CNG / BCrypt (PBKDF2-HMAC-SHA256)" if operating_system() == "Windows" else "OpenSSL via hashlib.pbkdf2_hmac (PBKDF2-HMAC-SHA256)"


def file_lock_backend() -> str:
    return "CreateFileW (ShareMode=0)" if operating_system() == "Windows" else "fcntl.flock (advisory) + Unix-Rechte 0600"
