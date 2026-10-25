"""Windows-weit eindeutiger Prozess: Kernel-Mutex + Qt-LocalSocket zum Wiederzeigen."""
from __future__ import annotations

import os
from .platform_support import operating_system

MUTEX_NAME = 'Global\\PythonBDE_Server_PythonBDE_v1'
SOCKET_NAME = 'PythonBDE_Server_Show_v1'


class WindowsMutex:
    def __init__(self):
        self.handle = None
        self.existing = False
        if operating_system() != 'Windows':
            return
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        self.handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'Windows-Mutex konnte nicht geöffnet werden')
        self.existing = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS

    def close(self):
        if self.handle is not None:
            import ctypes
            ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def signal_existing():
    """Die laufende Instanz auffordern, ihr Fenster sichtbar zu machen."""
    from PyQt5.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(700):
        return False
    sock.write(b'SHOW\n')
    sock.flush()
    sock.waitForBytesWritten(700)
    sock.disconnectFromServer()
    return True


class ActivationServer:
    def __init__(self, show_callback):
        from PyQt5.QtNetwork import QLocalServer
        self._server = QLocalServer()
        self._callback = show_callback
        # Unter Windows werden LocalSockets als lokale Named Pipes implementiert.
        if not self._server.listen(SOCKET_NAME):
            # Stale unix-domain socket bereinigen; Windows blockiert ein bereits gebundenes Pipe-Ende.
            if os.name != 'nt':
                QLocalServer.removeServer(SOCKET_NAME)
                if self._server.listen(SOCKET_NAME):
                    pass
                else:
                    raise OSError(self._server.errorString())
            else:
                raise OSError(self._server.errorString())
        self._server.newConnection.connect(self._read)
        self._connections = []

    def _read(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._connections.append(sock)
            sock.readyRead.connect(lambda s=sock: self._handle(s))
            sock.disconnected.connect(lambda s=sock: self._connections.remove(s) if s in self._connections else None)
            if sock.bytesAvailable():
                self._handle(sock)

    def _handle(self, sock):
        if b'SHOW' in bytes(sock.readAll())[:32]:
            self._callback()
        sock.disconnectFromServer()

    def close(self):
        self._server.close()
