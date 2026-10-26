"""GUI-Strukturtest – auf CI ohne native PyQt-Bibliothek ausführbar."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'pythonbde'
GUI = (ROOT / 'gui.py').read_text(encoding='utf-8')
DOCK = (ROOT / 'blocking_dock.py').read_text(encoding='utf-8')


class BlockingLayoutTests(unittest.TestCase):
    def test_menu_is_next_to_manager_and_has_requested_items(self):
        source = GUI[GUI.index('        manager_menu ='):GUI.index('        help_menu =')]
        self.assertIn('block_menu = self.menuBar().addMenu("Block")', source)
        self.assertLess(source.index('"Manager"'),source.index('"Block"'))
        for title in ('IP Range Blocking', 'Port Range Blocking', 'IP Blocking', 'Port Blocking', 'Block Domain'):
            self.assertIn(title,source)

    def test_docking_splitters_log_and_context_menu(self):
        for token in ('QSplitter(Qt.Vertical', 'QSplitter(Qt.Horizontal',
                      'QTreeWidget(', 'QPlainTextEdit()', 'customContextMenuRequested',
                      'NEW_BUTTONS[category]', "QPushButton('Save')", 'self.delete_rule'):
            self.assertIn(token,DOCK)
        self.assertIn('_show_exclusive_dock(self.blocking_dock)', GUI)

    def test_protocol_checks_before_authentication(self):
        source = (ROOT / 'protocol.py').read_text(encoding='utf-8')
        code = source[source.index('        if action == "login":'):source.index('        if action == "logout":')]
        self.assertLess(code.index('registry.blocked('), code.index('self.users.authenticate('))
        self.assertGreater(code.index('guard.check('), code.index('self.users.authenticate('))
        self.assertIn('state.get(\'peer_port\'',code)


if __name__ == '__main__':
    unittest.main()
