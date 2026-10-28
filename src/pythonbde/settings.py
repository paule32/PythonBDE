"""Permanente Server-Einstellungen neben server.py / der gepackten EXE."""
from __future__ import annotations

from dataclasses import dataclass
import configparser
import ipaddress
import os
from pathlib import Path
import sys
import tempfile
import uuid

from .tls_security import DEFAULT_CERT, DEFAULT_KEY, DEFAULT_CA_CERT

DEFAULT_PORT = 43650
DISCOVERY_PORT = 43651


def application_dir() -> Path:
    # Bei PyInstaller steht sys.executable für die eigenständige Serverdatei.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return application_dir() / "pythonbde.ini"


@dataclass(frozen=True)
class Settings:
    server_id: str
    ip: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    nic: str = ""
    tls_enabled: bool = True
    tls_certificate: str = DEFAULT_CERT
    tls_private_key: str = DEFAULT_KEY
    tls_ca_certificate: str = DEFAULT_CA_CERT
    tls_ca_private_key: str = "certificates/ca.key"

    def validate(self):
        try:
            address = ipaddress.ip_address(self.ip)
            if address.version != 4:
                raise ValueError("Nur IPv4 wird momentan unterstützt")
        except ValueError as exc:
            raise ValueError("Ungültige IP-Adresse") from exc
        if not isinstance(self.port, int) or not 1024 <= self.port <= 65535:
            raise ValueError("Der TCP-Port muss zwischen 1024 und 65535 liegen")
        try:
            uuid.UUID(self.server_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("Ungültige Server-ID in der INI-Datei") from exc
        if len(self.nic) > 200:
            raise ValueError("Ungültige Netzwerkadapterkennung")
        if not isinstance(self.tls_enabled, bool):
            raise ValueError("TLS enabled muss bool sein")
        if self.tls_enabled and (not self.tls_certificate.strip() or not self.tls_private_key.strip()):
            raise ValueError("TLS benötigt Zertifikat und privaten Schlüssel")
        if not self.tls_enabled and self.ip != "127.0.0.1":
            raise ValueError("Ohne TLS darf der Server nur 127.0.0.1 verwenden")
        return self


def load_settings(path: Path | None = None) -> Settings:
    path = Path(path) if path is not None else config_path()
    ini = configparser.ConfigParser(interpolation=None)
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            ini.read_file(file)
    data = ini["Server"] if ini.has_section("Server") else {}
    settings = Settings(
        server_id=data.get("id") or str(uuid.uuid4()),
        ip=data.get("ip", "127.0.0.1"),
        port=int(data.get("port", DEFAULT_PORT)),
        nic=data.get("nic", ""),
        tls_enabled=ini.getboolean("TLS", "enabled", fallback=True),
        tls_certificate=ini.get("TLS", "certificate", fallback=DEFAULT_CERT),
        tls_private_key=ini.get("TLS", "private_key", fallback=DEFAULT_KEY),
        tls_ca_certificate=ini.get("TLS", "ca_certificate", fallback=DEFAULT_CA_CERT),
        tls_ca_private_key=ini.get("TLS", "ca_private_key", fallback="certificates/ca.key"),
    ).validate()
    # Neue ID beim ersten Start dauerhaft sichern, nie bei normalem Neustart ändern.
    if not path.exists() or not data.get("id"):
        save_settings(settings, path)
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    settings.validate()
    path = Path(path) if path is not None else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ini = configparser.ConfigParser(interpolation=None)
    ini["Server"] = {"id": settings.server_id, "ip": settings.ip,
                     "port": str(settings.port), "nic": settings.nic}
    ini["TLS"] = {"enabled": str(settings.tls_enabled).lower(),
                  "certificate": settings.tls_certificate,
                  "private_key": settings.tls_private_key,
                  "ca_certificate": settings.tls_ca_certificate,
                  "ca_private_key": settings.tls_ca_private_key}
    # Tempdatei in demselben Verzeichnis + atomare Ersetzung.
    fd, tmp = tempfile.mkstemp(prefix=".pythonbde-", suffix=".tmp", dir=str(path.parent))
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            ini.write(file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
