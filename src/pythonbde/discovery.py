"""Schnelle PythonBDE-Erkennung per UDP-Subnetzbroadcast, kein invasiver Portscan.

Nur best-effort pro Broadcast-Domain: Firewalls, VLANs, Router oder gleichzeitige
Starts können Discovery verhindern. Kein global verteiltes Exklusivitätsprotokoll.
"""
from __future__ import annotations

import json
import select
import secrets
import socket
import time
from typing import Iterable

from .settings import DISCOVERY_PORT

MAGIC = "PYTHONBDE_DISCOVERY_V1"
MAX_PACKET = 1500


def create_probe(nonce: str | None = None) -> bytes:
    return json.dumps({"magic": MAGIC, "command": "probe",
                       "nonce": nonce or secrets.token_hex(12)}, separators=(",", ":")).encode("ascii")


def decode(packet: bytes) -> dict | None:
    if len(packet) > MAX_PACKET:
        return None
    try:
        obj = json.loads(packet.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    if isinstance(obj, dict) and obj.get("magic") == MAGIC:
        return obj
    return None


def discover_existing(server_id: str, broadcast_addresses: Iterable[str],
                      *, port: int = DISCOVERY_PORT, timeout: float = 0.30,
                      own_instance: str = "") -> dict | None:
    """Sendet kurz parallele Probes. Antwort identifiziert Produkt/ID/Host/Port.

    Der lokale Server-ID-Abgleich verhindert eine Antwort auf ein eigenes Probe.
    """
    addresses = sorted(set(broadcast_addresses) | {"127.0.0.1"})
    probe = create_probe()
    nonce = decode(probe)["nonce"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.bind(("0.0.0.0", 0))
        for target in addresses:
            try:
                udp.sendto(probe, (target, port))
            except OSError:
                pass  # einzelne NIC kann keine Broadcastpakete senden
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ready, _, _ = select.select([udp], [], [], max(0, end - time.monotonic()))
            if not ready:
                break
            try:
                raw, address = udp.recvfrom(MAX_PACKET+1)
            except OSError:
                continue
            item = decode(raw)
            if item and item.get("command") == "here" and item.get("nonce") == nonce and (
                    not own_instance or item.get("instance") != own_instance):
                if isinstance(item.get("id"), str) and isinstance(item.get("port"), int):
                    return {"id": item["id"], "address": address[0], "port": item["port"],
                            "duplicate_id": item["id"] == server_id}
    return None


def network_interfaces() -> list[dict]:
    """IPv4-NICs über Qt (identische Ermittlung unter Windows und Linux)."""
    from PyQt5.QtNetwork import QAbstractSocket, QNetworkInterface
    interfaces = []
    for nic in QNetworkInterface.allInterfaces():
        if not (nic.flags() & QNetworkInterface.IsUp):
            continue
        for entry in nic.addressEntries():
            addr = entry.ip()
            if addr.protocol() != QAbstractSocket.IPv4Protocol:
                continue
            broadcast = entry.broadcast().toString()
            interfaces.append({"name": nic.humanReadableName() or nic.name(),
                               "key": nic.name(), "ip": addr.toString(),
                               "broadcast": broadcast if broadcast and broadcast != "0.0.0.0" else ""})
    return interfaces


def broadcast_targets(interfaces: list[dict]) -> list[str]:
    return list(dict.fromkeys(n["broadcast"] for n in interfaces if n.get("broadcast")
                              and n.get("ip") != "127.0.0.1"))
