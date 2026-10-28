"""Portable regression tests of external Windows watchdog wiring."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pythonbde import native_watchdog as wd

ROOT = Path(__file__).resolve().parents[1]


class NativeWatchdogTests(unittest.TestCase):
    def test_arch_is_interpreter_bitness(self):
        self.assertIn(wd.watchdog_arch(), {"x86", "x64"})
        with patch.object(wd.struct, "calcsize", return_value=4):
            self.assertEqual(wd.watchdog_arch(), "x86")
        with patch.object(wd.struct, "calcsize", return_value=8):
            self.assertEqual(wd.watchdog_arch(), "x64")

    def test_bundled_paths_are_architecture_specific(self):
        self.assertEqual(wd.bundled_executable("x86", ROOT).name, "pythonbde_watchdog_x86.exe")
        self.assertEqual(wd.bundled_executable("x64", ROOT).name, "pythonbde_watchdog_x64.exe")

    def test_cache_uses_localappdata(self):
        result = wd.cached_executable("x64", env={"LOCALAPPDATA": "/fake/local"})
        self.assertIn("PythonBDE", result.parts)
        self.assertEqual(result.name, "pythonbde_watchdog_x64.exe")

    def test_compiler_targets_are_checked_before_use(self):
        machine = subprocess.CompletedProcess([], 0, stdout="x86_64-w64-mingw32\n")
        with patch.object(wd.shutil, "which", return_value="/fake/g++"), \
             patch.object(wd.subprocess, "run", return_value=machine):
            self.assertEqual(wd._find_compiler("x64"), "/fake/g++")
            self.assertIsNone(wd._find_compiler("x86"))

    def test_missing_compiler_does_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(wd, "_find_compiler", return_value=None), \
                 patch.object(wd, "append_error_log") as logger:
                result = wd.build_if_available(architecture="x64", root=ROOT,
                                               target=Path(directory) / "watchdog.exe")
            self.assertIsNone(result)
            logger.assert_called()

    def test_build_produces_executable_at_expected_location(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "watchdog.exe"
            def mocked_run(cmd, **kwargs):
                if cmd[0] != "fake-g++":
                    raise AssertionError("Unexpected compiler")
                Path(cmd[cmd.index("-o") + 1]).write_bytes(b"MZ-test-binary")
                self.assertIn("-municode", cmd)
                self.assertIn("-mwindows", cmd)
                return subprocess.CompletedProcess(cmd, 0, stdout="")
            with patch.object(wd, "_find_compiler", return_value="fake-g++"), \
                 patch.object(wd.subprocess, "run", side_effect=mocked_run):
                result = wd.build_if_available(architecture="x64", root=ROOT, target=target)
            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"MZ-test-binary")

    def test_linux_start_is_noop(self):
        if os.name == "nt":
            self.skipTest("Linux guard is only testable on non-Windows hosts")
        with patch.object(wd.subprocess, "Popen") as popen:
            self.assertFalse(wd.start_watchdog())
        popen.assert_not_called()

    def test_both_entry_points_hook_before_pyqt(self):
        for file in ("server.py", "rpc_client.py"):
            source = (ROOT / file).read_text(encoding="utf-8")
            self.assertLess(source.index("start_watchdog(app_name="),
                            source.index("from PyQt5."))

    def test_native_code_has_mutex_and_windows_edit_control(self):
        source = (ROOT / "watchdog" / "pythonbde_watchdog.cpp").read_text(encoding="utf-8")
        for fragment in ("CreateMutexW", "WaitForSingleObject", "GetExitCodeProcess",
                         "CreateWindowExW", "L\"EDIT\"", "CF_UNICODETEXT", "notify_ready"):
            self.assertIn(fragment, source)

    def test_readme_contains_architecture_graphic_and_original_docs(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("assets/watchdog_architektur.png", text)
        self.assertIn("Neu v0.6.3", text)
        self.assertTrue((ROOT / "assets/watchdog_architektur.png").stat().st_size > 5000)


if __name__ == "__main__":
    unittest.main()
