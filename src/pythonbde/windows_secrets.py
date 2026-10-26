"""Windows-only DPAPI at-rest protection and RSA-OAEP credential envelopes.

Notes:
* DPAPI protects the private key on its SERVER machine (current user).
* RSA-OAEP transfers a password encrypted to that server public key.
* TOFU fingerprint pinning on the client protects future connections, but a
  first connection MUST be verified out of band for strong MITM protection.
* This is NOT a substitute for authenticated TLS for the rest of JSONL traffic.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import secrets

ENVELOPE_ALGORITHM = 'RSA-OAEP-SHA256+AES-256-GCM'
MAX_SECRET_LENGTH = 8192


def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError as exc:
        raise RuntimeError('Für Windows Secrets ist das Paket cryptography erforderlich') from exc
    return hashes, serialization, padding, rsa, AESGCM


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if platform.system() != 'Windows':
        raise OSError('Windows DPAPI ist nur unter Windows verfügbar')

    class BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = BLOB(len(data), buffer)
    destination = BLOB()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    if decrypt:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
        args = [ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(destination)]
    else:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(BLOB), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
        args = [ctypes.byref(source), 'PythonBDE RPC Server', None, None, None, 0x1, ctypes.byref(destination)]
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(destination.pbData, ctypes.c_void_p))


def _fingerprint(public_pem: bytes) -> str:
    return hashlib.sha256(public_pem).hexdigest()


class ServerSecrets:
    """Single current-user DPAPI-protected RSA keypair for this installation."""

    def __init__(self, dbf_path: str | Path):
        if platform.system() != 'Windows':
            raise OSError('Windows Secrets Server benötigt Windows')
        hashes, serialization, padding, rsa, AESGCM = _crypto()
        self.path = Path(dbf_path).resolve().with_name('rpc_server_key.dpapi')
        if self.path.exists():
            raw_key = _dpapi(self.path.read_bytes(), decrypt=True)
            self.private_key = serialization.load_pem_private_key(raw_key, password=None)
        else:
            self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            raw_key = self.private_key.private_bytes(serialization.Encoding.PEM,
                                                     serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption())
            ciphertext = _dpapi(raw_key)
            # Exclusive creation: no accidental overwrite of an existing identity.
            with self.path.open('xb') as outfile:
                outfile.write(ciphertext)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        self.public_pem = self.private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.fingerprint = _fingerprint(self.public_pem)

    def hello_fields(self):
        return {'passwordTransport': ENVELOPE_ALGORITHM,
                'serverPublicKey': base64.b64encode(self.public_pem).decode('ascii'),
                'serverFingerprint': self.fingerprint}

    def decrypt_envelope(self, envelope: dict, expected_nonce: str) -> str:
        hashes, _, padding, _, AESGCM = _crypto()
        if not expected_nonce or not isinstance(envelope, dict):
            raise ValueError('Ungültige Windows-Secrets-Anmeldung')
        if envelope.get('alg') != ENVELOPE_ALGORITHM or envelope.get('serverFingerprint') != self.fingerprint:
            raise ValueError('Unbekannter Passwort-Transport')
        encoded = envelope.get('ciphertext', '')
        if not isinstance(encoded, str) or len(encoded) > MAX_SECRET_LENGTH:
            raise ValueError('Ungültige Passwortdaten')
        try:
            value = base64.b64decode(encoded, validate=True)
            wrapped_key = base64.b64decode(envelope.get('wrappedKey', ''), validate=True)
            iv = base64.b64decode(envelope.get('iv', ''), validate=True)
            aes_key = self.private_key.decrypt(wrapped_key, padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            raw = AESGCM(aes_key).decrypt(iv, value, expected_nonce.encode('ascii'))
            secret = json.loads(raw.decode('utf-8'))
            if not isinstance(secret, dict) or not hmac.compare_digest(str(secret.get('nonce', '')), expected_nonce):
                raise ValueError('Ungültige Client-Challenge')
            password = secret.get('password')
            if not isinstance(password, str) or len(password) > 256:
                raise ValueError('Ungültige Passwortdaten')
            return password
        except (ValueError, UnicodeError, TypeError, KeyError) as exc:
            raise ValueError('Passwortentschlüsselung fehlgeschlagen') from exc
        except Exception as exc:
            raise ValueError('Passwortentschlüsselung fehlgeschlagen') from exc


def encrypt_password(public_key_b64: str, fingerprint: str, nonce: str, password: str) -> dict:
    hashes, serialization, padding, _, AESGCM = _crypto()
    if not isinstance(password, str) or len(password) > 256 or not nonce:
        raise ValueError('Ungültige Passwortdaten')
    pem = base64.b64decode(public_key_b64, validate=True)
    if not hmac.compare_digest(_fingerprint(pem), fingerprint):
        raise ValueError('Server-Schlüssel Fingerprint stimmt nicht überein')
    key = serialization.load_pem_public_key(pem)
    raw = json.dumps({'nonce': nonce, 'password': password}, ensure_ascii=False,
                     separators=(',', ':')).encode('utf-8')
    aes_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(aes_key).encrypt(iv, raw, nonce.encode('ascii'))
    wrapped_key = key.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                 algorithm=hashes.SHA256(), label=None))
    return {'alg': ENVELOPE_ALGORITHM,
            'serverFingerprint': fingerprint,
            'wrappedKey': base64.b64encode(wrapped_key).decode('ascii'),
            'iv': base64.b64encode(iv).decode('ascii'),
            'ciphertext': base64.b64encode(ciphertext).decode('ascii')}


def trust_store_path() -> Path:
    base = Path(os.environ.get('APPDATA') or (Path.home() / '.config'))
    return base / 'PythonBDE' / 'trusted_rpc_servers.json'


def trusted_fingerprint(server: str, path: Path | None = None) -> str | None:
    location = Path(path) if path is not None else trust_store_path()
    if not location.is_file():
        return None
    data = json.loads(location.read_text('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Ungültige Server-Vertrauensdaten')
    return data.get(server)


def save_trusted_fingerprint(server: str, fingerprint: str, path: Path | None = None):
    location = Path(path) if path is not None else trust_store_path()
    location.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = json.loads(location.read_text('utf-8')) if location.exists() else {}
    data[server] = fingerprint
    temp = location.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temp, location)
    try:
        location.chmod(0o600)
    except OSError:
        pass


def make_nonce():
    return secrets.token_urlsafe(24)
