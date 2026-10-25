"""OS-native PBKDF2-Backends mit identischem Hashformat für Windows und Linux.

Windows: Cryptography Next Generation, bcrypt.dll / BCryptDeriveKeyPBKDF2.
Linux:   hashlib.pbkdf2_hmac, aus OpenSSL bereitgestellt.

Passwörter werden nicht entschlüsselbar gespeichert; in der DBF liegen nur
Hex-Salz, Hex-Hash und Iterationszahl. Die DBF bleibt plattformübergreifend
kompatibel. Kein stiller Rückfall auf ein anderes Hashverfahren.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import secrets

from .platform_support import operating_system

ITERATIONS = 310_000  # Bestandsformat: für vorhandene DBFs unverändert
SALT_BYTES = 16
HASH_BYTES = 32
MIN_ITERATIONS = 10_000
MAX_ITERATIONS = 5_000_000


def _cng_pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    """Windows CNG / BCryptDeriveKeyPBKDF2; NTSTATUS != 0 ist ein harter Fehler."""
    from ctypes import wintypes

    bcrypt = ctypes.WinDLL("bcrypt.dll")
    handle_type = ctypes.c_void_p
    ulong = wintypes.ULONG
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = [
        ctypes.POINTER(handle_type), wintypes.LPCWSTR, wintypes.LPCWSTR, ulong
    ]
    bcrypt.BCryptOpenAlgorithmProvider.restype = ctypes.c_long
    bcrypt.BCryptCloseAlgorithmProvider.argtypes = [handle_type, ulong]
    bcrypt.BCryptCloseAlgorithmProvider.restype = ctypes.c_long
    bcrypt.BCryptDeriveKeyPBKDF2.argtypes = [
        handle_type, ctypes.c_void_p, ulong, ctypes.c_void_p, ulong,
        ctypes.c_ulonglong, ctypes.c_void_p, ulong, ulong
    ]
    bcrypt.BCryptDeriveKeyPBKDF2.restype = ctypes.c_long

    handle = handle_type()
    status = bcrypt.BCryptOpenAlgorithmProvider(
        ctypes.byref(handle), "SHA256", None, 0x00000008  # BCRYPT_ALG_HANDLE_HMAC_FLAG
    )
    if status != 0:
        raise OSError(f"BCryptOpenAlgorithmProvider: NTSTATUS 0x{status & 0xffffffff:08X}")
    password_buf = ctypes.create_string_buffer(password, len(password) + 1)
    salt_buf = ctypes.create_string_buffer(salt, len(salt) + 1)
    out = (ctypes.c_ubyte * HASH_BYTES)()
    try:
        status = bcrypt.BCryptDeriveKeyPBKDF2(
            handle, password_buf, len(password), salt_buf, len(salt),
            iterations, out, HASH_BYTES, 0
        )
        if status != 0:
            raise OSError(f"BCryptDeriveKeyPBKDF2: NTSTATUS 0x{status & 0xffffffff:08X}")
        return bytes(out)
    finally:
        ctypes.memset(password_buf, 0, ctypes.sizeof(password_buf))
        ctypes.memset(out, 0, ctypes.sizeof(out))
        bcrypt.BCryptCloseAlgorithmProvider(handle, 0)


def _openssl_pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    """Linux: CPython hashlib.pbkdf2_hmac verwendet die OpenSSL-Implementierung."""
    if not hasattr(hashlib, "pbkdf2_hmac"):
        raise RuntimeError("PBKDF2-HMAC benötigt eine Python-Version mit OpenSSL-Unterstützung")
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=HASH_BYTES)


def derive(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    if not isinstance(password, str) or not isinstance(iterations, int) or isinstance(iterations, bool):
        raise ValueError("Ungültige Passwort- oder Hashparameter")
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise ValueError("PBKDF2-Iterationszahl außerhalb des zulässigen Bereichs")
    if not isinstance(salt, bytes) or len(salt) != SALT_BYTES:
        raise ValueError("PBKDF2-Salz muss genau 16 Bytes lang sein")
    raw = password.encode("utf-8")
    system = operating_system()
    if system == "Windows":
        return _cng_pbkdf2(raw, salt, iterations)
    return _openssl_pbkdf2(raw, salt, iterations)


def hash_password(password: str) -> dict:
    if not isinstance(password, str) or not 8 <= len(password) <= 256:
        raise ValueError("Das Passwort muss 8 bis 256 Zeichen haben.")
    salt = secrets.token_bytes(SALT_BYTES)
    return {"PWSALT": salt.hex(), "PWHASH": derive(password, salt).hex(), "PBKDFITER": ITERATIONS}


def verify_password(password: str, user: dict) -> bool:
    if not isinstance(password, str):
        return False
    try:
        salt = bytes.fromhex(user["PWSALT"])
        digest = bytes.fromhex(user["PWHASH"])
        iterations = int(user["PBKDFITER"])
        if len(salt) != SALT_BYTES or len(digest) != HASH_BYTES:
            return False
        return hmac.compare_digest(derive(password, salt, iterations), digest)
    except (KeyError, ValueError, TypeError):
        return False
