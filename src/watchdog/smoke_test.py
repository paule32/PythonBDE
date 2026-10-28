"""Explicit Windows-only watchdog smoke test, without starting the full GUI.

WARNING: --native-abort intentionally terminates this separate test process.
Never run it inside your PythonBDE server process.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

# Keep the test executable independently from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pythonbde.native_watchdog import start_watchdog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-abort", action="store_true",
                        help="Only for testing: deliberately abort this test process")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This test requires Windows")
    if not start_watchdog(app_name="PythonBDE Watchdog Smoke Test"):
        print("No Watchdog active: build the MinGW executable first")
        return 2
    print("Watchdog armed; test process terminates now", flush=True)
    if args.native_abort:
        os.abort()
    os._exit(33)


if __name__ == "__main__":
    raise SystemExit(main())
