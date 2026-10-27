"""Testet korrekte PKI-Kette fuer Qt5/QSslSocket und Python-ssl."""
from __future__ import annotations
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID
from pythonbde.tls_security import (
    make_ca_signed_server_certificates, make_test_certificate,
    validate_ca_bundle, validate_server_certificate,
)


class TestCaChain(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.paths = (base / 'server.crt', base / 'server.key', base / 'ca.crt', base / 'ca.key')
        make_ca_signed_server_certificates(*self.paths)

    def test_cert_uses_ca_as_issuer_and_restricts_roles(self):
        server = x509.load_pem_x509_certificate(self.paths[0].read_bytes())
        root = x509.load_pem_x509_certificate(self.paths[2].read_bytes())
        self.assertEqual(server.issuer, root.subject)
        self.assertTrue(root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertFalse(server.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH,
                      server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
        self.assertEqual(validate_ca_bundle(self.paths[2]), 1)
        self.assertEqual(validate_server_certificate(self.paths[0], self.paths[1]), 'RSA')
        if os.name == 'posix':
            self.assertEqual(self.paths[1].stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.paths[3].stat().st_mode & 0o777, 0o600)

    def test_do_not_overwrite_keypair_or_ca(self):
        before = [p.read_bytes() for p in self.paths]
        with self.assertRaises(FileExistsError):
            make_ca_signed_server_certificates(*self.paths)
        self.assertEqual(before, [p.read_bytes() for p in self.paths])

    def test_legacy_server_leaf_is_not_a_ca(self):
        base = Path(self.temporary.name)
        cert, _key = make_test_certificate(base / 'old_server.crt', base / 'old_server.key')
        with self.assertRaisesRegex(ValueError, 'Serverzertifikat statt einer CA'):
            validate_ca_bundle(cert)

    def test_ca_bundle_rejects_wrong_file(self):
        with self.assertRaisesRegex(ValueError, 'Serverzertifikat statt einer CA'):
            validate_ca_bundle(self.paths[0])
        with self.assertRaises(ValueError):
            validate_ca_bundle(self.paths[1])

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI nicht installiert")
    def test_openssl_verify_chain(self):
        result = subprocess.run(['openssl', 'verify', '-CAfile', str(self.paths[2]), str(self.paths[0])],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_tls_handshake_right_and_wrong_ca(self):
        server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
        server_ssl.load_cert_chain(str(self.paths[0]), str(self.paths[1]))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(3)
            port = listener.getsockname()[1]
            calls = []
            def server():
                for _ in range(3):
                    conn, _address = listener.accept()
                    try:
                        with server_ssl.wrap_socket(conn, server_side=True) as s:
                            calls.append(('ok', s.version()))
                            s.sendall(b'ok')
                    except ssl.SSLError:
                        calls.append(('reject', None))
            thread = threading.Thread(target=server, daemon=True)
            thread.start()
            verified = ssl.create_default_context(cafile=str(self.paths[2]))
            with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
                with verified.wrap_socket(sock, server_hostname='localhost') as tls:
                    self.assertEqual(tls.recv(2), b'ok')
            with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    verified.wrap_socket(sock, server_hostname='wrong.example')
            root2 = Path(self.temporary.name) / 'other'
            paths2 = tuple(root2 / p.name for p in self.paths)
            make_ca_signed_server_certificates(*paths2)
            untrusted = ssl.create_default_context(cafile=str(paths2[2]))
            with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    untrusted.wrap_socket(sock, server_hostname='localhost')
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(calls[0][0], 'ok')

if __name__ == '__main__':
    unittest.main()
