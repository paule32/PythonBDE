"""v0.5.0: platform-neutral emulation/geometry contract and Qt5 source layout."""
import ast
import unittest
from pathlib import Path

from pythonbde.emulation import GUI_SIZES, TUI_SIZES, validate_client_display
from pythonbde.rpc import create_window_request, result_message, validate_result

ROOT = Path(__file__).resolve().parents[1]
CLIENT = (ROOT / 'rpc_client.py').read_text(encoding='utf-8')
TREE = ast.parse(CLIENT)
CLIENT_CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'RpcTestClient')


def method(name):
    return next(n for n in CLIENT_CLASS.body if isinstance(n, ast.FunctionDef) and n.name == name)


class EmulationContract(unittest.TestCase):
    def test_default_legacy_mode(self):
        self.assertEqual(('winXP', {'unit':'pixels','width':640,'height':480}),
                         validate_client_display())

    def test_all_gui_resolutions_for_win95_and_winxp(self):
        for mode in ('win95','winXP'):
            for w,h in GUI_SIZES:
                display = {'width':w, 'height':h, 'unit':'pixels'}
                with self.subTest(mode=mode, resolution=(w,h)):
                    self.assertEqual((mode, display), validate_client_display(mode, display))

    def test_all_console_character_resolutions(self):
        self.assertEqual(((80,25),(80,50)), TUI_SIZES)
        for w,h in TUI_SIZES:
            expected={'width':w,'height':h,'unit':'cells'}
            self.assertEqual(('con', expected), validate_client_display('con', expected))

    def test_bad_modes_and_displays_rejected(self):
        for bad in ('xp','WIN95','console','',False,1,[],{},'win95\n'):
            with self.subTest(mode=bad), self.assertRaises(ValueError):
                validate_client_display(bad)
        for bad in (None, False, True, '640x480', {'unit':'pixels','width':True,'height':480},
                    {'unit':'cells','width':80,'height':50},
                    {'unit':'pixels','width':9999,'height':9999},
                    {'unit':'pixels','width':640},
                    {'unit':'pixels','width':-640,'height':480}):
            if bad is None:
                continue
            with self.subTest(display=bad), self.assertRaises(ValueError):
                validate_client_display('winXP', bad)
        with self.assertRaises(ValueError):
            validate_client_display('con', {'unit':'pixels','width':80,'height':25})
        with self.assertRaises(ValueError):
            validate_client_display('con', {'unit':'cells','width':80,'height':100})

    def test_client_rpc_mode_and_geometry_and_ack(self):
        for mode,size,unit in [('win95',(800,600),'pixels'),('winXP',(1024,768),'pixels'),
                               ('con',(80,50),'cells')]:
            payload={'unit':unit, 'width':size[0], 'height':size[1]}
            packet=create_window_request('session-123','10.0.0.4',system_mode=mode,display=payload)
            with self.subTest(mode=mode):
                self.assertEqual(mode, packet['systemMode'])
                self.assertEqual(payload, packet['display'])
                self.assertEqual('CreateWindow',packet['setFunc'])
                self.assertEqual((0,''), validate_result(result_message(packet,0),packet,'session-123'))

    def test_reject_unsupported_server_rpc_modes(self):
        with self.assertRaises(ValueError):
            create_window_request('sess','127.0.0.1',system_mode='win2000')


class ToggleStub:
    def __init__(self, value=False):
        self.value = value
        self.enabled = True
        self.blocked = False
    def isChecked(self):
        return self.value
    def setChecked(self, checked):
        self.value = bool(checked)
    def setEnabled(self, enabled):
        self.enabled = bool(enabled)
    def blockSignals(self, blocked):
        self.blocked = bool(blocked)


