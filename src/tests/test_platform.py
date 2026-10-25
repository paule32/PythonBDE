"""Tests für plattformübergreifende Hashes, Backendwahl, Dateisystem und CLI."""
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pythonbde.crypto import ITERATIONS, derive, hash_password, verify_password
from pythonbde.dbf import DBFStore
from pythonbde.platform_support import default_dbf_path, file_lock_backend, operating_system, password_backend


class TestPlatform(unittest.TestCase):
    def test_linux_pbkdf2_same_standard_vectors(self):
        salt = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        pw = "pässwört🔒"
        expected = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ITERATIONS, 32)
        with patch("pythonbde.platform_support.platform.system", return_value="Linux"):
            self.assertEqual(expected, derive(pw, salt))
            row = hash_password(pw)
            self.assertTrue(verify_password(pw, row))
            self.assertFalse(verify_password("wrong", row))

    def test_backend_select_windows_without_windows_dll(self):
        salt = bytes(range(16))
        with patch("pythonbde.platform_support.platform.system", return_value="Windows"), \
             patch("pythonbde.crypto._cng_pbkdf2", return_value=b"a" * 32) as backend:
            self.assertEqual(b"a" * 32, derive("test", salt))
            backend.assert_called_once_with(b"test", salt, ITERATIONS)
            self.assertIn("BCrypt", password_backend())
            self.assertIn("CreateFileW", file_lock_backend())

    def test_linux_backend_names(self):
        with patch("pythonbde.platform_support.platform.system", return_value="Linux"):
            self.assertIn("OpenSSL", password_backend())
            self.assertIn("flock", file_lock_backend())

    def test_unsupported_os_is_rejected(self):
        with patch("pythonbde.platform_support.platform.system", return_value="FreeBSD"):
            with self.assertRaises(RuntimeError):
                operating_system()
            with self.assertRaises(RuntimeError):
                derive("password123", bytes(16))

    def test_default_linux_xdg_and_windows_localappdata(self):
        with patch("pythonbde.platform_support.platform.system", return_value="Linux"), \
             patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/testxdg"}):
            self.assertEqual(Path("/tmp/testxdg/PythonBDE/users.dbf"), default_dbf_path())
        with patch("pythonbde.platform_support.platform.system", return_value="Windows"), \
             patch.dict(os.environ, {"LOCALAPPDATA": "C:/Testing/BDE"}):
            self.assertEqual(Path("C:/Testing/BDE/PythonBDE/users.dbf"), default_dbf_path())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Benötigt Linux")
    def test_linux_permissions_and_subprocess_lock(self):
        with tempfile.TemporaryDirectory() as td:
            filename = Path(td) / "users.dbf"
            filename.write_bytes(b"")
            os.chmod(filename, 0o666)
            with DBFStore(filename) as store:
                self.assertEqual(0o600, stat.S_IMODE(os.stat(filename).st_mode))
                code = """import sys
from pythonbde.dbf import DBFStore
try:
    with DBFStore(sys.argv[1]):
        sys.exit(10)
except OSError:
    sys.exit(0)
"""
                proc = subprocess.run([sys.executable, "-c", code, str(filename)],
                                      cwd=str(Path(__file__).resolve().parents[1]),
                                      capture_output=True, text=True)
                self.assertEqual(0, proc.returncode, proc.stderr)
            with DBFStore(filename):
                pass

    @unittest.skipUnless(sys.platform.startswith("linux"), "Benötigt Linux")
    def test_linux_symlink_dbf_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "real.dbf"
            shortcut = Path(td) / "shortcut.dbf"
            with DBFStore(target):
                pass
            shortcut.symlink_to(target)
            with self.assertRaises(OSError):
                DBFStore(shortcut)
            self.assertTrue(target.is_file())

    def test_invalid_crypto_parameters(self):
        with self.assertRaises(ValueError):
            derive("abc", b"short")
        with self.assertRaises(ValueError):
            derive("abc", bytes(16), 0)
        self.assertFalse(verify_password(None, {}))

    def test_linux_check_platform_without_pyqt5(self):
        if sys.platform != "linux":
            self.skipTest("Linux Laufzeittest")
        p = subprocess.run([sys.executable, "server.py", "--check-platform"],
                           cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True)
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn("Betriebssystem: Linux", p.stdout)
        self.assertIn("hashlib.pbkdf2_hmac", p.stdout)


if __name__ == "__main__":
    unittest.main()
