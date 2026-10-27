"""Qt5 TLS-Listener. RPC-Sitzung entsteht AUSSCHLIESSLICH nach encrypted."""
from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.QtNetwork import QSsl, QSslSocket, QSslCertificate, QSslKey, QTcpServer
from .tls_security import validate_server_certificate


class TLSTcpServer(QTcpServer):
    secureConnected = pyqtSignal(object)
    tlsFailure = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tls_enabled = True
        self._certificate = None
        self._key = None
        self._pending_handshakes = set()

    def configure(self, enabled: bool, certificate=None, private_key=None):
        if self.isListening():
            raise RuntimeError('TLS-Konfiguration nicht während laufendem Server ändern')
        self.tls_enabled = bool(enabled)
        if not enabled:
            self._certificate = self._key = None
            return
        if not QSslSocket.supportsSsl():
            raise RuntimeError('Qt5/OpenSSL bietet keine TLS-Unterstützung. Installation prüfen.')
        algorithm = validate_server_certificate(certificate, private_key)
        certificate_obj = QSslCertificate(open(certificate, 'rb').read(), QSsl.Pem)
        private_key_obj = QSslKey(open(private_key, 'rb').read(),
                                  QSsl.Rsa if algorithm == 'RSA' else QSsl.Ec,
                                  QSsl.Pem, QSsl.PrivateKey)
        if certificate_obj.isNull() or private_key_obj.isNull():
            raise ValueError('TLS-Zertifikat oder privater Schlüssel ungültig')
        self._certificate = certificate_obj
        self._key = private_key_obj

    def incomingConnection(self, descriptor):
        if not self.tls_enabled:
            return super().incomingConnection(descriptor)
        sock = QSslSocket(self)
        if not sock.setSocketDescriptor(descriptor):
            sock.deleteLater()
            self.tlsFailure.emit('TLS SocketDescriptor fehlgeschlagen')
            return
        sock.setLocalCertificate(self._certificate)
        sock.setPrivateKey(self._key)
        sock.setProtocol(QSsl.TlsV1_2OrLater)
        sock.setPeerVerifyMode(QSslSocket.VerifyNone)  # Keine Client-Zertifikate nötig; User-Passwort im TLS-Tunnel.
        self._pending_handshakes.add(sock)
        sock.encrypted.connect(lambda s=sock: self._ready(s))
        sock.disconnected.connect(lambda s=sock: self._discard(s))
        sock.sslErrors.connect(lambda errors, s=sock: self._tls_error(s, errors))
        sock.errorOccurred.connect(lambda err, s=sock: self._socket_error(s))
        QTimer.singleShot(10000, lambda s=sock: self._timeout(s))
        sock.startServerEncryption()

    def _ready(self, sock):
        if sock not in self._pending_handshakes:
            return
        self._pending_handshakes.discard(sock)
        if not sock.isEncrypted():
            sock.abort()
            return
        self.secureConnected.emit(sock)

    def _discard(self, sock):
        if sock in self._pending_handshakes:
            self._pending_handshakes.discard(sock)
            sock.deleteLater()

    def _tls_error(self, sock, errors):
        self.tlsFailure.emit('TLS-Handshake: ' + '; '.join(err.errorString() for err in errors)[:500])
        sock.abort()

    def _socket_error(self, sock):
        if sock in self._pending_handshakes:
            self.tlsFailure.emit('TLS-Verbindung fehlgeschlagen: ' + sock.errorString())

    def _timeout(self, sock):
        if sock in self._pending_handshakes:
            self.tlsFailure.emit('TLS-Handshake-Timeout')
            sock.abort()

    def close(self):
        for sock in list(self._pending_handshakes):
            sock.abort()
            sock.deleteLater()
        self._pending_handshakes.clear()
        super().close()
