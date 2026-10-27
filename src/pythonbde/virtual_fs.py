"""Per-account virtual file index and jailed server storage for RDP sessions.

The manifest is authoritative; clients NEVER receive physical paths. This is
not an OS sandbox for code running under the server's own user account.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path

MAX_FILE = 16 * 1024 * 1024
CHUNK = 20 * 1024
WINDOWS_DEVICES = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1,10)} | {f'LPT{i}' for i in range(1,10)}
SEGMENT = re.compile(r"[^/\\\x00-\x1f:<>|?*]{1,100}\Z")


class VirtualFileError(ValueError):
    pass


def virtual_path(path):
    if not isinstance(path, str) or not path or len(path) > 900 or '\\' in path:
        raise VirtualFileError('Invalid virtual path')
    if path.startswith('/') or path.endswith('/') or '//' in path:
        raise VirtualFileError('Absolute/empty virtual path refused')
    parts = path.split('/')
    if not all(p not in ('.', '..') and p.strip() == p and SEGMENT.fullmatch(p)
               and not p.endswith(('.', ' '))
               and p.split('.', 1)[0].upper() not in WINDOWS_DEVICES for p in parts):
        raise VirtualFileError('Unsafe virtual path')
    return '/'.join(parts)


def _atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.manifest-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600) if os.name == 'posix' else None
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            json.dump(data, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _secure_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise VirtualFileError('Unsafe storage directory')
    if os.name == 'posix':
        path.chmod(0o700)
    elif os.name == 'nt':
        # Deny inheritance; grant service identity and SYSTEM. Fail CLOSED.
        username = os.environ.get('USERNAME')
        if not username:
            raise VirtualFileError('Could not identify Windows service identity')
        cmd = ['icacls', str(path), '/inheritance:r', '/grant:r',
               f'{username}:(OI)(CI)F', 'SYSTEM:(OI)(CI)F']
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=12,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise VirtualFileError('Could not secure Windows workspace ACL')


class VirtualFS:
    def __init__(self, users_dbf):
        self.base = Path(users_dbf).resolve().parent / 'user_data'
        _secure_dir(self.base)
        self._secured = set()

    def workspace(self, user):
        token = user.get('FSROOT', '')
        if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
            raise VirtualFileError('Invalid user workspace ID')
        root = self.base / token
        if token not in self._secured:
            _secure_dir(root)
            self._secured.add(token)
        elif root.is_symlink() or not root.is_dir():
            raise VirtualFileError('Unsafe workspace directory')
        manifest = root / 'filesystem.json'
        if manifest.is_symlink():
            raise VirtualFileError('Unsafe virtual filesystem index')
        if not manifest.exists():
            for name in ('My Documents', 'Desktop'):
                _secure_dir(root / name)
            _atomic_json(manifest, {'version': 1, 'entries': {
                'My Documents': {'type': 'dir'}, 'Desktop': {'type': 'dir'}}})
        data = json.loads(manifest.read_text('utf-8'))
        if data.get('version') != 1 or not isinstance(data.get('entries'), dict):
            raise VirtualFileError('Invalid virtual filesystem index')
        if os.name == 'posix':
            manifest.chmod(0o600)
        return root, manifest, data

    def _physical(self, root, path):
        # The server builds physical paths exclusively from its own private
        # root and validated virtual segments. Reject symlinks at every level.
        parts = virtual_path(path).split('/')
        output = root
        for part in parts:
            output = output / part
            if output.is_symlink():
                raise VirtualFileError('Symbolic links are forbidden')
        if not output.resolve().is_relative_to(root.resolve()):
            raise VirtualFileError('Path escaped workspace')
        return output

    @staticmethod
    def _type(data, path, kind):
        if data['entries'].get(path, {}).get('type') != kind:
            raise VirtualFileError('Virtual entry not found')

    def list_dir(self, user, path='My Documents'):
        root, _, data = self.workspace(user)
        path = virtual_path(path)
        self._type(data, path, 'dir')
        self._physical(root, path)  # no symlinks
        prefix = path + '/'
        result = []
        for key, meta in data['entries'].items():
            if key.startswith(prefix) and '/' not in key[len(prefix):]:
                if not isinstance(meta, dict) or meta.get('type') not in ('dir', 'file'):
                    raise VirtualFileError('Invalid filesystem entry')
                physical = self._physical(root, key)
                if not physical.exists():
                    continue
                result.append({'name': key[len(prefix):], 'path': key,
                               'type': meta['type'], 'size': physical.stat().st_size if meta['type']=='file' else 0})
        return sorted(result, key=lambda x: (x['type'] != 'dir', x['name'].casefold()))

    def mkdir(self, user, path):
        root, manifest, data = self.workspace(user)
        path = virtual_path(path)
        parent = path.rsplit('/',1)[0] if '/' in path else ''
        self._type(data, parent, 'dir')
        if path in data['entries']:
            raise VirtualFileError('Virtual entry already exists')
        physical = self._physical(root, path)
        if physical.exists():
            raise VirtualFileError('Physical entry already exists')
        _secure_dir(physical)
        data['entries'][path] = {'type': 'dir'}
        _atomic_json(manifest, data)
        return {'created': path}

    def read(self, user, path, offset=0):
        root, _, data = self.workspace(user)
        path = virtual_path(path)
        self._type(data, path, 'file')
        if type(offset) is not int or offset < 0 or offset > MAX_FILE:
            raise VirtualFileError('Invalid file offset')
        physical = self._physical(root, path)
        if not physical.is_file():
            raise VirtualFileError('File not found')
        # O_NOFOLLOW protects the final component on POSIX.
        fd = os.open(physical, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > MAX_FILE:
                raise VirtualFileError('File exceeds 16 MiB')
            stream.seek(offset)
            chunk = stream.read(CHUNK)
        return {'path': path, 'offset': offset, 'size': size,
                'content': base64.b64encode(chunk).decode('ascii'), 'eof': offset+len(chunk)>=size}

    def begin_upload(self, user, path, overwrite=False):
        root, _, data = self.workspace(user)
        path = virtual_path(path)
        parent = path.rsplit('/',1)[0] if '/' in path else ''
        self._type(data, parent, 'dir')
        exists = path in data['entries']
        if exists and not overwrite:
            raise VirtualFileError('File exists; Modify permission required')
        if exists:
            self._type(data, path, 'file')
        physical = self._physical(root, path)
        if physical.exists() and not exists:
            raise VirtualFileError('Physical entry exists but is missing from virtual index')
        fd, tempname = tempfile.mkstemp(prefix='.bde-upload-', dir=root)
        if os.name == 'posix': os.fchmod(fd, 0o600)
        return {'path': path, 'root': root, 'temp': Path(tempname), 'file': os.fdopen(fd,'wb'), 'size': 0}

    def write_chunk(self, upload, encoded):
        if not isinstance(encoded, str) or len(encoded) > CHUNK*2:
            raise VirtualFileError('Invalid chunk size')
        try:
            blob = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise VirtualFileError('Invalid base64 chunk') from exc
        if len(blob)>CHUNK or upload['size']+len(blob)>MAX_FILE:
            raise VirtualFileError('File upload limit exceeded')
        upload['file'].write(blob)
        upload['size'] += len(blob)
        return {'written': upload['size']}

    def abort(self, upload):
        if upload:
            if not upload['file'].closed:
                upload['file'].close()
            upload['temp'].unlink(missing_ok=True)

    def commit(self, user, upload):
        path = upload['path']
        try:
            upload['file'].flush()
            os.fsync(upload['file'].fileno())
            upload['file'].close()
            root, manifest, data = self.workspace(user)
            if root != upload['root']:
                raise VirtualFileError('Workspace mismatch')
            destination = self._physical(root, path)
            if path in data['entries']:
                self._type(data, path, 'file')
            os.replace(upload['temp'], destination)
            data['entries'][path] = {'type':'file'}
            _atomic_json(manifest, data)
            return {'saved': path, 'size': upload['size']}
        finally:
            self.abort(upload)
