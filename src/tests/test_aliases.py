"""Persistenz, Sicherheitsregeln und Protokoll-Methoden des Alias-Managers."""
import ast
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from pythonbde.aliases import AliasRegistry, AliasError, AliasInUse

ROOT = Path(__file__).resolve().parents[1]


class TestAliasStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.registry = AliasRegistry(self.path / "users.dbf")

    def test_roundtrip_and_case_insensitive_duplicate(self):
        self.registry.create("Archiv", str(self.path))
        self.assertEqual("Archiv", self.registry.get("archiv")["name"])
        with self.assertRaisesRegex(AliasError, "existiert"):
            self.registry.create("ARCHIV", str(self.path))
        self.assertEqual("Archiv", AliasRegistry(self.path / "users.dbf").get("ARCHIV")["name"])

    def test_rename_and_delete_are_persistent(self):
        self.registry.create("Arch", str(self.path))
        self.registry.rename("ARCH", "Logs")
        self.assertIsNone(self.registry.get("Arch"))
        self.assertIsNotNone(AliasRegistry(self.path / "users.dbf").get("logs"))
        self.registry.delete("Logs")
        self.assertEqual([], AliasRegistry(self.path / "users.dbf").listing())

    def test_rename_to_same_case_is_allowed(self):
        self.registry.create("Archive", str(self.path))
        self.registry.rename("Archive", "ARCHIVE")
        self.assertEqual("ARCHIVE", self.registry.get("archive")["name"])

    def test_invalid_alias_name_and_folder(self):
        for name in ("../other", "Test Alias", "", "1Hello", "\x00bad", "öä"):
            with self.subTest(name=name), self.assertRaises(AliasError):
                self.registry.create(name, str(self.path))
        with self.assertRaises(OSError):
            self.registry.create("missing", str(self.path / "missing"))
        file_path = self.path / "a_file.txt"
        file_path.write_text("demo", encoding="utf-8")
        with self.assertRaisesRegex(AliasError, "Verzeichnis"):
            self.registry.create("missing", str(file_path))

    def test_path_repoint_and_private_file_on_posix(self):
        other = self.path / "data"
        other.mkdir()
        self.registry.create("One", str(self.path))
        self.registry.set_path("One", str(other))
        self.assertEqual(str(other.resolve()), self.registry.get("One")["path"])
        if __import__('os').name == 'posix':
            self.assertEqual(0o600, self.registry.path.stat().st_mode & 0o777)

    def test_persistent_write_failure_leaves_memory_untouched(self):
        self.registry.create("Old", str(self.path))
        with patch('pythonbde.aliases.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.registry.create("New", str(self.path))
        self.assertIsNone(self.registry.get("New"))
        self.assertIsNotNone(self.registry.get("Old"))


# Reale BDEServer-Methoden werden aus dem Qt-Modul per AST importiert,
# da PyQt5 auf dem Linux-Testhost nicht verfügbar sein muss.
protocol = ROOT / "pythonbde" / "protocol.py"
ast_root = ast.parse(protocol.read_text(encoding='utf8'))
server_class = next(n for n in ast_root.body if isinstance(n, ast.ClassDef) and n.name == 'BDEServer')
names = {'active_alias_sessions', 'delete_alias', 'create_alias', 'rename_alias',
         'update_alias_path', 'notify_alias_in_use', '_dispatch'}
nodes = [n for n in server_class.body if isinstance(n, ast.FunctionDef) and n.name in names]
from datetime import datetime, timezone
from pythonbde.auth import AuthError
ns = {'time': time, 'SESSION_TTL': 3600, 'AliasInUse': AliasInUse,
      'AliasError': AliasError, 'AuthError': AuthError,
      'datetime': datetime, 'timezone': timezone, 'parse_time': lambda _: None,
      'utcnow': datetime.utcnow}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(protocol), 'exec'), ns)


class Signal:
    def __init__(self):
        self.items = []

    def emit(self, *args):
        self.items.append(args)


