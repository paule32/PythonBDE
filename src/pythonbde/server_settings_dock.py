"""Server Settings dock: network on the left, certificate authority on the right."""
from __future__ import annotations
from dataclasses import replace
import ipaddress
from pathlib import Path
import uuid

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QCheckBox, QDockWidget, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)
from PyQt5.QtNetwork import QHostAddress, QTcpServer, QUdpSocket, QSslSocket

from .settings import application_dir, save_settings, DISCOVERY_PORT
from .discovery import network_interfaces, broadcast_targets, discover_existing
from .tls_security import (resolve_certificate_file, validate_certificate_set,
                           validate_server_certificate, make_ca_signed_server_certificates)


class ServerSettingsDock(QDockWidget):
    def __init__(self, window):
        super().__init__('Server Settings', window)
        self.setObjectName('PythonBDEServerSettingsDock')
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.window = window
        self.adapters = []

        root = QWidget(self)
        self.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        self.horizontal = QSplitter(Qt.Horizontal)
        layout.addWidget(self.horizontal, 1)

        # Left: existing network/TLS widgets.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        network_group = QGroupBox('Network Settings')
        network_form = QFormLayout(network_group)
        self.nic = QComboBox()
        self.ip = QLineEdit()
        self.ip.setPlaceholderText('127.0.0.1 or 0.0.0.0')
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        network_form.addRow('Network Interface (NIC)', self.nic)
        network_form.addRow('Listen IP', self.ip)
        network_form.addRow('TCP Port', self.port)
        self.nic.currentIndexChanged.connect(self._nic_changed)
        left_layout.addWidget(network_group)
        self.server_id_label = QLabel()
        self.server_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.server_id_label.setWordWrap(True)
        left_layout.addWidget(self.server_id_label)
        self.tls_toggle = QCheckBox('Enable TLS (required on LAN)')
        left_layout.addWidget(self.tls_toggle)
        advice = QLabel('TLS protects logins, JSON-RPC and .cpy modules. '
                        'Without TLS only 127.0.0.1 is permitted.')
        advice.setWordWrap(True)
        left_layout.addWidget(advice)
        left_layout.addStretch(1)
        self.horizontal.addWidget(left)

        # Right: CA / server certificate management.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        security_group = QGroupBox('Certificate Authority / Server Certificates')
        security_form = QFormLayout(security_group)
        self.ca_cert = QLineEdit()
        self.ca_key = QLineEdit()
        self.tls_cert = QLineEdit()
        self.tls_key = QLineEdit()
        self._paths = ((self.ca_cert, 'CA Certificate (ca.crt)', False),
                       (self.ca_key, 'CA Private Key (ca.key)', True),
                       (self.tls_cert, 'Server Certificate (server.crt)', False),
                       (self.tls_key, 'Server Private Key (server.key)', True))
        for field, label, secret in self._paths:
            browse = QPushButton('...')
            browse.setMaximumWidth(35)
            browse.clicked.connect(lambda checked=False, f=field: self._browse(f))
            group = QWidget()
            form = QHBoxLayout(group)
            form.setContentsMargins(0, 0, 0, 0)
            form.addWidget(field)
            form.addWidget(browse)
            security_form.addRow(label, group)
            if secret:
                field.setToolTip('Private key: keep on server only; never transfer to clients')
        right_layout.addWidget(security_group)
        generate_options = QGroupBox('New CA and TLS Certificate')
        opts = QFormLayout(generate_options)
        self.dns_names = QLineEdit('localhost')
        self.dns_names.setPlaceholderText('localhost,server1.local')
        self.cert_days = QSpinBox()
        self.cert_days.setRange(1, 825)
        self.cert_days.setValue(365)
        opts.addRow('DNS SANs (comma-separated)', self.dns_names)
        opts.addRow('Valid for (days)', self.cert_days)
        right_layout.addWidget(generate_options)
        cert_buttons = QHBoxLayout()
        self.save_cert_btn = QPushButton('Save Certificate Paths')
        self.test_cert_btn = QPushButton('Test Certificates')
        self.create_cert_btn = QPushButton('Generate New Certificates')
        for b in (self.save_cert_btn, self.test_cert_btn, self.create_cert_btn):
            cert_buttons.addWidget(b)
        right_layout.addLayout(cert_buttons)
        self.save_cert_btn.clicked.connect(self.save_config)
        self.test_cert_btn.clicked.connect(self.test_certificates)
        self.create_cert_btn.clicked.connect(self.generate_certificates)
        notice = QLabel('New CA means new client trust setup. Creating a new CA rotates the '
                        'server UUID. Stop the server before regeneration. Existing files are NEVER overwritten.')
        notice.setWordWrap(True)
        right_layout.addWidget(notice)
        right_layout.addStretch(1)
        self.horizontal.addWidget(right)
        self.horizontal.setStretchFactor(0, 1)
        self.horizontal.setStretchFactor(1, 1)

        bottom = QHBoxLayout()
        self.save_btn = QPushButton('Save Config')
        self.test_btn = QPushButton('Test-Config')
        self.cancel_btn = QPushButton('Cancel')
        for b in (self.save_btn, self.test_btn, self.cancel_btn):
            bottom.addWidget(b)
        bottom.addStretch()
        layout.addLayout(bottom)
        self.save_btn.clicked.connect(self.save_config)
        self.test_btn.clicked.connect(self.test_config)
        self.cancel_btn.clicked.connect(self.cancel)
        self.refresh()

    def _browse(self, field):
        filename, _ = QFileDialog.getOpenFileName(self, 'Select Certificate / Key',
                                                   str(application_dir()), 'PEM files (*.crt *.key *.pem);;All (*)')
        if filename:
            field.setText(filename)

    def _nic_changed(self, index):
        if index >= 0:
            data = self.nic.itemData(index)
            if data:
                self.ip.setText(data[1])

    def refresh(self):
        cfg = self.window.settings
        self.adapters = network_interfaces()
        self.nic.blockSignals(True)
        try:
            self.nic.clear()
            self.nic.addItem('All IPv4 Interfaces (0.0.0.0)', ('', '0.0.0.0'))
            for adapter in self.adapters:
                self.nic.addItem(f"{adapter['name']} — {adapter['ip']}",
                                 (adapter['key'], adapter['ip']))
            for index in range(self.nic.count()):
                if self.nic.itemData(index) == (cfg.nic, cfg.ip):
                    self.nic.setCurrentIndex(index)
                    break
        finally:
            self.nic.blockSignals(False)
        self.ip.setText(cfg.ip)
        self.port.setValue(cfg.port)
        self.server_id_label.setText(f'Server UUID: {cfg.server_id}')
        self.tls_toggle.setChecked(cfg.tls_enabled)
        self.ca_cert.setText(cfg.tls_ca_certificate)
        self.ca_key.setText(cfg.tls_ca_private_key)
        self.tls_cert.setText(cfg.tls_certificate)
        self.tls_key.setText(cfg.tls_private_key)

    def values(self):
        selected = self.nic.currentData()
        ip = self.ip.text().strip()
        return replace(self.window.settings, ip=ip, port=self.port.value(),
                       nic=selected[0] if selected and selected[1] == ip else '',
                       tls_enabled=self.tls_toggle.isChecked(),
                       tls_ca_certificate=self.ca_cert.text().strip(),
                       tls_ca_private_key=self.ca_key.text().strip(),
                       tls_certificate=self.tls_cert.text().strip(),
                       tls_private_key=self.tls_key.text().strip()).validate()

    def _verify_certificates(self, cfg):
        if not cfg.tls_enabled:
            return 'TLS disabled; loopback only'
        if not QSslSocket.supportsSsl():
            raise RuntimeError('TLS: Qt5/OpenSSL support not available')
        base = application_dir()
        ca = resolve_certificate_file(cfg.tls_ca_certificate, base)
        server = resolve_certificate_file(cfg.tls_certificate, base)
        server_key = resolve_certificate_file(cfg.tls_private_key, base)
        # CA private key can be stored offline after certificate generation.
        ca_key = None
        if cfg.tls_ca_private_key.strip():
            ca_key_path = Path(cfg.tls_ca_private_key).expanduser()
            if not ca_key_path.is_absolute():
                ca_key_path = base / ca_key_path
            if ca_key_path.is_file():
                ca_key = ca_key_path
        algorithm = validate_certificate_set(ca, server, server_key, ca_key)
        return f'OK: CA chain + {algorithm} server key verified'

    def test_certificates(self):
        try:
            answer = self._verify_certificates(self.values())
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            QMessageBox.warning(self, 'Certificate Test failed', str(exc))
            return
        QMessageBox.information(self, 'Certificates', answer)

    def save_config(self):
        try:
            cfg = self.values()
            self._verify_certificates(cfg)
            save_settings(cfg)
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            QMessageBox.warning(self, 'Save Config failed', str(exc))
            return False
        before = self.window.settings
        self.window.settings = cfg
        if self.window.server.listener.isListening() and cfg != before:
            QMessageBox.information(self, 'Server Settings',
                'Settings saved. Restart the server to apply network / TLS changes.')
        self.window.record(200, 'Server settings saved')
        self.window.statusBar().showMessage('Settings saved to pythonbde.ini')
        return True

    def test_config(self):
        try:
            cfg = self.values()
            self._verify_certificates(cfg)
            if self.window.server.listener.isListening() and (
                self.window.server.bind_ip, self.window.server.listener.serverPort()) == (cfg.ip, cfg.port):
                QMessageBox.information(self, 'Test-Config', 'OK: server already listens on this IP / port')
                return
            available = {'127.0.0.1', '0.0.0.0'} | {adapter['ip'] for adapter in self.adapters}
            if cfg.ip not in available:
                raise ValueError('IP does not belong to a local network interface')
            running = self.window.server.listener.isListening()
            found = discover_existing(cfg.server_id, broadcast_targets(self.adapters),
                  own_instance=self.window.server.instance_id if running else '')
            if found:
                raise OSError(f"PythonBDE server already discovered: {found['address']}:{found['port']}")
            listener = QTcpServer(self)
            try:
                if not listener.listen(QHostAddress(cfg.ip), cfg.port):
                    raise OSError('IP and/or Port already in use: ' + listener.errorString())
            finally:
                listener.close()
            if not running:
                udp = QUdpSocket(self)
                try:
                    if not udp.bind(QHostAddress.AnyIPv4, DISCOVERY_PORT, QUdpSocket.DontShareAddress):
                        raise OSError('Discovery port already in use: ' + udp.errorString())
                finally:
                    udp.close()
            QMessageBox.information(self, 'Test-Config', 'Network bind and certificate tests passed')
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            QMessageBox.warning(self, 'Test-Config failed', str(exc))

    def generate_certificates(self):
        if self.window.server.listener.isListening() or self.window._starting_server:
            QMessageBox.warning(self, 'Stop Server',
                'Stop the running server before generating new CA/server certificates.')
            return
        answer = QMessageBox.question(self, 'New CA and Server UUID',
            'Generating new certificates requires a NEW server UUID.\n'
            'Existing clients must trust the NEW ca.crt.\n'
            'Existing certificate files will NOT be overwritten.\n\n'
            'Create new certificates AND rotate the server UUID?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            cfg = self.values()
            base = application_dir()
            paths = []
            for value in (cfg.tls_certificate, cfg.tls_private_key,
                          cfg.tls_ca_certificate, cfg.tls_ca_private_key):
                path = Path(value).expanduser()
                paths.append(path if path.is_absolute() else base / path)
            ips = ['127.0.0.1']
            if cfg.ip not in ('0.0.0.0', '127.0.0.1'):
                ips.append(str(ipaddress.ip_address(cfg.ip)))
            dns = [x.strip() for x in self.dns_names.text().replace(';', ',').split(',') if x.strip()]
            make_ca_signed_server_certificates(*paths, dns_names=dns or ['localhost'],
                                                ip_addresses=ips, days=self.cert_days.value())
            new_cfg = replace(cfg, server_id=str(uuid.uuid4()))
            save_settings(new_cfg)
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            QMessageBox.warning(self, 'Certificate Creation failed', str(exc))
            return
        self.window.settings = new_cfg
        self.window.server.server_id = new_cfg.server_id
        self.refresh()
        self.window.record(200, 'New CA/server certificates generated; Server UUID rotated')
        QMessageBox.information(self, 'New Certificates',
                f'Certificates created.\nNew Server UUID: {new_cfg.server_id}\n'
                'Distribute ca.crt securely to all RPC clients. '
                'Keep ca.key offline and NEVER send private keys to clients.')

    def cancel(self):
        self.refresh()  # discard unsaved modifications
        self.close()    # restore previously visible docks
