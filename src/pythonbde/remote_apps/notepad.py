"""PythonBDE Notepad: classic plain-text editor as a signed remote .cpy widget.

When injected with remote_files, file I/O is routed to the server-only virtual workspace.
The trusted signer is responsible for the publisher identity; signed code is
not sandboxed. This module is deliberately self-contained for CPython .pyc.
"""
from __future__ import annotations

from pathlib import Path
import os
import tempfile

MAX_TEXT_BYTES = 16 * 1024 * 1024


def decode_text(data):
    """Decode text and retain its encoding/BOM choice and newline convention."""
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError('File exceeds the 16 MiB editor limit')
    if data.startswith(b'\xef\xbb\xbf'):
        text, encoding = data[3:].decode('utf-8'), 'utf-8-sig'
    elif data.startswith(b'\xff\xfe'):
        text, encoding = data[2:].decode('utf-16-le'), 'utf-16-le'
    elif data.startswith(b'\xfe\xff'):
        text, encoding = data[2:].decode('utf-16-be'), 'utf-16-be'
    else:
        try:
            text, encoding = data.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError:
            text, encoding = data.decode('cp1252'), 'cp1252'
    newline = '\r\n' if '\r\n' in text else ('\r' if '\r' in text else '\n')
    return text, encoding, newline


def encode_text(text, encoding='utf-8', newline='\n'):
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', newline)
    if encoding == 'utf-8-sig':
        return b'\xef\xbb\xbf' + text.encode('utf-8')
    if encoding == 'utf-16-le':
        return b'\xff\xfe' + text.encode('utf-16-le')
    if encoding == 'utf-16-be':
        return b'\xfe\xff' + text.encode('utf-16-be')
    return text.encode(encoding)


