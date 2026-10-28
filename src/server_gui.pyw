"""Start PythonBDE without a console on Windows (pythonw.exe)."""
from pythonbde.windows_console import hide_private_console

hide_private_console()  # Vor dem Import von Server, Watchdog oder Qt.

from server import main

if __name__ == "__main__":
    raise SystemExit(main())
