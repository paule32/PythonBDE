"""Best-effort *external* crash watchdog for PythonBDE on Windows.

This module imports neither Qt nor ctypes.WinDLL during module import. Start it
before importing PyQt5, so pythonw.exe's native crashes are observable by a
separate process. On Linux this module is a no-op.

The watchdog monitors this Python process, not all Python applications on the
machine.  Missing MinGW builds never block an otherwise healthy PythonBDE.
"""
from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import uuid

from pythonbde.gui_errors import append_error_log, log_path
from pythonbde.windows_process import hidden_process_kwargs

_LOCK = threading.Lock()
_STARTED = False
_FATAL_HANDLE = None
_PROCESS = None


def watchdog_arch() -> str:
    """Use the *interpreter* bitness, not Windows OS bitness."""
    return "x64" if struct.calcsize("P") == 8 else "x86"


def project_directory() -> Path:
    return Path(__file__).resolve().parent.parent


def bundled_executable(architecture=None, root=None) -> Path:
    root = Path(root) if root is not None else project_directory()
    return root / "watchdog" / "bin" / f"pythonbde_watchdog_{architecture or watchdog_arch()}.exe"


def cached_executable(architecture=None, env=None) -> Path:
    env = os.environ if env is None else env
    local = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "PythonBDE" / "watchdog" / f"pythonbde_watchdog_{architecture or watchdog_arch()}.exe"


def _compiler_candidates(architecture: str) -> tuple[str, ...]:
    if architecture == "x64":
        return ("x86_64-w64-mingw32-g++", "g++")
    return ("i686-w64-mingw32-g++", "g++")


def _find_compiler(architecture: str):
    for name in _compiler_candidates(architecture):
        exe = shutil.which(name)
        if not exe:
            continue
        try:
            machine = subprocess.run([exe, "-dumpmachine"], capture_output=True,
                                     text=True, timeout=8, check=True,
                                     **hidden_process_kwargs()).stdout.lower().strip()
        except (OSError, subprocess.SubprocessError):
            continue
        compatible = ("x86_64" in machine if architecture == "x64" else
                      any(x in machine for x in ("i686", "i586", "i386")))
        if compatible and ("mingw" in machine or "windows" in machine or "w64" in machine):
            return exe
    return None


def build_if_available(*, architecture=None, root=None, target=None) -> Path | None:
    """Compile with a matching MinGW compiler on first run if no EXE exists.

    The EXE is written atomically into LOCALAPPDATA, so read-only installations
    and concurrent server/client starts do not corrupt the bundled sources.
    """
    arch = architecture or watchdog_arch()
    base = Path(root) if root is not None else project_directory()
    binary = Path(target) if target is not None else cached_executable(arch)
    source = base / "watchdog" / "pythonbde_watchdog.cpp"
    if binary.is_file():
        return binary
    if not source.is_file():
        return None
    compiler = _find_compiler(arch)
    if not compiler:
        append_error_log(f"Watchdog: MinGW {arch} g++ fehlt; "
                         "watchdog/build_mingw32.bat bzw. build_mingw64.bat ausführen.\n")
        return None
    temp_binary = None
    try:
        binary.parent.mkdir(parents=True, exist_ok=True)
        temp_binary = binary.parent / ("." + binary.stem + "_" + uuid.uuid4().hex + ".exe")
        cmd = [compiler, "-std=c++17", "-O2", "-municode", "-mwindows",
               "-D_WIN32_WINNT=0x0601", "-static", "-static-libgcc", "-static-libstdc++",
               "-o", str(temp_binary), str(source), "-lshell32", "-luser32"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False,
                              **hidden_process_kwargs())
        if proc.returncode != 0 or not temp_binary.is_file():
            append_error_log("Watchdog: MinGW-Build fehlgeschlagen:\n" +
                             (proc.stderr or proc.stdout or f"Exit {proc.returncode}")[:6000])
            return None
        # Replacing an existing executable being watched is unnecessary; a
        # concurrent instance may have already successfully produced it.
        if not binary.is_file():
            os.replace(temp_binary, binary)
        return binary
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        append_error_log(f"Watchdog: Build-Fehler: {exc}\n")
        return None
    finally:
        if temp_binary is not None:
            try:
                temp_binary.unlink(missing_ok=True)
            except OSError:
                pass


def _fatal_log_path(pid: int) -> Path:
    return log_path().parent / f"pythonbde_fatal_{pid}.log"


def install_faulthandler(path: Path) -> bool:
    """Keep a per-PID file object alive for signal/SEH traceback writing."""
    global _FATAL_HANDLE
    if _FATAL_HANDLE is not None:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", encoding="utf-8", buffering=1)
        try:
            faulthandler.enable(file=handle, all_threads=True, c_stack=True)
        except TypeError:  # Python 3.13 and older
            faulthandler.enable(file=handle, all_threads=True)
        _FATAL_HANDLE = handle
        return True
    except (OSError, RuntimeError, ValueError) as exc:
        append_error_log(f"Watchdog: faulthandler-Log nicht verfügbar: {exc}\n")
        return False


def _create_ready_event():
    """Native event prevents the Python process outrunning watcher OpenProcess."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateEventW
    create.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    create.restype = wintypes.HANDLE
    wait = kernel32.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait.restype = wintypes.DWORD
    close = kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    name = f"Local\\PythonBDE_Watchdog_Ready_{os.getpid()}_{uuid.uuid4().hex}"
    event = create(None, False, False, name)
    if not event:
        raise OSError(ctypes.get_last_error(), "CreateEventW failed")
    return name, event, wait, close


def start_watchdog(*, app_name="PythonBDE", executable=None) -> bool:
    """Start one watchdog for this process (Windows only). Never raise.

    The native watchdog uses its own PID-scoped Win32 mutex, so duplicate
    starts from independent Python entry points will not duplicate dialogs.
    """
    global _STARTED, _PROCESS
    if os.name != "nt" or os.environ.get("PYTHONBDE_DISABLE_WATCHDOG") == "1":
        return False
    with _LOCK:
        if _STARTED:
            return True
        fatal = _fatal_log_path(os.getpid())
        install_faulthandler(fatal)
        binary = Path(executable) if executable is not None else bundled_executable()
        if not binary.is_file() and executable is None:
            binary = cached_executable()
        if not binary.is_file() and executable is None:
            binary = build_if_available()
        if binary is None or not Path(binary).is_file():
            append_error_log("Watchdog: keine EXE vorhanden; nativer Watchdog nicht aktiv.\n")
            return False
        event = None
        close = None
        try:
            name, event, wait, close = _create_ready_event()
            command = [str(binary), "--pid", str(os.getpid()),
                       "--role", str(app_name), "--fatal-log", str(fatal),
                       "--error-log", str(log_path()), "--ready-event", name]
            # Explicitly suppress console creation if an older watchdog
            # executable was accidentally built as a console program. Do NOT
            # use SW_HIDE here: that could hide the future Win32 error dialog.
            _PROCESS = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        close_fds=True, **hidden_process_kwargs(gui_executable=True))
            status = wait(event, 3000)
            if status != 0:  # WAIT_OBJECT_0
                append_error_log(f"Watchdog: Bereitschaftsereignis nicht signalisiert ({status}); "
                                 "native EXE oder Prozesszugriff prüfen.\n")
                return False
            _STARTED = True
            return True
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            append_error_log(f"Watchdog: Start fehlgeschlagen: {exc}\n")
            return False
        finally:
            if event is not None and close is not None:
                close(event)
