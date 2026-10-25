import datetime
from pathlib import Path
import tempfile
import unittest

from pythonbde.eventlog import EventLog, format_entry, MAX_UI_LINES


class TestEventLog(unittest.TestCase):
    def test_entry_date_time_status_and_message(self):
        text = format_entry(200, "GUI started", at=datetime.datetime(2026, 10, 25, 19, 30, 4))
        self.assertEqual("2026-10-25 19:30:04 | 200 | GUI started", text)
        self.assertEqual(1, len(text.splitlines()))
        with self.assertRaises(ValueError):
            format_entry(0, "bad")

    def test_file_next_to_dbf_ui_newest_first(self):
        with tempfile.TemporaryDirectory() as folder:
            log = EventLog(Path(folder) / "users.dbf")
            first = log.write(200, "GUI started")
            second = log.write(400, "User can not be created")
            self.assertEqual(Path(folder) / "python_bde.log", log.path)
            self.assertEqual([second, first], log.entries)
            self.assertEqual([first, second], log.path.read_text(encoding='utf8').splitlines())
            log.clear_view()
            self.assertEqual([], log.entries)
            self.assertEqual(2, len(log.path.read_text(encoding='utf8').splitlines()))

    def test_ui_at_capacity_is_cleared_for_new_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            log = EventLog(Path(folder) / "users.dbf")
            for i in range(MAX_UI_LINES):
                log.write(200, f"entry-{i}")
            self.assertEqual(MAX_UI_LINES, len(log.entries))
            newest = log.write(200, "after-limit")
            self.assertEqual([newest], log.entries)

    def test_file_is_limited_and_callbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            log = EventLog(Path(folder) / 'users.dbf', max_bytes=1200)
            events = []
            log.callbacks.append(events.append)
            for i in range(100):
                log.write(200, f"entry-{i:03d}")
            self.assertLessEqual(log.path.stat().st_size, 1200)
            self.assertEqual(100, len(events))
            self.assertTrue(log.path.read_text().endswith("entry-099\n"))

if __name__ == '__main__':
    unittest.main()
