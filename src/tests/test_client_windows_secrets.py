"""Tests for secure Windows credential envelopes without a Windows runtime."""
import ast
import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pythonbde.windows_secrets import (
    ENVELOPE_ALGORITHM, ServerSecrets, encrypt_password, make_nonce,
    save_trusted_fingerprint, trusted_fingerprint,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from pythonbde.auth import AuthError

BASE = Path(__file__).resolve().parents[1]
CLIENT = (BASE / 'rpc_client.py').read_text('utf-8')
SERVER = (BASE / 'pythonbde' / 'protocol.py').read_text('utf-8')


def fake_pair():
    obj = object.__new__(ServerSecrets)
    obj.private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    obj.public_pem = obj.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    from hashlib import sha256
    obj.fingerprint = sha256(obj.public_pem).hexdigest()
    return obj


class WindowsEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secrets = fake_pair()

    def test_envelope_roundtrip_uses_encrypted_password(self):
        nonce = make_nonce()
        packet = encrypt_password(self.secrets.hello_fields()['serverPublicKey'],
                                  self.secrets.fingerprint, nonce, 'übergeheim-&123!')
        self.assertEqual(ENVELOPE_ALGORITHM, packet['alg'])
        self.assertNotIn('password', packet)
        self.assertNotIn(b'geheim', base64.b64decode(packet['ciphertext']))
        self.assertEqual('übergeheim-&123!', self.secrets.decrypt_envelope(packet, nonce))

    def test_nonce_is_bound_to_tcp_session(self):
        packet = encrypt_password(self.secrets.hello_fields()['serverPublicKey'],
                                  self.secrets.fingerprint, 'session-nonce-A', 'secret')
        with self.assertRaises(ValueError):
            self.secrets.decrypt_envelope(packet, 'session-nonce-B')

    def test_wrong_fingerprint_refused(self):
        with self.assertRaises(ValueError):
            encrypt_password(self.secrets.hello_fields()['serverPublicKey'],
                             '00'*32, 'nonce', 'secret')

    def test_tampered_ciphertext_refused(self):
        packet = encrypt_password(self.secrets.hello_fields()['serverPublicKey'],
                                  self.secrets.fingerprint, 'once', 'secret')
        packet['ciphertext'] = base64.b64encode(b'broken').decode('ascii')
        with self.assertRaises(ValueError):
            self.secrets.decrypt_envelope(packet, 'once')

    def test_key_trust_persistence(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'trusted.json'
            self.assertIsNone(trusted_fingerprint('server:123', file))
            save_trusted_fingerprint('server:123', self.secrets.fingerprint, file)
            self.assertEqual(self.secrets.fingerprint, trusted_fingerprint('server:123', file))

    def test_client_hello_precedes_password(self):
        self.assertIn('self._send("hello", clientPlatform=platform.system())', CLIENT)
        self.assertIn('QSslSocket', CLIENT)
        self.assertIn('connectToHostEncrypted(', CLIENT)
        self.assertIn('setPeerVerifyMode(QSslSocket.VerifyPeer)', CLIENT)
        self.assertIn('info.get("tls") is not True', CLIENT)
        self.assertNotIn('ignoreSslErrors(', CLIENT)

    def test_hello_challenge_and_envelope_in_server(self):
        self.assertIn('state["hello_nonce"] = nonce', SERVER)
        self.assertIn('state.pop("hello_nonce", None)', SERVER)
        self.assertIn('self.windows_secrets.decrypt_envelope(envelope, nonce)', SERVER)
        self.assertIn('"password" in req', SERVER)

    def test_ui_layout_toolbar_and_movable_icon_exist(self):
        self.assertIn('display_layout = QHBoxLayout(display_box)', CLIENT)
        self.assertIn('display_layout.addLayout(geometry_layout, 2)', CLIENT)
        self.assertIn('toolbar.addAction(theme_icon(False)', CLIENT)
        self.assertIn('apply_application_theme(self._dark_theme)', CLIENT)
        self.assertIn('class DraggableCloseIcon(QWidget)', CLIENT)
        self.assertIn('def mouseMoveEvent(self, event)', CLIENT)
        self.assertIn('self.window().close()', CLIENT)
        self.assertIn('self._client_window.set_theme(self._dark_theme)', CLIENT)


if __name__ == '__main__':
    unittest.main()

class WindowsProtocolRoundtripTests(unittest.TestCase):
    """Execute actual extracted BDEServer methods to cover the JSON protocol."""

    @classmethod
    def setUpClass(cls):
        cls.secrets = fake_pair()

    def test_windows_hello_encrypted_login_roundtrip(self):
        from test_rpc import FakeServer, NAMESPACE
        server = FakeServer()
        server.windows_secrets = self.secrets
        sock = server.attach()
        with patch.dict(NAMESPACE, {'platform': SimpleNamespace(system=lambda: 'Windows'),
                                   'make_nonce': make_nonce}):
            hello = server._request(sock, {'action': 'hello'})[0]
            self.assertTrue(hello['ok'])
            data = hello['data']
            self.assertEqual(ENVELOPE_ALGORITHM, data['passwordTransport'])
            secret = encrypt_password(data['serverPublicKey'], data['serverFingerprint'], data['nonce'], 'good')
            packets = server._request(sock, {'action': 'login', 'clientPlatform': 'Windows',
                                             'username': 'user', 'passwordSecret': secret})
        self.assertTrue(packets[1]['ok'])
        self.assertEqual('CreateWindow', packets[2]['setFunc'])
        self.assertNotIn('hello_nonce', server.clients[sock])

    def test_replay_on_another_session_is_rejected(self):
        from test_rpc import FakeServer, NAMESPACE
        server = FakeServer()
        server.windows_secrets = self.secrets
        first = server.attach('session-1')
        second = server.attach('session-2')
        with patch.dict(NAMESPACE, {'platform': SimpleNamespace(system=lambda: 'Windows'),
                                   'make_nonce': make_nonce}):
            hello = server._request(first, {'action': 'hello'})[0]['data']
            server._request(second, {'action': 'hello'})
            secret = encrypt_password(hello['serverPublicKey'], hello['serverFingerprint'],
                                      hello['nonce'], 'good')
            result = server._request(second, {'action':'login','username':'user',
                                             'clientPlatform':'Windows', 'passwordSecret':secret})[-1]
        self.assertFalse(result['ok'])
        self.assertIsNone(server.clients[second]['username'])

    def test_windows_plaintext_client_rejected(self):
        from test_rpc import FakeServer, NAMESPACE
        server = FakeServer()
        server.windows_secrets = self.secrets
        sock = server.attach()
        with patch.dict(NAMESPACE, {'platform': SimpleNamespace(system=lambda: 'Windows'),
                                   'make_nonce': make_nonce}):
            result = server._request(sock, {'action': 'login', 'username':'user',
                                            'clientPlatform':'Windows','password':'good'})[-1]
        self.assertFalse(result['ok'])
