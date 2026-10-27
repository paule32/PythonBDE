"""RPC round-trip contracts and server state machine without a native Qt runtime."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import time
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pythonbde.rpc import (
    ERR_UNKNOWN_FUNCTION, RPC_TIMEOUT_SECONDS, create_window_request,
    result_message, validate_result,
)
from pythonbde.auth import AuthError, parse_time, utcnow

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_SOURCE = (ROOT / 'pythonbde' / 'protocol.py').read_text(encoding='utf-8')
TREE = ast.parse(PROTOCOL_SOURCE)
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'BDEServer')
METHOD_NAMES = {'_process_pending', '_dispatch', '_request_client_window',
                '_rpc_timeout', '_receive_rpc_result'}
METHODS = [n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name in METHOD_NAMES]


class FakeTimer:
    callbacks = []

    @classmethod
    def singleShot(cls, milliseconds, callback):
        cls.callbacks.append((milliseconds, callback))


NAMESPACE = {
    'json': json, 'AuthError': AuthError, 'parse_time': parse_time, 'utcnow': utcnow,
    'time': time, 'datetime': datetime, 'timezone': timezone,
    'MAX_LINE': 65536, 'SESSION_TTL': 3600,
    'QTimer': FakeTimer, 'create_window_request': create_window_request,
    'validate_result': validate_result,
}
exec(compile(ast.Module(body=METHODS, type_ignores=[]), '<extracted BDEServer methods>', 'exec'), NAMESPACE)


class FakeSignal:
    def __init__(self):
        self.calls = []
    def emit(self, *args):
        self.calls.append(args)


class FakeSocket:
    UnconnectedState = 0
    def __init__(self):
        self.packets = []
    def state(self):
        return 1
    def write(self, data):
        self.packets.append(json.loads(data.decode('utf-8')))


class FakeServer:
    _process_pending = NAMESPACE['_process_pending']
    _dispatch = NAMESPACE['_dispatch']
    _request_client_window = NAMESPACE['_request_client_window']
    _rpc_timeout = NAMESPACE['_rpc_timeout']
    _receive_rpc_result = NAMESPACE['_receive_rpc_result']
    _rpc_timeout_ms = RPC_TIMEOUT_SECONDS * 1000

    def __init__(self):
        self.audit = FakeSignal()
        self.status_changed = FakeSignal()
        self.message = FakeSignal()
        self.changed = FakeSignal()
        self.server_id = 'server-test'
        self.clients = {}
        self.users = types.SimpleNamespace(
            authenticate=lambda name, pwd: {'USERNAME': name, 'ADMIN': False} if pwd == 'good' else None,
            get=lambda name: {'USERNAME': name, 'ADMIN': False, 'LOCKUSER': False, 'EXPIRE': ''},
        )

    def attach(self, session='session-1', peer='127.0.0.1'):
        sock = FakeSocket()
        self.clients[sock] = {
            'buffer': bytearray(), 'username': None, 'logged_at': 0, 'login_time': '',
            'aliases': set(), 'session_id': session, 'peer': peer,
            'rpc_pending': None, 'rpc_status': 'idle', 'rpc_error_code': None,
        }
        return sock

    def _send(self, sock, data):
        sock.write(json.dumps(data).encode('utf8'))

    def _request(self, sock, data):
        self.clients[sock]['buffer'].extend(json.dumps(data).encode('utf8') + b'\n')
        self._process_pending(sock)
        return sock.packets


class RPCContracts(unittest.TestCase):
    def test_message_has_requested_fields_and_unique_id(self):
        a = create_window_request('session-1', '127.0.0.1')
        b = create_window_request('session-1', '127.0.0.1')
        self.assertEqual({'client': 'session-1', 'lastErrorCode': 0, 'setFunc': 'CreateWindow'},
                         {k:a[k] for k in ('client', 'lastErrorCode', 'setFunc')})
        self.assertEqual('rpc_request', a['event'])
        self.assertEqual('127.0.0.1', a['clientIp'])
        self.assertNotEqual(a['rpcId'], b['rpcId'])

    def test_result_contains_client_and_code(self):
        request = create_window_request('session-7')
        success = result_message(request, 0)
        self.assertEqual(0, success['lastErrorCode'])
        self.assertEqual('session-7', success['client'])
        self.assertEqual((0, ''), validate_result(success, request, 'session-7'))

    def test_error_response_is_positive(self):
        request = create_window_request('session-7')
        failure = result_message(request, ERR_UNKNOWN_FUNCTION, 'not supported')
        self.assertGreater(failure['lastErrorCode'], 0)
        self.assertEqual((ERR_UNKNOWN_FUNCTION, 'not supported'),
                         validate_result(failure, request, 'session-7'))

    def test_rejects_bad_result_types_and_routing(self):
        request = create_window_request('session-1')
        for value in (True, False, -1, 65536, '0', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_result({**result_message(request, 0), 'lastErrorCode': value}, request, 'session-1')
        with self.assertRaises(ValueError):
            validate_result(result_message(request, 0), request, 'session-2')
        with self.assertRaises(ValueError):
            validate_result({**result_message(request, 0), 'rpcId': 'wrong'}, request, 'session-1')
        with self.assertRaises(ValueError):
            validate_result(result_message(request, 0), None, 'session-1')


class TestServerRpc(unittest.TestCase):
    def setUp(self):
        FakeTimer.callbacks.clear()
        self.server = FakeServer()
        self.sock = self.server.attach()

    def login(self, sock=None):
        return self.server._request(sock or self.sock, {'action': 'login', 'username': 'user', 'password': 'good'})

    def test_login_reply_precedes_single_rpc_request(self):
        packets = self.login()
        self.assertEqual(2, len(packets))
        self.assertTrue(packets[0]['ok'])
        self.assertNotIn('event', packets[0])
        self.assertEqual('CreateWindow', packets[1]['setFunc'])
        self.assertEqual('session-1', packets[1]['client'])
        self.assertEqual('pending', self.server.clients[self.sock]['rpc_status'])
        self.assertEqual(RPC_TIMEOUT_SECONDS * 1000, FakeTimer.callbacks[0][0])

    def test_win95_session_mode_reaches_rpc_request(self):
        display = {"unit": "pixels", "width": 800, "height": 600}
        packets = self.server._request(self.sock, {"action":"login", "username":"user",
                                                 "password":"good", "systemMode":"win95",
                                                 "display":display})
        self.assertEqual(2, len(packets))
        self.assertEqual('win95', packets[0]['data']['systemMode'])
        self.assertEqual(display, packets[0]['data']['display'])
        self.assertEqual('win95', packets[1]['systemMode'])
        self.assertEqual(display, packets[1]['display'])
        self.assertEqual('win95', self.server.clients[self.sock]['system_mode'])

    def test_console_mode_eighty_by_fifty_reaches_rpc(self):
        display={"unit":"cells", "width":80, "height":50}
        packets = self.server._request(self.sock, {"action":"login", "username":"user",
                                                 "password":"good", "systemMode":"con",
                                                 "display":display})
        self.assertEqual(2, len(packets))
        self.assertEqual('con', packets[1]['systemMode'])
        self.assertEqual(display, packets[1]['display'])
        self.assertEqual('con', self.server.clients[self.sock]['system_mode'])

    def test_invalid_mode_rejected_without_login_and_rpc(self):
        packets = self.server._request(self.sock, {"action":"login", "username":"user",
                                                 "password":"good", "systemMode":"win98"})
        self.assertEqual(1, len(packets))
        self.assertFalse(packets[0]['ok'])
        self.assertIsNone(self.server.clients[self.sock]['username'])
        self.assertEqual([], FakeTimer.callbacks)

    def test_console_with_pixel_size_rejected(self):
        packets = self.server._request(self.sock, {"action":"login", "username":"user",
                                                 "password":"good", "systemMode":"con",
                                                 "display":{"unit":"pixels","width":80,"height":25}})
        self.assertEqual(1, len(packets))
        self.assertFalse(packets[0]['ok'])

    def test_rpc_dispatch_error_cannot_generate_duplicate_login_reply(self):
        def fail_rpc(sock, state):
            raise RuntimeError("simulated RPC transport failure")
        self.server._request_client_window = fail_rpc
        packets = self.login()
        self.assertEqual(1, len(packets))
        self.assertTrue(packets[0]["ok"])
        self.assertTrue(any(code == 400 for code, _ in self.server.audit.calls))

    def test_successful_roundtrip_acknowledgement(self):
        event = self.login()[1]
        self.server._request(self.sock, result_message(event, 0))
        self.assertEqual({'rpc_ack': True, 'client': 'session-1', 'lastErrorCode': 0},
                         self.sock.packets[-1]['data'])
        self.assertEqual('success', self.server.clients[self.sock]['rpc_status'])
        self.assertIsNone(self.server.clients[self.sock]['rpc_pending'])
        self.assertTrue(any('CreateWindow OK' in msg for _, msg in self.server.audit.calls))

    def test_positive_code_records_rpc_failure(self):
        event = self.login()[1]
        self.server._request(self.sock, result_message(event, 1002, 'window failed'))
        state = self.server.clients[self.sock]
        self.assertEqual('error', state['rpc_status'])
        self.assertEqual(1002, state['rpc_error_code'])
        self.assertTrue(any(code == 400 for code, _ in self.server.audit.calls))

    def test_invalid_ack_does_not_clear_pending(self):
        event = self.login()[1]
        self.server._request(self.sock, {**result_message(event, 0), 'rpcId': 'fake'})
        self.assertFalse(self.sock.packets[-1]['ok'])
        self.assertEqual('pending', self.server.clients[self.sock]['rpc_status'])
        self.assertIsNotNone(self.server.clients[self.sock]['rpc_pending'])

    def test_replay_is_rejected(self):
        event = self.login()[1]
        self.server._request(self.sock, result_message(event, 0))
        self.server._request(self.sock, result_message(event, 0))
        self.assertFalse(self.sock.packets[-1]['ok'])
        self.assertEqual('success', self.server.clients[self.sock]['rpc_status'])

    def test_other_client_same_ip_cannot_ack(self):
        event = self.login()[1]
        other = self.server.attach(session='session-2', peer='127.0.0.1')
        self.login(other)
        self.server._request(other, result_message(event, 0))
        self.assertFalse(other.packets[-1]['ok'])
        self.assertEqual('pending', self.server.clients[self.sock]['rpc_status'])

    def test_timeout_and_late_reply(self):
        event = self.login()[1]
        FakeTimer.callbacks[0][1]()
        self.assertEqual('timeout', self.server.clients[self.sock]['rpc_status'])
        self.server._request(self.sock, result_message(event, 0))
        self.assertFalse(self.sock.packets[-1]['ok'])
        self.assertTrue(any('timeout' in msg for _, msg in self.server.audit.calls))

    def test_unsuccessful_login_never_invokes_rpc(self):
        self.server._request(self.sock, {'action': 'login', 'username': 'user', 'password': 'bad'})
        self.assertEqual(1, len(self.sock.packets))
        self.assertFalse(self.sock.packets[0]['ok'])
        self.assertEqual([], FakeTimer.callbacks)

    def test_logout_clears_pending_rpc(self):
        self.login()
        self.server._request(self.sock, {'action': 'logout'})
        self.assertIsNone(self.server.clients[self.sock]['rpc_pending'])
        self.assertIsNone(self.server.clients[self.sock]['username'])

    def test_second_login_new_request_old_ack_refused(self):
        original = self.login()[1]
        self.login()
        second = self.sock.packets[-1]
        self.assertNotEqual(original['rpcId'], second['rpcId'])
        self.server._request(self.sock, result_message(original, 0))
        self.assertFalse(self.sock.packets[-1]['ok'])
        self.assertEqual('pending', self.server.clients[self.sock]['rpc_status'])

    def test_wrong_code_type_is_rejected(self):
        event = self.login()[1]
        self.server._request(self.sock, {**result_message(event, 0), 'lastErrorCode': True})
        self.assertFalse(self.sock.packets[-1]['ok'])
        self.assertEqual('pending', self.server.clients[self.sock]['rpc_status'])

    def test_unauthenticated_rpc_result_is_rejected(self):
        self.server._request(self.sock, {"action": "rpc_result", "client":"session-1", "rpcId":"123", "lastErrorCode":0})
        self.assertFalse(self.sock.packets[-1]['ok'])


class TestQtClientSource(unittest.TestCase):
    def test_qt_client_is_event_driven_and_creates_window(self):
        text = (ROOT / 'rpc_client.py').read_text(encoding='utf-8')
        ast.parse(text)
        for required in ('QSslSocket', 'readyRead.connect', 'CreatedWindow(', 'window.show()',
                         'result_message(', 'isVisible()', 'lastErrorCode', 'rpc_request'):
            self.assertIn(required, text)
        self.assertNotIn('subprocess.', text)
        self.assertNotIn('eval(', text)


if __name__ == '__main__':
    unittest.main()

# The actual client Qt event handlers are exercised with lightweight QWidget /
# timer doubles, not only text-matched, so failures propagate into ACK codes.
CLIENT_TEXT = (ROOT / 'rpc_client.py').read_text(encoding='utf-8')
CLIENT_CLASS = next(n for n in ast.parse(CLIENT_TEXT).body
                    if isinstance(n, ast.ClassDef) and n.name == 'RpcTestClient')
CLIENT_METHODS = [n for n in CLIENT_CLASS.body if isinstance(n, ast.FunctionDef)
                  and n.name in {'_handle_rpc', '_ack_created_window', '_ack_rpc'}]


class FakeWindow:
    """Existing communication window created after login, before RPC event."""
    def __init__(self):
        self.visible = True
        self.requests = []
        self.fail = False

    def set_rpc(self, request):
        if self.fail:
            raise RuntimeError("Simulated RPC widget failure")
        self.requests.append(request)

    def isVisible(self):
        return self.visible


CLIENT_NS = {'QTimer': FakeTimer,
             'ERR_UNKNOWN_FUNCTION': ERR_UNKNOWN_FUNCTION,
             'ERR_CREATE_WINDOW': 1002,
             'ERR_WINDOW_NOT_VISIBLE': 1003,
             'result_message': result_message}
exec(compile(ast.Module(body=CLIENT_METHODS, type_ignores=[]),
             '<rpc Qt callback methods>', 'exec'), CLIENT_NS)


class FakeRpcClient:
    _handle_rpc = CLIENT_NS['_handle_rpc']
    _ack_created_window = CLIENT_NS['_ack_created_window']
    _ack_rpc = CLIENT_NS['_ack_rpc']

    def __init__(self):
        self._logged_in = True
        self._client_window = FakeWindow()
        self._handled_rpc_ids = set()
        self.sent = []
        self.logs = []

    def _send(self, action, **args):
        self.sent.append({'action': action, **args})
        return True

    def _log(self, text, code=200):
        self.logs.append((code, text))


class TestQtRpcCallbacks(unittest.TestCase):
    def setUp(self):
        FakeTimer.callbacks.clear()
        self.client = FakeRpcClient()
        self.request = create_window_request('session-1')

    def test_create_window_rpc_dispatched_into_existing_window(self):
        win = self.client._client_window
        self.client._handle_rpc(self.request)
        self.assertIs(win, self.client._client_window)
        self.assertEqual([self.request], win.requests)
        self.assertEqual([], self.client.sent)
        FakeTimer.callbacks[0][1]()
        self.assertEqual(0, self.client.sent[0]['lastErrorCode'])
        self.assertEqual(self.request['rpcId'], self.client.sent[0]['rpcId'])

    def test_cannot_show_window_returns_error(self):
        self.client._client_window.visible = False
        self.client._handle_rpc(self.request)
        FakeTimer.callbacks[0][1]()
        self.assertEqual(1003, self.client.sent[0]['lastErrorCode'])

    def test_dispatch_failure_returns_error(self):
        self.client._client_window.fail = True
        self.client._handle_rpc(self.request)
        self.assertEqual(1002, self.client.sent[0]['lastErrorCode'])
        self.assertEqual([], self.client._client_window.requests)

    def test_unknown_rpc_name_is_never_executed(self):
        self.client._handle_rpc({**self.request, 'setFunc': 'RunShell'})
        self.assertEqual(1001, self.client.sent[0]['lastErrorCode'])
        self.assertEqual([], self.client._client_window.requests)

    def test_not_logged_in_client_does_not_execute(self):
        self.client._logged_in = False
        self.client._handle_rpc(self.request)
        self.assertEqual([], self.client._client_window.requests)
        self.assertEqual([], self.client.sent)

    def test_bad_packet_missing_rpc_id_is_ignored(self):
        self.client._handle_rpc({**self.request, 'rpcId': None})
        self.assertEqual([], self.client._client_window.requests)
        self.assertEqual([], self.client.sent)

    def test_missing_client_window_reports_error(self):
        self.client._client_window = None
        self.client._handle_rpc(self.request)
        self.assertEqual(1002, self.client.sent[0]['lastErrorCode'])

    def test_duplicate_rpc_id_is_not_reprocessed(self):
        self.client._handle_rpc(self.request)
        self.client._handle_rpc(self.request)
        self.assertEqual(1, len(self.client._client_window.requests))
        self.assertEqual(1002, self.client.sent[0]['lastErrorCode'])
