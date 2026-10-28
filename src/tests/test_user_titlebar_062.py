"""v0.6.2: AST regression checks for the custom Users/Admins dock title bar.

Qt5-free checks: the actual docking/mouse behavior still needs a native Qt5 run.
"""
import ast
from pathlib import Path
import unittest

GUI = (Path(__file__).resolve().parents[1] / "pythonbde" / "gui.py").read_text(encoding="utf-8")
ROOT = ast.parse(GUI)
USER_MANAGER = next(n for n in ROOT.body if isinstance(n, ast.ClassDef) and n.name == "UserManagerDock")


def method(name):
    n = next(n for n in USER_MANAGER.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(GUI, n)


class UserTitleBarStructureTests(unittest.TestCase):
    def test_actions_reside_in_custom_dock_titlebar(self):
        src = method("_install_title_bar")
        self.assertIn("self.setTitleBarWidget(title_bar)", src)
        self.assertIn('self.title_buttons[caption] = button', src)
        for label, func in (("New User", "new_user"),
                            ("Delete Account", "delete_user"),
                            ("Unlock", "unlock_user"),
                            ("Refresh", "refresh")):
            self.assertIn(f'("{label}", self.{func}', src)

    def test_content_has_no_extra_button_toolbar_row(self):
        init = method("__init__")
        self.assertIn("self._install_title_bar()", init)
        self.assertNotIn("layout.addLayout(actions)", init)
        self.assertIn("layout.addWidget(vertical)", init)
        self.assertIn("self.tree.setContextMenuPolicy", init)
        self.assertIn("self.details_frame", init)

    def test_titlebar_keeps_dock_controls(self):
        src = method("_install_title_bar")
        self.assertIn("QStyle.SP_TitleBarMaxButton", src)
        self.assertNotIn("standardIcon(QStyle.SP_DockWidgetFloatButton)", src)
        self.assertIn("QStyle.SP_TitleBarNormalButton", method("_sync_dock_title_controls"))
        self.assertIn("QStyle.SP_DockWidgetCloseButton", src)
        self.assertIn("self.float_button.clicked.connect(self._toggle_dock_floating)", src)
        self.assertIn("self.close_button.clicked.connect(self.close)", src)
        self.assertIn("self.topLevelChanged.connect(self._sync_dock_title_controls)", src)
        self.assertIn("self.featuresChanged.connect(self._sync_dock_title_controls)", src)

    def test_clicked_signal_does_not_pass_bool_to_refresh(self):
        src = method("_install_title_bar")
        self.assertIn("lambda checked=False, func=callback: func()", src)

    def test_dock_titlebar_keeps_dark_theme_compatibility(self):
        src = method("_install_title_bar")
        self.assertIn("QToolButton(title_bar)", src)
        self.assertNotIn("background-color:", src)


if __name__ == '__main__':
    unittest.main()
