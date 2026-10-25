"""Strukturtests für die neue Qt5-Oberfläche (ohne Qt-Laufzeit)."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'pythonbde' / 'gui.py'
s = SOURCE.read_text(encoding='utf8')
root = ast.parse(s)
classes = {n.name: n for n in root.body if isinstance(n, ast.ClassDef)}


def method(name):
    node = next(n for n in classes['MainWindow'].body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(s, node)


class TestLayout(unittest.TestCase):
    def test_information_precedes_about(self):
        m = method('_init_menu')
        self.assertIn('"Informations", self.show_informations', m)
        self.assertLess(m.index('"Informations"'), m.index('"About ..."'))
        info = method('show_informations')
        self.assertIn('Passwortschutz:', info)
        self.assertIn('self.users.store.path', info)
        self.assertIn('self.log.path', info)

    def test_statusbar_is_permanent_and_dynamic(self):
        init = method('__init__')
        self.assertIn('addPermanentWidget(self.status_server)', init)
        self.assertIn('addPermanentWidget(self.status_logins)', init)
        update = method('update_status')
        self.assertIn('Server: Started', update)
        self.assertIn('Server: Stopped', update)
        self.assertIn('Logged-In:', update)

    def test_aliases_dock_has_both_splitters_and_live_log(self):
        alias = ast.get_source_segment(s, classes['AliasesDock'])
        self.assertIn('QSplitter(Qt.Horizontal)', alias)
        self.assertIn('QSplitter(Qt.Vertical)', alias)
        self.assertIn('QPlainTextEdit()', alias)
        for label in ('"New"', '"Delete"', '"Rename"'):
            self.assertIn(label, alias)
        m = method('_init_menu')
        self.assertIn('"Aliases", self.show_aliases', m)
        self.assertIn('_show_exclusive_dock(self.aliases_dock)', method('show_aliases'))

    def test_no_old_info_box_in_users(self):
        user = ast.get_source_segment(s, classes['UserManagerDock'])
        self.assertNotIn('self.server_info = QLabel', user)
        self.assertNotIn('self.crypto_info = QLabel', user)
        self.assertNotIn('self.paths_info = QLabel', user)


if __name__ == '__main__':
    unittest.main()