class FakeServer:
    active_alias_sessions = ns['active_alias_sessions']
    delete_alias = ns['delete_alias']
    create_alias = ns['create_alias']
    rename_alias = ns['rename_alias']
    update_alias_path = ns['update_alias_path']
    notify_alias_in_use = ns['notify_alias_in_use']
    _dispatch = ns['_dispatch']

    def __init__(self, path):
        self.aliases = AliasRegistry(path / 'users.dbf')
        self.aliases.create('Books', str(path))
        self.clients = {"socket1": {"username": "max", "session_id": "session-1", "peer": "localhost",
                                    "login_time": "2026-10-25", "logged_at": time.monotonic(),
                                    "aliases": {"books"}}}
        self.users = types.SimpleNamespace(
            get=lambda name: {'USERNAME': name, 'ADMIN': name == 'max',
                              'LOCKUSER': False, 'EXPIRE': ''},
            authenticate=lambda name, password: {'USERNAME': name, 'ADMIN': name == 'max'})
        self.audit = Signal()
        self.status_changed = Signal()
        self.sent = []
        self.actions = []
        self.server_id = 'test'

    def _send(self, sock, event):
        self.sent.append((sock, event))

    def note_action(self, *args):
        self.actions.append(args)


class TestAliasInUse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = FakeServer(Path(self.tmp.name))

    def test_in_use_blocks_removal_without_confirmation(self):
        with self.assertRaises(AliasInUse) as ctx:
            self.server.delete_alias('books')
        self.assertEqual('max', ctx.exception.sessions[0]['username'])
        self.assertIsNotNone(self.server.aliases.get('Books'))
        self.assertEqual('admin_notice', self.server.sent[0][1]['event'])

    def test_confirmed_delete_notifies_clients_and_clears_reservation(self):
        self.server.delete_alias('BOOKS', confirmed=True)
        self.assertIsNone(self.server.aliases.get('Books'))
        self.assertEqual(set(), self.server.clients['socket1']['aliases'])
        self.assertEqual('alias_removed', self.server.sent[-1][1]['event'])

    def test_rename_and_repoint_blocked_during_use(self):
        with self.assertRaises(AliasInUse):
            self.server.rename_alias('Books', 'NewBooks')
        with self.assertRaises(AliasInUse):
            self.server.update_alias_path('Books', self.tmp.name)
        self.assertIsNotNone(self.server.aliases.get('Books'))

    def test_network_client_selects_and_releases_alias(self):
        state = self.server.clients['socket1']
        state['aliases'] = set()
        listing = self.server._dispatch(state, {'action': 'list_aliases'})
        self.assertEqual(['Books'], listing)
        self.assertTrue(self.server._dispatch(state, {'action': 'select_alias', 'alias': 'books'})['selected'])
        self.assertEqual({'books'}, state['aliases'])
        with self.assertRaises(AliasInUse):
            self.server.delete_alias('Books')
        self.server._dispatch(state, {'action': 'release_alias', 'alias': 'BOOKS'})
        self.assertEqual(set(), state['aliases'])
        self.server.delete_alias('Books')

    def test_login_logout_clears_alias_reservations(self):
        state = self.server.clients['socket1']
        self.server._dispatch(state, {'action': 'logout'})
        self.assertEqual(set(), state['aliases'])
        self.server._dispatch(state, {'action': 'login', 'username': 'max', 'password': 'secret'})
        self.assertEqual(set(), state['aliases'])
        self.assertEqual('max', state['username'])

    def test_alias_not_available_raises_without_reservation(self):
        state = self.server.clients['socket1']
        with self.assertRaises(AliasError):
            self.server._dispatch(state, {'action': 'select_alias', 'alias': 'other'})
        self.assertEqual({'books'}, state['aliases'])

    def test_alias_listing_does_not_leak_server_paths(self):
        state = self.server.clients['socket1']
        result = self.server._dispatch(state, {'action': 'list_aliases'})
        self.assertEqual(['Books'], result)
        self.assertNotIn(self.tmp.name, str(result))

    def test_expired_session_does_not_prevent_removal(self):
        self.server.clients['socket1']['logged_at'] = time.monotonic() - 3601
        self.server.delete_alias('Books')
        self.assertIsNone(self.server.aliases.get('Books'))


if __name__ == '__main__':
    unittest.main()
