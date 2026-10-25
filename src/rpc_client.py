"""PythonBDE RPC Testclient mit eigener Qt5-GUI (Windows und Linux).

Start this process on the client machine. It logs into the server and then
handles server->client CreateWindow requests; no remote process execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QTcpSocket
from PyQt5.QtWidgets import (
    QApplication, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from pythonbde.rpc import (ERR_CREATE_WINDOW, ERR_UNKNOWN_FUNCTION,
                           ERR_WINDOW_NOT_VISIBLE, result_message)

MAX_LINE = 64 * 1024
MAX_BUFFER = 128 * 1024


class CreatedWindow(QWidget):
    """A REAL window created in response to the RPC request."""
    closed = pyqtSignal()
    def __init__(self, client_id: str, server_name: str):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("PythonBDE – RPC CreateWindow")
        self.resize(440, 190)
        box = QVBoxLayout(self)
        greeting = QLabel("CreateWindow vom PythonBDE-Server erfolgreich ausgeführt.")
        greeting.setWordWrap(True)
        box.addWidget(greeting)
        info = QLabel(f"Client-ID: {client_id}\nServer: {server_name}")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(info)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        box.addWidget(self.close_button)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class RpcTestClient(QMainWindow):
    def __init__(self, host: str, port: int):
        super().__init__()
        self.setWindowTitle("PythonBDE – JSON RPC Client")
        self.resize(680, 410)
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(self._connected)
        self.sock.readyRead.connect(self._read)
        self.sock.disconnected.connect(self._disconnected)
        self.sock.errorOccurred.connect(self._socket_error)
        self._buffer = bytearray()
        self._pending = deque()
        self._logged_in = False
        self._rpc_windows = {}  # RPC request IDs -> created top-level widgets
        self._server_name = f"{host}:{port}"
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        form = QFormLayout()
        self.host = QLineEdit(host)
        self.port = QLineEdit(str(port))
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Server IP/Host", self.host)
        form.addRow("TCP Port", self.port)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.login_button = QPushButton("Connect / Login")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        self.login_button.clicked.connect(self.connect_login)
        self.disconnect_button.clicked.connect(self.disconnect_client)
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.disconnect_button)
        layout.addLayout(buttons)
        self.status = QLabel("Disconnected – Login to receive CreateWindow")
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def _log(self, message: str):
        self.log.appendPlainText(message)

    def connect_login(self):
        if self.sock.state() != QAbstractSocket.UnconnectedState:
            return
        try:
            port = int(self.port.text())
            if not 1 <= port <= 65535:
                raise ValueError("Ungültiger Port")
        except ValueError as exc:
            QMessageBox.warning(self, "Port", str(exc))
            return
        if not self.username.text() or not self.password.text():
            QMessageBox.warning(self, "Login", "Benutzername und Passwort eingeben")
            return
        self._server_name = f"{self.host.text().strip()}:{port}"
        self._pending.clear()
        self._buffer.clear()
        self._logged_in = False
        self.login_button.setEnabled(False)
        self.status.setText("Connecting ...")
        self.sock.connectToHost(self.host.text().strip(), port)

    def _connected(self):
        self._log("TCP connected; sending login")
        password = self.password.text()
        self._send("login", username=self.username.text(), password=password)
        self.password.clear()
        self.disconnect_button.setEnabled(True)

    def _send(self, action: str, **values):
        if self.sock.state() != QAbstractSocket.ConnectedState:
            return False
        payload = json.dumps({"action": action, **values}, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8") + b"\n"
        self._pending.append(action)
        self.sock.write(payload)
        return True

    def _read(self):
        self._buffer.extend(bytes(self.sock.readAll()))
        if len(self._buffer) > MAX_BUFFER:
            self._log("Incoming data exceeded maximum; disconnecting")
            self.disconnect_client()
            return
        while b"\n" in self._buffer:
            pos = self._buffer.index(10)
            line = bytes(self._buffer[:pos])
            del self._buffer[:pos + 1]
            if len(line) > MAX_LINE:
                self._log("RPC message too large")
                self.disconnect_client()
                return
            try:
                packet = json.loads(line.decode("utf-8"))
                if not isinstance(packet, dict):
                    raise ValueError("JSON object expected")
            except (UnicodeError, ValueError) as exc:
                self._log(f"Invalid server JSON: {exc}")
                self.disconnect_client()
                return
            if packet.get("event") == "rpc_request":
                self._handle_rpc(packet)
            elif "event" in packet:
                self._handle_event(packet)
            else:
                self._handle_reply(packet)

    def _handle_reply(self, packet):
        action = self._pending.popleft() if self._pending else "unexpected"
        if action == "login":
            self._logged_in = bool(packet.get("ok"))
            if self._logged_in:
                self.status.setText("Logged in – waiting for RPC requests")
                self._log(f"Login successful: {self.username.text()}")
            else:
                self.status.setText("Login failed")
                self._log("Login rejected: " + str(packet.get("error", "unknown")))
                self.disconnect_client()
        elif action == "rpc_result":
            accepted = bool(packet.get("ok") and packet.get("data", {}).get("rpc_ack"))
            self._log("RPC confirmation accepted" if accepted else
                      "RPC confirmation rejected: " + str(packet.get("error", "unknown")))
        elif action != "unexpected":
            self._log(f"Reply {action}: {packet.get('ok')}")
        else:
            self._log("Unexpected server response")

    def _handle_event(self, packet):
        event = packet["event"]
        if event == "server_message":
            self._log("SERVER MESSAGE: " + str(packet.get("text", "")))
        elif event == "kicked":
            self._log("Kicked: " + str(packet.get("reason", "")))
            self.disconnect_client()
        else:
            self._log(f"Server event: {event}")

    def _handle_rpc(self, packet):
        if not self._logged_in:
            self._log("Ignoring RPC before successful login")
            return
        if not isinstance(packet.get("client"), str) or not isinstance(packet.get("rpcId"), str):
            self._log("Invalid RPC: missing client or rpcId")
            return
        if packet.get("setFunc") != "CreateWindow":
            self._send("rpc_result", **{k:v for k,v in
                       result_message(packet, ERR_UNKNOWN_FUNCTION, "Unknown RPC function").items()
                       if k != "action"})
            return
        # DO NOT execute arbitrary code/command lines received from the server.
        try:
            if packet["rpcId"] in self._rpc_windows:
                raise RuntimeError("RPC already processed")
            window = CreatedWindow(packet["client"], self._server_name)
            self._rpc_windows[packet["rpcId"]] = window
            window.closed.connect(lambda rid=packet["rpcId"]:
                                  self._rpc_windows.pop(rid, None))
            window.show()
            self._log(f"CreateWindow received for {packet['client']}")
        except Exception as exc:
            self._ack_rpc(packet, ERR_CREATE_WINDOW, str(exc))
            return
        # Verify after Qt has processed Show events; don't claim success if hidden.
        QTimer.singleShot(0, lambda p=packet, w=window: self._ack_created_window(p, w))

    def _ack_created_window(self, packet, window):
        if window.isVisible():
            self._ack_rpc(packet, 0)
            self._log("CreateWindow successful; lastErrorCode=0")
        else:
            self._ack_rpc(packet, ERR_WINDOW_NOT_VISIBLE, "Window not visible")

    def _ack_rpc(self, packet, code, error=""):
        result = result_message(packet, code, error)
        self._send(result.pop("action"), **result)

    def _socket_error(self, error):
        self._log("TCP error: " + self.sock.errorString())
        self.status.setText("Connection error")

    def _disconnected(self):
        self._logged_in = False
        self._pending.clear()
        self._buffer.clear()
        self.login_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.status.setText("Disconnected")
        self._log("TCP disconnected")

    def disconnect_client(self):
        if self.sock.state() == QAbstractSocket.ConnectedState:
            if self._logged_in:
                self._send("logout")
            self.sock.disconnectFromHost()
        elif self.sock.state() != QAbstractSocket.UnconnectedState:
            self.sock.abort()
        self.login_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)

    def closeEvent(self, event):
        self.sock.abort()
        for window in list(self._rpc_windows.values()):
            window.close()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description="PythonBDE JSON RPC Qt5 client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=43650)
    options = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = RpcTestClient(options.host, options.port)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
