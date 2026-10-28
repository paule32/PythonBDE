"""v0.6.6: regressions for Qt5 standard pixmaps and console-free Windows startup.

The Linux CI environment does not have Qt5/Win32. Windows-specific startup
flags are tested via a simulated Windows subprocess module configuration.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pythonbde import native_watchdog as wd
from pythonbde import windows_console as wc
from pythonbde import windows_process as wp

ROOT = Path(__file__).resolve().parents[1]


class ConsoleFreeStartupTests(unittest.TestCase):
    def test_windows_compiler_has_no_console_and_hidden_startupinfo(self):
        info = SimpleNamespace(dwFlags=0, wShowWindow=777)
        with patch.object(wp, 'os', SimpleNamespace(name='nt')), \
             patch.object(wp.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
             patch.object(wp.subprocess, 'STARTF_USESHOWWINDOW', 1, create=True), \
             patch.object(wp.subprocess, 'STARTUPINFO', return_value=info, create=True):
            opts = wp.hidden_process_kwargs()
        self.assertEqual(opts['creationflags'], 0x08000000)
        self.assertEqual(opts['startupinfo'].dwFlags, 1)
        self.assertEqual(opts['startupinfo'].wShowWindow, 0)

    def test_watchdog_gui_must_not_be_hidden(self):
        # A native Win32 crash-report window must still be allowed to appear.
        with patch.object(wp, 'os', SimpleNamespace(name='nt')), \
             patch.object(wp.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True):
            self.assertEqual(wp.hidden_process_kwargs(gui_executable=True),
                             {'creationflags': 0x08000000})

    def test_non_windows_subprocess_settings_are_unmodified(self):
        with patch.object(wp, 'os', SimpleNamespace(name='posix')):
            self.assertEqual(wp.hidden_process_kwargs(), {})
            self.assertEqual(wp.hidden_process_kwargs(gui_executable=True), {})

    def test_watchdog_compiler_probe_uses_hidden_mode(self):
        import subprocess
        response = subprocess.CompletedProcess([], 0, stdout='i686-w64-mingw32\n')
        with patch.object(wd.shutil, 'which', return_value='/fake/compiler'), \
             patch.object(wd, 'hidden_process_kwargs', return_value={'creationflags': 99}), \
             patch.object(wd.subprocess, 'run', return_value=response) as run:
            self.assertEqual(wd._find_compiler('x86'), '/fake/compiler')
            self.assertEqual(run.call_args.kwargs['creationflags'], 99)

    def test_watchdog_build_and_launch_use_correct_modes(self):
        src = (ROOT / 'pythonbde' / 'native_watchdog.py').read_text('utf-8')
        self.assertIn('**hidden_process_kwargs())', src)
        self.assertIn('**hidden_process_kwargs(gui_executable=True)', src)
        self.assertIn('"-mwindows"', src)
        self.assertIn('"-municode"', src)

    def test_windows_acls_do_not_flash_a_console(self):
        for name in ('tls_security.py', 'virtual_fs.py'):
            src = (ROOT / 'pythonbde' / name).read_text('utf-8')
            self.assertIn('**hidden_process_kwargs()', src)

    def test_early_console_hiding_is_gui_only(self):
        for name in ('server_gui.pyw', 'rpc_client_gui.pyw'):
            src = (ROOT / name).read_text('utf-8')
            self.assertLess(src.index('hide_private_console()'),
                            src.index('import main'))
        for name in ('server.py', 'rpc_client.py'):
            src = (ROOT / name).read_text('utf-8')
            self.assertNotIn('hide_private_console()', src)
        self.assertFalse(wc.hide_private_console()) if __import__('os').name != 'nt' else None

    def test_float_button_icon_uses_defined_qt5_symbols(self):
        src = (ROOT / 'pythonbde' / 'gui.py').read_text('utf-8')
        self.assertNotIn('standardIcon(QStyle.SP_DockWidgetFloatButton)', src)
        self.assertIn('QStyle.SP_TitleBarMaxButton', src)
        self.assertIn('QStyle.SP_TitleBarNormalButton', src)
        self.assertIn('QStyle.SP_DockWidgetCloseButton', src)


if __name__ == '__main__':
    unittest.main()
