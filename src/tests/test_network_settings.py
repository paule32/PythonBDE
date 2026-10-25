"""Plattformunabhängige Tests für INI und UDP-Discovery."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
import uuid

from pythonbde.settings import Settings, load_settings, save_settings
from pythonbde.discovery import MAGIC, decode, discover_existing, broadcast_targets, create_probe


class TestServerSettings(unittest.TestCase):
    def test_ini_persist_unique_server_id(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = Path(temp) / "pythonbde.ini"
            initial = load_settings(cfg)
            self.assertTrue(cfg.exists())
            self.assertEqual("127.0.0.1", initial.ip)
            self.assertEqual(43650, initial.port)
            uuid.UUID(initial.server_id)
            self.assertEqual(initial, load_settings(cfg))
            custom = Settings(server_id=initial.server_id, ip="0.0.0.0", port=43652, nic="eth0")
            save_settings(custom, cfg)
            self.assertEqual(custom, load_settings(cfg))
            self.assertIn("port = 43652", cfg.read_text())
            if os.name == "posix":
                self.assertEqual(0o600, cfg.stat().st_mode & 0o777)

    def test_invalid_settings_rejected(self):
        original = str(uuid.uuid4())
        for ip, port in (("hostname.local", 43650), ("::1", 43650), ("127.0.0.1", 80),
                         ("127.0.0.1", 65536)):
            with self.subTest(ip=ip, port=port), self.assertRaises(ValueError):
                Settings(original, ip, port).validate()
        with self.assertRaises(ValueError):
            Settings("bad-id").validate()

    def test_broadcast_target_dedup(self):
        self.assertEqual(["192.168.1.255"], broadcast_targets([
            {"ip": "127.0.0.1", "broadcast": "127.255.255.255"},
            {"ip": "192.168.1.3", "broadcast": "192.168.1.255"},
            {"ip": "192.168.1.4", "broadcast": "192.168.1.255"},
        ]))

    def test_udp_discovery_real_loopback(self):
        ready = threading.Event()
        data = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as response_socket:
            response_socket.bind(("127.0.0.1", 0))
            response_socket.settimeout(2)
            port = response_socket.getsockname()[1]

            def responder():
                ready.set()
                try:
                    packet, sender = response_socket.recvfrom(1500)
                    data.append(decode(packet))
                    response_socket.sendto(json.dumps({"magic": MAGIC, "command": "here",
                         "id": "remote", "port": 43650, "instance": "remote-run",
                         "nonce": decode(packet)["nonce"]}).encode(), sender)
                except OSError:
                    pass
            thread = threading.Thread(target=responder)
            thread.start()
            ready.wait(1)
            try:
                found = discover_existing("local", [], port=port, timeout=.3)
            finally:
                thread.join(2)
        self.assertEqual("remote", found["id"])
        self.assertEqual("127.0.0.1", found["address"])
        self.assertFalse(found["duplicate_id"])
        self.assertEqual("probe", data[0]["command"])

    def test_duplicate_id_still_detected(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.bind(("127.0.0.1", 0))
            udp.settimeout(1)
            port = udp.getsockname()[1]

            def responder():
                packet, sender = udp.recvfrom(1500)
                udp.sendto(json.dumps({"magic": MAGIC, "command": "here",
                        "id": "same", "port": 43650, "instance": "other",
                        "nonce": decode(packet)["nonce"]}).encode(), sender)
            thread = threading.Thread(target=responder)
            thread.start()
            try:
                found = discover_existing("same", [], port=port, timeout=.3,
                                          own_instance="our-instance")
            finally:
                thread.join(2)
        self.assertTrue(found["duplicate_id"])

    def test_discovery_packet_validation(self):
        self.assertIsNone(decode(b"bad json"))
        self.assertIsNone(decode(b"x"*1600))
        self.assertEqual("probe", decode(create_probe())["command"])

if __name__ == "__main__":
    unittest.main()
