"""Regression tests for client disconnect auditing, without native PyQt5.

The production BDEServer methods are extracted via the AST so these tests
exercise the real server logic while providing lightweight Qt socket doubles.
"""
from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from pythonbde.auth import AuthError, parse_time, utcnow
from pythonbde.eventlog import EventLog

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "pythonbde" / "protocol.py").read_text(encoding="utf-8"))
CLASS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "BDEServer")
SELECTED = {"_gone", "_log_connection_closed", "stop", "_dispatch", "_find_session", "kick", "ban"}
METHODS = [node for node in CLASS.body
           if isinstance(node, ast.FunctionDef) and node.name in SELECTED]
CONTEXT = {
    "AuthError": AuthError, "parse_time": parse_time, "utcnow": utcnow,
    "time": time, "datetime": datetime, "timezone": timezone,
    "SESSION_TTL": 3600,
}
exec(compile(ast.Module(body=METHODS, type_ignores=[]), "<real BDEServer methods>", "exec"), CONTEXT)


class Signal:
    def __init__(self):
        self.calls = []
    def emit(self, *args):
        self.calls.append(args)


class Listener:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


class Socket:
    def __init__(self):
        self.server = None
        self.deleted = False
        self.closed = False
        self.packets = []
        self.disconnect_count = 0

    def disconnectFromHost(self):
        self.disconnect_count += 1
        # Qt may emit disconnected immediately while stop() is in progress.
        if self.server is not None:
            self.server._gone(self)

    def close(self):
        self.closed = True

    def deleteLater(self):
        self.deleted = True


class Server:
    _gone = CONTEXT["_gone"]
    _log_connection_closed = CONTEXT["_log_connection_closed"]
    stop = CONTEXT["stop"]
    _dispatch = CONTEXT["_dispatch"]
    _find_session = CONTEXT["_find_session"]
    kick = CONTEXT["kick"]
    ban = CONTEXT["ban"]

    def __init__(self):
        self.clients = {}
        self.audit = Signal()
        self.status_changed = Signal()
        self.message = Signal()
        self.changed = Signal()
        self.listener = Listener()
        self.discovery = Listener()
        self.started_at = "2026-10-26"
        self.users = SimpleNamespace(
            authenticate=lambda name, password: {"USERNAME": name, "ADMIN": False} if password == "correct" else None,
            get=lambda name: {"USERNAME": name, "ADMIN": False, "LOCKUSER": False, "EXPIRE": ""},
            edit=lambda *args, **kwargs: True,
        )

    def attach(self, username="", ip="127.0.0.1", session="session-1"):
        sock = Socket()
        sock.server = self
        self.clients[sock] = {
            "session_id": session, "peer": ip, "username": username or None,
            "last_username": username or None, "disconnect_reason": None,
            "disconnect_logged": False, "aliases": set(), "logged_at": time.monotonic(),
            "login_time": "", "rpc_pending": None,
        }
        return sock

    def _send(self, sock, message):
        sock.packets.append(message)

    def note_action(self, *args):
        pass

    def revoke_sessions(self, username):
        for state in self.clients.values():
            if state['username'] == username:
                state['username'] = None

    def _audit_disconnects(self):
        return [(code, msg) for code, msg in self.audit.calls if msg.startswith("Client disconnected:")]


class DisconnectAuditTests(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def test_window_close_while_logged_in(self):
        socket = self.server.attach("alice", "192.168.1.77", "session-9")
        socket.disconnectFromHost()
        self.assertEqual([(200, "Client disconnected: user=alice, client=session-9, "
                                "ip=192.168.1.77, reason=connection closed")],
                         self.server._audit_disconnects())
        self.assertNotIn(socket, self.server.clients)
        self.assertTrue(socket.deleted)
        self.assertEqual(1, len(self.server.status_changed.calls))

    def test_logout_then_socket_close_keeps_username_and_reason(self):
        socket = self.server.attach("alice")
        result = self.server._dispatch(self.server.clients[socket], {"action": "logout"})
        self.assertTrue(result["logged_out"])
        socket.disconnectFromHost()
        self.assertEqual(1, len(self.server._audit_disconnects()))
        self.assertIn("user=alice", self.server._audit_disconnects()[0][1])
        self.assertIn("reason=logout", self.server._audit_disconnects()[0][1])
        self.assertEqual(1, len([m for _, m in self.server.audit.calls if m.startswith("User logged out:")]))

    def test_duplicate_disconnected_signal_no_duplicate_audit(self):
        socket = self.server.attach("alice")
        socket.disconnectFromHost()
        socket.disconnectFromHost()
        self.assertEqual(1, len(self.server._audit_disconnects()))

    def test_unauthenticated_close_is_visible_in_log(self):
        socket = self.server.attach()
        socket.disconnectFromHost()
        self.assertIn("user=unauthenticated", self.server._audit_disconnects()[0][1])

    def test_kick_captures_reason_and_user_after_revocation(self):
        socket = self.server.attach("alice")
        self.server.kick("session-1")
        self.assertTrue(socket.deleted)
        self.assertEqual(1, len(self.server._audit_disconnects()))
        self.assertIn("reason=kicked by administrator", self.server._audit_disconnects()[0][1])
        self.assertIn("user=alice", self.server._audit_disconnects()[0][1])

    def test_ban_captures_reason_and_user(self):
        self.server.attach("alice")
        self.server.ban("session-1")
        self.assertEqual(1, len(self.server._audit_disconnects()))
        self.assertIn("reason=account banned by administrator", self.server._audit_disconnects()[0][1])

    def test_server_stop_logs_every_session_once(self):
        a = self.server.attach("alice", session="session-1")
        b = self.server.attach("bob", session="session-2")
        self.server.stop()
        self.assertEqual(2, len(self.server._audit_disconnects()))
        self.assertTrue(all("reason=server stopped" in msg for _, msg in self.server._audit_disconnects()))
        self.assertEqual({}, self.server.clients)
        self.assertTrue(a.deleted and b.deleted)
        self.assertTrue(self.server.listener.closed and self.server.discovery.closed)

    def test_last_authenticated_account_after_relogin(self):
        sock = self.server.attach("alice")
        self.server._dispatch(self.server.clients[sock], {"action": "logout"})
        self.server._dispatch(self.server.clients[sock],
                              {"action": "login", "username": "bob", "password": "correct"})
        sock.disconnectFromHost()
        self.assertIn("user=bob", self.server._audit_disconnects()[0][1])
        self.assertIn("reason=connection closed", self.server._audit_disconnects()[0][1])

    def test_disconnect_is_written_to_existing_log_file(self):
        sock = self.server.attach("alice")
        sock.disconnectFromHost()
        with TemporaryDirectory() as folder:
            eventlog = EventLog(Path(folder) / "users.dbf")
            for code, message in self.server.audit.calls:
                eventlog.write(code, message)
            text = eventlog.path.read_text(encoding="utf-8")
            self.assertIn("Client disconnected: user=alice", text)
            self.assertIn("| 200 |", text)
            self.assertEqual(len(eventlog.entries), 1)


if __name__ == "__main__":
    unittest.main()
