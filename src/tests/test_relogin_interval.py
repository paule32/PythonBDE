"""Real server login function + per-account monotonic 60s interval."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ast
import unittest
from pythonbde.blocking import ReLoginIntervalGuard
from test_rpc import FakeServer, FakeTimer, NAMESPACE
from pythonbde.auth import AuthError

SOURCE = (Path(__file__).resolve().parents[1] / 'pythonbde' / 'protocol.py').read_text('utf-8')
LOGIN = next(x for x in ast.parse(SOURCE).body if isinstance(x, ast.ClassDef) and x.name == 'LoginRejected')
exec(compile(ast.Module(body=[LOGIN], type_ignores=[]), '<LoginRejected>', 'exec'), NAMESPACE)


class ReloginGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.guard = ReLoginIntervalGuard(60, lambda: self.now[0])

    def test_interval_measured_from_login_not_logout(self):
        self.guard.record_success('User')
        self.assertEqual(60, self.guard.remaining('USER'))
        self.now[0] += 10
        self.assertEqual(50, self.guard.remaining('user'))
        self.now[0] += 49
        self.assertEqual(1, self.guard.remaining('user'))
        self.now[0] += 1
        self.assertEqual(0, self.guard.remaining('user'))

    def test_other_users_independent_and_no_refresh_on_check(self):
        self.guard.record_success('alice')
        self.assertEqual(0, self.guard.remaining('bob'))
        self.now[0] += 5
        for _ in range(10):
            self.assertEqual(55, self.guard.remaining('alice'))


class ReloginProtocolTests(unittest.TestCase):
    def setUp(self):
        FakeTimer.callbacks.clear()
        self.srv = FakeServer()
        self.now = [100.0]
        self.srv.relogin_guard = ReLoginIntervalGuard(60, lambda: self.now[0])
        self.one = self.srv.attach('session-1')
        self.two = self.srv.attach('session-2')

    def request(self, sock, action, **kwargs):
        self.srv._request(sock, {'action':action, **kwargs})
        return sock.packets[-1]

    def test_logout_early_then_second_login_waits_remainder(self):
        self.request(self.one, 'login', username='alice', password='good')
        self.assertTrue(self.one.packets[0]['ok'])
        self.request(self.one, 'logout')
        self.now[0] += 10
        result = self.request(self.two, 'login', username='Alice', password='good')
        self.assertFalse(result['ok'])
        self.assertEqual(429, result['errorCode'])
        self.assertEqual(50, result['retryAfterSeconds'])
        self.assertIsNone(self.srv.clients[self.two]['username'])
        self.now[0] += 50
        result = self.request(self.two, 'login', username='Alice', password='good')
        self.assertEqual('CreateWindow', result['setFunc'])
        self.assertEqual(True, self.two.packets[-2]['ok'])

    def test_disconnect_does_not_clear_relogin_limit(self):
        self.request(self.one, 'login', username='alice', password='good')
        self.srv.clients.pop(self.one)
        self.now[0] += 35
        result = self.request(self.two, 'login', username='alice', password='good')
        self.assertEqual(429, result['errorCode'])
        self.assertEqual(25, result['retryAfterSeconds'])

    def test_invalid_password_does_not_create_interval(self):
        self.request(self.one, 'login', username='alice', password='wrong')
        self.assertEqual(0, self.srv.relogin_guard.remaining('alice'))

    def test_same_authenticated_socket_may_reauth(self):
        self.request(self.one, 'login', username='alice', password='good')
        self.now[0] += 5
        self.request(self.one, 'login', username='alice', password='good')
        self.assertTrue(self.one.packets[-2]['ok'])
        self.assertEqual(55, self.srv.relogin_guard.remaining('alice'))

if __name__ == '__main__':
    unittest.main()
