"""GUI-Start/Stop-Regressionstests ohne grafisches Qt-Testsystem.

Prüft den *tatsächlichen* MainWindow-Methoden-Code in einem leichtgewichtigen
Test-Doppel, statt eine ähnliche Start/Stop-Logik nur separat nachzubauen.
Ein visueller Test auf Windows/Linux mit PyQt5 bleibt zusätzlich erforderlich.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "pythonbde" / "gui.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
              and node.name == "MainWindow")
MANAGER = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
               and node.name == "UserManagerDock")
LOGPANEL = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
                and node.name == "LogStatusPanel")


class TestGuiStructure(unittest.TestCase):
    def test_status_labels_only_in_information_dialog_and_statusbar(self):
        def attrs(node):
            return {target.attr for assignment in ast.walk(node)
                    if isinstance(assignment, ast.Assign)
                    for target in assignment.targets if isinstance(target, ast.Attribute)}
        for label in ("server_info", "crypto_info", "paths_info"):
            self.assertNotIn(label, attrs(MANAGER))
            self.assertNotIn(label, attrs(WINDOW))
        self.assertIn("status_server", attrs(WINDOW))
        self.assertIn("status_logins", attrs(WINDOW))
        window_source = ast.get_source_segment(SOURCE.read_text(encoding="utf8"), WINDOW)
        self.assertNotIn("setCentralWidget(", window_source)
        self.assertNotIn("self.logging_dock =", window_source)
        self.assertIn("Qt.TopDockWidgetArea", window_source)

    def test_start_button_is_left_of_stop_button(self):
        gui_source = SOURCE.read_text(encoding="utf8")
        panel_source = ast.get_source_segment(gui_source, LOGPANEL)
        self.assertLess(panel_source.index('QPushButton("Start Server")'),
                        panel_source.index('QPushButton("Stop Server")'))
        self.assertLess(panel_source.index('controls.addWidget(self.start_button)'),
                        panel_source.index('controls.addWidget(self.stop_button)'))


def main_window_methods():
    names = {"start_server", "stop_server", "update_status"}
    method_nodes = [node for node in WINDOW.body if isinstance(node, ast.FunctionDef)
                    and node.name in names]
    # Die Methoden werden unverändert aus der Produktionsdatei übernommen.
    namespace = {"OSError": OSError, "ValueError": ValueError,
                 "QMessageBox": SimpleNamespace(warning=lambda *args: None)}
    exec(compile(ast.Module(body=method_nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


METHODS = main_window_methods()


class FakeControl:
    def __init__(self):
        self.enabled = None
        self.text = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, value):
        self.text = value


class FakeListener:
    def __init__(self):
        self.running = False

    def isListening(self):
        return self.running


class FakeServer:
    def __init__(self):
        self.listener = FakeListener()
        self.starts = 0
        self.stops = 0
        self.fail = False
        self.bind_ip = "127.0.0.1"

    def start(self, port, ip, server_id, **tls_settings):
        self.starts += 1
        if self.fail:
            raise OSError("Port bereits in Benutzung")
        self.listener.running = True

    def stop(self):
        self.stops += 1
        self.listener.running = False

    def status_snapshot(self):
        return {"port": 43650 if self.listener.running else 0,
                "login_count": 0}


class FakeWindow:
    start_server = METHODS["start_server"]
    stop_server = METHODS["stop_server"]
    update_status = METHODS["update_status"]

    def __init__(self):
        self.server = FakeServer()
        self.settings = SimpleNamespace(port=43650, ip="127.0.0.1", server_id="test-id")
        self.manager_dock = SimpleNamespace(
            log_status=SimpleNamespace(
                start_button=FakeControl(), stop_button=FakeControl(),
                set_running=self._set_running))
        self.action_start = FakeControl()
        self.action_stop = FakeControl()
        self.status_server = FakeControl()
        self.status_logins = FakeControl()
        self._starting_server = False
        self.events = []
        self.update_status()

    def _set_running(self, running):
        self.manager_dock.log_status.start_button.setEnabled(not running)
        self.manager_dock.log_status.stop_button.setEnabled(running)

    def record(self, code, message):
        self.events.append((code, message))


class TestGuiStartControls(unittest.TestCase):
    def test_successful_start_disables_button_and_blocks_second_start(self):
        wnd = FakeWindow()
        self.assertTrue(wnd.manager_dock.log_status.start_button.enabled)
        self.assertFalse(wnd.manager_dock.log_status.stop_button.enabled)
        wnd.settings.tls_enabled = True
        wnd.settings.tls_certificate = "certificates/server.crt"
        wnd.settings.tls_private_key = "certificates/server.key"
        wnd.start_server()
        self.assertEqual(1, wnd.server.starts)
        self.assertFalse(wnd.manager_dock.log_status.start_button.enabled)
        self.assertFalse(wnd.action_start.enabled)
        self.assertTrue(wnd.manager_dock.log_status.stop_button.enabled)
        self.assertTrue(wnd.action_stop.enabled)
        wnd.settings.tls_enabled = True
        wnd.settings.tls_certificate = "certificates/server.crt"
        wnd.settings.tls_private_key = "certificates/server.key"
        wnd.start_server()  # bewusster Doppelaufruf, auch ohne disabled Qt-Button
        self.assertEqual(1, wnd.server.starts)
        wnd.stop_server()
        self.assertFalse(wnd.server.listener.isListening())
        self.assertTrue(wnd.manager_dock.log_status.start_button.enabled)
        self.assertFalse(wnd.manager_dock.log_status.stop_button.enabled)
        wnd.settings.tls_enabled = True
        wnd.settings.tls_certificate = "certificates/server.crt"
        wnd.settings.tls_private_key = "certificates/server.key"
        wnd.start_server()
        self.assertEqual(2, wnd.server.starts)

    def test_failed_start_keeps_start_button_enabled(self):
        wnd = FakeWindow()
        wnd.server.fail = True
        wnd.settings.tls_enabled = True
        wnd.settings.tls_certificate = "certificates/server.crt"
        wnd.settings.tls_private_key = "certificates/server.key"
        wnd.start_server()
        self.assertFalse(wnd.server.listener.isListening())
        self.assertTrue(wnd.manager_dock.log_status.start_button.enabled)
        self.assertFalse(wnd.manager_dock.log_status.stop_button.enabled)
        self.assertEqual(400, wnd.events[0][0])

    def test_attempt_in_progress_is_guarded(self):
        wnd = FakeWindow()
        wnd._starting_server = True
        wnd.settings.tls_enabled = True
        wnd.settings.tls_certificate = "certificates/server.crt"
        wnd.settings.tls_private_key = "certificates/server.key"
        wnd.start_server()
        self.assertEqual(0, wnd.server.starts)
        self.assertFalse(wnd.manager_dock.log_status.start_button.enabled)
        self.assertFalse(wnd.manager_dock.log_status.stop_button.enabled)


if __name__ == "__main__":
    unittest.main()