def atomic_save(path, contents):
    """Avoid truncating an existing document after a failed write."""
    path = Path(path)
    if len(contents) > MAX_TEXT_BYTES + 4:
        raise ValueError('File exceeds the 16 MiB editor limit')
    fd, tmp = tempfile.mkstemp(prefix='.pythonbde-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(contents)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def create_widget(parent):
    from PyQt5.QtCore import Qt, QEvent, QTimer
    from PyQt5.QtGui import QFont, QKeySequence, QTextDocument, QTextCursor
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QLabel, QMenuBar,
        QAction, QMessageBox, QFileDialog, QDialog, QFormLayout, QLineEdit,
        QPushButton, QCheckBox, QDialogButtonBox, QInputDialog, QFontDialog,
        QMdiSubWindow,
    )

    class FindReplaceDialog(QDialog):
        def __init__(self, editor):
            super().__init__(editor)
            self.owner = editor
            self.setWindowTitle('Find and Replace')
            form = QFormLayout(self)
            self.find_text = QLineEdit(self)
            self.replace_text = QLineEdit(self)
            self.case = QCheckBox('Match case', self)
            self.whole = QCheckBox('Whole words', self)
            form.addRow('Find what:', self.find_text)
            form.addRow('Replace with:', self.replace_text)
            form.addRow(self.case)
            form.addRow(self.whole)
            for label, callback in [('Find Next', self.find_next),
                                    ('Replace', self.replace),
                                    ('Replace All', self.replace_all)]:
                button = QPushButton(label, self)
                button.clicked.connect(callback)
                form.addRow(button)
            self.find_text.setText(editor.last_find)
            self.find_text.selectAll()
            self.find_text.setFocus()

        def flags(self):
            flags = QTextDocument.FindFlags()
            if self.case.isChecked(): flags |= QTextDocument.FindCaseSensitively
            if self.whole.isChecked(): flags |= QTextDocument.FindWholeWords
            return flags

        def find_next(self):
            self.owner.find_next(self.find_text.text(), self.flags())

        def replace(self):
            needle = self.find_text.text()
            if not needle:
                return
            cursor = self.owner.editor.textCursor()
            selected = cursor.selectedText()
            if selected and (selected == needle if self.case.isChecked() else selected.casefold() == needle.casefold()):
                cursor.insertText(self.replace_text.text())
            self.find_next()

        def replace_all(self):
            needle = self.find_text.text()
            if not needle:
                return
            flags = self.flags()
            text_editor = self.owner.editor
            cursor = QTextCursor(text_editor.document())
            cursor.beginEditBlock()
            found = 0
            try:
                while found < 100000:
                    match = text_editor.document().find(needle, cursor, flags)
                    if match.isNull():
                        break
                    match.insertText(self.replace_text.text())
                    cursor = match
                    found += 1
            finally:
                cursor.endEditBlock()
            self.owner.status.setText(f'Replaced {found} occurrence(s)')

    class NotepadWidget(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.file_path = None
            self.encoding = 'utf-8'
            self.newline = '\r\n' if os.name == 'nt' else '\n'
            self.last_find = ''
            self._allow_close = False
            self._parent_window = None
            self.zoom = 0
            self.setMinimumSize(280, 200)
            root = QVBoxLayout(self)
            root.setContentsMargins(2, 2, 2, 2)
            root.setSpacing(0)
            menu = QMenuBar(self)
            menu.setNativeMenuBar(False)
            root.setMenuBar(menu)
            file_menu = menu.addMenu('File')
            edit_menu = menu.addMenu('Edit')
            format_menu = menu.addMenu('Format')
            view_menu = menu.addMenu('View')
            help_menu = menu.addMenu('Help')
            def action(where, label, callback, shortcut=None, checkable=False):
                a = QAction(label, self)
                if shortcut: a.setShortcut(QKeySequence(shortcut))
                a.setCheckable(checkable)
                a.triggered.connect(callback)
                where.addAction(a)
                return a
            action(file_menu, 'New', self.new_document, 'Ctrl+N')
            action(file_menu, 'Open...', self.open_document, 'Ctrl+O')
            action(file_menu, 'Save', self.save_document, 'Ctrl+S')
            action(file_menu, 'Save As...', self.save_as, 'Ctrl+Shift+S')
            file_menu.addSeparator()
            action(file_menu, 'Print...', self.print_document, 'Ctrl+P')
            file_menu.addSeparator()
            action(file_menu, 'Exit', self.exit_editor)
            action(edit_menu, 'Undo', lambda: self.editor.undo(), 'Ctrl+Z')
            action(edit_menu, 'Redo', lambda: self.editor.redo(), 'Ctrl+Y')
            edit_menu.addSeparator()
            action(edit_menu, 'Cut', lambda: self.editor.cut(), 'Ctrl+X')
            action(edit_menu, 'Copy', lambda: self.editor.copy(), 'Ctrl+C')
            action(edit_menu, 'Paste', lambda: self.editor.paste(), 'Ctrl+V')
            action(edit_menu, 'Delete', self.delete_selection, 'Del')
            edit_menu.addSeparator()
            action(edit_menu, 'Find...', self.open_find, 'Ctrl+F')
            action(edit_menu, 'Find Next', self.find_again, 'F3')
            action(edit_menu, 'Replace...', self.open_find, 'Ctrl+H')
            action(edit_menu, 'Go To...', self.go_to_line, 'Ctrl+G')
            action(edit_menu, 'Select All', lambda: self.editor.selectAll(), 'Ctrl+A')
            action(edit_menu, 'Time/Date', self.insert_timestamp, 'F5')
            wrap_action = action(format_menu, 'Word Wrap', self.set_word_wrap, checkable=True)
            wrap_action.setChecked(True)
            action(format_menu, 'Font...', self.select_font)
            self.status_action = action(view_menu, 'Status Bar', self.toggle_status, checkable=True)
            self.status_action.setChecked(True)
            action(view_menu, 'Zoom In', lambda: self.adjust_zoom(1), 'Ctrl++')
            action(view_menu, 'Zoom Out', lambda: self.adjust_zoom(-1), 'Ctrl+-')
            action(view_menu, 'Restore Default Zoom', self.reset_zoom, 'Ctrl+0')
            action(help_menu, 'About Notepad', self.about)
            self.editor = QPlainTextEdit(self)
            self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            self.editor.setFont(QFont('Consolas', 10))
            root.addWidget(self.editor, 1)
            self.status = QLabel(self)
            self.status.setContentsMargins(5, 2, 5, 2)
            root.addWidget(self.status)
            self.editor.cursorPositionChanged.connect(self.update_status)
            self.editor.textChanged.connect(self.update_status)
            self.editor.document().modificationChanged.connect(self.update_title)
            self.update_title()
            self.update_status()
            QTimer.singleShot(0, self._watch_mdi_close)

        def _watch_mdi_close(self):
            p = self.parentWidget()
            while p is not None and not isinstance(p, QMdiSubWindow):
                p = p.parentWidget()
            if p is not None:
                self._parent_window = p
                p.installEventFilter(self)
                self.update_title()

        def eventFilter(self, source, event):
            if source is self._parent_window and event.type() == QEvent.Close:
                if not self._confirm_changes(closing=True):
                    event.ignore()
                    return True
            return super().eventFilter(source, event)

        def closeEvent(self, event):
            if self._confirm_changes(closing=True): event.accept()
            else: event.ignore()

        def _confirm_changes(self, closing=False):
            if self._allow_close or not self.editor.document().isModified():
                return True
            choice = QMessageBox.question(self, 'Notepad', 'Save changes to the document?',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Cancel:
                return False
            if choice == QMessageBox.Save and not self.save_document():
                return False
            self._allow_close = closing
            return True

        def update_title(self, *_):
            title = (Path(self.file_path).name if self.file_path else 'Untitled') + ' - Notepad'
            if self.editor.document().isModified(): title = '*' + title
            if self._parent_window is not None:
                self._parent_window.setWindowTitle(title)
            self.setWindowTitle(title)

        def update_status(self, *_):
            cursor = self.editor.textCursor()
            line = cursor.blockNumber() + 1
            col = cursor.positionInBlock() + 1
            enc = self.encoding.upper()
            nl = 'Windows (CRLF)' if self.newline == '\r\n' else ('Mac (CR)' if self.newline == '\r' else 'Unix (LF)')
            self.status.setText(f'Ln {line}, Col {col}    Characters: {len(self.editor.toPlainText())}    {enc}    {nl}')
            self.update_title()

        def new_document(self):
            if not self._confirm_changes(): return False
            self._allow_close = False
            self.editor.clear()
            self.editor.document().setModified(False)
            self.file_path = None
            self.encoding = 'utf-8'
            self.update_title()
            return True

        def open_document(self):
            if not self._confirm_changes(): return False
            bridge = getattr(self, 'remote_files', None)
            if bridge is not None:
                name = bridge.open_dialog('open', [('Text files', ['*.txt','*.log','*.ini','*.csv','*.md']),
                                                    ('All files', ['*'])])
            else:
                name, _ = QFileDialog.getOpenFileName(self, 'Open', str(Path.home()),
                                                  'Text files (*.txt *.log *.ini *.csv *.md);;All files (*)')
            if not name:
                self._allow_close = False
                return False
            try:
                data = bridge.read_bytes(name) if bridge is not None else Path(name).read_bytes()
                text, encoding, newline = decode_text(data)
                self.editor.setPlainText(text)
                self.editor.document().setModified(False)
                self._allow_close = False
                self.file_path, self.encoding, self.newline = name, encoding, newline
                self.update_status()
                return True
            except (OSError, ValueError, UnicodeError) as exc:
                QMessageBox.critical(self, 'Notepad', f'Could not open file:\n{exc}')
                return False

        def save_document(self):
            if not self.file_path: return self.save_as()
            try:
                bridge = getattr(self, 'remote_files', None)
                data = encode_text(self.editor.toPlainText(), self.encoding, self.newline)
                if bridge is not None:
                    bridge.write_bytes(self.file_path, data)
                else:
                    atomic_save(self.file_path, data)
                self.editor.document().setModified(False)
                self.update_status()
                return True
            except (OSError, ValueError, UnicodeError) as exc:
                QMessageBox.critical(self, 'Notepad', f'Could not save file:\n{exc}')
                return False

        def save_as(self):
            bridge = getattr(self, 'remote_files', None)
            if bridge is not None:
                name = bridge.open_dialog('save', [('Text files', ['*.txt']), ('All files', ['*'])])
            else:
                name, _ = QFileDialog.getSaveFileName(self, 'Save As',
                        self.file_path or str(Path.home()/'Untitled.txt'), 'Text files (*.txt);;All files (*)')
            if not name: return False
            original = self.file_path
            self.file_path = name
            if self.save_document(): return True
            self.file_path = original
            return False

        def delete_selection(self):
            cursor = self.editor.textCursor()
            if not cursor.hasSelection(): cursor.deleteChar()
            else: cursor.removeSelectedText()

        def open_find(self):
            dialog = FindReplaceDialog(self)
            dialog.exec_()

        def find_next(self, needle, flags=None):
            if not needle: return False
            self.last_find = needle
            flags = flags if flags is not None else QTextDocument.FindFlags()
            if self.editor.find(needle, flags): return True
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.End if (flags & QTextDocument.FindBackward) else QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            if self.editor.find(needle, flags): return True
            QMessageBox.information(self, 'Notepad', f'Cannot find: {needle}')
            return False

        def find_again(self):
            if self.last_find: self.find_next(self.last_find)
            else: self.open_find()

        def go_to_line(self):
            maxline = max(1, self.editor.document().blockCount())
            line, ok = QInputDialog.getInt(self, 'Go To Line', 'Line number:', 1, 1, maxline)
            if ok:
                cursor = QTextCursor(self.editor.document().findBlockByNumber(line - 1))
                self.editor.setTextCursor(cursor)
                self.editor.setFocus()

        def insert_timestamp(self):
            from datetime import datetime
            self.editor.insertPlainText(datetime.now().strftime('%H:%M %d.%m.%Y'))

        def set_word_wrap(self, enabled):
            self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap)

        def select_font(self):
            font, ok = QFontDialog.getFont(self.editor.font(), self, 'Font')
            if ok: self.editor.setFont(font)

        def adjust_zoom(self, step):
            if step > 0: self.editor.zoomIn(step)
            else: self.editor.zoomOut(-step)
            self.zoom += step

        def reset_zoom(self):
            if self.zoom:
                self.editor.zoomOut(self.zoom)
                self.zoom = 0

        def toggle_status(self, visible):
            self.status.setVisible(visible)

        def print_document(self):
            bridge = getattr(self, 'remote_files', None)
            if bridge is not None:
                bridge.print_text(self.editor.toPlainText(), 'Print Notepad')
                return
            try:
                from PyQt5.QtPrintSupport import QPrinter, QPrintDialog
                printer = QPrinter(QPrinter.HighResolution)
                if QPrintDialog(printer, self).exec_() == QDialog.Accepted:
                    self.editor.print_(printer)
            except Exception as exc:
                QMessageBox.warning(self, 'Notepad', f'Printing unavailable:\n{exc}')

        def exit_editor(self):
            if self._parent_window is not None: self._parent_window.close()
            else: self.close()

        def about(self):
            bridge = getattr(self, 'remote_files', None)
            if bridge is not None:
                bridge.about('About Notepad', 'PythonBDE Notepad\n(c) 2026 by Jens Kallup - paule32')
                return
            QMessageBox.about(self, 'About Notepad',
                  'PythonBDE Notepad\nClassic plain-text editor (.cpy remote application)\n'
                  '(c) 2026 by Jens Kallup - paule32')

    return NotepadWidget(parent)
