"""Qt-free regression checks for PythonBDE v0.4.9 RPC client layout."""
import ast
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "rpc_client.py").read_text("utf-8")
MODULE = ast.parse(SOURCE)
EXPECTED_SIZES = (
    (640, 480), (800, 600), (1024, 768), (1280, 720),
    (1280, 768), (1280, 800), (1280, 1024),
)


def class_method(name, method):
    cls = next(x for x in MODULE.body if isinstance(x, ast.ClassDef) and x.name == name)
    return next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == method)


class RpcClientLayout049Tests(unittest.TestCase):
    def test_exact_display_resolutions_order(self):
        node = next(x for x in MODULE.body if isinstance(x, ast.Assign)
                    and any(isinstance(y, ast.Name) and y.id == "WINDOW_SIZES" for y in x.targets))
        self.assertEqual(ast.literal_eval(node.value), EXPECTED_SIZES)
        self.assertIn('self.geometry_combo.addItem(f"{width} x {height}", (width, height))', SOURCE)

    def test_client_work_area_can_shrink_but_cannot_grow_larger(self):
        init = class_method("CreatedWindow", "__init__")
        body = ast.unparse(init)
        self.assertIn("self.setMinimumSize(120, 90)", body)
        self.assertIn("self.setMaximumSize(*geometry)", body)
        self.assertIn("self.resize(*geometry)", body)
        self.assertLess(body.index('self.setMaximumSize(*geometry)'), body.index('self.resize(*geometry)'))
        self.assertNotIn('setFixedSize', body)
        self.assertIn('window = CreatedWindow(self.username.text().strip(), self._server_name,', SOURCE)
        self.assertIn('mode=mode, tui_geometry=', SOURCE)

    def test_header_gradient_and_text(self):
        header = class_method("RemoteDesktopHeader", "paintEvent")
        body = ast.unparse(header)
        self.assertIn('QLinearGradient(0, 0, 0, self.height())', body)
        self.assertIn("gradient.setColorAt(0.0, QColor('#2472BF'))", body)
        self.assertIn("gradient.setColorAt(1.0, QColor('#FFFFFF'))", body)
        self.assertIn("'Remotedesktop'", body)
        self.assertIn("'Connection'", body)
        self.assertIn('drawRoundedRect', body)
        self.assertLess(SOURCE.index('layout.addWidget(self.connection_header)'),
                        SOURCE.index('layout.addWidget(self.tabs)'))

    def test_common_tab_contains_credentials_and_buttons(self):
        init = ast.unparse(class_method('RpcTestClient', '__init__'))
        self.assertIn('self.tabs.addTab(self.common_tab, "Common")', SOURCE)
        self.assertIn('self.tabs.addTab(self.display_tab, "Display")', SOURCE)
        for label in ('Server IP / host', 'TCP Port', 'Username', 'Password'):
            self.assertIn('form.addRow("' + label + '"', SOURCE)
        self.assertIn('self.port = QSpinBox()', SOURCE)
        self.assertIn('self.port.setValue(port if 1 <= port <= 65535 else 43650)', SOURCE)
        self.assertIn('common_layout.addLayout(buttons)', SOURCE)
        self.assertNotIn('settings_dock', SOURCE)
        self.assertNotIn('QDockWidget', SOURCE)

    def test_display_tab_retains_horizontal_controls_and_dummy_fullscreen(self):
        self.assertIn('display_layout = QHBoxLayout(display_box)', SOURCE)
        self.assertIn('display_layout.addLayout(modes_layout, 1)', SOURCE)
        self.assertIn('display_layout.addLayout(geometry_layout, 2)', SOURCE)
        self.assertIn('QRadioButton("Windowed")', SOURCE)
        self.assertIn('QRadioButton("Full Screen")', SOURCE)
        self.assertIn('self.fullscreen_radio.setEnabled(False)', SOURCE)

    def test_status_bar_and_menu_without_settings(self):
        self.assertIn('self.status = QLabel("Disconnected")', SOURCE)
        self.assertIn('self.statusBar().addPermanentWidget(self.status)', SOURCE)
        self.assertIn('self.status.setText("Connecting ...")', SOURCE)
        self.assertIn('self.status.setText("Disconnected")', SOURCE)
        self.assertNotIn('layout.addWidget(self.status)', SOURCE)
        menus = ast.unparse(class_method('RpcTestClient', '_init_menu'))
        self.assertIn('addMenu(\'File\')', menus)
        self.assertIn('addMenu(\'Help\')', menus)
        self.assertNotIn('Settings', menus)

    def test_login_rpc_and_close_behavior_retained(self):
        self.assertIn('self._show_client_window()', SOURCE)
        self.assertIn('window.set_rpc(packet)', SOURCE)
        self.assertIn('window.closed.connect(self._on_client_window_closed)', SOURCE)
        self.assertIn('self.disconnect_client()', ast.unparse(class_method('RpcTestClient', '_on_client_window_closed')))
        self.assertIn('apply_application_theme(self._dark_theme)', SOURCE)


if __name__ == '__main__':
    unittest.main()
