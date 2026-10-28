"""v0.6.1: time-window boundaries, isolation, validation and atomic persistence."""
import json
from pathlib import Path
import tempfile
import unittest
from pythonbde.time_windows import (
    DAYS, TYPES, SLOTS_PER_DAY, empty_schedule, load_schedule,
    save_schedule, set_slot, slot_label, time_window_path,
)


class TimeWindowTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(SLOTS_PER_DAY, 96)
        self.assertEqual(slot_label(0), '00:00–00:15')
        self.assertEqual(slot_label(95), '23:45–24:00')
        for i in (-1, 96):
            with self.assertRaises(ValueError):
                slot_label(i)

    def test_day_independent_and_exclusive_categories(self):
        schedule = empty_schedule()
        set_slot(schedule, 'Monday', 1, TYPES[0])
        set_slot(schedule, 'Tuesday', 1, TYPES[1])
        set_slot(schedule, 'Monday', 1, TYPES[2])
        self.assertEqual(schedule['Monday'][1], 'Free-Time')
        self.assertEqual(schedule['Tuesday'][1], 'Maintaine-Time')
        self.assertEqual(schedule['Sunday'][1], '')
        set_slot(schedule, 'Monday', 1, '')
        self.assertEqual(schedule['Monday'][1], '')
        with self.assertRaises(ValueError):
            set_slot(schedule, 'Monday', 96, TYPES[0])
        with self.assertRaises(ValueError):
            set_slot(schedule, 'Monday', 1, 'invalid')

    def test_roundtrip_and_reject_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'time_windows.json'
            self.assertEqual(load_schedule(path), empty_schedule())
            week = empty_schedule()
            week['Sunday'][95] = TYPES[2]
            save_schedule(path, week)
            self.assertEqual(load_schedule(path), week)
            data = json.loads(path.read_text())
            self.assertEqual(data['slot_minutes'], 15)
            data['days']['Monday'][4] = 'HACK'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_schedule(path)
            if __import__('os').name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_length_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'users.dbf'
            self.assertEqual(time_window_path(path), Path(tmp) / 'time_windows.json')
            schedule = empty_schedule()
            schedule[DAYS[0]] = schedule[DAYS[0]][:-1]
            with self.assertRaises(ValueError):
                save_schedule(Path(tmp) / 'out.json', schedule)
            self.assertFalse((Path(tmp) / 'out.json').exists())

if __name__ == '__main__':
    unittest.main()
