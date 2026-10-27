import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pythonbde.auth import UserManager, AuthError
from pythonbde.dbf import DBFStore, make_dbf, parse_dbf, LEGACY_FIELDS
from pythonbde.virtual_fs import VirtualFS, VirtualFileError, CHUNK, virtual_path


class VirtualFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'users.dbf'
        self.store = DBFStore(self.path)
        self.addCleanup(self.store.close)
        self.users = UserManager(self.store)
        self.users.bootstrap('admin', 'Secure Password123!')
        self.users.create('alice', 'Secure Password123!', {'READ': True, 'WRITE':True, 'MODIFY':True})
        self.users.create('bob', 'Secure Password123!', {'READ': True, 'WRITE':True, 'MODIFY':True})
        self.fs = VirtualFS(self.path)

    def test_login_type_marker(self):
        a = self.users.get('alice')
        self.assertEqual('RDP', a['ACCTYPE'])
        self.users.edit('alice', account_type='DB')
        self.assertEqual('DB', self.users.authenticate('alice', 'Secure Password123!')['ACCTYPE'])
        self.assertRaises(AuthError, self.users.edit, 'alice', account_type='unsupported')

    def test_fsroot_stable_and_per_account(self):
        a, b = self.users.get('alice'), self.users.get('bob')
        self.assertNotEqual(a['FSROOT'], b['FSROOT'])
        root, manifest, data = self.fs.workspace(a)
        self.assertEqual({'Desktop','My Documents'},set(data['entries']))
        self.assertTrue((root/'Desktop').is_dir())
        self.assertTrue(manifest.is_file())
        self.assertNotIn(str(root),json.dumps(self.fs.list_dir(a)))
        if os.name == 'posix':
            self.assertEqual(0o600, manifest.stat().st_mode & 0o777)
            self.assertEqual(0o700, root.stat().st_mode & 0o777)

    def test_dir_create_save_read_and_manifest(self):
        alice = self.users.get('alice')
        self.fs.mkdir(alice, 'My Documents/Letters')
        data = b'Hello\r\nWorld!'
        upload = self.fs.begin_upload(alice,'My Documents/Letters/a.txt')
        self.fs.write_chunk(upload,base64.b64encode(data).decode('ascii'))
        self.fs.commit(alice,upload)
        entries = self.fs.list_dir(alice,'My Documents/Letters')
        self.assertEqual('a.txt',entries[0]['name'])
        self.assertEqual(data,base64.b64decode(self.fs.read(alice,'My Documents/Letters/a.txt')['content']))
        self.assertRaises(VirtualFileError,self.fs.read,self.users.get('bob'),'My Documents/Letters/a.txt')
        self.assertRaises(VirtualFileError,self.fs.begin_upload,alice,'My Documents/Letters/a.txt')
        overw = self.fs.begin_upload(alice,'My Documents/Letters/a.txt',True)
        self.fs.write_chunk(overw,base64.b64encode(b'new').decode())
        self.fs.commit(alice,overw)
        self.assertEqual(b'new',base64.b64decode(self.fs.read(alice,'My Documents/Letters/a.txt')['content']))

    def test_large_file_chunks(self):
        alice = self.users.get('alice')
        raw = b'ABCD' * (CHUNK // 2 + 19)
        upload = self.fs.begin_upload(alice,'Desktop/data.bin')
        for i in range(0,len(raw),CHUNK):
            self.fs.write_chunk(upload,base64.b64encode(raw[i:i+CHUNK]).decode())
        self.fs.commit(alice, upload)
        parts = []
        for i in range(0,len(raw),CHUNK):
            parts.append(base64.b64decode(self.fs.read(alice,'Desktop/data.bin',i)['content']))
        self.assertEqual(raw,b''.join(parts))

    def test_path_traversal_and_symbolic_link_denied(self):
        for name in ('../admin','My Documents/../admin','/root/file','C:\\Windows','Desktop//file','My Documents/.','My Documents/AUX:bad', 'My Documents/CON.txt', 'Desktop/COM1', ''):
            self.assertRaises(VirtualFileError,virtual_path,name)
        if hasattr(os,'symlink'):
            alice = self.users.get('alice')
            root,_,_ = self.fs.workspace(alice)
            (root/'My Documents'/'evil').symlink_to(self.path)
            self.assertRaises(VirtualFileError,self.fs.begin_upload,alice,'My Documents/evil')

    def test_abort_cleans_temp(self):
        alice = self.users.get('alice')
        upload = self.fs.begin_upload(alice,'My Documents/bad.txt')
        tmp = upload['temp']
        self.fs.abort(upload)
        self.assertFalse(tmp.exists())
        self.assertEqual([], self.fs.list_dir(alice))

    def test_legacy_dbf_schema_readable(self):
        import pythonbde.dbf as dbf
        row = self.users.get('alice').copy()
        for k in ('ACCTYPE','FSROOT'):
            row.pop(k, None)
        with patch.object(dbf,'FIELDS',list(LEGACY_FIELDS)), \
             patch.object(dbf,'HEADER_LEN',32+len(LEGACY_FIELDS)*32+1), \
             patch.object(dbf,'RECORD_LEN',1+sum(v[2] for v in LEGACY_FIELDS)):
            old = dbf.make_dbf({'alice':row})
        upgraded = parse_dbf(old)['alice']
        self.assertEqual('RDP',upgraded['ACCTYPE'])
        self.assertEqual(32,len(upgraded['FSROOT']))

    def test_new_account_never_reuses_old_workspace(self):
        old = self.users.get('alice')['FSROOT']
        self.users.delete('alice')
        self.users.create('alice','Secure Password123!',{'READ':True})
        self.assertNotEqual(old,self.users.get('alice')['FSROOT'])

if __name__=='__main__':unittest.main()
