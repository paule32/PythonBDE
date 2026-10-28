"""Regression guard for the Win32 LONG vs C++ int template deduction error."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WatchdogMinGWBuildSourceTests(unittest.TestCase):
    def test_rect_differences_use_int_for_std_max(self):
        source = (ROOT / "watchdog" / "pythonbde_watchdog.cpp").read_text(encoding="utf-8")
        self.assertIn("std::max(100, static_cast<int>(rc.right - rc.left))", source)
        self.assertIn("std::max(100, static_cast<int>(rc.bottom - rc.top))", source)
        self.assertNotIn("std::max(100, rc.right - rc.left)", source)
        self.assertNotIn("std::max(100, rc.bottom - rc.top)", source)


if __name__ == "__main__":
    unittest.main()
