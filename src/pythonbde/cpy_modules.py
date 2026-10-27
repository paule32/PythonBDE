"""Trusted PythonBDE .cpy modules: signed, compiled Python for Qt MDI clients.

A .cpy is a ZIP package containing manifest.json and module.pyc. It is signed
using Ed25519; clients MUST preinstall the trusted public key out of band.
Untrusted .cpy files are never unmarshalled, imported or executed.

IMPORTANT: authentication of origin is NOT a sandbox. A signed module executes
with all rights of the client Python process. Provision signing keys carefully.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import platform
import re
import sys
import types
import zipfile

MAX_CPY_BYTES = 32 * 1024
# Bytecode is more compressible than source; retain a distinct size limit
# for uncompressed ZIP members (never trust the compressed size alone).
MAX_CPY_MEMBER_BYTES = 128 * 1024
MAX_CPY_EVENT_BYTES = 60 * 1024
MODULE_TITLES = {
    'notepad': 'Notepad', 'wordpad': 'WordPad', 'calculator': 'Calculator',
    'msdos': 'MS-DOS Prompt', 'explorer': 'Windows Explorer',
    'control-panel': 'Control Panel', 'printers': 'Printers',
    'find-files': 'Find Files', 'help': 'Help',
    'run': 'Run', 'shutdown': 'Shut Down',
}
MODULE_FILES = {key: ('notepad.py' if key == 'notepad' else
                      'calculator.py' if key == 'calculator' else
                      'wordpad.py' if key == 'wordpad' else 'placeholder.py')
                for key in MODULE_TITLES}
MODULE_IDS = frozenset(MODULE_FILES)
ID_RE = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')


def _ed25519():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def _public_bytes(key):
    serialization, _, _ = _ed25519()
    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)


class ModuleSigner:
    """Persistent signing key on the server; DPAPI encrypted on Windows."""

    def __init__(self, dbf_path):
        serialization, Ed25519PrivateKey, _ = _ed25519()
        folder = Path(dbf_path).resolve().parent
        self.private_path = folder / 'module_signing_private.key'
        self.public_path = folder / 'module_signing_public.pem'
        if self.private_path.exists():
            raw = self.private_path.read_bytes()
            if platform.system() == 'Windows':
                from .windows_secrets import _dpapi
                raw = _dpapi(raw, decrypt=True)
            self.private_key = serialization.load_der_private_key(raw, password=None)
            if not isinstance(self.private_key, Ed25519PrivateKey):
                raise ValueError('Unsupported module signing private key')
        else:
            self.private_key = Ed25519PrivateKey.generate()
            raw = self.private_key.private_bytes(serialization.Encoding.DER,
                                                 serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption())
            if platform.system() == 'Windows':
                from .windows_secrets import _dpapi
                raw = _dpapi(raw)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
            handle = os.open(self.private_path, flags, 0o600)
            try:
                if platform.system() == 'Windows':
                    from .start_menu import _restrict_windows_acl
                    _restrict_windows_acl(self.private_path, directory=False)
                with os.fdopen(handle, 'wb') as fp:
                    handle = -1
                    fp.write(raw)
            except BaseException:
                # An ACL failure must not leave an empty, unusable identity.
                if handle != -1:
                    os.close(handle)
                    handle = -1
                self.private_path.unlink(missing_ok=True)
                raise
            finally:
                if handle != -1:
                    os.close(handle)
            if platform.system() != 'Windows':
                self.private_path.chmod(0o600)
        self.public_pem = _public_bytes(self.private_key)
        self.key_id = hashlib.sha256(self.public_pem).hexdigest()
        if self.public_path.exists():
            if self.public_path.read_bytes() != self.public_pem:
                raise ValueError('Module signing public key mismatch')
        else:
            self.public_path.write_bytes(self.public_pem)

    def event(self, module_id: str, session_id: str, request_id: str) -> dict:
        if module_id not in MODULE_IDS or not isinstance(session_id, str):
            raise ValueError('Unknown remote module')
        content = compiled_module_package(module_id)
        if len(content) > MAX_CPY_BYTES:
            raise ValueError('Compiled module exceeds allowed size')
        packet = {
            'event': 'module_package', 'format': 'pythonbde-cpy/1',
            'client': session_id, 'requestId': request_id, 'moduleId': module_id,
            'sha256': hashlib.sha256(content).hexdigest(),
            'keyId': self.key_id,
            'signature': base64.b64encode(self.private_key.sign(
                _signature_input(module_id, session_id, request_id, content))).decode('ascii'),
            'cpy': base64.b64encode(content).decode('ascii'),
        }
        if len(json.dumps(packet, separators=(',', ':')).encode('utf-8')) > MAX_CPY_EVENT_BYTES:
            raise ValueError('Compiled module exceeds protocol size limit')
        return packet


def _signature_input(module_id, session_id, request_id, content):
    """Bind signature to the intended module and single request/session."""
    context = json.dumps({'moduleId': module_id, 'client': session_id,
                          'requestId': request_id},
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    return b'PythonBDE-CPY-1\0' + context + b'\0' + content


def compiled_module_package(module_id: str) -> bytes:
    if module_id not in MODULE_FILES:
        raise ValueError('Not a published PythonBDE module')
    source_path = Path(__file__).with_name('remote_apps') / MODULE_FILES[module_id]
    source = source_path.read_text('utf-8')
    if MODULE_FILES[module_id] == 'placeholder.py':
        source = 'MODULE_TITLE = ' + repr(MODULE_TITLES[module_id]) + '\n' + source
    code = compile(source, f'<pythonbde:{module_id}>', 'exec', dont_inherit=True)
    # Supported only when client and server use the same CPython minor ABI.
    pyc = importlib.util.MAGIC_NUMBER + (b'\0' * 12) + marshal.dumps(code)
    manifest = {'format': 'pythonbde-cpy/1', 'id': module_id,
                'title': MODULE_TITLES[module_id],
                'pythonTag': sys.implementation.cache_tag, 'entrypoint': 'create_widget'}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, separators=(',', ':'), ensure_ascii=False))
        archive.writestr('module.pyc', pyc)
    return buf.getvalue()


def verify_and_load(event: dict, public_key_path) -> tuple[dict, types.ModuleType]:
    """Check publisher pin + signature + format BEFORE decoding executable bytecode."""
    serialization, _, Ed25519PublicKey = _ed25519()
    if (not isinstance(event, dict) or event.get('event') != 'module_package' or
            event.get('format') != 'pythonbde-cpy/1' or event.get('moduleId') not in MODULE_IDS):
        raise ValueError('Unsupported module transfer')
    pinned_pem = Path(public_key_path).read_bytes()  # Fails closed without explicit pin
    if hashlib.sha256(pinned_pem).hexdigest() != event.get('keyId'):
        raise ValueError('Untrusted module signing key')
    public_key = serialization.load_pem_public_key(pinned_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError('Module publisher key is not Ed25519')
    encoded = event.get('cpy')
    if not isinstance(encoded, str) or len(encoded) > (MAX_CPY_BYTES * 4 // 3 + 16):
        raise ValueError('Module transfer exceeds size limit')
    try:
        package = base64.b64decode(encoded, validate=True)
        signature = base64.b64decode(event['signature'], validate=True)
    except (ValueError, KeyError) as exc:
        raise ValueError('Corrupt module transport') from exc
    if len(package) > MAX_CPY_BYTES or hashlib.sha256(package).hexdigest() != event.get('sha256'):
        raise ValueError('Corrupt module digest')
    try:
        public_key.verify(signature, _signature_input(
            event['moduleId'], event.get('client'), event.get('requestId'), package))
    except Exception as exc:
        raise ValueError('Module signature verification failed') from exc
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        if set(archive.namelist()) != {'manifest.json', 'module.pyc'}:
            raise ValueError('Unexpected .cpy contents')
        if any(i.file_size > MAX_CPY_MEMBER_BYTES or i.file_size < 0
               for i in archive.infolist()) or sum(i.file_size for i in archive.infolist()) > MAX_CPY_MEMBER_BYTES:
            raise ValueError('Invalid .cpy member size')
        manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
        pyc = archive.read('module.pyc')
    if (manifest.get('format') != 'pythonbde-cpy/1' or
            manifest.get('id') != event['moduleId'] or
            manifest.get('pythonTag') != sys.implementation.cache_tag or
            manifest.get('entrypoint') != 'create_widget' or
            not isinstance(manifest.get('title'), str)):
        raise ValueError('Incompatible or invalid .cpy manifest/Python ABI')
    if len(pyc) < 17 or pyc[:4] != importlib.util.MAGIC_NUMBER:
        raise ValueError('Incompatible .cpy bytecode')
    # The following executes trusted, signed publisher code with full local
    # permissions. This is NOT a restricted interpreter or security sandbox.
    code = marshal.loads(pyc[16:])
    if not isinstance(code, types.CodeType):
        raise ValueError('Invalid compiled code')
    mod = types.ModuleType(f'pythonbde_remote_{event["moduleId"]}')
    exec(code, mod.__dict__)
    if not callable(getattr(mod, 'create_widget', None)):
        raise ValueError('Missing create_widget entrypoint')
    return manifest, mod
