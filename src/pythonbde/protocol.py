"""Qt5 TCP/JSON-Lines Protokoll; Fernzugriff ausschließlich in geschützten Netzen/TLS-Proxy."""
from __future__ import annotations

import json
import platform
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QHostAddress, QTcpServer, QUdpSocket

from .discovery import create_probe, decode, discover_existing, network_interfaces, broadcast_targets, MAGIC
from .settings import DISCOVERY_PORT

from .auth import AuthError, UserManager, parse_time, utcnow
from .aliases import AliasRegistry, AliasError, AliasInUse
from .rpc import RPC_TIMEOUT_SECONDS, create_window_request, validate_result
from .blocking import BlockingRegistry, DuplicateLoginGuard, ReLoginIntervalGuard, resolve_domains
from .windows_secrets import ServerSecrets, make_nonce
from .start_menu import serialized_temporary_menu
from .cpy_modules import ModuleSigner, MODULE_IDS, ID_RE

MAX_LINE = 64 * 1024
MAX_QUEUE = 128 * 1024
SESSION_TTL = 60 * 60


class LoginRejected(AuthError):
    def __init__(self, message, code=403, retry_after=0):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class BDEServer(QObject):
    message = pyqtSignal(str)
    changed = pyqtSignal()
    status_changed = pyqtSignal()
    audit = pyqtSignal(int, str)

    def __init__(self, users: UserManager, parent=None):
        super().__init__(parent)
        self.users = users
        self.aliases = AliasRegistry(users.store.path)
        self.blocking = BlockingRegistry(users.store.path)
        self.login_guard = DuplicateLoginGuard(20)
        self.relogin_guard = ReLoginIntervalGuard(60)
        self.windows_secrets = ServerSecrets(users.store.path) if platform.system() == "Windows" else None
        # DNS-Auflösung niemals im Qt GUI-Thread oder Login-Handler ausführen.
        self._dns_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='PythonBDE-DNS')
        self._dns_future = None
        self._dns_timer = QTimer(self)
        self._dns_timer.setInterval(1000)
        self._dns_timer.timeout.connect(self._poll_domain_dns)
        self._dns_timer.start()
        self._dns_next_refresh = 0.0
        self.refresh_blocked_domains()
        self.listener = QTcpServer(self)
        self.listener.newConnection.connect(self._accepted)
        self.discovery = QUdpSocket(self)
        self.discovery.readyRead.connect(self._answer_discovery)
        self.clients = {}  # socket -> {buffer, username, logged_at, login_time}
        self._module_signer = None  # Initialize lazily for a module request.
        self.server_id = ""
        self.bind_ip = "127.0.0.1"
        self.last_action = None
        self.started_at = ""
        self.instance_id = str(uuid.uuid4())
        self._next_session = 0
        self._rpc_timeout_ms = RPC_TIMEOUT_SECONDS * 1000

    def refresh_blocked_domains(self):
        """Cache im Hintergrund neu auflösen; gilt für eingehende Logins."""
        if self._dns_future is not None and not self._dns_future.done():
            # Eine inzwischen neu hinzugefügte Domain beim nächsten Poll
            # sofort nachladen und nicht 60 Sekunden warten lassen.
            self._dns_refresh_queued = True
            return
        self._dns_refresh_queued = False
        domains = self.blocking.domains()
        if domains:
            self._dns_future = self._dns_executor.submit(resolve_domains, domains)
        else:
            self.blocking.update_domain_ips({})
        self._dns_next_refresh = time.monotonic() + 60

    def _poll_domain_dns(self):
        if self._dns_future is not None and self._dns_future.done():
            try:
                self.blocking.update_domain_ips(self._dns_future.result())
            except Exception as err:
                self.audit.emit(400, f"Domain DNS lookup failed: {type(err).__name__}")
            self._dns_future = None
            if getattr(self, '_dns_refresh_queued', False):
                self.refresh_blocked_domains()
        if time.monotonic() >= self._dns_next_refresh:
            self.refresh_blocked_domains()

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
        self.refresh_blocked_domains()
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
        for sock, state in list(self.clients.items()):
            # Remove state BEFORE closing the socket. The Qt disconnected signal
            # may be synchronous; _gone() must not log the same session twice.
            self.clients.pop(sock, None)
            self._log_connection_closed(state, reason="server stopped")
            sock.disconnectFromHost()
            sock.close()
            sock.deleteLater()
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
                                 "rpc_error_code": state.get("rpc_error_code", None),
                                 "system_mode": state.get("system_mode", "winXP")})
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
        state.update(username=None, logged_at=0, login_time="", aliases=set(),
                     disconnect_reason="kicked by administrator")
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
            self.clients[peer]["disconnect_reason"] = "account banned by administrator"
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
                                  "peer": sock.peerAddress().toString(), "peer_port": sock.peerPort(), "aliases": set(),
                                  "last_username": None, "disconnect_reason": None,
                                  "disconnect_logged": False,
                                  "rpc_pending": None, "rpc_status": "idle", "rpc_error_code": None, "hello_nonce": None,
                                  "system_mode": "winXP", "client_display": None}
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._gone(s))
            self.status_changed.emit()

    def _log_connection_closed(self, state, *, reason=None):
        """Record exactly one disconnect event per TCP session.

        A successful logout clears ``username`` before the TCP FIN arrives.
        ``last_username`` therefore preserves the account name for auditing.
        This method is used by both _gone() and stop().
        """
        if state.get("disconnect_logged", False):
            return
        state["disconnect_logged"] = True
        username = state.get("last_username") or state.get("username") or "unauthenticated"
        session_id = state.get("session_id", "unknown")
        peer = state.get("peer", "unknown")
        cause = reason or state.get("disconnect_reason") or "connection closed"
        self.audit.emit(200, f"Client disconnected: user={username}, "
                             f"client={session_id}, ip={peer}, reason={cause}")

    def _gone(self, sock):
        state = self.clients.pop(sock, None)
        if state is None:
            return  # Already handled by stop(), or a duplicate Qt signal.
        self._log_connection_closed(state)
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
        request = create_window_request(
            state["session_id"], state["peer"],
            system_mode=state.get("system_mode", "winXP"),
            display=state.get("client_display"),
        )
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
                # RPC module packages follow their own ordinary response; only
                # approved, compiled and signed server modules are transferable.
                if req.get('action') == 'load_module':
                    module_request = state.pop('_module_on_request', None)
                    if module_request:
                        try:
                            if self._module_signer is None:
                                self._module_signer = ModuleSigner(self.users.store.path)
                            payload = self._module_signer.event(
                                module_request['moduleId'], state['session_id'], module_request['requestId'])
                            self._send(sock, payload)
                            self.audit.emit(200, f"Signed .cpy module sent: {module_request['moduleId']} to {state['session_id']}")
                        except Exception as exc:
                            self.audit.emit(400, f"Module package failure: {type(exc).__name__}")
                            self._send(sock, {'event': 'module_error', 'requestId': module_request['requestId'],
                                              'moduleId': module_request['moduleId'], 'client': state['session_id'],
                                              'message': 'Server could not sign/compile the module'})
                # First the ordinary login response, THEN an asynchronous RPC.
                # This avoids mixing the original login reply with a GUI request.
                if req.get("action") == "login" and state.pop("_rpc_on_login", True) and state.get("username"):
                    try:
                        self._request_client_window(sock, state)
                        if state.get("system_mode") in ("win95", "winXP"):
                            try:
                                menu_data = serialized_temporary_menu(
                                    state["system_mode"], state["session_id"])
                                self._send(sock, menu_data)
                                self.audit.emit(200, f"Start menu JSON delivered: {state['session_id']}")
                            except (OSError, ValueError) as menu_error:
                                # Never send an unsecured temporary file's content.
                                self.audit.emit(400, "Start menu delivery failed: "
                                                + type(menu_error).__name__)
                    except Exception:
                        # RPC delivery must NEVER produce a second login reply.
                        self.audit.emit(400, f"RPC CreateWindow dispatch failed: {state['session_id']}")
            except (ValueError, TypeError, KeyError, AuthError) as e:
                error_reply = {"ok": False, "error": str(e)}
                if isinstance(e, AuthError) and hasattr(e, "code"):
                    error_reply.update(errorCode=e.code, retryAfterSeconds=e.retry_after)
                self._send(sock, error_reply)
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
        if action == "hello":
            # Nonce exists only on this TCP connection. Each hello invalidates
            # the previous challenge; a successful/failed login consumes it.
            nonce = make_nonce()
            state["hello_nonce"] = nonce
            result = {"platform": platform.system(), "nonce": nonce,
                      "passwordTransport": "plaintext-warning", "version": "0.5.3"}
            if getattr(self, 'windows_secrets', None) is not None:
                result.update(self.windows_secrets.hello_fields())
            return result
        if action == "ping":
            return {"name": "PythonBDE", "version": "0.5.3", "protocol": "jsonl/1",
                    "server_id": self.server_id}
        if action == "login":
            from pythonbde.emulation import validate_client_display
            system_mode, client_display = validate_client_display(
                req.get("systemMode"), req.get("display")
            )
            name = req.get("username", "")
            # Both-Windows clients must use the DPAPI-protected server RSA key;
            # legacy and non-Windows clients remain interoperable after an
            # explicit plaintext warning in the new Qt5 client.
            envelope = req.get("passwordSecret")
            if envelope is not None:
                if getattr(self, 'windows_secrets', None) is None:
                    raise AuthError("Windows Secrets ist auf diesem Server nicht verfügbar")
                nonce = state.pop("hello_nonce", None)
                if not nonce or "password" in req:
                    raise AuthError("Ungültiger Login-Handshake")
                try:
                    password = self.windows_secrets.decrypt_envelope(envelope, nonce)
                except ValueError as exc:
                    raise AuthError("Passwortentschlüsselung fehlgeschlagen") from exc
            else:
                state.pop("hello_nonce", None)
                if getattr(self, 'windows_secrets', None) is not None:
                    # Fail closed for legacy/unidentified clients on a Windows
                    # server. Mixed-OS clients must explicitly opt in after
                    # displaying the plaintext warning in their UI.
                    if (req.get("clientPlatform") != "Linux" or
                            req.get("allowPlaintext") is not True):
                        raise AuthError("Windows-Server: passwordSecret erforderlich; Klartext nur nach Freigabe auf Linux-Clients")
                password = req.get("password", "")
            if not isinstance(name, str) or not isinstance(password, str) or len(name) > 48 or len(password) > 256:
                raise AuthError("Anmeldung fehlgeschlagen")
            # Bereits angemeldete Clients werden bei Fremd-/Zweitlogin nicht
            # ausgeloggt. Ein Identitätswechsel benötigt zuerst logout.
            existing = state.get("username")
            if existing and existing != name.casefold():
                raise LoginRejected("Bitte zuerst abmelden", 409)
            registry = getattr(self, 'blocking', None)
            if registry is not None:
                # Peer-Metadaten kommen vom OS-Socket, nie aus JSON-Feldern.
                try:
                    blocked = registry.blocked(state.get('peer', ''), state.get('peer_port', 0), name)
                except (ValueError, TypeError):
                    blocked = None
                if blocked:
                    self.audit.emit(400, f"Login blocked by {blocked['type']}: client={state.get('peer')}, user={name}")
                    raise LoginRejected('Login abgewiesen: Blocking-Regel aktiv', 403)
            guard = getattr(self, 'login_guard', None)
            # Keine Username-Aufzählung/20s-DOS durch unberechtigte Dritte:
            # Zweitlogin-Sperre erst nach erfolgreich geprüftem Passwort setzen.
            user = self.users.authenticate(name, password)
            if user is None:
                self.audit.emit(400, "Login failed")
                raise AuthError("Anmeldung fehlgeschlagen")
            if existing:
                # Re-Authentifizierung derselben TCP-Verbindung ist zulässig.
                # Die Verbindung wird bei konkurrierenden Logins nie gekickt.
                state.update(system_mode=system_mode, client_display=client_display,
                             _rpc_on_login=True)
                return {**user, "systemMode": system_mode, "display": client_display}
            if guard is not None:
                conflict, seconds = guard.check(name, state, self.clients.values(), SESSION_TTL)
                if conflict:
                    reason = ('Benutzer bereits angemeldet' if conflict == 'duplicate' else
                              'Temporäre Loginsperre')
                    self.audit.emit(400, f"Duplicate login rejected: user={name}, reason={conflict}, wait={seconds}s")
                    raise LoginRejected(f'{reason}; mindestens {seconds} Sekunden gesperrt (und bis die bestehende Sitzung endet)', 409, seconds)
            # This is a per-account interval from the previous successful login.
            # Do NOT apply it to re-authentication over the SAME authenticated
            # TCP socket, and do NOT update it after failed attempts.
            relogin = getattr(self, 'relogin_guard', None)
            if relogin is not None:
                seconds = relogin.remaining(user["USERNAME"])
                if seconds:
                    self.audit.emit(400, f"Relogin rejected: user={name}, wait={seconds}s")
                    raise LoginRejected(f'Erneute Anmeldung erst in {seconds} Sekunden möglich', 429, seconds)
            state.update(username=user["USERNAME"].casefold(), last_username=user["USERNAME"],
                         disconnect_reason=None, logged_at=time.monotonic(),
                         login_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), aliases=set(),
                         rpc_pending=None, rpc_status="idle", rpc_error_code=None,
                         system_mode=system_mode, client_display=client_display,
                         _rpc_on_login=True)
            self.status_changed.emit()
            if relogin is not None:
                relogin.record_success(user["USERNAME"])
            self.audit.emit(200, f"User logged in: {user['USERNAME']} (mode={system_mode})")
            return {**user, "systemMode": system_mode, "display": client_display}
        if action == 'load_module':
            # Client-provided module IDs are never converted into file paths.
            # Signed bytecode is available only after an authenticated GUI login.
            if not state.get('username'):
                raise AuthError('Module request requires login')
            if state.get('system_mode') not in ('win95', 'winXP'):
                raise ValueError('Modules require a graphical desktop')
            module_id = req.get('moduleId')
            request_id = req.get('requestId')
            if (module_id not in MODULE_IDS or not isinstance(request_id, str) or
                    not ID_RE.fullmatch(request_id)):
                raise ValueError('Unknown module or invalid request ID')
            state['_module_on_request'] = {'moduleId': module_id, 'requestId': request_id}
            return {'moduleQueued': True, 'moduleId': module_id, 'requestId': request_id}
        if action == "logout":
            username = state.get("username")
            state.update(username=None, logged_at=0, login_time="", aliases=set(),
                         rpc_pending=None, disconnect_reason="logout")
            self.status_changed.emit()
            if username:
                self.audit.emit(200, f"User logged out: {username} ({state['session_id']})")
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
