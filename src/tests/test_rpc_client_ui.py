"""Qt-free functional checks for the actual RPC Client controller methods."""
import ast
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import unittest
from types import SimpleNamespace

SOURCE = (Path(__file__).resolve().parents[1] / 'rpc_client.py').read_text('utf-8')
AST = ast.parse(SOURCE)
CLS = next(n for n in AST.body if isinstance(n, ast.ClassDef) and n.name == 'RpcTestClient')
NAMES = {'_on_client_window_closed', '_disconnected', '_handle_reply', '_log'}
METHODS = [n for n in CLS.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
NS = {'log_line': None, 'MAX_LOG_LINES': 500, 'QMessageBox': SimpleNamespace(warning=lambda *args: None)}
fmt = next(n for n in AST.body if isinstance(n, ast.FunctionDef) and n.name == 'log_line')
exec(compile(ast.Module(body=[fmt], type_ignores=[]), 'log_line', 'exec'), {'datetime': datetime}, NS)
exec(compile(ast.Module(body=METHODS, type_ignores=[]), 'rpc_client_functions', 'exec'), NS)

class StubEditor:
    def __init__(self):
        self.content = ''
    def setPlainText(self, contents):
        self.content = contents

class StubLabel:
    def __init__(self):
        self.value = ''
    def setText(self, value):
        self.value = value

class StubWindow:
    def __init__(self):
        self.log = StubEditor()
        self.deleted = False
    def deleteLater(self):
        self.deleted = True

class StubClient:
    _on_client_window_closed = NS['_on_client_window_closed']
    _disconnected = NS['_disconnected']
    _handle_reply = NS['_handle_reply']
    _log = NS['_log']
    def __init__(self):
        self._pending = deque()
        self._buffer = bytearray()
        self._handled_rpc_ids = set()
        self._log_lines = deque(maxlen=500)
        self.log = StubEditor()
        self._client_window = StubWindow()
        self._logged_in = False
        self._closing_program = False
        self._window_teardown = False
        self.status = StubLabel()
        self.login_button = SimpleNamespace(setEnabled=lambda value: None)
        self.disconnect_button = SimpleNamespace(setEnabled=lambda value: None)
        self.username = SimpleNamespace(text=lambda: 'alice')
        self.calls = []
    def _show_client_window(self):
        self.calls.append('open-client-window')
    def _close_client_window(self):
        self.calls.append('close-client-window')
        self._client_window = None
    def disconnect_client(self):
        self.calls.append('disconnect')
    def show(self):
        self.calls.append('show-login-screen')
    def raise_(self):
        pass
    def activateWindow(self):
        pass

class ClientUiTests(unittest.TestCase):
    def test_log_format_datetime_code_and_sanitized_one_line(self):
        dt = datetime(2026, 10, 26, 13, 4, 5, tzinfo=timezone.utc)
        self.assertEqual('2026-10-26 13:04:05 | 429 | please wait 55 seconds',
                         NS['log_line'](429, 'please wait\n55 seconds', dt))

    def test_log_newest_first_and_max500(self):
        fake = StubClient()
        for n in range(505):
            fake._log('entry %03d' % n)
        lines = fake.log.content.splitlines()
        self.assertEqual(500, len(lines))
        self.assertIn('entry 504', lines[0])
        self.assertIn('entry 005', lines[-1])
        self.assertEqual(fake.log.content, fake._client_window.log.content)

    def test_successful_login_opens_selected_client_window(self):
        fake = StubClient()
        fake._pending.append('login')
        fake._handle_reply({'ok': True, 'data': {'USERNAME':'alice'}})
        self.assertTrue(fake._logged_in)
        self.assertIn('open-client-window', fake.calls)

    def test_client_window_close_returns_login_and_disconnects(self):
        fake = StubClient()
        window = fake._client_window
        fake._on_client_window_closed()
        self.assertTrue(window.deleted)
        self.assertIsNone(fake._client_window)
        self.assertEqual(fake.calls[-2:], ['show-login-screen','disconnect'])

    def test_server_disconnect_closes_rpc_window_and_shows_login(self):
        fake = StubClient()
        fake._logged_in = True
        fake._disconnected()
        self.assertFalse(fake._logged_in)
        self.assertEqual(fake.calls[:2], ['close-client-window', 'show-login-screen'])

    def test_required_menus_tabs_sizes_and_close_behavior(self):
        self.assertIn('addMenu("File")', SOURCE)
        self.assertIn('addAction("Close", self.close)', SOURCE)
        self.assertNotIn('addMenu("Settings")', SOURCE)
        self.assertIn('addMenu("Help")', SOURCE)
        self.assertIn('addAction("About ...", self.show_about)', SOURCE)
        self.assertIn('self.tabs = QTabWidget(central)', SOURCE)
        self.assertIn('self.tabs.addTab(self.common_tab, "Common")', SOURCE)
        self.assertIn('self.tabs.addTab(self.display_tab, "Display")', SOURCE)
        self.assertIn('QGroupBox("Display:")', SOURCE)
        self.assertIn('QRadioButton("Full Screen")', SOURCE)
        self.assertIn('self.fullscreen_radio.setEnabled(False)', SOURCE)
        self.assertIn('self.statusBar().addPermanentWidget(self.status)', SOURCE)
        self.assertIn('layout.addWidget(self.log, stretch=1)', SOURCE)
        self.assertIn('QTimer.singleShot(0, QApplication.instance().quit)', SOURCE)


if __name__ == '__main__':
    unittest.main()
