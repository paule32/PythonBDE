"""Start PythonBDE RPC Client without a console on Windows."""
from pythonbde.windows_console import hide_private_console

hide_private_console()  # Vor dem Import von RPC-Client, Watchdog oder Qt.

from rpc_client import main

if __name__ == "__main__":
    raise SystemExit(main())
