"""v0.6.1: certificate trust, INI fields, and GUI integration structure."""
import ast
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from pythonbde.settings import load_settings, save_settings
from pythonbde.tls_security import make_ca_signed_server_certificates, validate_certificate_set

ROOT = Path(__file__).resolve().parents[1]

class CertificateSettingsTests(unittest.TestCase):
    def test_ca_pair_and_mismatched_server(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            a = tuple(d / ('first_' + name) for name in ('server.crt','server.key','ca.crt','ca.key'))
            b = tuple(d / ('second_' + name) for name in ('server.crt','server.key','ca.crt','ca.key'))
            make_ca_signed_server_certificates(*a)
            make_ca_signed_server_certificates(*b)
            self.assertEqual(validate_certificate_set(a[2], a[0], a[1], a[3]), 'RSA')
            self.assertEqual(validate_certificate_set(a[2], a[0], a[1]), 'RSA')
            with self.assertRaises(ValueError):
                validate_certificate_set(b[2], a[0], a[1])
            with self.assertRaises(ValueError):
                validate_certificate_set(a[2], a[0], a[1], b[3])
            with self.assertRaises(FileExistsError):
                make_ca_signed_server_certificates(*a)

    def test_ca_settings_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.ini'
            cfg = load_settings(path)
            new = replace(cfg, tls_ca_certificate='other/root.crt',
                          tls_ca_private_key='other/root.key')
            save_settings(new, path)
            self.assertEqual(load_settings(path), new)
            self.assertIn('ca_certificate = other/root.crt', path.read_text())

    def test_gui_docks_and_stop_guard(self):
        gui = (ROOT / 'pythonbde' / 'gui.py').read_text()
        settings = (ROOT / 'pythonbde' / 'server_settings_dock.py').read_text()
        schedule = (ROOT / 'pythonbde' / 'time_window_dock.py').read_text()
        for text in (gui, settings, schedule):
            ast.parse(text)
        self.assertIn('"Time Window", self.show_time_window', gui)
        self.assertIn('_show_exclusive_dock(self.settings_dock)', gui)
        self.assertIn('_show_exclusive_dock(self.time_window_dock)', gui)
        for label in ('CA Certificate (ca.crt)', 'CA Private Key (ca.key)',
                      'Server Certificate (server.crt)', 'Server Private Key (server.key)',
                      'Generate New Certificates', 'Test Certificates'):
            self.assertIn(label, settings)
        self.assertIn('self.window.server.listener.isListening()', settings)
        self.assertIn('server_id=str(uuid.uuid4())', settings)
        self.assertIn('QSplitter(Qt.Horizontal)', settings)
        self.assertIn('QTableWidget(4, SLOTS_PER_DAY', schedule)

if __name__ == '__main__':
    unittest.main()
