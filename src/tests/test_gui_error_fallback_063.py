"""GUI exception-reporting regression checks (no Qt/Windows required)."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pythonbde import gui_errors


class GUIErrorFallbackTests(unittest.TestCase):
    def test_writes_full_traceback_into_user_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'errors.log'
            with patch.object(gui_errors, '_LOG_PATH', path), \
                 patch.object(gui_errors, '_qt_trace_dialog', return_value=True) as qt:
                try:
                    raise RuntimeError('test crash')
                except RuntimeError as exc:
                    result = gui_errors.report_exception(type(exc), exc, exc.__traceback__)
            self.assertEqual(result, path)
            self.assertIn('RuntimeError: test crash', path.read_text(encoding='utf-8'))
            self.assertIn('Traceback (most recent call last)', qt.call_args.args[1])

    def test_windows_textedit_attempted_when_qt_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'errors.log'
            with patch.object(gui_errors, '_LOG_PATH', path), \
                 patch.object(gui_errors, '_qt_trace_dialog', return_value=False), \
                 patch.object(gui_errors, '_win32_trace_editor', return_value=True) as native:
                gui_errors.show_traceback('Qt start failed', 'Traceback here')
                self.assertEqual(native.call_count, 1)
                self.assertIn('Traceback here', native.call_args.args[1])

    def test_stderr_split_into_lines_without_losing_fragments(self):
        original = io.StringIO()
        mirror = gui_errors._StderrToFile(original)
        recorded = []
        with patch.object(gui_errors, 'append_error_log', side_effect=lambda s: recorded.append(s)):
            mirror.write('Traceback ') 
            mirror.write('line 1\nline 2')
            mirror.flush()
        self.assertEqual(recorded, ['Traceback line 1\n', 'line 2'])
        self.assertEqual(original.getvalue(), 'Traceback line 1\nline 2')

    def test_keyboard_interrupt_and_system_exit_do_not_open_dialog(self):
        with patch.object(gui_errors, 'show_traceback') as popup:
            gui_errors.report_exception(KeyboardInterrupt, KeyboardInterrupt(), None)
            gui_errors.report_exception(SystemExit, SystemExit(0), None)
        popup.assert_not_called()

    def test_unhandled_hook_uses_traceback_reporter(self):
        with patch.object(gui_errors, 'report_exception') as reporter:
            gui_errors._main_hook(ValueError, ValueError('fail'), None)
        self.assertEqual(reporter.call_args.args[0], ValueError)

    def test_stderr_write_survives_missing_console(self):
        mirror = gui_errors._StderrToFile(None)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(gui_errors, '_LOG_PATH', Path(directory) / 'errors.log'):
                self.assertEqual(mirror.write('startup warning\n'), len('startup warning\n'))
                mirror.flush()
                self.assertIn('startup warning', (Path(directory)/'errors.log').read_text())


if __name__ == '__main__':
    unittest.main()
