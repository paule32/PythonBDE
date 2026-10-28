"""v0.5.3: compiled/verified .cpy module round trips + desktop UI contracts."""
import ast
import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from pythonbde.cpy_modules import (
    ModuleSigner, MODULE_IDS, MAX_CPY_EVENT_BYTES, compiled_module_package,
    verify_and_load,
)

ROOT = Path(__file__).resolve().parents[1]
CLIENT = (ROOT / 'rpc_client.py').read_text(encoding='utf-8')
CLIENT_AST = ast.parse(CLIENT)


def fake_pyqt():
    """Mock ONLY package imports: signature and bytecode run in real CPython."""
    qt = types.ModuleType('PyQt5')
    widgets = types.ModuleType('PyQt5.QtWidgets')

    class Widget:
        def __init__(self, *args, **kwargs):
            self.placeholder = ''
        def setPlaceholderText(self, text):
            self.placeholder = text
        def setReadOnly(self, state):
            self.readonly = state
        def setPlainText(self, text):
            self.text = text

    class Layout(Widget):
        def addWidget(self, widget):
            pass

    class Button(Widget):
        @property
        def clicked(self):
            return self
        def connect(self, cb):
            pass

    for name in ('QWidget', 'QLabel', 'QLineEdit', 'QPlainTextEdit'):
        setattr(widgets, name, Widget)
    widgets.QVBoxLayout = Layout
    widgets.QPushButton = Button
    return {'PyQt5': qt, 'PyQt5.QtWidgets': widgets}


