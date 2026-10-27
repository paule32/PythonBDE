"""In-desktop MDI dialogs and synchronous, session-bound JSON virtual FS client.

Only intended for the Qt event thread. Nested event loop has a 10s timeout;
remote file blocks are capped at 20 KiB per JSONL response.
"""
from __future__ import annotations

import base64
from pathlib import PurePosixPath

from PyQt5.QtCore import QEventLoop, QTimer, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QHBoxLayout, QVBoxLayout,
    QGridLayout, QListWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QMdiSubWindow, QMessageBox, QTextBrowser, QPlainTextEdit,
)
from .virtual_fs import virtual_path, CHUNK, MAX_FILE


class RemoteFileBrowser(QWidget):
    finished = pyqtSignal(object)

    def __init__(self, bridge, mode, filters, start=None):
        super().__init__()
        self.bridge = bridge
        self.mode = mode
        self.folder = start if start in ('My Documents', 'Desktop') else 'My Documents'
        self.setWindowTitle('My Documents' if mode == 'browse' else ('Open File' if mode == 'open' else 'Save As ...'))
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for text, callback in [('Home', lambda: self.show_folder('My Documents')),
                               ('Up', self.up), ('Refresh', self.refresh), ('New Folder', self.mkdir)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.new_folder_row = QWidget(self)
        new_folder_layout = QHBoxLayout(self.new_folder_row)
        new_folder_layout.setContentsMargins(0, 0, 0, 0)
        new_folder_layout.addWidget(QLabel('New folder:'))
        self.new_folder_name = QLineEdit(self)
        new_folder_layout.addWidget(self.new_folder_name)
        create_folder = QPushButton('Create')
        create_folder.clicked.connect(self._create_folder)
        new_folder_layout.addWidget(create_folder)
        cancel_folder = QPushButton('Cancel')
        cancel_folder.clicked.connect(self.new_folder_row.hide)
        new_folder_layout.addWidget(cancel_folder)
        layout.addWidget(self.new_folder_row)
        self.new_folder_row.hide()
        middle = QHBoxLayout()
        self.places = QListWidget(self)
        self.places.setMaximumWidth(135)
        for name in ('My Documents', 'Desktop'):
            self.places.addItem(name)
        self.places.itemClicked.connect(lambda item: self.show_folder(item.text()))
        middle.addWidget(self.places)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(['Name', 'Type', 'Size'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.open_item)
        self.table.itemSelectionChanged.connect(self.select_item)
        middle.addWidget(self.table, stretch=1)
        layout.addLayout(middle, stretch=1)
        bottom = QGridLayout()
        bottom.addWidget(QLabel('Path / File name:'), 0, 0)
        self.file_name = QLineEdit(self)
        bottom.addWidget(self.file_name, 0, 1)
        bottom.addWidget(QLabel('File type:'), 0, 2)
        self.filter = QComboBox(self)
        for title, patterns in filters:
            self.filter.addItem(title, patterns)
        self.filter.currentIndexChanged.connect(self.refresh)
        bottom.addWidget(self.filter, 0, 3)
        layout.addLayout(bottom)
        buttons = QHBoxLayout()
        buttons.addStretch()
        submit = QPushButton('Close' if mode == 'browse' else ('Open' if mode == 'open' else 'Save'))
        submit.clicked.connect(self.submit)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(lambda: self.finished.emit(None))
        buttons.addWidget(submit)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.refresh()

    def show_folder(self, folder):
        try:
            virtual_path(folder)
            self.folder = folder
            self.file_name.clear()
            self.refresh()
        except (ValueError, RuntimeError) as err:
            self.bridge.alert(str(err))

    def refresh(self, *_):
        try:
            listing = self.bridge.call('vfs_list', path=self.folder)
            self.table.setRowCount(0)
            patterns = self.filter.currentData() or ['*']
            for item in listing:
                import fnmatch
                if item['type'] == 'file' and not any(fnmatch.fnmatch(item['name'].lower(), p.lower()) for p in patterns):
                    continue
                row = self.table.rowCount()
                self.table.insertRow(row)
                for col, text in enumerate((item['name'], 'Folder' if item['type']=='dir' else 'File',
                                            '' if item['type']=='dir' else str(item['size']))):
                    cell = QTableWidgetItem(text)
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col, cell)
        except (ValueError, RuntimeError) as err:
            self.bridge.alert(str(err))

    def up(self):
        if '/' in self.folder:
            self.show_folder(self.folder.rsplit('/', 1)[0])

    def mkdir(self):
        self.new_folder_name.clear()
        self.new_folder_row.show()
        self.new_folder_name.setFocus()

    def _create_folder(self):
        name = self.new_folder_name.text().strip()
        if not name:
            self.bridge.alert('Please enter a folder name')
            return
        try:
            self.bridge.call('vfs_mkdir', path=virtual_path(self.folder + '/' + name))
            self.new_folder_row.hide()
            self.refresh()
        except (RuntimeError, ValueError) as err:
            self.bridge.alert(str(err))

    def select_item(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            self.file_name.setText(self.table.item(row, 0).text())

    def open_item(self, item):
        row = item.row()
        name = self.table.item(row,0).text()
        if self.table.item(row,1).text() == 'Folder':
            self.show_folder(self.folder + '/' + name)
        else:
            self.file_name.setText(name)
            if self.mode != 'browse':
                self.submit()

    def submit(self):
        if self.mode == 'browse':
            self.finished.emit(None)
            return
        try:
            filename = self.file_name.text().strip()
            if self.mode == 'save' and '.' not in filename:
                patterns = self.filter.currentData() or ['*']
                if patterns[0].startswith('*.'):
                    filename += patterns[0][1:]
            path = virtual_path(self.folder + '/' + filename)
            if self.mode == 'open':
                listing = self.bridge.call('vfs_list', path=self.folder)
                if not any(i['path'] == path and i['type'] == 'file' for i in listing):
                    raise ValueError('File does not exist in virtual directory')
            self.finished.emit(path)
        except (ValueError, RuntimeError) as err:
            self.bridge.alert(str(err))


class RemoteFiles:
    """Explicit bridge injected ONLY into trusted editor widgets."""
    def __init__(self, client):
        self.client = client
        self.pending = None

    def call(self, action, **kwargs):
        if not self.client._logged_in or self.pending is not None:
            raise RuntimeError('Not connected or another file request is pending')
        loop = QEventLoop()
        self.pending = {'action': action, 'loop': loop, 'packet': None}
        try:
            if not self.client._send(action, **kwargs):
                raise RuntimeError('Could not send virtual file request')
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(10000)
            loop.exec_()
            packet = self.pending['packet']
            if not packet:
                raise RuntimeError('Virtual file request timed out')
            if not packet.get('ok'):
                raise RuntimeError(str(packet.get('error','Virtual filesystem error')))
            return packet.get('data')
        finally:
            self.pending = None

    def received(self, action, packet):
        if self.pending and self.pending['action'] == action:
            self.pending['packet'] = packet
            self.pending['loop'].quit()
            return True
        return False

    def _open_mdi(self, widget, title, width=580, height=420):
        window = self.client._client_window
        if not window or window.workspace is None:
            raise RuntimeError('No active RDP desktop')
        sub = window.workspace.addSubWindow(widget)
        sub.setWindowTitle(title)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.resize(min(width, max(240, window.workspace.width()-10)),
                   min(height, max(180, window.workspace.height()-10)))
        sub.show()
        window.workspace.setActiveSubWindow(sub)
        window._keep_desktop_behind_windows()
        return sub

    def open_dialog(self, mode='open', filters=(('All files',['*']),), start='My Documents'):
        browser = RemoteFileBrowser(self, mode, filters, start)
        sub = self._open_mdi(browser, browser.windowTitle())
        loop = QEventLoop()
        result = [None]
        def finish(value):
            result[0] = value
            loop.quit()
        browser.finished.connect(finish)
        sub.destroyed.connect(loop.quit)
        loop.exec_()
        sub.close()
        return result[0]

    def browse_documents(self):
        browser = RemoteFileBrowser(self, 'browse', [('All files', ['*'])], 'My Documents')
        sub = self._open_mdi(browser, 'My Documents')
        browser.finished.connect(lambda _result: sub.close())
        return sub

    def read_bytes(self, path):
        virtual_path(path)
        result = bytearray()
        offset = 0
        while True:
            packet = self.call('vfs_read', path=path, offset=offset)
            data = base64.b64decode(packet['content'], validate=True)
            result.extend(data)
            offset += len(data)
            if offset > MAX_FILE:
                raise RuntimeError('Remote file is too large')
            if packet['eof']:
                return bytes(result)
            if not data:
                raise RuntimeError('Server returned an empty non-final file chunk')

    def write_bytes(self, path, content):
        virtual_path(path)
        if len(content) > MAX_FILE:
            raise RuntimeError('File is larger than 16 MiB')
        self.call('vfs_begin', path=path)
        try:
            for offset in range(0, len(content), CHUNK):
                self.call('vfs_chunk', content=base64.b64encode(content[offset:offset+CHUNK]).decode('ascii'))
            return self.call('vfs_commit')
        except Exception:
            try: self.call('vfs_abort')
            except Exception: pass
            raise

    def alert(self, text, title='Remote Desktop'):
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(str(text))
        label.setWordWrap(True)
        layout.addWidget(label)
        close = QPushButton('OK')
        close.clicked.connect(lambda: w.parentWidget().close())
        layout.addWidget(close)
        self._open_mdi(w, title, 400, 190)

    def about(self, title, description):
        self.alert(description, title)

    def print_text(self, text, title='Print', *, rich=False):
        from PyQt5.QtPrintSupport import QPrinter, QPrinterInfo
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel('Print to installed printer'))
        printers = QComboBox(w)
        for info in QPrinterInfo.availablePrinters():
            printers.addItem(info.printerName())
        layout.addWidget(printers)
        layout.addWidget(QLabel(f'Document: {len(text)} characters'))
        def print_it():
            if not printers.currentText():
                self.alert('No printer available', 'Print')
                return
            from PyQt5.QtGui import QTextDocument
            printer = QPrinter(QPrinter.HighResolution)
            printer.setPrinterName(printers.currentText())
            doc = QTextDocument()
            if rich:
                doc.setHtml(text)
            else:
                doc.setPlainText(text)
            doc.print_(printer)
            w.parentWidget().close()
        b = QPushButton('Print')
        b.clicked.connect(print_it)
        layout.addWidget(b)
        self._open_mdi(w, title, 380, 200)
