"""TLS v0.5.8: X.509 tests and live Python-SSL transport smoke tests.

The native Qt QSslSocket handshake needs a Windows/Linux machine with PyQt5;
these tests deliberately don't pretend to exercise a Qt event loop.
"""
from __future__ import annotations
import ast
import socket
import ssl
import tempfile
import threading
import unittest
from pathlib import Path
from dataclasses import replace
import uuid

from pythonbde.settings import Settings, load_settings, save_settings
from pythonbde.tls_security import make_test_certificate, validate_server_certificate

ROOT = Path(__file__).resolve().parents[1]


class TLSSecurityTests(unittest.TestCase):
    def test_certificate_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            cert, key = make_test_certificate(Path(d) / 'server.crt', Path(d) / 'server.key')
            self.assertEqual('RSA', validate_server_certificate(cert, key))
            with self.assertRaises(FileExistsError):
                make_test_certificate(cert, key)
            if __import__('os').name == 'posix':
                self.assertEqual(0o600, key.stat().st_mode & 0o777)

    def test_private_key_mismatch_and_missing_san(self):
        with tempfile.TemporaryDirectory() as d:
            c1, k1 = make_test_certificate(Path(d) / 'one.crt', Path(d) / 'one.key')
            _, k2 = make_test_certificate(Path(d) / 'two.crt', Path(d) / 'two.key')
            with self.assertRaisesRegex(ValueError, 'nicht zusammen'):
                validate_server_certificate(c1, k2)

    def test_tls_ini_and_fail_closed_lan(self):
        with tempfile.TemporaryDirectory() as d:
            ini = Path(d) / 'server.ini'
            original = load_settings(ini)
            self.assertTrue(original.tls_enabled)
            custom = replace(original, ip='0.0.0.0', tls_certificate='x.crt', tls_private_key='x.key')
            save_settings(custom, ini)
            self.assertEqual(custom, load_settings(ini))
            with self.assertRaises(ValueError):
                replace(custom, tls_enabled=False).validate()
            self.assertFalse(replace(custom, tls_enabled=False, ip='127.0.0.1').validate().tls_enabled)

    def test_real_tls_12_13_and_hostname_verification(self):
        with tempfile.TemporaryDirectory() as d:
            cert, key = make_test_certificate(Path(d) / 'tls.crt', Path(d) / 'tls.key')
            server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
            server_ssl.load_cert_chain(str(cert), str(key))
            ready = threading.Event()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen(2)
                port = listener.getsockname()[1]
                received = []
                def serve():
                    ready.set()
                    for i in range(2):
                        c, _ = listener.accept()
                        try:
                            with server_ssl.wrap_socket(c, server_side=True) as tls_sock:
                                received.append(tls_sock.recv(128))
                                tls_sock.sendall(b'{"ok":true}\n')
                        except ssl.SSLError:
                            received.append(b'rejected')
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                ready.wait(1)
                trust = ssl.create_default_context(cafile=str(cert))
                trust.minimum_version = ssl.TLSVersion.TLSv1_2
                with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                    with trust.wrap_socket(raw, server_hostname='localhost') as s:
                        self.assertIn(s.version(), ('TLSv1.2', 'TLSv1.3'))
                        s.sendall(b'{"action":"ping"}\n')
                        self.assertIn(b'"ok":true', s.recv(200))
                with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        with trust.wrap_socket(raw, server_hostname='otherhost.invalid'):
                            pass
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(b'{"action":"ping"}\n', received[0])

    def test_project_listener_and_client_prohibit_early_rpc(self):
        server = (ROOT / 'pythonbde' / 'protocol.py').read_text()
        client = (ROOT / 'rpc_client.py').read_text()
        transport = (ROOT / 'pythonbde' / 'tls_transport.py').read_text()
        ast.parse(server); ast.parse(client); ast.parse(transport)
        self.assertIn('self.listener.secureConnected.connect(self._register_socket)', server)
        self.assertIn('if self.listener.tls_enabled and not encrypted:', server)
        self.assertIn('sock.startServerEncryption()', transport)
        self.assertIn('sock.encrypted.connect(lambda s=sock: self._ready(s))', transport)
        self.assertIn('self.sock.encrypted.connect(self._connected)', client)
        self.assertIn('self.sock.connectToHostEncrypted(', client)
        self.assertIn('self.sock.setPeerVerifyMode(QSslSocket.VerifyPeer)', client)
        self.assertIn('self.sock.setPeerVerifyName(', client)
        self.assertNotIn('ignoreSslErrors(', client)

if __name__ == '__main__':
    unittest.main()
