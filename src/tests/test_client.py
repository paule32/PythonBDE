"""Tests für den Beispielclient ohne laufenden Qt-Server."""
import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import client_example


class TestClient(unittest.TestCase):
    def test_send_reads_one_response_without_print(self):
        channel = MagicMock()
        channel.readline.return_value = b'{"ok":true,"data":{"USERNAME":"admin"}}\n'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            data = client_example.send(None, channel, "login", username="admin", password="top secret")
        self.assertEqual("", output.getvalue())
        self.assertTrue(data["ok"])
        wire = channel.write.call_args[0][0]
        self.assertEqual(1, wire.count(b"\n"))
        self.assertEqual("login", json.loads(wire)["action"])
        self.assertNotIn(b'top secret', output.getvalue().encode())

    def test_normal_login_prints_one_answer_and_no_whoami(self):
        response = {"ok": True, "data": {"USERNAME": "admin", "ADMIN": True}}
        calls = []
        def fake_send(sock, f, action, **kw):
            calls.append(action)
            if action == "hello":
                return {"ok": True, "data": {"tls": True}}
            if action == "login":
                return response
            return {"ok": True, "data": {"logged_out": True}}
        output = io.StringIO()
        with patch.object(client_example.socket, "create_connection"), \
             patch.object(client_example.ssl, "create_default_context"), \
             patch.object(client_example.Path, "is_file", return_value=True) as conn, \
             patch.object(client_example, "send", side_effect=fake_send), \
             patch("builtins.input", return_value="admin"), \
             patch.object(client_example.getpass, "getpass", return_value="secure"), \
             contextlib.redirect_stdout(output):
            self.assertEqual(0, client_example.main([]))
        self.assertEqual(["hello", "login", "logout"], calls)
        lines = output.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertEqual("login", json.loads(lines[0])["action"])
        self.assertNotIn("secure", output.getvalue())

    def test_async_message_is_not_confused_with_reply(self):
        channel = MagicMock()
        channel.readline.side_effect = [
            b'{"event":"server_message","text":"Maintenance"}\n',
            b'{"ok":true,"data":{"USERNAME":"admin"}}\n',
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            response = client_example.send(None, channel, "login", username="admin", password="secret")
        self.assertTrue(response["ok"])
        self.assertIn("Maintenance", stderr.getvalue())
        self.assertNotIn("secret", stderr.getvalue())

    def test_kick_event_causes_disconnect_error(self):
        channel = MagicMock()
        channel.readline.return_value = b'{"event":"kicked","reason":"Admin"}\n'
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(ConnectionError):
                client_example.send(None, channel, "whoami")

    def test_failed_login_no_followup(self):
        calls = []
        def fake_send(sock, f, action, **kw):
            calls.append(action)
            return ({"ok": True, "data": {"tls": True}} if action == "hello"
                    else {"ok": False, "error": "Anmeldung fehlgeschlagen"})
        output = io.StringIO()
        with patch.object(client_example.socket, "create_connection"), \
             patch.object(client_example.ssl, "create_default_context"), \
             patch.object(client_example.Path, "is_file", return_value=True), \
             patch.object(client_example, "send", side_effect=fake_send), \
             patch("builtins.input", return_value="admin"), \
             patch.object(client_example.getpass, "getpass", return_value="bad"), \
             contextlib.redirect_stdout(output):
            self.assertEqual(1, client_example.main([]))
        self.assertEqual(["hello", "login"], calls)
        self.assertEqual(1, len(output.getvalue().splitlines()))

    def test_explicit_whoami_adds_second_answer(self):
        calls = []
        def fake_send(sock, f, action, **kw):
            calls.append(action)
            return {"ok": True, "data": {"ADMIN": False, "tls": True}}
        output = io.StringIO()
        with patch.object(client_example.socket, "create_connection"), \
             patch.object(client_example.ssl, "create_default_context"), \
             patch.object(client_example.Path, "is_file", return_value=True), \
             patch.object(client_example, "send", side_effect=fake_send), \
             patch("builtins.input", return_value="gast"), \
             patch.object(client_example.getpass, "getpass", return_value="safe"), \
             contextlib.redirect_stdout(output):
            self.assertEqual(0, client_example.main(["--whoami"]))
        self.assertEqual(["hello", "login", "whoami", "logout"], calls)
        self.assertEqual(2, len(output.getvalue().splitlines()))


if __name__ == "__main__":
    unittest.main()
