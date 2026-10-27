"""v0.5.5: desktop icons always behind QMdiSubWindow, with unobscured snap positions.

The geometry helper is tested without Qt so this runs on CI without PyQt5.
The Qt hierarchy is additionally checked against the real source tree.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'rpc_client.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
HELPER = next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
              and node.name == 'desktop_drop_position')
namespace = {'DESKTOP_GRID': 48, 'DESKTOP_ICON_SIZE': 48}
exec(compile(ast.Module(body=[HELPER], type_ignores=[]), 'rpc_client_geom', 'exec'), namespace)
drop = namespace['desktop_drop_position']


def overlaps(icon, rect, width=96, height=78):
    x, y = icon
    rx, ry, rw, rh = rect
    return x < rx+rw and x+width > rx and y < ry+rh and y+height > ry


class DesktopDropGeometryTests(unittest.TestCase):
    def test_free_cell_keeps_48_pixel_graphic_alignment(self):
        pos = drop(49, 95, 640, 480)
        self.assertEqual(pos, (24, 96))
        self.assertEqual((pos[0] + 24) % 48, 0)
        self.assertEqual(pos[1] % 48, 0)

    def test_window_overlap_moves_icon_to_nearest_free_cell(self):
        application = (0, 0, 190, 150)
        pos = drop(48, 48, 640, 480, [application])
        self.assertFalse(overlaps(pos, application))
        self.assertEqual(pos[1], 192)
        self.assertEqual((pos[0]+24) % 48, 0)

    def test_multiple_windows_prevent_drop_on_any_window(self):
        occupied = [(0, 0, 180, 140), (160, 140, 280, 220)]
        pos = drop(192, 192, 640, 480, occupied)
        self.assertTrue(all(not overlaps(pos, rectangle) for rectangle in occupied))
        self.assertGreaterEqual(pos[0], 0)
        self.assertGreaterEqual(pos[1], 0)

    def test_maximized_window_does_not_enable_foreground_icons(self):
        pos = drop(48, 48, 640, 480, [(0, 0, 640, 480)])
        self.assertGreaterEqual(pos[0], 0)
        self.assertLessEqual(pos[0] + 96, 640)
        self.assertGreaterEqual(pos[1], 0)
        self.assertLessEqual(pos[1] + 78, 480)

    def test_tiny_desktop_never_places_icon_at_negative_coordinates(self):
        self.assertEqual((0, 0), drop(99, 99, 50, 50))


class DesktopLayerContractTests(unittest.TestCase):
    def test_desktop_layer_owns_grid_and_icon(self):
        self.assertIn('class DesktopIconLayer(QWidget)', SOURCE)
        self.assertIn('self.desktop_layer = DesktopIconLayer(viewport)', SOURCE)
        self.assertIn('self.grid_overlay = DesktopGridOverlay(self.desktop_layer)', SOURCE)
        self.assertIn('self.close_icon.setParent(self.desktop_layer)', SOURCE)
        self.assertNotIn('self.close_icon.setParent(self.workspace.viewport())', SOURCE)

    def test_layer_is_lowered_against_mdi_windows_on_activation_and_drag(self):
        self.assertIn('self.desktop_layer.lower()', SOURCE)
        self.assertIn('self.workspace.subWindowActivated.connect(self._keep_desktop_behind_windows)', SOURCE)
        self.assertIn('owner.place_desktop_icon(self, x, y)', SOURCE)
        self.assertIn('self._keep_desktop_behind_windows()', SOURCE)
        self.assertIn('self.taskbar.raise_()', SOURCE)

    def test_grid_stays_inside_desktop_layer_after_viewport_resize(self):
        self.assertIn('viewport.installEventFilter(self)', SOURCE)
        self.assertIn('event.type() == QEvent.Resize', SOURCE)
        self.assertIn('self.grid_overlay.setGeometry(self.desktop_layer.rect())', SOURCE)
        self.assertIn('self.grid_overlay.lower()', SOURCE)
        self.assertNotIn('self.grid_overlay.raise_()', SOURCE)


if __name__ == '__main__':
    unittest.main()
