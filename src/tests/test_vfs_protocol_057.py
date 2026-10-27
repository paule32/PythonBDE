import ast
import base64
import tempfile
import unittest
from pathlib import Path

from test_rpc import FakeServer, NAMESPACE
from pythonbde.auth import AuthError, UserManager
from pythonbde.dbf import DBFStore
from pythonbde.virtual_fs import VirtualFS, VirtualFileError
from pythonbde.emulation import validate_client_display

NAMESPACE['VirtualFileError']=VirtualFileError
NAMESPACE['validate_client_display']=validate_client_display
SOURCE=(Path(__file__).resolve().parents[1]/'pythonbde/protocol.py').read_text('utf-8')
LOGIN=next(item for item in ast.parse(SOURCE).body if isinstance(item,ast.ClassDef) and item.name=='LoginRejected')
exec(compile(ast.Module(body=[LOGIN],type_ignores=[]),'<login>', 'exec'),NAMESPACE)


class VirtualProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=DBFStore(Path(self.temp.name)/'users.dbf')
        self.addCleanup(self.store.close)
        self.users=UserManager(self.store)
        self.users.bootstrap('admin','StrongPassword!123')
        self.users.create('rdp','StrongPassword!123',{'READ':True,'WRITE':True,'MODIFY':True})
        self.users.create('db','StrongPassword!123',{'READ':True},account_type='DB')
        self.server=FakeServer()
        self.server.users=self.users
        self.server.virtual_fs=VirtualFS(self.store.path)
        self.rdp_socket=self.server.attach('rdp-sess')
        self.db_socket=self.server.attach('db-sess')

    def ask(self,socket,action,**fields):
        old=len(socket.packets)
        self.server._request(socket,{'action':action,**fields})
        return socket.packets[old]

    def test_only_matching_account_type_can_login(self):
        self.assertFalse(self.ask(self.db_socket,'login',username='db',password='StrongPassword!123')['ok'])
        self.assertTrue(self.ask(self.db_socket,'login',username='db',password='StrongPassword!123',systemMode='db',display=None)['ok'])
        self.assertIsNone(self.server.clients[self.db_socket].get('rpc_pending'))
        self.assertTrue(self.ask(self.rdp_socket,'login',username='rdp',password='StrongPassword!123')['ok'])
        self.assertEqual('RDP',self.server.clients[self.rdp_socket]['system_mode'] == 'db' and 'DB' or 'RDP')
        self.assertFalse(self.ask(self.db_socket,'vfs_list',path='My Documents')['ok'])

    def test_virtual_file_upload_download(self):
        self.ask(self.rdp_socket,'login',username='rdp',password='StrongPassword!123')
        self.assertTrue(self.ask(self.rdp_socket,'vfs_mkdir',path='My Documents/Notes')['ok'])
        self.assertTrue(self.ask(self.rdp_socket,'vfs_begin',path='My Documents/Notes/a.txt')['ok'])
        self.assertTrue(self.ask(self.rdp_socket,'vfs_chunk',content=base64.b64encode(b'Hello').decode())['ok'])
        self.assertTrue(self.ask(self.rdp_socket,'vfs_commit')['ok'])
        listing=self.ask(self.rdp_socket,'vfs_list',path='My Documents/Notes')
        self.assertEqual('a.txt',listing['data'][0]['name'])
        result=self.ask(self.rdp_socket,'vfs_read',path='My Documents/Notes/a.txt')
        self.assertEqual(b'Hello',base64.b64decode(result['data']['content']))
        bad=self.ask(self.rdp_socket,'vfs_read',path='My Documents/../../admin')
        self.assertFalse(bad['ok'])

if __name__=='__main__':unittest.main()
