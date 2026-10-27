"""Eigenständiger PyQt5 TLS-Client für JSON-Lines.

Prüft die Zertifikatskette UND den Hostnamen gegen die beim Server
angegebene Identität; bricht bei SSL-Fehlern ab.
"""
import argparse
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QTimer
from PyQt5.QtNetwork import QSsl, QSslCertificate, QSslSocket

from framing import JsonLines, encode_message


class TlsJsonClient:
    def __init__(self, app, host, port, ca_file, timeout_ms=10000):
        if not QSslSocket.supportsSsl():
            raise RuntimeError('Qt5/OpenSSL: TLS nicht verfügbar')
        self.app = app
        self.reader = JsonLines()
        self.sock = QSslSocket()
        certs = QSslCertificate.fromPath(str(Path(ca_file).resolve()))
        if not certs:
            raise ValueError('Kein gültiges CA-/Serverzertifikat gefunden')
        self.sock.addCaCertificates(certs)
        self.sock.setPeerVerifyMode(QSslSocket.VerifyPeer)
        self.sock.setProtocol(QSsl.TlsV1_2OrLater)
        self.sock.encrypted.connect(self._on_encrypted)
        self.sock.readyRead.connect(self._on_read)
        self.sock.sslErrors.connect(self._on_ssl_errors)
        self.sock.errorOccurred.connect(self._on_error)
        self.sock.disconnected.connect(self._on_disconnected)
        self._completed = False
        self._timeout = QTimer()
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)
        self._timeout.start(timeout_ms)
        self.sock.connectToHostEncrypted(host, port)

    def _on_encrypted(self):
        print('TLS ausgehandelt:', self.sock.sessionCipher().name())
        # ERST nach dem TLS-Handshake RPC-Daten senden.
        if self.sock.isEncrypted():
            self.sock.write(encode_message({'action': 'ping'}))

    def _on_read(self):
        if not self.sock.isEncrypted():
            self._fail('Unverschlüsselte Antwort abgewiesen')
            return
        try:
            packets = self.reader.feed(bytes(self.sock.readAll()))
        except (ValueError, UnicodeError) as exc:
            self._fail(f'Ungültige Antwort: {exc}')
            return
        for packet in packets:
            print('RPC-Antwort:', packet)
            self._finish(0 if packet.get('ok') else 1)

    def _on_ssl_errors(self, errors):
        for error in errors:
            print('TLS-Zertifikatsfehler:', error.errorString(), file=sys.stderr)
        # Absichtlich keine Ausnahme und KEIN ignoreSslErrors().
        self._fail('TLS-Zertifikatsprüfung fehlgeschlagen')

    def _on_error(self, error):
        if not self._completed:
            self._fail(self.sock.errorString())

    def _on_timeout(self):
        self._fail('TLS-Verbindung zeitlich abgelaufen')

    def _on_disconnected(self):
        if not self._completed:
            self._fail('Verbindung vorzeitig getrennt')

    def _fail(self, message):
        print(message, file=sys.stderr)
        self._finish(1)

    def _finish(self, code):
        if self._completed:
            return
        self._completed = True
        self._timeout.stop()
        self.sock.abort()
        self.app.exit(code)


def main():
    parser = argparse.ArgumentParser(description='PythonBDE Qt5 TLS-Democlient')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=43650)
    parser.add_argument('--cafile', default='certificates/server.crt')
    args = parser.parse_args()
    app = QCoreApplication(sys.argv)
    try:
        client = TlsJsonClient(app, args.host, args.port, args.cafile)
    except (OSError, ValueError, RuntimeError) as exc:
        print('TLS-Client-Initialisierung fehlgeschlagen:', exc, file=sys.stderr)
        return 1
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
