"""v0.6.7: Qt5-freier Regressionstest für die Titelleisten-Ausrichtung."""
import ast
from pathlib import Path
import unittest

GUI = (Path(__file__).resolve().parents[1] / "pythonbde" / "gui.py").read_text(encoding="utf-8")
ROOT = ast.parse(GUI)
DOCK = next(n for n in ROOT.body if isinstance(n, ast.ClassDef) and n.name == "UserManagerDock")
INSTALL = next(n for n in DOCK.body if isinstance(n, ast.FunctionDef) and n.name == "_install_title_bar")
SOURCE = ast.get_source_segment(GUI, INSTALL)


class UserTitleBarAlignmentTests(unittest.TestCase):
    def test_title_does_not_consume_expanding_space(self):
        self.assertIn("row.addWidget(heading)", SOURCE)
        self.assertNotIn("row.addWidget(heading, 1)", SOURCE)

    def test_actions_left_dock_controls_right(self):
        # Layout: heading | account actions | flexible space | float | close.
        parts = ("row.addWidget(heading)", "row.addWidget(button)",
                 "row.addStretch(1)", "row.addWidget(self.float_button)",
                 "row.addWidget(self.close_button)")
        indices = [SOURCE.index(x) for x in parts]
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(SOURCE.count("row.addStretch(1)"), 1)

    def test_all_actions_and_callbacks_retained(self):
        for caption, method in (("New User", "new_user"),
                                ("Delete Account", "delete_user"),
                                ("Unlock", "unlock_user"),
                                ("Refresh", "refresh")):
            self.assertIn(f'("{caption}", self.{method}', SOURCE)
        self.assertIn("self.float_button.clicked.connect(self._toggle_dock_floating)", SOURCE)
        self.assertIn("self.close_button.clicked.connect(self.close)", SOURCE)


if __name__ == "__main__":
    unittest.main()
