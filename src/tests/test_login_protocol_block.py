"""Login-Sperren auf echter _process_pending/_dispatch JSONL-Logik, ohne Qt."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from pythonbde.auth import AuthError
from pythonbde.blocking import TYPES, BlockingRegistry, DuplicateLoginGuard
from test_rpc import FakeServer, FakeTimer, NAMESPACE

# Die bestehenden RPC-Tests laden die tatsächlichen Servermethoden per AST,
# damit sie unabhängig vom lokal vorhandenen Qt5-Paket getestet werden können.
source = (Path(__file__).resolve().parents[1] / 'pythonbde' / 'protocol.py').read_text('utf-8')
module = ast.parse(source)
login_exception = next(x for x in module.body if isinstance(x, ast.ClassDef) and x.name == 'LoginRejected')
exec(compile(ast.Module(body=[login_exception], type_ignores=[]), '<server LoginRejected>', 'exec'), NAMESPACE)


class LoginProtocolBlockingTests(unittest.TestCase):
    def setUp(self):
        FakeTimer.callbacks.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.srv = FakeServer()
        self.srv.blocking = BlockingRegistry(Path(self.tmp.name) / 'users.dbf')
        self.now = [100.0]
        self.srv.login_guard = DuplicateLoginGuard(20, lambda: self.now[0])
        self.s1 = self.srv.attach('session-1', '192.0.2.11')
        self.s2 = self.srv.attach('session-2', '192.0.2.12')
        self.srv.clients[self.s1]['peer_port'] = 45678
        self.srv.clients[self.s2]['peer_port'] = 45679

    def login(self, sock, username='user', password='good'):
        old_len = len(sock.packets)
        self.srv._request(sock, {'action':'login', 'username':username, 'password':password})
        return sock.packets[old_len:]

    def test_duplicate_login_20_seconds_original_remains_active(self):
        first = self.login(self.s1)
        self.assertTrue(first[0]['ok'])
        self.assertEqual('CreateWindow', first[1]['setFunc'])
        second = self.login(self.s2)
        self.assertEqual(1,len(second))
        self.assertFalse(second[0]['ok'])
        self.assertEqual(409,second[0]['errorCode'])
        self.assertEqual(20,second[0]['retryAfterSeconds'])
        self.assertEqual('user',self.srv.clients[self.s1]['username'])
        self.assertIsNone(self.srv.clients[self.s2]['username'])
        # Die erste Sitzung ist weiterhin authentifiziert und kann regulär
        # logout senden; der Konkurrenzlogin hat sie nicht beeinflusst.
        self.assertEqual('user', self.srv.clients[self.s1]['username'])
        self.srv._request(self.s1, {'action':'logout'})
        self.assertTrue(self.s1.packets[-1]['ok'])
        self.now[0] += 5
        still = self.login(self.s2)
        self.assertEqual(409,still[0]['errorCode'])
        self.assertEqual(15,still[0]['retryAfterSeconds'])
        self.now[0] += 15
        accepted = self.login(self.s2)
        self.assertTrue(accepted[0]['ok'])
        self.assertEqual('CreateWindow',accepted[1]['setFunc'])

    def test_invalid_password_cannot_trigger_duplicate_lock(self):
        self.login(self.s1)
        rejected = self.login(self.s2, password='wrong')
        self.assertFalse(rejected[0]['ok'])
        self.assertNotIn('retryAfterSeconds', rejected[0])
        self.assertEqual({},self.srv.login_guard.until)
        self.srv._request(self.s1, {'action':'logout'})
        accepted = self.login(self.s2)
        self.assertTrue(accepted[0]['ok'])

    def test_ip_range_denies_even_valid_login_pre_auth(self):
        self.srv.blocking.upsert(TYPES[0], {'start':'192.0.2.10','end':'192.0.2.20'})
        got = self.login(self.s2)
        self.assertEqual(403, got[0]['errorCode'])
        self.assertFalse(got[0]['ok'])
        self.assertEqual(1,len(got))
        self.assertIsNone(self.srv.clients[self.s2]['username'])
        self.assertEqual({},self.srv.login_guard.until)

    def test_single_ip_denied_other_ip_allowed(self):
        self.srv.blocking.upsert(TYPES[2], {'ip':'192.0.2.11'})
        self.assertFalse(self.login(self.s1)[0]['ok'])
        self.assertTrue(self.login(self.s2)[0]['ok'])

    def test_client_source_port_denied(self):
        self.srv.blocking.upsert(TYPES[1], {'start':45679,'end':45679})
        self.assertEqual(403,self.login(self.s2)[0]['errorCode'])
        self.assertTrue(self.login(self.s1)[0]['ok'])

    def test_same_connection_can_still_login(self):
        self.login(self.s1)
        result = self.login(self.s1)
        self.assertTrue(result[0]['ok'])
        self.assertEqual('user',self.srv.clients[self.s1]['username'])
        self.assertFalse(self.srv.login_guard.until)

    def test_user_blocked_without_ip_block(self):
        self.srv.blocking.upsert(TYPES[5], {'username':'USER'})
        self.assertEqual(403, self.login(self.s1)[0]['errorCode'])
        self.assertEqual(403, self.login(self.s2)[0]['errorCode'])


if __name__ == '__main__':
    unittest.main()
