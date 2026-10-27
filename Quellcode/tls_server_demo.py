"""Eigenständiger PyQt5 TLS/JSON-Lines-Demoserver.

Kein authentifizierender PythonBDE-Server: dient zum TLS-Funktionstest.
"""
import argparse
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtNetwork import (
    QHostAddress, QSsl, QSslCertificate, QSslKey, QSslSocket, QTcpServer,
)

from framing import JsonLines, encode_message


class TlsJsonServer(QTcpServer):
    def __init__(self, certificate_path, key_path, parent=None):
        super().__init__(parent)
        if not QSslSocket.supportsSsl():
            raise RuntimeError('Qt5/OpenSSL: TLS nicht verfügbar')
        self.certificate = QSslCertificate(
            Path(certificate_path).read_bytes(), QSsl.Pem)
        self.key = QSslKey(
            Path(key_path).read_bytes(), QSsl.Rsa, QSsl.Pem, QSsl.PrivateKey)
        if self.certificate.isNull() or self.key.isNull():
            raise ValueError('Zertifikat oder RSA-Schlüssel ungültig')
        self._sockets = set()
        self._readers = {}

    def incomingConnection(self, descriptor):
        sock = QSslSocket(self)
        if not sock.setSocketDescriptor(descriptor):
            sock.deleteLater()
            return
        sock.setLocalCertificate(self.certificate)
        sock.setPrivateKey(self.key)
        sock.setProtocol(QSsl.TlsV1_2OrLater)
        # Ein Client-Zertifikat ist für dieses Demo nicht erforderlich.
        sock.setPeerVerifyMode(QSslSocket.VerifyNone)
        self._sockets.add(sock)
        sock.encrypted.connect(lambda s=sock: self._encrypted(s))
        sock.disconnected.connect(lambda s=sock: self._disconnected(s))
        sock.sslErrors.connect(lambda errors, s=sock: self._ssl_errors(s, errors))
        sock.errorOccurred.connect(lambda error, s=sock: print(
            'TLS-Socketfehler:', s.errorString(), file=sys.stderr))
        sock.startServerEncryption()

    def _encrypted(self, sock):
        self._readers[sock] = JsonLines()
        sock.readyRead.connect(lambda s=sock: self._read(s))
        print('TLS verbunden:', sock.peerAddress().toString(),
              'Cipher:', sock.sessionCipher().name())

    def _ssl_errors(self, sock, errors):
        for error in errors:
            print('SSL-Fehler:', error.errorString(), file=sys.stderr)
        # Absichtlich KEIN ignoreSslErrors()!
        sock.disconnectFromHost()

    def _read(self, sock):
        if not sock.isEncrypted():
            sock.abort()
            return
        reader = self._readers.get(sock)
        if reader is None:
            sock.abort()
            return
        try:
            requests = reader.feed(bytes(sock.readAll()))
            for request in requests:
                # Demo-Aktion: keine Passwörter und keine Datenbankrechte!
                if request.get('action') == 'ping':
                    result = {'ok': True, 'data': {'pong': True, 'tls': True}}
                else:
                    result = {'ok': False, 'error': 'Demo unterstützt nur ping'}
                sock.write(encode_message(result))
        except (ValueError, UnicodeError) as exc:
            print('Ungültige RPC-Anfrage:', exc, file=sys.stderr)
            sock.abort()

    def _disconnected(self, sock):
        self._readers.pop(sock, None)
        self._sockets.discard(sock)
        sock.deleteLater()


def main():
    parser = argparse.ArgumentParser(description='PythonBDE Qt5 TLS-Demoserver')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=43650)
    parser.add_argument('--cert', default='certificates/server.crt')
    parser.add_argument('--key', default='certificates/server.key')
    args = parser.parse_args()
    app = QCoreApplication(sys.argv)
    try:
        server = TlsJsonServer(args.cert, args.key)
    except (OSError, ValueError, RuntimeError) as exc:
        print('TLS-Initialisierung fehlgeschlagen:', exc, file=sys.stderr)
        return 1
    if not server.listen(QHostAddress(args.host), args.port):
        print('Bind fehlgeschlagen:', server.errorString(), file=sys.stderr)
        return 1
    print(f'TLS-Demoserver hört auf {args.host}:{args.port}')
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
