"""Statusfarben für die Kontodetails im Qt5-User-Manager.

Plattformneutral und ohne Qt-Abhängigkeit, damit Windows und Linux dieselbe
Logik verwenden. Die Farbe ist eine *Anzeige*, keine Berechtigungsprüfung.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from .auth import parse_time

ADMIN_RED = "#D32F2F"
USER_GREEN = "#2E7D32"
LOCKED_YELLOW = "#FBC02D"
EMPTY_TRANSPARENT = "transparent"


def account_border(user: Mapping | None, *, now: datetime | None = None) -> tuple[str, str]:
    """Gibt (Rahmenfarbe, Status) zurück; eine Sperre hat immer Vorrang.

    LOCKUSER ist die manuelle Sperre. LOCKUNTIL kennzeichnet eine derzeit
    aktive automatische Sperre nach fehlgeschlagenen Logins. Ein abgelaufener
    LOCKUNTIL-Wert ist keine weiterhin bestehende Sperre. EXPIRE ist eine
    getrennte Gültigkeitsregel und wird hier nicht als 'Lock' dargestellt.
    """
    if user is None:
        return EMPTY_TRANSPARENT, "Kein Konto ausgewählt"
    if user.get("LOCKUSER"):
        return LOCKED_YELLOW, "Konto manuell gesperrt"
    lock_until = parse_time(user.get("LOCKUNTIL", ""))
    current = now if now is not None else datetime.now(timezone.utc)
    if lock_until is not None and lock_until.tzinfo is not None and current < lock_until:
        return LOCKED_YELLOW, "Konto vorübergehend gesperrt bis " + lock_until.astimezone().strftime("%d.%m.%Y %H:%M")
    if user.get("ADMIN"):
        return ADMIN_RED, "Administrator"
    return USER_GREEN, "Benutzer"