class EmulationUiLogic(unittest.TestCase):
    def setup_client(self):
        from types import SimpleNamespace
        from pythonbde.emulation import validate_client_display
        ns = {'validate_client_display':validate_client_display,
              'TUI_WINDOW_SIZES':TUI_SIZES, 'WINDOW_SIZES':GUI_SIZES}
        for name in ('_select_system_mode','_select_geometry_mode','_display_selection'):
            node=method(name)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<emulation client>', 'exec'),ns)
        cl=SimpleNamespace(win95_radio=ToggleStub(False), winxp_radio=ToggleStub(True),
                           console_radio=ToggleStub(False),
                           gui_geometry_radio=ToggleStub(True),
                           tui_geometry_radio=ToggleStub(False),
                           geometry_combo=SimpleNamespace(currentData=lambda:(1280,720), setEnabled=lambda x:None),
                           tui_geometry_combo=SimpleNamespace(currentData=lambda:(80,50), setEnabled=lambda x:None),
                           _last_gui_mode='winXP')
        cl._select_system_mode=lambda mode:ns['_select_system_mode'](cl,mode)
        cl._select_geometry_mode=lambda mode:ns['_select_geometry_mode'](cl,mode)
        cl._display_selection=lambda:ns['_display_selection'](cl)
        return cl

    def test_console_selection_enables_tui_and_disables_gui(self):
        cl=self.setup_client()
        cl.console_radio.setChecked(True)
        cl.winxp_radio.setChecked(False)
        cl._select_system_mode('con')
        self.assertTrue(cl.tui_geometry_radio.isChecked())
        self.assertFalse(cl.gui_geometry_radio.isChecked())
        self.assertEqual(('con',{'unit':'cells','width':80,'height':50}),cl._display_selection())

    def test_win95_selection_enables_gui_and_protocol_mode(self):
        cl=self.setup_client()
        cl.win95_radio.setChecked(True)
        cl.winxp_radio.setChecked(False)
        cl._select_system_mode('win95')
        self.assertTrue(cl.gui_geometry_radio.isChecked())
        self.assertFalse(cl.tui_geometry_radio.isChecked())
        self.assertEqual(('win95',{'unit':'pixels','width':1280,'height':720}),cl._display_selection())


class EmulationLayout(unittest.TestCase):
    def test_common_left_fields_and_right_emulation_panel(self):
        source = ast.unparse(method('__init__'))
        self.assertIn('common_panels = QHBoxLayout()',source)
        self.assertIn("QGroupBox('Connection')",source)
        self.assertIn("QGroupBox('System Emulation')",source)
        self.assertIn('common_panels.addWidget(connection_panel, 3)',source)
        self.assertIn('common_panels.addWidget(emulation_panel, 2)',source)
        for label in ('Windows 95','Windows XP','Console'):
            self.assertIn(f"QRadioButton('{label}')",source)
        for label in ('Server IP / host','TCP Port','Username','Password'):
            self.assertIn(f"form.addRow('{label}'",source)

    def test_display_geometry_radio_and_tui_sizes(self):
        source = ast.unparse(method('__init__'))
        self.assertIn("QRadioButton('GUI Geometry')",source)
        self.assertIn("QRadioButton('TUI Geometry')",source)
        self.assertIn('QGridLayout()',source)
        self.assertIn('geometry_layout.addWidget(self.gui_geometry_radio, 0, 0)',source)
        self.assertIn('geometry_layout.addWidget(self.geometry_combo, 0, 1)',source)
        self.assertIn('geometry_layout.addWidget(self.tui_geometry_radio, 1, 0)',source)
        self.assertIn('geometry_layout.addWidget(self.tui_geometry_combo, 1, 1)',source)
        self.assertIn('self.geometry_mode_group = QButtonGroup(self)',source)
        self.assertIn('self.display_mode_group = QButtonGroup(self)',source)
        self.assertIn('self.system_mode_group = QButtonGroup(self)',source)
        self.assertIn('self.fullscreen_radio.setEnabled(False)',source)

    def test_payload_in_tls_login(self):
        source=ast.unparse(method('_handle_hello'))
        self.assertGreaterEqual(source.count('systemMode=self._requested_mode'),1)
        self.assertGreaterEqual(source.count('display=self._requested_display'),1)
        selected=ast.unparse(method('_display_selection'))
        self.assertIn("'cells'",selected)
        self.assertIn("'pixels'",selected)

    def test_window_skins_and_console_are_distinct(self):
        cls=next(x for x in TREE.body if isinstance(x,ast.ClassDef) and x.name=='CreatedWindow')
        init=ast.unparse(next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='__init__'))
        self.assertIn('EmulatedTaskbar(mode, self)',init)
        self.assertIn('self.terminal_view = terminal',init)
        self.assertIn('QFontMetrics',init)
        self.assertIn('self.setMaximumSize(*geometry)',init)
        self.assertIn('DraggableCloseIcon(self)',init)
        taskbar=next(x for x in TREE.body if isinstance(x,ast.ClassDef) and x.name=='EmulatedTaskbar')
        paint=ast.unparse(next(x for x in taskbar.body if isinstance(x,ast.FunctionDef) and x.name=='paintEvent'))
        self.assertIn("'win95'",paint)
        self.assertIn('QLinearGradient',paint)


if __name__ == '__main__':
    unittest.main()
