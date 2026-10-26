"""Regressionen für den Windows-95-Desktopfarbton, ohne PyQt5-Abhängigkeit."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]


def _source_tree():
    source = (BASE / "rpc_client.py").read_text(encoding="utf-8")
    return source, ast.parse(source)


class Windows95DesktopTests(unittest.TestCase):
    def test_default_teal_is_classic_windows95_color(self):
        _, tree = _source_tree()
        assignments = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertEqual("#008080", assignments.get("WIN95_DESKTOP_COLOR"))

    def test_background_is_painted_only_for_win95(self):
        _, tree = _source_tree()
        window_class = next(node for node in tree.body
                            if isinstance(node, ast.ClassDef) and node.name == "CreatedWindow")
        paint = next(node for node in window_class.body
                     if isinstance(node, ast.FunctionDef) and node.name == "paintEvent")
        body = ast.unparse(paint)
        self.assertIn("self.mode != 'win95'", body)
        self.assertIn("painter.fillRect(self.rect(), QColor(WIN95_DESKTOP_COLOR))", body)
        self.assertIn("super().paintEvent(event)", body)
        self.assertNotIn("self._dark_theme", body)

    def test_existing_taskbar_keeps_grey_while_desktop_is_teal(self):
        _, tree = _source_tree()
        taskbar = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "EmulatedTaskbar")
        paint = next(node for node in taskbar.body
                     if isinstance(node, ast.FunctionDef) and node.name == "paintEvent")
        self.assertIn("#c0c0c0", ast.unparse(paint))

    def test_theme_change_repaints_workspace(self):
        _, tree = _source_tree()
        window_class = next(node for node in tree.body
                            if isinstance(node, ast.ClassDef) and node.name == "CreatedWindow")
        set_theme = next(node for node in window_class.body
                         if isinstance(node, ast.FunctionDef) and node.name == "set_theme")
        self.assertIn("self.update()", ast.unparse(set_theme))


if __name__ == "__main__":
    unittest.main()
