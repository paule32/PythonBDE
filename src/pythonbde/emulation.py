"""Versioned, platform-independent RPC desktop/display selections.

This module intentionally does NOT claim to run Windows 95 or Windows XP.
It defines a wire protocol hint and validates client-selected dimensions.
"""
from __future__ import annotations

SYSTEM_MODES = ("win95", "winXP", "con")
GUI_SIZES = (
    (640, 480), (800, 600), (1024, 768), (1280, 720),
    (1280, 768), (1280, 800), (1280, 1024),
)
TUI_SIZES = ((80, 25), (80, 50))


def validate_client_display(mode=None, display=None):
    """Normalize and validate untrusted login metadata.

    Missing fields are supported for older clients and use the XP UI skin.
    Returns (system_mode, {width, height, unit}).
    """
    if mode is None:
        mode = "winXP"  # backwards compatible with v0.4.9 clients
    if type(mode) is not str or mode not in SYSTEM_MODES:
        raise ValueError("Ungültiger systemMode (win95, winXP, con erwartet)")

    sizes = TUI_SIZES if mode == "con" else GUI_SIZES
    unit = "cells" if mode == "con" else "pixels"
    if display is None:
        width, height = sizes[0]
    else:
        if not isinstance(display, dict) or display.get("unit") != unit:
            raise ValueError("Ungültige Display-Einheit für den gewählten Modus")
        width, height = display.get("width"), display.get("height")
        if type(width) is not int or type(height) is not int or (width, height) not in sizes:
            raise ValueError("Nicht unterstützte GUI-/TUI-Geometrie")
    return mode, {"unit": unit, "width": width, "height": height}
