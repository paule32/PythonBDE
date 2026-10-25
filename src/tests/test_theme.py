"""Theme-Regression ohne PyQt5: QSS, Ressourcen und GUI-Verdrahtung."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "pythonbde" / "gui.py"
THEME = ROOT / "pythonbde" / "theme.py"


def extract_function(source: str, function_name: str, *, klass: str | None = None):
    tree = ast.parse(source)
    nodes = tree.body
    if klass is not None:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == klass).body
    f = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == function_name)
    return ast.get_source_segment(source, f)


class TestQtTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.theme = THEME.read_text(encoding="utf-8")
        # Stylesheet-Funktion benötigt selbst kein Qt5: separat kompilieren.
        module = ast.parse(cls.theme)
        func = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "theme_stylesheet")
        namespace = {"ARROWS": THEME.parent / "assets"}
        exec(compile(ast.Module(body=[func], type_ignores=[]), str(THEME), "exec"), namespace)
        cls.stylesheet = staticmethod(namespace["theme_stylesheet"])

    def test_menu_has_english_help_and_preserves_entries(self):
        m = extract_function(self.gui, "_init_menu", klass="MainWindow")
        self.assertIn('addMenu("Help")', m)
        self.assertNotIn('addMenu("Hilfe")', m)
        self.assertIn('"Informations", self.show_informations', m)
        self.assertIn('"About ...", self.show_about', m)

    def test_toolbar_contains_one_theme_toggle(self):
        src = extract_function(self.gui, "_init_theme_toolbar", klass="MainWindow")
        self.assertIn('QToolBar("Appearance", self)', src)
        self.assertEqual(src.count("self.theme_toolbar.addAction("), 1)
        self.assertIn("self.action_theme.triggered.connect(self.toggle_theme)", src)
        self.assertIn("Qt.ToolButtonIconOnly", src)

    def test_toggle_changes_active_theme_and_icon(self):
        init = extract_function(self.gui, "__init__", klass="MainWindow")
        self.assertIn("self.apply_theme(False)", init)
        method = extract_function(self.gui, "toggle_theme", klass="MainWindow")
        self.assertIn("self.apply_theme(not self._dark_theme)", method)
        applied = extract_function(self.gui, "apply_theme", klass="MainWindow")
        self.assertIn("apply_application_theme(self._dark_theme)", applied)
        self.assertIn("theme_icon(self._dark_theme)", applied)
        self.assertIn("self.manager_dock.update_account_border()", applied)
        theme_icon = extract_function(self.theme, "theme_icon")
        self.assertIn("if dark:", theme_icon)
        self.assertIn("drawEllipse", theme_icon)  # Sonne
        self.assertIn("outside.subtracted(cutout)", theme_icon)  # Mond

    def test_both_styles_are_different_and_include_navy_scrollbars(self):
        light, dark = self.stylesheet(False), self.stylesheet(True)
        self.assertNotEqual(light, dark)
        self.assertIn("#f1f4f9", light)
        self.assertIn("#151b26", dark)
        for style in (light, dark):
            for token in ("QScrollBar:vertical", "QScrollBar:horizontal",
                          "QScrollBar::up-arrow:vertical", "QScrollBar::down-arrow:vertical",
                          "QScrollBar::left-arrow:horizontal", "QScrollBar::right-arrow:horizontal"):
                self.assertIn(token, style)
            self.assertIn("#081b3d", style)
            self.assertEqual(style.count("{"), style.count("}"))
            self.assertNotIn("@UP@", style)
            self.assertNotIn("@DOWN@", style)

    def test_yellow_arrow_png_resources_exist(self):
        for direction in ("up", "down", "left", "right"):
            image = THEME.parent / "assets" / f"scroll_{direction}.png"
            self.assertTrue(image.is_file(), str(image))
            self.assertTrue(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn(image.as_posix(), self.stylesheet(True))

    def test_application_theme_applies_to_all_dialogs(self):
        src = extract_function(self.theme, "apply_application_theme")
        self.assertIn('app.setStyle("Fusion")', src)
        self.assertIn("app.setPalette(theme_palette(dark))", src)
        self.assertIn("app.setStyleSheet(theme_stylesheet(dark))", src)


if __name__ == "__main__":
    unittest.main()
