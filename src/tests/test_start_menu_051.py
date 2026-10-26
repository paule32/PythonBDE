"""v0.5.1: ephemeral JSON, validation, protocol and Qt5 structure regression."""
import ast
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from pythonbde.start_menu import (
    DEFAULT_MENU, MAX_DEPTH, MAX_MENU_BYTES, menu_payload, validate_menu,
    serialized_temporary_menu,
)

ROOT = Path(__file__).resolve().parents[1]


class StartMenuPayloadTests(unittest.TestCase):
    def test_default_menu_and_nested_programs(self):
        p = menu_payload('win95', 'session-7')
        self.assertEqual('menu_config', p['event'])
        self.assertEqual(1, p['menuVersion'])
        self.assertEqual('session-7', p['client'])
        self.assertEqual('Programs', p['items'][0]['label'])
        self.assertEqual('Accessories', p['items'][0]['children'][0]['label'])
        self.assertEqual('Shut Down...', p['items'][-1]['label'])

    def test_xp_uses_same_template_but_distinct_mode(self):
        w95 = menu_payload('win95', 'session-a')
        xp = menu_payload('winXP', 'session-b')
        self.assertEqual(w95['items'], xp['items'])
        self.assertEqual(xp['systemMode'], 'winXP')

    def test_reject_console_menu_and_missing_client(self):
        for mode in ('con', 'XP', None):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                menu_payload(mode, 'session-7')
        with self.assertRaises(ValueError):
            menu_payload('win95', '')

    def test_payload_is_independent_copy(self):
        first = menu_payload('win95', 'session-7')
        first['items'][0]['label'] = 'Modified'
        self.assertEqual(DEFAULT_MENU[0]['label'], menu_payload('win95', 'session-8')['items'][0]['label'])

    def test_reject_unknown_dangerous_actions_and_paths(self):
        for field, value in [('command', 'cmd.exe'), ('executable', '/bin/sh'),
                             ('path', 'C:/windows/system32/cmd.exe'), ('rpc', 'delete_user')]:
            nodes = copy.deepcopy(DEFAULT_MENU)
            nodes[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_menu(nodes)

    def test_reject_duplicate_id(self):
        nodes = copy.deepcopy(DEFAULT_MENU)
        nodes[1]['id'] = nodes[0]['id']
        with self.assertRaises(ValueError):
            validate_menu(nodes)

    def test_reject_malformed_text_and_flags(self):
        nodes = copy.deepcopy(DEFAULT_MENU)
        nodes[0]['label'] = 'Hello\nInjected'
        with self.assertRaises(ValueError):
            validate_menu(nodes)
        nodes = copy.deepcopy(DEFAULT_MENU)
        nodes[0]['disabled'] = 'false'
        with self.assertRaises(ValueError):
            validate_menu(nodes)

    def test_reject_nesting_too_deep(self):
        node = {'id': 'leaf', 'label': 'Leaf'}
        for n in range(MAX_DEPTH):
            node = {'id': f'level{n}', 'label': f'Level {n}', 'children': [node]}
        with self.assertRaises(ValueError):
            validate_menu([node])

    def test_reject_huge_menu(self):
        nodes = [{'id': f'x{i}', 'label': 'X' * 70} for i in range(95)]
        with self.assertRaises(ValueError):
            validate_menu(nodes)

    def test_wire_size(self):
        p = menu_payload('win95','session-test')
        self.assertLess(len(json.dumps(p).encode()), MAX_MENU_BYTES)


class TemporaryFileTests(unittest.TestCase):
    def test_returns_identical_payload_and_removes_files(self):
        with tempfile.TemporaryDirectory() as base:
            p = serialized_temporary_menu('win95', 'session-14', parent=base)
            self.assertEqual(p, menu_payload('win95', 'session-14'))
            self.assertEqual([], list(Path(base).iterdir()))

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions test')
    def test_posix_mode_is_private_during_serialization(self):
        import pythonbde.start_menu as sm
        opened = []
        original_open = Path.open
        def intercepted_open(path, *args, **kwargs):
            if Path(path).name == 'start_menu.json':
                opened.append((stat.S_IMODE(Path(path).stat().st_mode),
                               stat.S_IMODE(Path(path).parent.stat().st_mode)))
            return original_open(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as base, patch.object(Path, 'open', intercepted_open):
            sm.serialized_temporary_menu('winXP', 'session-9', parent=base)
        self.assertEqual([(0o600,0o700)], opened)

    def test_windows_acl_is_applied_to_directory_and_file(self):
        import pythonbde.start_menu as sm
        checks = []
        with tempfile.TemporaryDirectory() as base, patch('platform.system', return_value='Windows'):
            with patch.object(sm, '_restrict_windows_acl', side_effect=lambda p, directory: checks.append((p.name, directory))):
                sm.serialized_temporary_menu('win95', 'session-9', parent=base)
            self.assertEqual([], list(Path(base).iterdir()))
        self.assertEqual(True, checks[0][1])
        self.assertEqual(('start_menu.json', False), checks[1])

    def test_windows_acl_failure_does_not_write_or_leave_json(self):
        import pythonbde.start_menu as sm
        with tempfile.TemporaryDirectory() as base, patch('platform.system', return_value='Windows'):
            with patch.object(sm, '_restrict_windows_acl', side_effect=PermissionError('DACL refused')):
                with self.assertRaises(PermissionError):
                    sm.serialized_temporary_menu('win95', 'session-9', parent=base)
            self.assertEqual([], list(Path(base).iterdir()))


class QtStructureTests(unittest.TestCase):
    def test_clickable_taskbar_and_json_menu_methods(self):
        source = (ROOT / 'rpc_client.py').read_text(encoding='utf8')
        tree = ast.parse(source)
        taskbar = next(cls for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name=='EmulatedTaskbar')
        work = next(cls for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name=='CreatedWindow')
        client = next(cls for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name=='RpcTestClient')
        self.assertIn('mousePressEvent', [node.name for node in taskbar.body if isinstance(node, ast.FunctionDef)])
        for method in ('configure_start_menu','show_start_menu'):
            self.assertIn(method, [node.name for node in work.body if isinstance(node, ast.FunctionDef)])
        handle_event = next(n for n in client.body if isinstance(n,ast.FunctionDef) and n.name=='_handle_event')
        self.assertIn('menu_config',ast.unparse(handle_event))
        resize = next(n for n in work.body if isinstance(n,ast.FunctionDef) and n.name=='resizeEvent')
        self.assertIn('self.taskbar.raise_()',ast.unparse(resize))

    def test_server_sends_menu_after_login_and_rpc(self):
        source=(ROOT/'pythonbde'/'protocol.py').read_text(encoding='utf8')
        tree=ast.parse(source)
        server=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BDEServer')
        process=next(n for n in server.body if isinstance(n,ast.FunctionDef) and n.name=='_process_pending')
        code=ast.unparse(process)
        self.assertIn("req.get('action') == 'login'",code)
        self.assertLess(code.index('self._request_client_window(sock, state)'),
                        code.index('serialized_temporary_menu('))
        self.assertIn("state.get('system_mode') in ('win95', 'winXP')",code)


if __name__ == '__main__':
    unittest.main()
