"""Qt5 TCP/JSON-Lines Protokoll; Fernzugriff ausschließlich in geschützten Netzen/TLS-Proxy."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QHostAddress, QTcpServer, QUdpSocket

from .discovery import create_probe, decode, discover_existing, network_interfaces, broadcast_targets, MAGIC
from .settings import DISCOVERY_PORT

from .auth import AuthError, UserManager, parse_time, utcnow

MAX_LINE = 64 * 1024
MAX_QUEUE = 128 * 1024
SESSION_TTL = 60 * 60


class BDEServer(QObject):
    message = pyqtSignal(str)
    changed = pyqtSignal()
    status_changed = pyqtSignal()
    audit = pyqtSignal(int, str)

    def __init__(self, users: UserManager, parent=None):
        super().__init__(parent)
        self.users = users
        self.listener = QTcpServer(self)
        self.listener.newConnection.connect(self._accepted)
        self.discovery = QUdpSocket(self)
        self.discovery.readyRead.connect(self._answer_discovery)
        self.clients = {}  # socket -> {buffer, username, logged_at, login_time}
        self.server_id = ""
        self.bind_ip = "127.0.0.1"
        self.last_action = None
        self.started_at = ""
        self.instance_id = str(uuid.uuid4())
        self._next_session = 0

    def start(self, port: int = 43650, ip: str = "127.0.0.1", *, server_id: str = ""):
        if self.listener.isListening():
            return True
        if not 1024 <= port <= 65535:
            raise ValueError("Port außerhalb des gültigen Bereichs")
        addr = QHostAddress(ip)
        if addr.isNull() or addr.protocol() != QHostAddress("127.0.0.1").protocol():
            raise ValueError("Ungültige IPv4-Bind-Adresse")
        local_ips = {"0.0.0.0", "127.0.0.1"} | {n["ip"] for n in network_interfaces()}
        if ip not in local_ips:
            raise ValueError("Die angegebene IP gehört zu keiner lokalen Netzwerkkarte")
        identity = server_id or self.server_id or "local-server"
        peer = discover_existing(identity, broadcast_targets(network_interfaces()))
        if peer:
            raise OSError(("Doppelte Server-ID! " if peer["duplicate_id"] else "") +
                          "Nur 1 PythonBDE-Server pro Netzwerk erlaubt! "
                          f"Bereits vorhanden: {peer['address']}:{peer['port']} (ID {peer['id']})")
        # Erst Bind reservieren, dann Discovery-Port. Fehlstart schließt beide Handles.
        if not self.listener.listen(addr, port):
            raise OSError(f"IP and/or Port already in use: {self.listener.errorString()}")
        try:
            if not self.discovery.bind(QHostAddress.AnyIPv4, DISCOVERY_PORT,
                                       QUdpSocket.DontShareAddress):
                raise OSError("Discovery-Port bereits in Benutzung (anderer PythonBDE-Server? ): "
                              + self.discovery.errorString())
        except BaseException:
            self.discovery.close()
            self.listener.close()
            raise
        self.server_id = identity
        self.bind_ip = ip
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.message.emit(f"Server gestartet: {ip}:{self.listener.serverPort()} (ID {identity})")
        self.audit.emit(200, f"Server started: {ip}:{port}")
        self.status_changed.emit()
        return True

    def stop(self):
        self.discovery.close()
        self.listener.close()
        for sock in list(self.clients):
            sock.disconnectFromHost()
            sock.close()
        self.clients.clear()
        self.started_at = ""
        self.message.emit("Server angehalten")
        self.audit.emit(200, "Server stopped")
        self.status_changed.emit()

    def _answer_discovery(self):
        while self.discovery.hasPendingDatagrams():
            datagram, sender, sender_port = self.discovery.readDatagram(1501)
            packet = decode(bytes(datagram))
            if packet and packet.get("command") == "probe" and self.listener.isListening():
                response = json.dumps({"magic": MAGIC, "command": "here", "id": self.server_id,
                                       "port": self.listener.serverPort(),
                                       "instance": self.instance_id, "nonce": packet.get("nonce", "")}).encode("ascii")
                self.discovery.writeDatagram(response, sender, sender_port)

    def note_action(self, operation: str, username: str = "", table: str = ""):
        """Gemeinsame Anzeige für Adminaktionen und künftige Record-Operationen."""
        self.last_action = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "operation": operation, "username": username, "table": table}
        self.status_changed.emit()

    def status_snapshot(self) -> dict:
        now = time.monotonic()
        sessions = []
        for state in self.clients.values():
            if state["username"] and (now - state["logged_at"]) <= SESSION_TTL:
                sessions.append({"username": state["username"],
                                 "login_time": state["login_time"],
                                 "session_id": state["session_id"],
                                 "peer": state["peer"]})
        return {"running": self.listener.isListening(), "ip": self.bind_ip,
                "port": self.listener.serverPort() if self.listener.isListening() else 0,
                "id": self.server_id, "started_at": self.started_at,
                "connected_clients": len(self.clients), "session_count": len(sessions),
                "login_count": len({s["username"] for s in sessions}),
                "sessions": sessions, "last_action": self.last_action}

    def revoke_sessions(self, username=None):
        for state in self.clients.values():
            if username is None or state["username"] == username.casefold():
                state.update(username=None, logged_at=0, login_time="")
        self.status_changed.emit()

    def _find_session(self, session_id):
        for sock, state in self.clients.items():
            if state["session_id"] == session_id and state["username"]:
                return sock, state
        return None, None

    def send_message(self, message: str, session_id: str | None = None) -> int:
        """Async-Ereignis an ein oder alle angemeldeten JSONL-Clients senden."""
        message = str(message).strip()
        if not message or len(message) > 2048:
            raise ValueError("Nachricht muss 1 bis 2048 Zeichen enthalten")
        delivered = 0
        for sock, state in list(self.clients.items()):
            if state["username"] and (session_id is None or state["session_id"] == session_id):
                self._send(sock, {"event": "server_message", "text": message})
                delivered += 1
        if session_id is not None and not delivered:
            raise ValueError("Sitzung nicht mehr vorhanden")
        self.audit.emit(200, f"Message sent to {delivered} client(s)")
        return delivered

    def kick(self, session_id: str, *, message: str = ""):
        sock, state = self._find_session(session_id)
        if state is None:
            raise ValueError("Sitzung nicht mehr vorhanden")
        username = state["username"]
        if message:
            self.send_message(message, session_id)
        self._send(sock, {"event": "kicked", "reason": "Sitzung durch Administrator beendet"})
        state.update(username=None, logged_at=0, login_time="")
        # disconnectFromHost() liefert bereits gepufferte Nachrichten vor FIN aus.
        sock.disconnectFromHost()
        self.audit.emit(200, f"User kicked: {username}")
        self.status_changed.emit()

    def kick_all(self, message="") -> int:
        session_ids = [s["session_id"] for s in self.clients.values() if s["username"]]
        if message:
            self.send_message(message)
        for session_id in session_ids:
            try:
                self.kick(session_id)
            except ValueError:
                pass
        return len(session_ids)

    def ban(self, session_id: str):
        sock, state = self._find_session(session_id)
        if state is None:
            raise ValueError("Sitzung nicht mehr vorhanden")
        username = state["username"]
        self.users.edit(username, lock_user=True)
        peers = [peer for peer, peer_state in self.clients.items()
                 if peer_state["username"] == username]
        for peer in peers:
            self._send(peer, {"event": "kicked", "reason": "Konto gesperrt"})
            peer.disconnectFromHost()
        self.revoke_sessions(username)
        self.changed.emit()
        self.note_action("Update Record", username, "users.dbf")
        self.audit.emit(200, f"User banned: {username}")
        self.status_changed.emit()

    def _accepted(self):
        while self.listener.hasPendingConnections():
            sock = self.listener.nextPendingConnection()
            self._next_session += 1
            self.clients[sock] = {"buffer": bytearray(), "username": None, "logged_at": 0, "login_time": "",
                                  "session_id": f"session-{self._next_session}",
                                  "peer": sock.peerAddress().toString()}
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._gone(s))
            self.status_changed.emit()

    def _gone(self, sock):
        self.clients.pop(sock, None)
        sock.deleteLater()
        self.status_changed.emit()

    def _send(self, sock, data):
        if sock.state() == sock.UnconnectedState:
            return
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        sock.write(encoded)

    def _read(self, sock):
        state = self.clients.get(sock)
        if state is None:
            return
        state["buffer"].extend(bytes(sock.readAll()))
        if len(state["buffer"]) > MAX_QUEUE:
            self._send(sock, {"ok": False, "error": "Anfrage zu groß"})
            sock.disconnectFromHost()
            return
        if len(state["buffer"]) > MAX_LINE and b"\n" not in state["buffer"]:
            self._send(sock, {"ok": False, "error": "Zeile zu groß"})
            sock.disconnectFromHost()
            return
        self._process_pending(sock)

    def _process_pending(self, sock):
        state = self.clients.get(sock)
        if state is None:
            return
        for _ in range(40):
            req = None
            try:
                end = state["buffer"].index(10)
            except ValueError:
                break
            line = bytes(state["buffer"][:end]); del state["buffer"][:end+1]
            if len(line) > MAX_LINE:
                self._send(sock, {"ok": False, "error": "Zeile zu groß"})
                sock.disconnectFromHost()
                return
            try:
                req = json.loads(line.decode("utf-8"))
                if not isinstance(req, dict):
                    raise ValueError("JSON-Objekt erwartet")
                result = self._dispatch(state, req)
                self._send(sock, {"ok": True, "data": result})
            except (ValueError, TypeError, KeyError, AuthError) as e:
                self._send(sock, {"ok": False, "error": str(e)})
                if isinstance(req, dict) and req.get("action") in (
                        "create_user", "edit_user", "delete_user", "unlock_user"):
                    self.audit.emit(400, f"User operation failed: {req.get('action')} ({type(e).__name__})")
            except Exception:
                # Keine internen Stacktraces/Dateipfade an Netzwerkclients ausgeben.
                self._send(sock, {"ok": False, "error": "Interner Serverfehler"})
                self.message.emit("Fehler bei der Anfrageverarbeitung (siehe lokale Diagnose)")
        if b"\n" in state["buffer"] and sock in self.clients:
            QTimer.singleShot(0, lambda s=sock: self._process_pending(s))

    def _dispatch(self, state, req):
        action = req.get("action")
        if action == "ping":
            return {"name": "PythonBDE", "version": "0.4.0", "protocol": "jsonl/1",
                    "server_id": self.server_id}
        if action == "login":
            state.update(username=None, logged_at=0, login_time="")
            name = req.get("username", "")
            password = req.get("password", "")
            if not isinstance(name, str) or not isinstance(password, str) or len(name) > 48 or len(password) > 256:
                raise AuthError("Anmeldung fehlgeschlagen")
            user = self.users.authenticate(name, password)
            if user is None:
                self.audit.emit(400, "Login failed")
                raise AuthError("Anmeldung fehlgeschlagen")
            state.update(username=user["USERNAME"].casefold(), logged_at=time.monotonic(),
                         login_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
            self.status_changed.emit()
            self.audit.emit(200, f"User logged in: {user['USERNAME']}")
            return user
        if action == "logout":
            state.update(username=None, logged_at=0, login_time="")
            self.status_changed.emit()
            self.audit.emit(200, "User logged out")
            return {"logged_out": True}
        name = state["username"]
        if not name or time.monotonic() - state["logged_at"] > SESSION_TTL:
            state.update(username=None, logged_at=0, login_time="")
            raise AuthError("Nicht angemeldet oder Sitzung abgelaufen")
        current = self.users.get(name)
        if not current or current["LOCKUSER"] or (parse_time(current["EXPIRE"]) and utcnow() > parse_time(current["EXPIRE"])):
            state.update(username=None, logged_at=0, login_time="")
            raise AuthError("Konto gesperrt/abgelaufen")
        if action == "whoami":
            from .auth import public_user
            return public_user(current)
        if action not in ("list_users", "create_user", "edit_user", "delete_user", "unlock_user"):
            raise ValueError("Unbekannte Aktion")
        if not current["ADMIN"]:
            raise AuthError("Administratorrecht erforderlich")
        if action == "list_users":
            return self.users.listing()
        username = req.get("username", "")
        if action == "delete_user" and isinstance(username, str) and username.casefold() == current["USERNAME"].casefold():
            raise AuthError("Das eigene Administratorkonto darf nicht gelöscht werden")
        if not isinstance(username, str) or len(username) > 48:
            raise ValueError("Ungültiger Benutzername")
        if action == "create_user":
            result = self.users.create(username, req.get("password"), req.get("rights", {}),
                                       lock_user=req.get("lock_user", False),
                                       count_pass=req.get("count_pass", 5),
                                       count_limit=req.get("count_limit", 15), expire=req.get("expire", ""))
        elif action == "edit_user":
            result = self.users.edit(username, password=req.get("password"),
                                     rights=req.get("rights"), lock_user=req.get("lock_user"),
                                     count_pass=req.get("count_pass"), count_limit=req.get("count_limit"),
                                     expire=req.get("expire"))
        elif action == "delete_user":
            self.users.delete(username)
            result = {"deleted": True}
        else:
            self.users.unlock(username)
            result = {"unlocked": True}
        self.revoke_sessions(username)
        self.changed.emit()
        self.note_action({"create_user": "Insert Record", "edit_user": "Modify Record",
                          "delete_user": "Delete Record", "unlock_user": "Update Record"}[action],
                         username, "users.dbf")
        self.message.emit(f"Benutzerverwaltung: {action} ({username})")
        self.audit.emit(200, {
            "create_user": "User successfully created",
            "edit_user": "User successfully modified",
            "delete_user": "User successfully deleted",
            "unlock_user": "User successfully unlocked",
        }[action] + f": {username}")
        return result
