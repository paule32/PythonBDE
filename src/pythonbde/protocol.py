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
from .aliases import AliasRegistry, AliasError, AliasInUse
from .rpc import RPC_TIMEOUT_SECONDS, create_window_request, validate_result

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
        self.aliases = AliasRegistry(users.store.path)
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
        self._rpc_timeout_ms = RPC_TIMEOUT_SECONDS * 1000

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
                                 "peer": state["peer"],
                                 "aliases": sorted(state.get("aliases", set())),
                                 "rpc": state.get("rpc_status", "idle"),
                                 "rpc_error_code": state.get("rpc_error_code", None)})
        return {"running": self.listener.isListening(), "ip": self.bind_ip,
                "port": self.listener.serverPort() if self.listener.isListening() else 0,
                "id": self.server_id, "started_at": self.started_at,
                "connected_clients": len(self.clients), "session_count": len(sessions),
                "login_count": len({s["username"] for s in sessions}),
                "sessions": sessions, "last_action": self.last_action}

    def revoke_sessions(self, username=None):
        for state in self.clients.values():
            if username is None or state["username"] == username.casefold():
                state.update(username=None, logged_at=0, login_time="", aliases=set(), rpc_pending=None)
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
        state.update(username=None, logged_at=0, login_time="", aliases=set())
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

    def active_alias_sessions(self, alias_name: str) -> list[dict]:
        """Nur aktive Login-Sitzungen, die diesen Alias ausdrücklich gewählt haben."""
        key = alias_name.casefold()
        now = time.monotonic()
        return [{"username": s["username"], "session_id": s["session_id"],
                 "peer": s["peer"], "login_time": s["login_time"]}
                for s in self.clients.values()
                if s["username"] and now - s["logged_at"] <= SESSION_TTL
                and key in s.get("aliases", ())]

    def notify_alias_in_use(self, name, sessions):
        """Audit und asynchrone Nachricht an eingeloggte Admin-Clients."""
        self.audit.emit(400, f"Alias is in use: {name} ({len(sessions)} session(s))")
        for sock, state in list(self.clients.items()):
            if not state["username"]:
                continue
            account = self.users.get(state["username"])
            if account and account["ADMIN"]:
                self._send(sock, {"event": "admin_notice", "kind": "alias_in_use",
                                  "alias": name, "session_count": len(sessions)})

    def create_alias(self, name, folder):
        result = self.aliases.create(name, folder)
        self.note_action("Insert Alias", "", name)
        self.audit.emit(200, f"Alias successfully created: {name}")
        return result

    def rename_alias(self, old_name, new_name):
        sessions = self.active_alias_sessions(old_name)
        if sessions:
            self.notify_alias_in_use(old_name, sessions)
            raise AliasInUse(old_name, sessions)
        result = self.aliases.rename(old_name, new_name)
        self.note_action("Rename Alias", "", old_name)
        self.audit.emit(200, f"Alias successfully renamed: {old_name} -> {new_name}")
        return result

    def update_alias_path(self, name, folder):
        sessions = self.active_alias_sessions(name)
        if sessions:
            self.notify_alias_in_use(name, sessions)
            raise AliasInUse(name, sessions)
        result = self.aliases.set_path(name, folder)
        self.note_action("Modify Alias", "", name)
        self.audit.emit(200, f"Alias successfully updated: {name}")
        return result

    def delete_alias(self, name, *, confirmed=False):
        """Auch für direkte Aufrufer ist Bestätigung bei aktiver Benutzung Pflicht."""
        sessions = self.active_alias_sessions(name)
        if sessions and not confirmed:
            self.notify_alias_in_use(name, sessions)
            raise AliasInUse(name, sessions)
        # Erst persistent löschen, danach Clients benachrichtigen. Falls der
        # Schreibvorgang fehlschlägt, bleiben deren Reservierungen bestehen.
        result = self.aliases.delete(name)
        key = name.casefold()
        for sock, state in list(self.clients.items()):
            if key in state.get("aliases", ()):
                state["aliases"].discard(key)
                self._send(sock, {"event": "alias_removed", "alias": name,
                                  "reason": "Alias durch Administrator entfernt"})
        self.note_action("Delete Alias", "", name)
        self.audit.emit(200, f"Alias successfully deleted: {name}")
        self.status_changed.emit()
        return result

    def _accepted(self):
        while self.listener.hasPendingConnections():
            sock = self.listener.nextPendingConnection()
            self._next_session += 1
            self.clients[sock] = {"buffer": bytearray(), "username": None, "logged_at": 0, "login_time": "",
                                  "session_id": f"session-{self._next_session}",
                                  "peer": sock.peerAddress().toString(), "aliases": set(),
                                  "rpc_pending": None, "rpc_status": "idle", "rpc_error_code": None}
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

    def _request_client_window(self, sock, state):
        """Send one CreateWindow command following a successful login.

        A new login clears any old pending command. Responses are strictly
        correlated to both the TCP session and rpcId.
        """
        request = create_window_request(state["session_id"], state["peer"])
        state["rpc_pending"] = request
        state["rpc_status"] = "pending"
        state["rpc_error_code"] = None
        self._send(sock, request)
        self.audit.emit(200, f"RPC CreateWindow sent: {request['client']}")
        self.status_changed.emit()
        QTimer.singleShot(self._rpc_timeout_ms, lambda s=sock, rid=request["rpcId"]: self._rpc_timeout(s, rid))

    def _rpc_timeout(self, sock, rpc_id):
        state = self.clients.get(sock)
        if not state:
            return
        pending = state.get("rpc_pending")
        if not pending or pending["rpcId"] != rpc_id:
            return
        state["rpc_pending"] = None
        state["rpc_status"] = "timeout"
        state["rpc_error_code"] = None
        self.audit.emit(400, f"RPC CreateWindow timeout: {state['session_id']}")
        self.status_changed.emit()

    def _receive_rpc_result(self, state, req):
        pending = state.get("rpc_pending")
        code, details = validate_result(req, pending, state["session_id"])
        state["rpc_pending"] = None
        state["rpc_error_code"] = code
        state["rpc_status"] = "success" if code == 0 else "error"
        message = f"RPC CreateWindow {'OK' if code == 0 else 'failed'}: {state['session_id']} (code={code})"
        if details:
            message += f" ({details})"
        self.audit.emit(200 if code == 0 else 400, message)
        self.status_changed.emit()
        return {"rpc_ack": True, "client": state["session_id"], "lastErrorCode": code}

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
                # First the ordinary login response, THEN an asynchronous RPC.
                # This avoids mixing the original login reply with a GUI request.
                if req.get("action") == "login" and state.get("username"):
                    try:
                        self._request_client_window(sock, state)
                    except Exception:
                        # RPC delivery must NEVER produce a second login reply.
                        self.audit.emit(400, f"RPC CreateWindow dispatch failed: {state['session_id']}")
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
            return {"name": "PythonBDE", "version": "0.4.4", "protocol": "jsonl/1",
                    "server_id": self.server_id}
        if action == "login":
            state.update(username=None, logged_at=0, login_time="", aliases=set())
            name = req.get("username", "")
            password = req.get("password", "")
            if not isinstance(name, str) or not isinstance(password, str) or len(name) > 48 or len(password) > 256:
                raise AuthError("Anmeldung fehlgeschlagen")
            user = self.users.authenticate(name, password)
            if user is None:
                self.audit.emit(400, "Login failed")
                raise AuthError("Anmeldung fehlgeschlagen")
            state.update(username=user["USERNAME"].casefold(), logged_at=time.monotonic(),
                         login_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), aliases=set(),
                         rpc_pending=None, rpc_status="idle", rpc_error_code=None)
            self.status_changed.emit()
            self.audit.emit(200, f"User logged in: {user['USERNAME']}")
            return user
        if action == "logout":
            state.update(username=None, logged_at=0, login_time="", aliases=set(), rpc_pending=None)
            self.status_changed.emit()
            self.audit.emit(200, "User logged out")
            return {"logged_out": True}
        name = state["username"]
        if not name or time.monotonic() - state["logged_at"] > SESSION_TTL:
            state.update(username=None, logged_at=0, login_time="", aliases=set())
            raise AuthError("Nicht angemeldet oder Sitzung abgelaufen")
        current = self.users.get(name)
        if not current or current["LOCKUSER"] or (parse_time(current["EXPIRE"]) and utcnow() > parse_time(current["EXPIRE"])):
            state.update(username=None, logged_at=0, login_time="", aliases=set())
            raise AuthError("Konto gesperrt/abgelaufen")
        if action == "rpc_result":
            return self._receive_rpc_result(state, req)
        if action == "whoami":
            from .auth import public_user
            return public_user(current)
        if action == "list_aliases":
            # Nur Namen, keine absoluten Server-Dateisystempfade ausgeben.
            return [entry["name"] for entry in self.aliases.listing()]
        if action == "select_alias":
            alias = self.aliases.get(req.get("alias"))
            if alias is None:
                raise AliasError("Alias nicht vorhanden")
            state.setdefault("aliases", set()).add(alias["name"].casefold())
            self.status_changed.emit()
            self.audit.emit(200, f"Alias selected: {alias['name']} ({state['username']})")
            return {"alias": alias["name"], "selected": True}
        if action == "release_alias":
            alias_name = req.get("alias")
            if not isinstance(alias_name, str):
                raise AliasError("Ungültiger Aliasname")
            state.setdefault("aliases", set()).discard(alias_name.casefold())
            self.status_changed.emit()
            return {"released": True}
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
