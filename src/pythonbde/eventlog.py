"""GUI- und Datei-Log: eine Quelle, mehrere Qt-Ansichten.

Dateilog chronologisch (zum Live-Tailing), GUI neueste Zeile zuerst.
Keine Passwörter oder Stacktraces in Protokollmeldungen aufnehmen.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import threading

MAX_UI_LINES = 500
MAX_LOG_BYTES = 5 * 1024 * 1024


def format_entry(code: int, message: str, *, at: datetime | None = None) -> str:
    if not 100 <= int(code) <= 599:
        raise ValueError('Ungültiger Statuscode')
    now = at or datetime.now().astimezone()
    clean = ' '.join(str(message).replace('\x00', '').split())[:600]
    return f'{now:%Y-%m-%d} {now:%H:%M:%S} | {int(code)} | {clean}'


class EventLog:
    """Thread-sicherer Datei-Log; Qt-Signal-Bridge wird vom GUI-Thread aufgerufen."""

    def __init__(self, dbf_path, *, max_bytes=MAX_LOG_BYTES):
        self.path = Path(dbf_path).absolute().parent / 'python_bde.log'
        self.max_bytes = max_bytes
        self.entries: list[str] = []
        self.callbacks = []
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, code: int, message: str) -> str:
        line = format_entry(code, message)
        with self._lock:
            # 500 Einträge => bereinigen und mit der jüngsten Meldung neu beginnen.
            if len(self.entries) >= MAX_UI_LINES:
                self.entries.clear()
            self.entries.insert(0, line)
            data = (line + '\n').encode('utf-8', errors='replace')
            # Nicht sperren; andere Programme dürfen die Log-Datei lesen.
            if not self.path.exists():
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, 'ab') as stream:
                    stream.write(data)
            else:
                with self.path.open('ab') as stream:
                    stream.write(data)
            # Nur seltene Rotation: den ältesten Teil abschneiden, ganze Zeilen behalten.
            if self.path.stat().st_size > self.max_bytes:
                with self.path.open('rb') as stream:
                    stream.seek(-self.max_bytes, os.SEEK_END)
                    tail = stream.read()
                boundary = tail.find(b'\n')
                tail = tail[boundary + 1:] if boundary >= 0 else b''
                with self.path.open('wb') as stream:
                    stream.write(tail)
            for callback in tuple(self.callbacks):
                callback(line)
        return line

    def clear_view(self):
        """Nur GUI-Puffer löschen, nicht die persistente Audit-Historie."""
        with self._lock:
            self.entries.clear()

    def export_view(self, destination):
        Path(destination).write_text('\n'.join(self.entries) + ('\n' if self.entries else ''), encoding='utf-8')
