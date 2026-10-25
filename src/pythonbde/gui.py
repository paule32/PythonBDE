"""PyQt5 Administrations-GUI für PythonBDE."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtCore import QDateTime, Qt, QTimer, QSize
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QDockWidget, QTreeWidget, QTreeWidgetItem, QSplitter,
    QScrollArea, QComboBox, QDialogButtonBox, QTextEdit, QAction, QFrame,
    QPlainTextEdit, QFileDialog, QMenu, QStyle, QSizePolicy, QToolBar
)
from .auth import AuthError, RIGHTS, UserManager, parse_time, timestamp
from .protocol import BDEServer
from .settings import Settings, load_settings, save_settings, DISCOVERY_PORT
from .discovery import discover_existing, network_interfaces, broadcast_targets
from PyQt5.QtNetwork import QHostAddress, QTcpServer, QUdpSocket
from .platform_support import operating_system, password_backend
from .user_visuals import account_border
from .eventlog import EventLog
from .aliases import AliasError, AliasInUse
from .theme import apply_application_theme, theme_icon


class CredentialDialog(QDialog):
    def __init__(self, parent=None, bootstrap=False):
        super().__init__(parent)
        self.setWindowTitle("Ersten Administrator anlegen" if bootstrap else "Administrator-Anmeldung")
        layout = QFormLayout(self)
        self.username = QLineEdit("admin" if bootstrap else "")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        layout.addRow("Benutzername", self.username)
        layout.addRow("Passwort", self.password)
        self.confirm = None
        if bootstrap:
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.Password)
            layout.addRow("Passwort wiederholen", self.confirm)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def _accept(self):
        if self.confirm and self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "Passwort", "Passwörter stimmen nicht überein")
            return
        self.accept()



class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, server: BDEServer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Server Settings")
        self.settings = settings
        self.server = server
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.adapters = network_interfaces()
        self.nic = QComboBox()
        self.nic.addItem("Alle Adapter / Alle IPv4-Adressen", ("", "0.0.0.0"))
        for adapter in self.adapters:
            self.nic.addItem(f"{adapter['name']} — {adapter['ip']}",
                             (adapter["key"], adapter["ip"]))
        self.ip = QLineEdit(settings.ip)
        self.ip.setPlaceholderText("127.0.0.1 oder 0.0.0.0")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(settings.port)
        self.port.setToolTip("Standard-Port 43650")
        form.addRow("Network Interface (NIC)", self.nic)
        form.addRow("Listen IP", self.ip)
        form.addRow("TCP Port", self.port)
        self.nic.currentIndexChanged.connect(self._nic_changed)
        for i in range(self.nic.count()):
            if self.nic.itemData(i) == (settings.nic, settings.ip):
                self.nic.setCurrentIndex(i)
                break
        layout.addLayout(form)
        layout.addWidget(QLabel(f"Server-ID (dauerhaft): {settings.server_id}"))
        notice = QLabel("Hinweis: Externe TCP-Verbindungen übertragen Passwörter derzeit im Klartext. "
                        "Für Netzzugriffe TLS-Proxy/VPN verwenden.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Save Config")
        self.test_btn = QPushButton("Test-Config")
        self.cancel_btn = QPushButton("Cancel")
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.test_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)
        self.save_btn.clicked.connect(self._save)
        self.test_btn.clicked.connect(self._test)
        self.cancel_btn.clicked.connect(self.reject)

    def _nic_changed(self, index):
        if index >= 0:
            self.ip.setText(self.nic.itemData(index)[1])

    def values(self):
        selected = self.nic.currentData()
        return replace(self.settings, ip=self.ip.text().strip(), port=self.port.value(),
                       nic=selected[0] if selected and selected[1] == self.ip.text().strip() else "").validate()

    def _save(self):
        try:
            settings = self.values()
            save_settings(settings)
        except (OSError, ValueError) as err:
            QMessageBox.warning(self, "Save Config", str(err))
            return
        self.settings = settings
        self.accept()

    def _test(self):
        try:
            cfg = self.values()
            if self.server.listener.isListening() and (
                self.server.bind_ip == cfg.ip and self.server.listener.serverPort() == cfg.port
            ):
                QMessageBox.information(self, "Test-Config", "OK: Server lauscht bereits an dieser IP und diesem Port.")
                return
            addresses = {"127.0.0.1", "0.0.0.0"} | {a["ip"] for a in self.adapters}
            if cfg.ip not in addresses:
                raise ValueError("Die IP ist keiner lokalen Netzwerkkarte zugeordnet")
            found = discover_existing(cfg.server_id, broadcast_targets(self.adapters),
                                      own_instance=self.server.instance_id if self.server.listener.isListening() else "")
            if found:
                raise OSError("Nur ein PythonBDE-Server pro Netzwerk erlaubt: "
                              f"{found['address']}:{found['port']} (ID {found['id']})")
            temporary = QTcpServer(self)
            try:
                if not temporary.listen(QHostAddress(cfg.ip), cfg.port):
                    raise OSError("IP and/or Port already in use: " + temporary.errorString())
            finally:
                temporary.close()
            if not self.server.listener.isListening():
                udp = QUdpSocket(self)
                try:
                    if not udp.bind(QHostAddress.AnyIPv4, DISCOVERY_PORT, QUdpSocket.DontShareAddress):
                        raise OSError("Discovery-Port in Benutzung: " + udp.errorString())
                finally:
                    udp.close()
            QMessageBox.information(self, "Test-Config", "OK: Bind-Test erfolgreich. Server kann lokal starten. "
                                    "Netzwerk-Discovery ist best-effort.")
        except (OSError, ValueError) as err:
            QMessageBox.warning(self, "Test-Config fehlgeschlagen", str(err))


class UserEditor(QWidget):
    """Alle Eigenschaften werden direkt rechts im Manager-Dock bearbeitet."""
    def __init__(self, on_save, parent=None):
        super().__init__(parent)
        self.on_save = on_save
        self.user = None
        self.is_new = False
        outer = QVBoxLayout(self)
        self.heading = QLabel("Wähle links einen Benutzer oder Administrator aus.")
        outer.addWidget(self.heading)
        basic = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Leer lassen = unverändert")
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        basic.addRow("Username", self.username)
        basic.addRow("Password", self.password)
        basic.addRow("Confirm Password", self.confirm)
        outer.addLayout(basic)
        rights_group = QGroupBox("User Permissions")
        grid = QGridLayout(rights_group)
        self.rights = {}
        for i, right in enumerate(RIGHTS):
            cb = QCheckBox(right.title() if right != "ANSICHT" else "Ansicht")
            self.rights[right] = cb
            grid.addWidget(cb, i // 3, i % 3)
        outer.addWidget(rights_group)
        options = QGroupBox("Password Options")
        form = QFormLayout(options)
        self.lock_user = QCheckBox("Lock User")
        self.count_pass = QSpinBox()
        self.count_pass.setRange(0, 99999)
        self.count_pass.setToolTip("0 = Unbegrenzt falsche Passwortversuche")
        self.count_limit = QSpinBox()
        self.count_limit.setRange(0, 99999)
        self.count_limit.setSuffix(" Minuten")
        self.count_limit.setToolTip("0 = Keine automatische Wartezeit")
        self.expire = QCheckBox("Expire")
        self.expire_dt = QDateTimeEdit()
        self.expire_dt.setCalendarPopup(True)
        self.expire_dt.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.expire.toggled.connect(self.expire_dt.setEnabled)
        form.addRow(self.lock_user)
        form.addRow("Count Pass", self.count_pass)
        form.addRow("Count Pass Limit", self.count_limit)
        form.addRow(self.expire, self.expire_dt)
        outer.addWidget(options)
        readonly = QGroupBox("Record Status (Read Only)")
        status_form = QFormLayout(readonly)
        self.readonly = {}
        for field in ("FAILS", "LOCKUNTIL", "CREATED", "UPDATED"):
            label = QLineEdit()
            label.setReadOnly(True)
            self.readonly[field] = label
            status_form.addRow(field, label)
        outer.addWidget(readonly)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save User")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.set_user(None)

    def set_user(self, user, *, is_new=False):
        self.user = user
        self.is_new = is_new
        self.setEnabled(bool(user) or is_new)
        self.heading.setText("New User" if is_new else ("User: " + user["USERNAME"] if user else
                                               "Wähle links einen Benutzer oder Administrator aus."))
        self.username.setText(user["USERNAME"] if user else "")
        self.username.setReadOnly(not is_new)
        self.password.clear()
        self.confirm.clear()
        self.password.setPlaceholderText("Mindestens 8 Zeichen" if is_new else "Leer lassen = unverändert")
        for right, cb in self.rights.items():
            cb.setChecked(bool(user and user.get(right)))
        self.lock_user.setChecked(bool(user and user.get("LOCKUSER")))
        self.count_pass.setValue(user["COUNTPASS"] if user else 5)
        self.count_limit.setValue(user["COUNTLIM"] if user else 15)
        self.expire.setChecked(bool(user and user.get("EXPIRE")))
        self.expire_dt.setDateTime(QDateTime.currentDateTime().addYears(1))
        if user and user.get("EXPIRE") and parse_time(user["EXPIRE"]):
            value = QDateTime.fromString(user["EXPIRE"], Qt.ISODate)
            if value.isValid():
                self.expire_dt.setDateTime(value.toLocalTime())
        self.expire_dt.setEnabled(self.expire.isChecked())
        for field, label in self.readonly.items():
            label.setText(str(user.get(field, "")) if user else "")

    def _save(self):
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "Password", "Passwörter stimmen nicht überein")
            return
        if self.is_new and not self.password.text():
            QMessageBox.warning(self, "Password", "Neuer Benutzer benötigt ein Passwort")
            return
        expires = ""
        if self.expire.isChecked():
            selected = self.expire_dt.dateTime().toPyDateTime()
            if selected.tzinfo is None:
                selected = selected.astimezone()
            expires = timestamp(selected)
        payload = {"username": self.username.text().strip(), "password": self.password.text() or None,
                   "rights": {key: box.isChecked() for key, box in self.rights.items()},
                   "lock_user": self.lock_user.isChecked(), "count_pass": self.count_pass.value(),
                   "count_limit": self.count_limit.value(), "expire": expires}
        self.on_save(payload, self.is_new)


class LogStatusPanel(QWidget):
    """GUI-Log oben; Live-Sitzungen/Status unten – jeweils resizebar."""
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.server = window.server
        root = QVBoxLayout(self)
        root.setContentsMargins(3, 3, 3, 3)
        self.main_splitter = QSplitter(Qt.Vertical)
        log_box = QWidget()
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(3, 3, 3, 3)
        log_layout.addWidget(QLabel("Server Logging (neueste Meldungen zuerst, max. 500 Zeilen)"))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        log_layout.addWidget(self.log_text)
        buttons = QHBoxLayout()
        save_button = QPushButton("Save As ...")
        clear_button = QPushButton("Clear Text")
        save_button.clicked.connect(self.save_as)
        clear_button.clicked.connect(self.clear_text)
        buttons.addWidget(save_button)
        buttons.addWidget(clear_button)
        buttons.addStretch()
        log_layout.addLayout(buttons)
        self.main_splitter.addWidget(log_box)

        status_box = QWidget()
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(3, 3, 3, 3)
        status_layout.addWidget(QLabel("Server Status / Active Sessions"))
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_layout.addWidget(self.info)
        self.sessions = QTreeWidget()
        self.sessions.setHeaderLabels(["Logged-in User", "Login Time (UTC)"])
        self.sessions.setColumnWidth(0, 210)
        self.sessions.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sessions.customContextMenuRequested.connect(self.session_menu)
        status_layout.addWidget(self.sessions)
        controls = QHBoxLayout()
        for label, method in (("Send Message To All", self.send_all),
                              ("Kick All with Message", self.kick_all_message)):
            button = QPushButton(label)
            button.clicked.connect(method)
            controls.addWidget(button)
        # Start/Stop gehören direkt in das Status-Panel. Die Buttons werden
        # erst nach erfolgreichem Listen() umgeschaltet; ein Fehlstart lässt
        # Start aktiv, sodass der Benutzer die Konfiguration korrigieren kann.
        self.start_button = QPushButton("Start Server")
        self.stop_button = QPushButton("Stop Server")
        self.start_button.clicked.connect(self.window.start_server)
        self.stop_button.clicked.connect(self.window.stop_server)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        status_layout.addLayout(controls)
        self.main_splitter.addWidget(status_box)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes([290, 220])
        root.addWidget(self.main_splitter)
        self.window.log.callbacks.append(self.append_log)
        self._render_log()
        self.server.status_changed.connect(self.refresh)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def _render_log(self):
        self.log_text.setPlainText("\n".join(self.window.log.entries))
        self.log_text.verticalScrollBar().setValue(0)

    def append_log(self, line):
        # EventLog verwaltet Kapazität und Rücksetzen; Editor wird synchronisiert.
        self._render_log()

    def save_as(self):
        destination, _ = QFileDialog.getSaveFileName(self, "Save Log As", "python_bde_export.log",
                                                      "Log-Dateien (*.log *.txt);;Alle Dateien (*)")
        if destination:
            try:
                Path(destination).write_text(self.log_text.toPlainText() + "\n", encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Save As", str(exc))

    def clear_text(self):
        self.window.log.clear_view()
        for panel in self.window.log_panels:
            panel._render_log()

    def refresh(self):
        status = self.server.status_snapshot()
        self.set_running(status["running"])
        action = status["last_action"]

        last = (f"{action['operation']} / {action['username']} / {action['table']} ({action['time']})"
                if action else "-")
        self.info.setText(f"Server: {'Running' if status['running'] else 'Stopped'} | "
                          f"ID: {status['id']} | {status['ip']}:{status['port']} | "
                          f"Connected: {status['connected_clients']} | Logged-in: {status['login_count']}\n"
                          f"Started (UTC): {status['started_at'] or '-'} | Last Action: {last}")
        selected_id = self.selected_session_id()
        self.sessions.blockSignals(True)
        self.sessions.clear()
        selected = None
        for session in status["sessions"]:
            node = QTreeWidgetItem(self.sessions, [session["username"], session["login_time"]])
            node.setData(0, Qt.UserRole, session["session_id"])
            node.setToolTip(0, session.get("peer", ""))
            if session["session_id"] == selected_id:
                selected = node
        if selected is not None:
            self.sessions.setCurrentItem(selected)
        self.sessions.blockSignals(False)

    def set_running(self, running):
        """Status der Start-/Stop-Schalter an den realen Listener koppeln."""
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(bool(running))

    def selected_session_id(self):
        item = self.sessions.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def _session(self):
        session_id = self.selected_session_id()
        return next((s for s in self.server.status_snapshot()["sessions"]
                     if s["session_id"] == session_id), None)

    def _prompt_message(self, title):
        text, ok = QInputDialog.getMultiLineText(self, title, "Message", "")
        if not ok or not text.strip():
            return None
        return text.strip()

    def _perform(self, operation, action):
        try:
            action()
        except (ValueError, AuthError, OSError) as exc:
            self.window.record(400, f"{operation} failed: {exc}")
            QMessageBox.warning(self, operation, str(exc))
        self.refresh()

    def session_menu(self, position):
        node = self.sessions.itemAt(position)
        if node is not None:
            self.sessions.setCurrentItem(node)
        session_id = self.selected_session_id() if node is not None else None
        menu = QMenu(self)
        send = menu.addAction("Send Message")
        kick = menu.addAction("Kick")
        ban = menu.addAction("Bann")
        status = menu.addAction("Status")
        menu.addSeparator()
        send_all = menu.addAction("Send Message To All")
        kick_all = menu.addAction("Kick All")
        for action in (send, kick, ban, status):
            action.setEnabled(bool(session_id))
        chosen = menu.exec_(self.sessions.viewport().mapToGlobal(position))
        if chosen == send:
            self.send_selected(session_id)
        elif chosen == kick:
            self.kick_selected(session_id)
        elif chosen == ban:
            self.ban_selected(session_id)
        elif chosen == status:
            self.show_session_status(session_id)
        elif chosen == send_all:
            self.send_all()
        elif chosen == kick_all:
            self.kick_all()

    def send_selected(self, session_id):
        message = self._prompt_message("Send Message")
        if message:
            self._perform("Send Message", lambda: self.server.send_message(message, session_id))

    def kick_selected(self, session_id):
        session = self._session()
        if session and QMessageBox.question(self, "Kick", f"Sitzung von {session['username']} beenden?") == QMessageBox.Yes:
            self._perform("Kick", lambda: self.server.kick(session_id))

    def ban_selected(self, session_id):
        session = self._session()
        if session and QMessageBox.question(self, "Bann", f"'{session['username']}' dauerhaft sperren und kicken?") == QMessageBox.Yes:
            self._perform("Bann", lambda: self.server.ban(session_id))

    def show_session_status(self, session_id):
        session = self._session()
        if session is not None:
            QMessageBox.information(self, "Client Status", "\n".join(
                f"{key}: {value}" for key, value in session.items()))

    def send_all(self):
        message = self._prompt_message("Send Message To All")
        if message:
            self._perform("Send Message To All", lambda: self.server.send_message(message))

    def kick_all(self):
        if QMessageBox.question(self, "Kick All", "Alle angemeldeten Benutzer abmelden?") == QMessageBox.Yes:
            self._perform("Kick All", self.server.kick_all)

    def kick_all_message(self):
        message = self._prompt_message("Kick All with Message")
        if message:
            if QMessageBox.question(self, "Kick All", "Nachricht senden und alle Sitzungen beenden?") == QMessageBox.Yes:
                self._perform("Kick All", lambda: self.server.kick_all(message))


class UserManagerDock(QDockWidget):
    def __init__(self, window):
        super().__init__("Users / Admins", window)
        self.window = window
        self.setObjectName("PythonBDEUserManager")
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        actions = QHBoxLayout()
        for text, callback in (("New User", self.new_user), ("Delete Account", self.delete_user),
                               ("Unlock", self.unlock_user), ("Refresh", self.refresh)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        splitter = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Users / Admins")
        self.tree.setMinimumWidth(180)
        self.tree.currentItemChanged.connect(self._selection_changed)
        splitter.addWidget(self.tree)
        # Der 3-Pixel-Rahmen umschließt das gesamte rechte Panel. Er gehört
        # ausdrücklich NICHT zum QScrollArea-Inhalt (sonst scrollt er mit).
        self.details_frame = QFrame()
        self.details_frame.setObjectName("PythonBDEAccountDetailsFrame")
        self.details_frame.setFrameShape(QFrame.NoFrame)
        details_layout = QVBoxLayout(self.details_frame)
        details_layout.setContentsMargins(5, 5, 5, 5)
        details_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        self.editor = UserEditor(self.save_user)
        scroll.setWidget(self.editor)
        details_layout.addWidget(scroll)
        splitter.addWidget(self.details_frame)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([250, 650])
        # Vertikaler Splitter: oben Konten, unten Logging + Live-Status.
        vertical = QSplitter(Qt.Vertical)
        vertical.addWidget(splitter)
        self.log_status = LogStatusPanel(window)
        window.log_panels.append(self.log_status)
        vertical.addWidget(self.log_status)
        vertical.setSizes([370, 300])
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 2)
        layout.addWidget(vertical)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)

        # Auch noch nicht gespeicherte Änderungen an Admin/Lock User sind
        # sofort am Rahmen sichtbar. Erst Save User schreibt sie in die DBF.
        self.editor.rights["ADMIN"].toggled.connect(self.update_account_border)
        self.editor.lock_user.toggled.connect(self.update_account_border)
        # Eine automatische Sperre kann unabhängig von der GUI durch falsche
        # Anmeldungen entstehen bzw. nach Ablauf von selbst verschwinden.
        self.border_timer = QTimer(self)
        self.border_timer.setInterval(1000)
        self.border_timer.timeout.connect(self.update_account_border)
        self.border_timer.start()
        self.refresh()

    def update_account_border(self, *_):
        """Rot=Admin, Grün=User, Gelb=gesperrt; Sperre hat Vorrang."""
        if self.editor.is_new:
            account = {"ADMIN": self.editor.rights["ADMIN"].isChecked(),
                       "LOCKUSER": self.editor.lock_user.isChecked(), "LOCKUNTIL": ""}
        elif self.editor.user is not None:
            name = self.editor.user["USERNAME"]
            # Aktuellen DBF-Status lesen: automatische Login-Sperren werden
            # auch ohne ein explizites 'Refresh' sichtbar.
            stored = self.window.users.get(name)
            if stored is None:
                account = None
            else:
                account = dict(stored)
                account["ADMIN"] = self.editor.rights["ADMIN"].isChecked()
                account["LOCKUSER"] = self.editor.lock_user.isChecked()
        else:
            account = None
        color, status = account_border(account)
        if getattr(self, "_last_account_border", None) == (color, status):
            return
        self._last_account_border = (color, status)
        self.details_frame.setStyleSheet(
            "QFrame#PythonBDEAccountDetailsFrame {"
            f" border: 3px solid {color};"
            " border-radius: 0px;"
            "}"
        )
        self.details_frame.setToolTip(status)

    def refresh(self, choose=None):
        if choose is None:
            choose = self.selected_name()
        self.tree.blockSignals(True)
        self.tree.clear()
        users_node = QTreeWidgetItem(self.tree, ["Users"])
        admins_node = QTreeWidgetItem(self.tree, ["Admins"])
        selected = None
        for user in self.window.users.listing():
            node = QTreeWidgetItem(admins_node if user["ADMIN"] else users_node, [user["USERNAME"]])
            node.setData(0, Qt.UserRole, user["USERNAME"])
            if choose and user["USERNAME"].casefold() == choose.casefold():
                selected = node
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if selected:
            self.tree.setCurrentItem(selected)
        else:
            self.tree.setCurrentItem(None)
            self.editor.set_user(None)
            self.update_account_border()

    def selected_name(self):
        node = self.tree.currentItem()
        return node.data(0, Qt.UserRole) if node is not None else None

    def _selection_changed(self, current, previous):
        name = current.data(0, Qt.UserRole) if current else None
        self.editor.set_user(self.window.users.get(name) if name else None)
        self.update_account_border()

    def _tree_menu(self, position):
        item = self.tree.itemAt(position)
        if item is not None:
            self.tree.setCurrentItem(item)
        menu = QMenu(self)
        new_user = menu.addAction("New User")
        new_admin = menu.addAction("New Admin")
        menu.addSeparator()
        delete = menu.addAction("Delete Account")
        delete.setEnabled(bool(self.selected_name()))
        selected = menu.exec_(self.tree.viewport().mapToGlobal(position))
        if selected == new_user:
            self.new_user()
        elif selected == new_admin:
            self.new_admin()
        elif selected == delete:
            self.delete_user()

    def new_admin(self):
        self.new_user()
        self.editor.rights["ADMIN"].setChecked(True)
        self.editor.heading.setText("New Admin")
        self.update_account_border()

    def new_user(self):
        self.tree.setCurrentItem(None)
        self.editor.set_user(None, is_new=True)
        self.update_account_border()
        self.editor.username.setFocus()

    def save_user(self, data, is_new):
        name = data.pop("username")
        try:
            if is_new:
                self.window.users.create(name, data.pop("password"), data.pop("rights"), **data)
                operation = "Insert Record"
                description = "User successfully created"
            else:
                self.window.users.edit(name, **data)
                self.window.server.revoke_sessions(name)
                operation = "Modify Record"
                description = "User successfully modified"
            self.window.record(200, f"{description}: {name}")
            self.window.server.note_action(operation, name, "users.dbf")
            self.refresh(choose=name)
            self.window.update_status()
        except (AuthError, ValueError, OSError) as err:
            verb = "created" if is_new else "modified"
            self.window.record(400, f"User can not be {verb}: {name} ({err})")
            QMessageBox.warning(self, "User Management", str(err))

    def delete_user(self):
        name = self.selected_name()
        if not name:
            return
        if name.casefold() == self.window.admin_username.casefold():
            self.window.record(400, f"User can not be deleted: active administrator {name}")
            QMessageBox.warning(self, "Delete Account", "Das eigene Administratorkonto darf nicht gelöscht werden.")
            return
        if QMessageBox.question(self, "Delete User", f"Benutzer '{name}' wirklich löschen?") != QMessageBox.Yes:
            return
        try:
            self.window.users.delete(name)
            self.window.record(200, f"User successfully deleted: {name}")
            self.window.server.revoke_sessions(name)
            self.window.server.note_action("Delete Record", name, "users.dbf")
            self.refresh()
        except (AuthError, ValueError, OSError) as err:
            self.window.record(400, f"User can not be deleted: {name} ({err})")
            QMessageBox.warning(self, "User Management", str(err))

    def unlock_user(self):
        name = self.selected_name()
        if not name:
            return
        try:
            self.window.users.unlock(name)
            self.window.server.revoke_sessions(name)
            self.window.server.note_action("Update Record", name, "users.dbf")
            self.refresh(choose=name)
        except (AuthError, ValueError, OSError) as err:
            QMessageBox.warning(self, "User Management", str(err))


class AliasesDock(QDockWidget):
    """Alias-Katalog links, Verzeichnis-/Eigenschaften rechts und Live-Log unten."""
    def __init__(self, window):
        super().__init__("Aliases", window)
        self.setObjectName("PythonBDEAliasesDock")
        self.window = window
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        base = QWidget()
        self.setWidget(base)
        outer = QVBoxLayout(base)
        outer.setContentsMargins(4, 4, 4, 4)
        self.vertical = QSplitter(Qt.Vertical)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(3, 3, 3, 3)

        toolbar = QHBoxLayout()
        self.new_button = QPushButton("New")
        self.delete_button = QPushButton("Delete")
        self.rename_button = QPushButton("Rename")
        for button, method in ((self.new_button, self.new_alias),
                               (self.delete_button, self.delete_alias),
                               (self.rename_button, self.rename_alias)):
            toolbar.addWidget(button)
            button.clicked.connect(method)
        toolbar.addStretch(1)
        top_layout.addLayout(toolbar)

        self.horizontal = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Aliases")
        self.tree.currentItemChanged.connect(self.selection_changed)
        self.horizontal.addWidget(self.tree)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Alias Properties"))
        form = QFormLayout()
        self.alias_name = QLineEdit()
        self.alias_name.setReadOnly(True)
        self.folder = QLineEdit()
        form.addRow("Alias", self.alias_name)
        form.addRow("Directory", self.folder)
        right_layout.addLayout(form)
        folder_buttons = QHBoxLayout()
        browse = QPushButton("Browse ...")
        save_path = QPushButton("Save Directory")
        browse.clicked.connect(self.browse_directory)
        save_path.clicked.connect(self.save_directory)
        folder_buttons.addWidget(browse)
        folder_buttons.addWidget(save_path)
        folder_buttons.addStretch(1)
        right_layout.addLayout(folder_buttons)
        right_layout.addWidget(QLabel("Ausgewählter Alias wird durch den Server verwaltet."))
        right_layout.addStretch()
        self.horizontal.addWidget(right)
        self.horizontal.setStretchFactor(0, 1)
        self.horizontal.setStretchFactor(1, 3)
        self.horizontal.setSizes([240, 660])
        top_layout.addWidget(self.horizontal)
        self.vertical.addWidget(top)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(3, 3, 3, 3)
        log_layout.addWidget(QLabel("Server Logging (neueste Meldung zuerst)"))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        log_layout.addWidget(self.log_text)
        log_actions = QHBoxLayout()
        export = QPushButton("Save As ...")
        clear = QPushButton("Clear Text")
        export.clicked.connect(self.save_log)
        clear.clicked.connect(self.clear_log)
        log_actions.addWidget(export)
        log_actions.addWidget(clear)
        log_actions.addStretch(1)
        log_layout.addLayout(log_actions)
        self.vertical.addWidget(log_panel)
        self.vertical.setStretchFactor(0, 3)
        self.vertical.setStretchFactor(1, 2)
        self.vertical.setSizes([380, 220])
        outer.addWidget(self.vertical)
        self.window.log.callbacks.append(self._append_log)
        self._render_log()
        self.refresh()

    def _append_log(self, line):
        if self.isVisible():
            self._render_log()

    def _render_log(self):
        self.log_text.setPlainText("\n".join(self.window.log.entries))
        self.log_text.verticalScrollBar().setValue(0)

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Log As", "python_bde_export.log",
                                              "Log-Dateien (*.log *.txt);;Alle Dateien (*)")
        if path:
            try:
                Path(path).write_text(self.log_text.toPlainText() + "\n", encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Save As", str(exc))

    def clear_log(self):
        self.window.log.clear_view()
        for panel in self.window.log_panels:
            panel._render_log()

    def selected_alias(self):
        node = self.tree.currentItem()
        return node.data(0, Qt.UserRole) if node is not None else None

    def refresh(self, choose=None):
        if choose is None:
            choose = self.selected_alias()
        self.tree.blockSignals(True)
        self.tree.clear()
        selected = None
        for item in self.window.server.aliases.listing():
            node = QTreeWidgetItem(self.tree, [item["name"]])
            node.setData(0, Qt.UserRole, item["name"])
            if choose and item["name"].casefold() == choose.casefold():
                selected = node
        self.tree.blockSignals(False)
        self.tree.setCurrentItem(selected)
        if selected is None:
            self.selection_changed(None, None)
        self.delete_button.setEnabled(bool(selected))
        self.rename_button.setEnabled(bool(selected))

    def selection_changed(self, current, _previous):
        name = current.data(0, Qt.UserRole) if current else None
        item = self.window.server.aliases.get(name) if name else None
        self.alias_name.setText(item["name"] if item else "")
        self.folder.setText(item["path"] if item else "")
        self.folder.setEnabled(bool(item))
        self.delete_button.setEnabled(bool(item))
        self.rename_button.setEnabled(bool(item))

    def _error(self, operation, err):
        self.window.record(400, f"Alias {operation} failed: {err}")
        QMessageBox.warning(self, "Aliases", str(err))

    def new_alias(self):
        name, ok = QInputDialog.getText(self, "New Alias", "Alias name")
        if not ok or not name.strip():
            return
        directory = QFileDialog.getExistingDirectory(self, "Select Alias Directory")
        if not directory:
            return
        try:
            self.window.server.create_alias(name.strip(), directory)
            self.refresh(choose=name.strip())
        except (OSError, ValueError) as err:
            self._error("creation", err)

    def rename_alias(self):
        name = self.selected_alias()
        if not name:
            return
        changed, ok = QInputDialog.getText(self, "Rename Alias", "New alias name", text=name)
        if not ok or not changed.strip() or changed == name:
            return
        try:
            self.window.server.rename_alias(name, changed.strip())
            self.refresh(choose=changed.strip())
        except (OSError, ValueError) as err:
            self._error("rename", err)

    def browse_directory(self):
        if not self.selected_alias():
            return
        directory = QFileDialog.getExistingDirectory(self, "Select Alias Directory", self.folder.text())
        if directory:
            self.folder.setText(directory)

    def save_directory(self):
        name = self.selected_alias()
        if not name:
            return
        try:
            self.window.server.update_alias_path(name, self.folder.text())
            self.refresh(choose=name)
        except (OSError, ValueError) as err:
            self._error("update", err)

    def delete_alias(self):
        name = self.selected_alias()
        if not name:
            return
        if QMessageBox.question(self, "Delete Alias", f"Alias '{name}' wirklich löschen?") != QMessageBox.Yes:
            return
        try:
            self.window.server.delete_alias(name)
        except AliasInUse as err:
            # Die Prüfung liegt zusätzlich im Server: ohne explizite
            # Bestätigung ist das Löschen dort grundsätzlich verboten.
            used_by = "\n".join(f"• {entry['username']} ({entry['peer']}, {entry['session_id']})"
                                   for entry in err.sessions[:30])
            warning = (f"Alias '{name}' wird noch von {len(err.sessions)} aktiven Sitzung(en) verwendet:\n"
                       f"{used_by}\n\n"
                       "Beim Löschen werden alle Alias-Reservierungen aufgehoben und betroffene "
                       "Clients benachrichtigt. Trotzdem löschen?")
            if QMessageBox.warning(self, "Alias wird verwendet", warning,
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            try:
                self.window.server.delete_alias(name, confirmed=True)
            except (OSError, ValueError) as e:
                self._error("deletion", e)
                return
        except (OSError, ValueError) as err:
            self._error("deletion", err)
            return
        self.refresh()


class BackupDock(QDockWidget):
    """Vorbereitung für DBF-Backup. Noch keine Backup-/Restore-Aktion möglich."""
    def __init__(self, window):
        super().__init__("Backup", window)
        self.setObjectName("PythonBDEBackupDock")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(QLabel("Backup Manager"))
        text = QLabel("Vorbereiteter Bereich für gesicherte DBF-Backups, Restore und Prüfsummen.\n"
                      "Die Funktionen sind noch nicht aktiviert.")
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()
        self.setWidget(body)


class MainWindow(QMainWindow):
    COPYRIGHT = " (c) 2026 by Jens Kallup - paule32"

    def __init__(self, users: UserManager, settings: Settings | int | None = None,
                 *, admin_username="", log=None):
        super().__init__()
        self.users = users
        self.admin_username = admin_username or "admin"
        self.log = log if log is not None else EventLog(users.store.path)
        self.log_panels = []
        self._force_close = False
        self._window_hiding = False
        self._docks_switching = False
        self._starting_server = False
        if isinstance(settings, Settings):
            self.settings = settings
        elif isinstance(settings, int):
            self.settings = replace(load_settings(), port=settings)
        else:
            self.settings = load_settings()
        self.server = BDEServer(users, self)
        self.server.server_id = self.settings.server_id
        self.server.message.connect(self.statusBar().showMessage)
        self.server.audit.connect(self.record)
        self.server.changed.connect(self._users_changed)
        self.server.status_changed.connect(self.update_status)
        self.manager_dock = None
        self.backup_dock = None
        self.aliases_dock = None
        self.setWindowTitle(f"PythonBDE – BDE Server ({operating_system()})" + self.COPYRIGHT)
        # QMainWindow besitzt bewusst kein centralWidget: der User-Manager
        # soll die *gesamte* freie Fläche füllen. Ein verborgenes Dashboard
        # erzeugte bislang nach Minimieren/Normalisieren eine linke Spalte.
        self._init_menu()
        self._init_theme_toolbar()
        # Dauerhafte Statusfelder: die kurzlebigen showMessage()-Texte bleiben
        # im freien linken Statusbar-Bereich sichtbar.
        self.status_server = QLabel("Server: Stopped", self)
        self.status_logins = QLabel("Logged-In: 0", self)
        self.status_server.setMinimumWidth(135)
        self.status_logins.setMinimumWidth(110)
        self.statusBar().addPermanentWidget(self.status_server)
        self.statusBar().addPermanentWidget(self.status_logins)
        self.resize(940, 650)
        self.show_users()  # Startansicht: Labels, Accounts, Log und Status zusammen
        self.update_status()
        self.apply_theme(False)  # Start im Light-Mode: Mond in der ToolBar
        self.record(200, "GUI started")

    def record(self, code, message):
        try:
            self.log.write(code, message)
        except OSError as exc:
            self.statusBar().showMessage(f"Logging error: {exc}")

    def _menu_action(self, menu, label, callback):
        item = QAction(label, self)
        item.triggered.connect(callback)
        menu.addAction(item)
        return item

    def _init_menu(self):
        file_menu = self.menuBar().addMenu("File")
        self._menu_action(file_menu, "Close", self.exit_application)
        server_menu = self.menuBar().addMenu("Server")
        self.action_start = self._menu_action(server_menu, "Start", self.start_server)
        self.action_stop = self._menu_action(server_menu, "Stop", self.stop_server)
        server_menu.addSeparator()
        self._menu_action(server_menu, "Status", self.show_status)
        self._menu_action(server_menu, "Settings", self.show_settings)
        manager_menu = self.menuBar().addMenu("Manager")
        self._menu_action(manager_menu, "Users", self.show_users)
        self._menu_action(manager_menu, "Aliases", self.show_aliases)
        self._menu_action(manager_menu, "Backup", self.show_backup)
        help_menu = self.menuBar().addMenu("Help")
        self._menu_action(help_menu, "Informations", self.show_informations)
        self._menu_action(help_menu, "About ...", self.show_about)

    def _init_theme_toolbar(self):
        """Genau ein Umschaltbutton: Mond=Light, Sonne=Dark."""
        self._dark_theme = False
        self.theme_toolbar = QToolBar("Appearance", self)
        self.theme_toolbar.setObjectName("PythonBDEAppearanceToolBar")
        self.theme_toolbar.setMovable(False)
        self.theme_toolbar.setFloatable(False)
        self.theme_toolbar.setIconSize(QSize(26, 26))
        self.theme_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(Qt.TopToolBarArea, self.theme_toolbar)
        self.action_theme = QAction(self)
        self.action_theme.setObjectName("PythonBDEThemeToggle")
        self.action_theme.triggered.connect(self.toggle_theme)
        self.theme_toolbar.addAction(self.action_theme)

    def apply_theme(self, dark: bool):
        """Den Light/Dark-Style global setzen und das angezeigte Icon tauschen."""
        self._dark_theme = bool(dark)
        apply_application_theme(self._dark_theme)
        # Ein globaler QSS-Wechsel darf den lokalen 3px-Kontorahmen
        # (rot/grün/gelb) nicht überdecken oder bis zum Timer verzögern.
        if self.manager_dock is not None:
            self.manager_dock._last_account_border = None
            self.manager_dock.update_account_border()
        self.action_theme.setIcon(theme_icon(self._dark_theme))
        target = "light" if self._dark_theme else "dark"
        self.action_theme.setText(f"Switch to {target} mode")
        self.action_theme.setToolTip(f"Switch to {target} mode")
        self.action_theme.setStatusTip(f"Switch to {target} mode")

    def toggle_theme(self):
        self.apply_theme(not self._dark_theme)

    def start_server(self):
        # Doppelte Klicks, Tastatur-Shortcuts und direkte Methodenaufrufe
        # dürfen niemals zwei parallele Startversuche erzeugen.
        if self._starting_server or self.server.listener.isListening():
            self.update_status()
            return
        self._starting_server = True
        self.update_status()
        try:
            self.server.start(self.settings.port, self.settings.ip,
                              server_id=self.settings.server_id)
        except (OSError, ValueError) as err:
            self.record(400, f"Server can not be started: {err}")
            QMessageBox.warning(self, "Server Start failed", str(err))
        finally:
            self._starting_server = False
            self.update_status()

    def stop_server(self):
        if self.server.listener.isListening():
            self.server.stop()
        self.update_status()

    def update_status(self):
        running = self.server.listener.isListening()
        status = self.server.status_snapshot()
        self.status_server.setText("Server: Started" if running else "Server: Stopped")
        self.status_logins.setText(f"Logged-In: {status['login_count']}")
        if self.manager_dock is not None:
            self.manager_dock.log_status.set_running(running or self._starting_server)
            if self._starting_server and not running:
                self.manager_dock.log_status.stop_button.setEnabled(False)
        # Während eines laufenden Startversuchs gesondert blockieren,
        # anschließend ausschließlich nach dem tatsächlichen Listen-Zustand.
        self.action_start.setEnabled(not running and not self._starting_server)
        self.action_stop.setEnabled(running)

    def show_settings(self):
        dlg = SettingsDialog(self.settings, self.server, self)
        if dlg.exec_() == QDialog.Accepted:
            before = self.settings
            self.settings = dlg.settings
            if self.server.listener.isListening() and (before.ip, before.port) != (self.settings.ip, self.settings.port):
                QMessageBox.information(self, "Settings", "Konfiguration gespeichert. Stop/Start des Servers "
                                        "erforderlich, um IP und Port zu übernehmen.")
            self.statusBar().showMessage("Serverkonfiguration in pythonbde.ini gespeichert")

    def show_status(self):
        # Status ist fest im User-Manager eingebettet; kein zweites Log-Dock.
        self.show_users()
        self.manager_dock.log_status.refresh()
        self.manager_dock.log_status.sessions.setFocus()

    def _show_exclusive_dock(self, dock):
        """Nur das gewählte Dock anzeigen; voriges Layout für Close merken."""
        if dock.isVisible():
            dock.raise_()
            return
        dock._previous_docks = [d for d in self.findChildren(QDockWidget)
                                if d is not dock and d.isVisible()]
        self._docks_switching = True
        try:
            for other in dock._previous_docks:
                other.hide()
        finally:
            self._docks_switching = False
        dock.show()
        dock.raise_()

    def _restore_after_dock(self, dock, visible):
        if visible or self._window_hiding or self._docks_switching:
            return
        previous = getattr(dock, "_previous_docks", None)
        if previous is None:
            return
        dock._previous_docks = None
        for other in previous:
            other.show()

    def show_users(self):
        if self.manager_dock is None:
            self.manager_dock = UserManagerDock(self)
            # Oberer Dockbereich nimmt die volle Fensterbreite ein und kann
            # weiterhin mit der Maus an andere Dockpositionen gezogen werden.
            self.addDockWidget(Qt.TopDockWidgetArea, self.manager_dock)
            self.manager_dock.hide()
            self.manager_dock.visibilityChanged.connect(
                lambda visible: self._restore_after_dock(self.manager_dock, visible))
        self.manager_dock.refresh()
        self._show_exclusive_dock(self.manager_dock)

    def show_aliases(self):
        if self.aliases_dock is None:
            self.aliases_dock = AliasesDock(self)
            self.log_panels.append(self.aliases_dock)
            self.addDockWidget(Qt.TopDockWidgetArea, self.aliases_dock)
            self.aliases_dock.hide()
            self.aliases_dock.visibilityChanged.connect(
                lambda visible: self._restore_after_dock(self.aliases_dock, visible))
        self.aliases_dock.refresh()
        self.aliases_dock._render_log()
        self._show_exclusive_dock(self.aliases_dock)

    def show_backup(self):
        if self.backup_dock is None:
            self.backup_dock = BackupDock(self)
            self.addDockWidget(Qt.TopDockWidgetArea, self.backup_dock)
            self.backup_dock.hide()
            self.backup_dock.visibilityChanged.connect(
                lambda visible: self._restore_after_dock(self.backup_dock, visible))
        self._show_exclusive_dock(self.backup_dock)

    def _users_changed(self):
        if self.manager_dock is not None and self.manager_dock.isVisible():
            self.manager_dock.refresh()

    def show_informations(self):
        """Informationsdialog statt breitenziehender Labels im Dock."""
        dlg = QDialog(self)
        dlg.setWindowTitle("PythonBDE – Informations")
        dlg.resize(620, 170)
        layout = QVBoxLayout(dlg)
        crypto = QLabel("Passwortschutz: " + password_backend())
        paths = QLabel(f"DBF: {self.users.store.path}\nLog: {self.log.path}")
        for label in (crypto, paths):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
            layout.addWidget(label)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dlg.reject)
        close.accepted.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec_()

    def show_about(self):
        QMessageBox.about(self, "About PythonBDE",
                          "PythonBDE v0.4.3" + self.COPYRIGHT +
                          "\nBDE-style server\nQt5 / Python / Windows + Linux\nPBKDF2-HMAC-SHA256")

    def activate_from_second_instance(self):
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.record(200, "GUI restored by second launch")
        QMessageBox.information(self, "PythonBDE", "Das Serverprogramm wurde bereits gestartet.")

    def exit_application(self):
        self._force_close = True
        self.close()

    def closeEvent(self, event):
        if self.server.listener.isListening() and not self._force_close:
            self.record(200, "GUI hidden")
            self._window_hiding = True
            self.hide()
            self._window_hiding = False
            event.ignore()
            return
        self.stop_server()
        self.record(200, "GUI closed.")
        event.accept()
        QTimer.singleShot(0, QApplication.instance().quit)