class SignedCpyRoundtrip(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.signer = ModuleSigner(root/'users.dbf')
        self.pub = self.signer.public_path

    def test_packages_are_real_zip_with_python_bytecode_and_manifest(self):
        for mid in MODULE_IDS:
            with self.subTest(module=mid):
                raw = compiled_module_package(mid)
                with zipfile.ZipFile(io.BytesIO(raw)) as package:
                    self.assertEqual({'manifest.json', 'module.pyc'}, set(package.namelist()))
                    manifest = json.loads(package.read('manifest.json'))
                    self.assertEqual(mid, manifest['id'])
                    self.assertEqual(sys.implementation.cache_tag, manifest['pythonTag'])
                    self.assertEqual(importlib.util.MAGIC_NUMBER, package.read('module.pyc')[:4])

    def test_signed_load_after_independent_pinning(self):
        for mid in MODULE_IDS:
            with self.subTest(module=mid):
                packet = self.signer.event(mid, 'session-101', 'm1')
                with patch.dict(sys.modules, fake_pyqt()):
                    manifest, mod = verify_and_load(packet, self.pub)
                    # Full GUI modules require a real Qt5 runtime. A separate
                    # test verifies their pure engines, and this test verifies
                    # signature/bytecode loading without constructing a window.
                    widget = mod.create_widget(None) if mid not in ('calculator', 'notepad', 'wordpad', 'spreadsheet') else None
                self.assertEqual(mid, manifest['id'])
                self.assertTrue(callable(mod.create_widget))
                if mid not in ('calculator', 'notepad', 'wordpad', 'spreadsheet'):
                    self.assertIsNotNone(widget)
                self.assertLess(len(json.dumps(packet).encode()), MAX_CPY_EVENT_BYTES)

    def test_private_key_owner_only_on_linux(self):
        if sys.platform.startswith('linux'):
            self.assertEqual(0o600, stat.S_IMODE(self.signer.private_path.stat().st_mode))
        self.assertNotIn(b'PRIVATE KEY', self.signer.public_path.read_bytes())

    def test_signing_identity_persists(self):
        again = ModuleSigner(Path(self.temp.name)/'users.dbf')
        self.assertEqual(self.signer.key_id, again.key_id)

    def test_tampered_package_rejected(self):
        packet = self.signer.event('notepad', 'session-a', 'm1')
        raw = bytearray(base64.b64decode(packet['cpy']))
        raw[-10] ^= 1
        packet['cpy'] = base64.b64encode(raw).decode()
        with self.assertRaises(ValueError):
            verify_and_load(packet, self.pub)

    def test_replay_into_another_session_rejected(self):
        packet = self.signer.event('notepad', 'session-a', 'm1')
        for field, value in [('client', 'session-other'), ('requestId', 'm2'), ('moduleId', 'calculator')]:
            p = dict(packet, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_and_load(p, self.pub)

    def test_untrusted_publisher_and_absent_pin_rejected(self):
        packet = self.signer.event('notepad', 'session-a', 'm1')
        with self.assertRaises(FileNotFoundError):
            verify_and_load(packet, Path(self.temp.name)/'no-trusted-key.pem')
        other = Path(self.temp.name)/'elsewhere'
        other.mkdir()
        second = ModuleSigner(other/'users.dbf')
        with self.assertRaises(ValueError):
            verify_and_load(packet, second.public_path)

    def test_reject_invalid_module_identifier_and_protocol_oversize(self):
        for name in ('../../etc/passwd', 'os.system', 'unsupported', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.signer.event(name, 'session-a', 'm1')
        packet = self.signer.event('notepad', 'session-a', 'm1')
        packet['cpy'] = 'A' * 200_000
        with self.assertRaises(ValueError):
            verify_and_load(packet, self.pub)

    def test_reject_incorrect_python_cache_tag_after_valid_signature(self):
        with zipfile.ZipFile(io.BytesIO(compiled_module_package('notepad'))) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            blob = archive.read('module.pyc')
        manifest['pythonTag'] = 'cpython-other-version'
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('module.pyc', blob)
        raw = output.getvalue()
        packet = self.signer.event('notepad','session-a','m1')
        from pythonbde.cpy_modules import _signature_input
        import hashlib
        packet['cpy'] = base64.b64encode(raw).decode()
        packet['sha256'] = hashlib.sha256(raw).hexdigest()
        packet['signature'] = base64.b64encode(self.signer.private_key.sign(
            _signature_input('notepad', 'session-a', 'm1', raw))).decode()
        with self.assertRaisesRegex(ValueError, 'ABI'):
            verify_and_load(packet, self.pub)


class DesktopUiContract(unittest.TestCase):
    def test_xp_sky_and_hill_vector_painting(self):
        self.assertIn('XP_SKY_COLOR = "#4EAAF0"', CLIENT)
        self.assertIn('hill.cubicTo(', CLIENT)
        self.assertIn("QColor('#27812b')", CLIENT)
        self.assertIn("self.workspace.setBackground(QBrush(picture))", CLIENT)

    def test_icon_size_title_pressed_overlay_and_cells(self):
        self.assertIn('DESKTOP_GRID = 48', CLIENT)
        self.assertIn('DESKTOP_ICON_SIZE = 48', CLIENT)
        self.assertIn("QColor(50, 130, 255, 115)", CLIENT)
        self.assertIn('self._pressed = False', CLIENT)
        self.assertIn("'Disconnect'", CLIENT)
        self.assertIn('Qt.AlignHCenter', CLIENT)
        self.assertIn('snapped_to_grid(glyph_x', CLIENT)
        self.assertIn('DesktopGridOverlay', CLIENT)

    def test_snap_grid_math(self):
        node = next(n for n in CLIENT_AST.body if isinstance(n,ast.FunctionDef) and n.name=='snapped_to_grid')
        env = {'DESKTOP_GRID':48,'DESKTOP_ICON_SIZE':48}
        exec(compile(ast.Module(body=[node],type_ignores=[]), '<grid>', 'exec'),env)
        snap = env['snapped_to_grid']
        self.assertEqual((48,96), snap(49,80,640,480))
        self.assertEqual((0,0), snap(-40,-9,640,480))
        self.assertEqual((592,432), snap(9999,9999,640,480))

    def test_mdi_windows_minimize_restore_and_task_buttons(self):
        self.assertIn('QMdiArea(self)', CLIENT)
        self.assertIn('QMdiSubWindow(self.workspace)', CLIENT)
        self.assertIn('sub.showMinimized()', CLIENT)
        self.assertIn('sub.showNormal()', CLIENT)
        self.assertIn('self.taskbar.set_app(module_id, title', CLIENT)
        self.assertIn('self.taskbar.remove_app(module_id)', CLIENT)
        self.assertIn('self.taskbar.raise_()', CLIENT)

    def test_module_request_is_only_by_allowed_id_and_no_shell(self):
        self.assertIn('if menu_id not in MODULE_IDS', CLIENT)
        self.assertIn('verify_and_load(packet, trusted_path)', CLIENT)
        self.assertIn('self._client_window.launch_module_widget(', CLIENT)
        protocol = (ROOT/'pythonbde'/'protocol.py').read_text('utf8')
        self.assertIn("if action == 'load_module'", protocol)
        self.assertIn('self._module_signer.event(', protocol)


class ModuleServerProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT/'pythonbde'/'protocol.py').read_text('utf8'))
        server_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BDEServer')
        dispatch = next(n for n in server_cls.body if isinstance(n, ast.FunctionDef) and n.name == '_dispatch')
        from pythonbde.auth import AuthError
        from pythonbde.cpy_modules import MODULE_IDS, ID_RE
        env = {'AuthError': AuthError, 'MODULE_IDS': MODULE_IDS, 'ID_RE': ID_RE}
        exec(compile(ast.Module(body=[dispatch], type_ignores=[]),'<server dispatch>','exec'), env)
        cls.dispatch = staticmethod(env['_dispatch'])

    def test_module_request_requires_authenticated_gui_session(self):
        from pythonbde.auth import AuthError
        request = {'action': 'load_module', 'moduleId': 'notepad', 'requestId': 'm1'}
        for state in ({'username':None,'system_mode':'winXP'},
                      {'username':'user','system_mode':'con'}):
            with self.subTest(state=state), self.assertRaises((AuthError, ValueError)):
                self.dispatch(None, state, request)

    def test_valid_module_request_queues_exact_identity(self):
        state = {'username':'user','system_mode':'win95'}
        result = self.dispatch(None, state,
                               {'action':'load_module','moduleId':'notepad','requestId':'m12'})
        self.assertEqual({'moduleQueued': True,'moduleId':'notepad','requestId':'m12'}, result)
        self.assertEqual({'moduleId':'notepad','requestId':'m12'}, state['_module_on_request'])

    def test_bad_ids_never_create_pending_module(self):
        for name in ('../secrets', 'notpython', 'run.exe', None):
            state = {'username':'user','system_mode':'winXP'}
            with self.subTest(name=name), self.assertRaises((ValueError, TypeError)):
                self.dispatch(None, state,
                              {'action':'load_module','moduleId':name,'requestId':'m1'})
            self.assertNotIn('_module_on_request', state)

    def test_request_id_is_constrained(self):
        state = {'username':'user','system_mode':'winXP'}
        for rid in ('', '../m1', 123, 'm!' , 'x'*100):
            with self.subTest(rid=rid), self.assertRaises((ValueError, TypeError)):
                self.dispatch(None, state,
                              {'action':'load_module','moduleId':'notepad','requestId':rid})


if __name__=='__main__':
    unittest.main()
