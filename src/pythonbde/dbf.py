"""Kleiner dBASE-III-DBF-Store: Windows exklusiv, Linux advisory flock.

Achtung: DBF enthält Passworthashes, aber kein Dateiverschlüsselungsverfahren.
"""
from __future__ import annotations

import datetime as dt
import os
import struct
import stat
from pathlib import Path

from .platform_support import operating_system

FIELDS = [
    ("USERNAME", "C", 48),
    ("PWSALT", "C", 32), ("PWHASH", "C", 64), ("PBKDFITER", "N", 9),
    ("ADMIN", "L", 1), ("READ", "L", 1), ("WRITE", "L", 1),
    ("ANSICHT", "L", 1), ("MODIFY", "L", 1), ("LOCK", "L", 1),
    ("LOCKUSER", "L", 1), ("COUNTPASS", "N", 5), ("COUNTLIM", "N", 5),
    ("FAILS", "N", 5), ("LOCKUNTIL", "C", 20), ("EXPIRE", "C", 20),
    ("CREATED", "C", 20), ("UPDATED", "C", 20),
]
HEADER_LEN = 32 + 32 * len(FIELDS) + 1
RECORD_LEN = 1 + sum(width for _, _, width in FIELDS)
MAX_USERS = 10_000


def _exclusive_open(path: Path):
    """Windows: share mode 0; andere Prozesse dürfen nicht einmal READ öffnen."""
    if operating_system() == "Windows":
        import ctypes
        import msvcrt
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        h = k.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)  # GENERIC_READ|WRITE, share=0, OPEN_ALWAYS
        if h == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "DBF bereits geöffnet oder keine Berechtigung", str(path))
        try:
            fd = msvcrt.open_osfhandle(h, os.O_RDWR | os.O_BINARY)
            return os.fdopen(fd, "r+b", buffering=0)
        except BaseException:
            k.CloseHandle(h)
            raise
    # Linux: kooperatives flock; chmod schützt zusätzlich vor anderen UIDs.
    # Hinweis: Programme derselben UID können flock ignorieren. Es existiert
    # kein gleichwertiger obligatorischer CreateFileW-ShareMode=0 unter Linux.
    import fcntl
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Die Benutzer-DBF muss eine reguläre Datei sein")
        os.fchmod(fd, 0o600)  # Auch eine bereits vorhandene DBF einschränken.
        f = os.fdopen(fd, "r+b", buffering=0)
    except BaseException:
        os.close(fd)
        raise
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except BaseException:
        f.close()
        raise


def _encode_field(value, field_type: str, width: int) -> bytes:
    if field_type == "L":
        return b"T" if bool(value) else b"F"
    if field_type == "N":
        value = str(int(value or 0)).encode("ascii")
        if len(value) > width:
            raise ValueError("Numerischer DBF-Wert ist zu groß")
        return value.rjust(width, b" ")
    value = "" if value is None else str(value)
    data = value.encode("cp1252", errors="strict")
    if len(data) > width:
        raise ValueError("DBF-Feld zu lang")
    return data.ljust(width, b" ")


def _decode_field(raw: bytes, kind: str):
    if kind == "L":
        return raw.upper() in (b"T", b"Y")
    if kind == "N":
        return int(raw.strip() or b"0")
    return raw.rstrip(b" \0").decode("cp1252")


def make_dbf(users: dict[str, dict]) -> bytes:
    if len(users) > MAX_USERS:
        raise ValueError("Zu viele Benutzer")
    today = dt.date.today()
    head = bytearray(HEADER_LEN)
    head[0] = 0x03
    head[1:4] = bytes(((today.year - 1900) % 256, today.month, today.day))
    struct.pack_into("<IHH", head, 4, len(users), HEADER_LEN, RECORD_LEN)
    head[29] = 0x03  # Windows Latin-1/1252; Benutzernamen werden ASCII-validiert
    for i, (name, kind, width) in enumerate(FIELDS):
        pos = 32 + 32 * i
        head[pos:pos+11] = name.encode("ascii").ljust(11, b"\0")
        head[pos+11] = ord(kind)
        head[pos+16] = width
    head[-1] = 0x0d
    data = bytearray(head)
    for user in users.values():
        data.extend(b" ")
        for name, kind, width in FIELDS:
            data.extend(_encode_field(user.get(name), kind, width))
    data.append(0x1a)
    return bytes(data)


def parse_dbf(blob: bytes) -> dict[str, dict]:
    if len(blob) == 0:
        return {}
    if len(blob) < HEADER_LEN or blob[0] != 0x03:
        raise ValueError("Unbekanntes oder beschädigtes DBF-Format")
    count, head_len, record_len = struct.unpack_from("<IHH", blob, 4)
    if head_len != HEADER_LEN or record_len != RECORD_LEN or count > MAX_USERS:
        raise ValueError("Abweichendes DBF-Schema/Anzahl Datensätze")
    if blob[head_len-1] != 0x0d or len(blob) < head_len + count*record_len:
        raise ValueError("Beschädigter DBF-Header/abgeschnittene Datensätze")
    for i, (name, kind, width) in enumerate(FIELDS):
        field = blob[32+i*32:64+i*32]
        if field[:11].split(b"\0", 1)[0] != name.encode() or field[11] != ord(kind) or field[16] != width:
            raise ValueError(f"DBF-Schema stimmt bei {name} nicht überein")
    users = {}
    for n in range(count):
        offset = head_len + n*record_len
        record = blob[offset:offset+record_len]
        if record[0:1] != b" ":
            raise ValueError("Unerwarteter gelöschter/ungültiger DBF-Datensatz")
        pos = 1
        row = {}
        for name, kind, width in FIELDS:
            row[name] = _decode_field(record[pos:pos+width], kind)
            pos += width
        key = row["USERNAME"].casefold()
        if not key or key in users:
            raise ValueError("Ungültige oder doppelte Benutzernamen")
        users[key] = row
    return users


class DBFStore:
    def __init__(self, path: str | Path):
        self.path = Path(os.path.abspath(Path(path).expanduser()))  # Symlink NICHT auflösen: O_NOFOLLOW muss greifen
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = _exclusive_open(self.path)
        try:
            self.users = self._load()
            if self.file.seek(0, os.SEEK_END) == 0:
                self.flush()
        except BaseException:
            self.close()
            raise

    def _load(self):
        self.file.seek(0)
        return parse_dbf(self.file.read())

    def flush(self):
        blob = make_dbf(self.users)
        self.file.seek(0)
        self.file.write(blob)
        self.file.truncate(len(blob))
        self.file.flush()
        os.fsync(self.file.fileno())

    def change(self, callback):
        """Eine Änderung im RAM durchführen; bei Schreibfehler vorherigen Stand wiederherstellen."""
        import copy
        previous = copy.deepcopy(self.users)
        try:
            result = callback(self.users)
            self.flush()
            return result
        except BaseException:
            self.users = previous
            raise

    def close(self):
        if getattr(self, "file", None) and not self.file.closed:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
