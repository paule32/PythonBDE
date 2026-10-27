"""PythonBDE WordPad: rich-text editor shipped as one signed .cpy module.

Supports TXT, HTML, ODT (via Qt QTextDocumentWriter), and common text/font/
paragraph RTF features. RTF support is intentionally a documented subset,
not a Microsoft WordPad-format compatibility guarantee. Remote file dialogs and JSON file operations stay within the RDP workspace; do not load this as an untrusted Python script.
"""
from __future__ import annotations

from pathlib import Path
import html
import os
import re
import tempfile
import base64
import io
import zipfile
import xml.etree.ElementTree as ET

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024


def atomic_save(path, data):
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds the 16 MiB limit')
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.pythonbde-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def rtf_escape(value):
    """Write valid RTF escaping even for non-BMP Unicode characters."""
    out = []
    for ch in value:
        if ch == '\\': out.append('\\\\')
        elif ch == '{': out.append('\\{')
        elif ch == '}': out.append('\\}')
        elif ch == '\t': out.append('\\tab ')
        elif ch == '\n': out.append('\\line ')
        elif 32 <= ord(ch) < 127: out.append(ch)
        else:
            encoded = ch.encode('utf-16-le')
            for at in range(0, len(encoded), 2):
                n = int.from_bytes(encoded[at:at+2], 'little')
                out.append(f'\\u{n if n < 32768 else n - 65536}?')
    return ''.join(out)


def rtf_to_html(data):
    """Parse the text/formatting subset of RTF without executing embedded data.

    Recognizes paragraph alignment, bold/italic/underline/strikeout, font size,
    ANSI hex escapes, Unicode and RGB colors; ignores embedded objects/pictures
    and unknown RTF destinations. Uses HTML escaping for the output.
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError('RTF file too large')
    if isinstance(data, bytes):
        text = data.decode('latin1')
    else:
        text = data
    if not text.lstrip().startswith('{\\rtf'):
        raise ValueError('Not an RTF document')
    colors = ['#000000']
    colortbl = re.search(r'\{\\colortbl\s*([^{}]*)\}', text)
    if colortbl:
        for entry in colortbl.group(1).split(';')[1:]:
            r = re.search(r'\\red(\d+)', entry)
            g = re.search(r'\\green(\d+)', entry)
            b = re.search(r'\\blue(\d+)', entry)
            colors.append('#%02x%02x%02x' % tuple(min(255, int(v.group(1))) if v else 0 for v in (r, g, b)))
    state = {'b':False,'i':False,'ul':False,'strike':False,'fs':24,'cf':0,'align':'left'}
    stack = []
    paragraphs = []
    current = []
    buffer = []
    active_style = None
    pending_high = None

    def style():
        return tuple(state[k] for k in ('b','i','ul','strike','fs','cf'))

    def flush():
        nonlocal buffer, active_style
        if buffer:
            current.append((''.join(buffer), active_style))
            buffer = []

    def char(c):
        nonlocal active_style
        styling = style()
        if styling != active_style:
            flush()
            active_style = styling
        buffer.append(c)

    def paragraph():
        nonlocal current, active_style
        flush()
        paragraphs.append((state['align'], current))
        current = []
        active_style = None

    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '{':
            # Skip groups that contain metadata, binary objects or formatting tables.
            m = re.match(r'\{\\(?:fonttbl|colortbl|stylesheet|pict|object|info|\*|listtable|listoverridetable)(?:\b|\s)', text[i:])
            if m:
                depth = 1
                i += 1
                while i < len(text) and depth:
                    if text[i] == '\\' and i+1 < len(text):
                        if text[i+1] in '{}\\': i += 2; continue
                        if text[i+1] == "'" and i+3 < len(text): i += 4; continue
                    if text[i] == '{': depth += 1
                    elif text[i] == '}': depth -= 1
                    i += 1
                continue
            stack.append(state.copy())
            i += 1
            continue
        if ch == '}':
            flush()
            if stack: state = stack.pop()
            i += 1
            continue
        if ch == '\\':
            i += 1
            if i >= len(text): break
            ch = text[i]
            if ch in ('\\', '{', '}'):
                char(ch); i += 1; continue
            if ch == "'" and i+2 < len(text):
                try: char(bytes.fromhex(text[i+1:i+3]).decode('cp1252'))
                except ValueError: pass
                i += 3; continue
            if ch == '~': char('\u00a0'); i += 1; continue
            if ch == '_': char('\u2011'); i += 1; continue
            if ch == '-': char('\u00ad'); i += 1; continue
            if not ch.isalpha():
                i += 1; continue
            start = i
            while i < len(text) and text[i].isalpha(): i += 1
            command = text[start:i]
            start_num = i
            if i < len(text) and text[i] == '-': i += 1
            while i < len(text) and text[i].isdigit(): i += 1
            try: number = int(text[start_num:i]) if i > start_num else None
            except ValueError: number = None
            if i < len(text) and text[i] == ' ': i += 1
            if command in ('b','i','ul','strike'):
                flush(); state[command] = number != 0
            elif command == 'ulnone':
                flush(); state['ul'] = False
            elif command == 'fs' and number is not None:
                flush(); state['fs'] = max(8, min(number, 192))
            elif command == 'cf' and number is not None:
                flush(); state['cf'] = max(0, number)
            elif command in ('ql','qr','qc','qj'):
                state['align'] = {'ql':'left','qr':'right','qc':'center','qj':'justify'}[command]
            elif command == 'pard':
                flush()
                state.update({'b':False,'i':False,'ul':False,'strike':False,'fs':24,'cf':0,'align':'left'})
            elif command == 'plain':
                flush()
                state.update({'b':False,'i':False,'ul':False,'strike':False,'fs':24,'cf':0})
            elif command == 'par': paragraph()
            elif command == 'line': char('\n')
            elif command == 'tab': char('\t')
            elif command == 'emdash': char('\u2014')
            elif command == 'endash': char('\u2013')
            elif command == 'bullet': char('\u2022')
            elif command == 'u' and number is not None:
                n = number & 0xFFFF
                if 0xD800 <= n <= 0xDBFF:
                    pending_high = n
                elif 0xDC00 <= n <= 0xDFFF and pending_high is not None:
                    char(chr(0x10000 + ((pending_high-0xD800)<<10) + n-0xDC00))
                    pending_high = None
                else:
                    pending_high = None
                    if not 0xD800 <= n <= 0xDFFF: char(chr(n))
                # Standard \uc1 fallback char: skip ASCII, escaped literal or hex.
                if i < len(text) and text[i] not in '{}\\': i += 1
                elif text[i:i+2] == "\\'": i += 4
                elif text[i:i+2] in ('\\\\','\\{','\\}'): i += 2
            continue
        if ch not in '\r\n\x00': char(ch)
        i += 1
    paragraph()
    output = ['<html><body>']
    for alignment, spans in paragraphs:
        output.append(f'<p style="text-align:{alignment};margin:0">')
        for s, fmt in spans:
            b, ital, ul, strike, points, color = fmt
            styles = [f'font-size:{points/2:g}pt']
            if b: styles.append('font-weight:bold')
            if ital: styles.append('font-style:italic')
            if ul or strike:
                decorations = ('underline ' if ul else '') + ('line-through' if strike else '')
                styles.append('text-decoration:' + decorations.strip())
            if 0 < color < len(colors): styles.append('color:' + colors[color])
            escaped = html.escape(s).replace('\n', '<br/>').replace('\t', '&#9;')
            output.append('<span style="' + ';'.join(styles) + '">' + escaped + '</span>')
        output.append('</p>')
    return ''.join(output) + '</body></html>'



def odt_to_html(data):
    """Safe, basic ODT text import (styles beyond alignment are not guaranteed)."""
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError('ODT file exceeds 16 MiB')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        try:
            item = archive.getinfo('content.xml')
            if item.file_size > MAX_DOCUMENT_BYTES:
                raise ValueError('ODT content too large')
            content = archive.read(item)
        except KeyError as exc:
            raise ValueError('ODT has no content.xml') from exc
    root = ET.fromstring(content)
    text_ns = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
    paragraphs = []
    for node in root.iter():
        if node.tag in (text_ns + 'p', text_ns + 'h'):
            txt = ''.join(node.itertext())
            paragraphs.append('<p>' + html.escape(txt) + '</p>')
    return '<html><body>' + ''.join(paragraphs) + '</body></html>'


def create_widget(parent):
    from PyQt5.QtCore import Qt, QEvent, QDateTime, QTimer, QUrl
    from PyQt5.QtGui import (
        QFont, QColor, QKeySequence, QTextCursor, QTextDocument, QTextCharFormat,
        QTextListFormat, QImage, QTextDocumentWriter,
    )
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QToolBar, QTextEdit,
        QAction, QFileDialog, QMessageBox, QFontComboBox, QSpinBox, QComboBox,
        QDialog, QFormLayout, QLineEdit, QCheckBox, QPushButton, QLabel,
        QColorDialog, QInputDialog, QMdiSubWindow,
    )

    def document_to_rtf(document):
        """Export common paragraph/character formatting without third-party tools."""
        palette = ['#000000']
        blocks = []
        block = document.begin()
        while block.isValid():
            fragments = []
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    col = fmt.foreground().color()
                    color = col.name().lower() if col.isValid() else '#000000'
                    if color not in palette: palette.append(color)
                    fragments.append((fragment.text(), fmt, color))
                iterator += 1
            blocks.append((block, fragments))
            block = block.next()
        color_table = '{\\colortbl ;' + ''.join(
            f'\\red{int(c[1:3],16)}\\green{int(c[3:5],16)}\\blue{int(c[5:7],16)};'
            for c in palette[1:]) + '}'
        out = ['{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc1',
               '{\\fonttbl{\\f0\\fnil Arial;}}', color_table, '\n']
        for block, fragments in blocks:
            align = {Qt.AlignLeft:'\\ql', Qt.AlignRight:'\\qr',
                     Qt.AlignHCenter:'\\qc', Qt.AlignJustify:'\\qj'}.get(
                         block.blockFormat().alignment(), '\\ql')
            out.append('\\pard' + align + ' ')
            if block.textList() is not None:
                out.append('\\bullet\\tab ')
            for text, fmt, color in fragments:
                points = fmt.fontPointSize()
                if points <= 0: points = 12.0
                out.append('{\\b%d\\i%d\\ul%d\\strike%d\\fs%d\\cf%d ' % (
                    1 if fmt.fontWeight() >= QFont.Bold else 0,
                    1 if fmt.fontItalic() else 0,
                    1 if fmt.fontUnderline() else 0,
                    1 if fmt.fontStrikeOut() else 0,
                    max(8,min(192,round(points*2))), palette.index(color)))
                out.append(rtf_escape(text))
                out.append('}')
            out.append('\\par\n')
        out.append('}')
        return ''.join(out).encode('ascii')

    class RichFindDialog(QDialog):
        def __init__(self, owner):
            super().__init__(owner)
            self.owner = owner
            self.setWindowTitle('Find / Replace')
            form = QFormLayout(self)
            self.find = QLineEdit(owner.last_find, self)
            self.replace = QLineEdit(self)
            self.case = QCheckBox('Match case', self)
            self.whole = QCheckBox('Whole words', self)
            form.addRow('Find:', self.find)
            form.addRow('Replace:', self.replace)
            form.addRow(self.case)
            form.addRow(self.whole)
            for label, fn in [('Find Next', self.find_next),
                              ('Replace', self.replace_one),
                              ('Replace All', self.replace_all)]:
                b = QPushButton(label, self)
                b.clicked.connect(fn)
                form.addRow(b)
            self.find.setFocus()

        def flags(self):
            flags = QTextDocument.FindFlags()
            if self.case.isChecked(): flags |= QTextDocument.FindCaseSensitively
            if self.whole.isChecked(): flags |= QTextDocument.FindWholeWords
            return flags

        def find_next(self):
            self.owner.find_next(self.find.text(), self.flags())

        def replace_one(self):
            needle = self.find.text()
            if not needle: return
            cursor = self.owner.editor.textCursor()
            chosen = cursor.selectedText()
            if chosen and (chosen == needle if self.case.isChecked() else chosen.casefold() == needle.casefold()):
                cursor.insertText(self.replace.text())
            self.find_next()

        def replace_all(self):
            if not self.find.text(): return
            cursor = QTextCursor(self.owner.editor.document())
            cursor.beginEditBlock()
            count = 0
            try:
                while count < 100000:
                    result = self.owner.editor.document().find(self.find.text(), cursor, self.flags())
                    if result.isNull(): break
                    result.insertText(self.replace.text())
                    cursor = result
                    count += 1
            finally:
                cursor.endEditBlock()
            self.owner.status.setText(f'Replaced {count} occurrence(s)')

    class WordPadWidget(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.file_path = None
            self.last_find = ''
            self._mdi_parent = None
            self._confirmed = False
            self._images = {}  # in-memory resources, embedded into HTML on save
            self.setMinimumSize(360, 230)
            self.editor = QTextEdit(self)
            self.editor.setAcceptRichText(True)
            self.editor.setFont(QFont('Arial', 11))
            root = QVBoxLayout(self)
            root.setContentsMargins(2,2,2,2)
            root.setSpacing(1)
            menu = QMenuBar(self)
            menu.setNativeMenuBar(False)
            root.setMenuBar(menu)
            filemenu = menu.addMenu('File')
            editmenu = menu.addMenu('Edit')
            viewmenu = menu.addMenu('View')
            insertmenu = menu.addMenu('Insert')
            formatmenu = menu.addMenu('Format')
            helpmenu = menu.addMenu('Help')
            def act(m, label, cb, shortcut=None, check=False):
                a = QAction(label, self)
                if shortcut: a.setShortcut(QKeySequence(shortcut))
                a.setCheckable(check)
                a.triggered.connect(cb)
                m.addAction(a)
                return a
            act(filemenu, 'New', self.new_document, 'Ctrl+N')
            act(filemenu, 'Open...', self.open_document, 'Ctrl+O')
            act(filemenu, 'Save', self.save_document, 'Ctrl+S')
            act(filemenu, 'Save As...', self.save_as, 'Ctrl+Shift+S')
            filemenu.addSeparator()
            act(filemenu, 'Print...', self.print_document, 'Ctrl+P')
            filemenu.addSeparator()
            act(filemenu, 'Exit', self.exit_app)
            act(editmenu,'Undo',self.editor.undo,'Ctrl+Z')
            act(editmenu,'Redo',self.editor.redo,'Ctrl+Y')
            editmenu.addSeparator()
            act(editmenu,'Cut',self.editor.cut,'Ctrl+X')
            act(editmenu,'Copy',self.editor.copy,'Ctrl+C')
            act(editmenu,'Paste',self.editor.paste,'Ctrl+V')
            editmenu.addSeparator()
            act(editmenu,'Find...',self.show_find,'Ctrl+F')
            act(editmenu,'Replace...',self.show_find,'Ctrl+H')
            act(editmenu,'Select All',self.editor.selectAll,'Ctrl+A')
            act(viewmenu,'Zoom In',lambda: self.editor.zoomIn(1),'Ctrl++')
            act(viewmenu,'Zoom Out',lambda: self.editor.zoomOut(1),'Ctrl+-')
            act(insertmenu,'Picture...',self.insert_picture)
            act(insertmenu,'Date and Time...',self.insert_date)
            act(formatmenu,'Text Color...',self.choose_color)
            act(formatmenu,'Bulleted List',self.bullet_list)
            act(formatmenu,'Numbered List',self.numbered_list)
            act(helpmenu,'About WordPad',self.about)
            self.toolbar = QToolBar('Formatting', self)
            self.toolbar.setMovable(False)
            root.addWidget(self.toolbar)
            self.font_combo = QFontComboBox(self)
            self.font_combo.setMinimumWidth(95)
            self.font_combo.currentFontChanged.connect(self.apply_font)
            self.toolbar.addWidget(self.font_combo)
            self.size_spinner = QSpinBox(self)
            self.size_spinner.setRange(6,96)
            self.size_spinner.setValue(11)
            self.size_spinner.setSuffix(' pt')
            self.size_spinner.valueChanged.connect(self.apply_font_size)
            self.toolbar.addWidget(self.size_spinner)
            self.toolbar.addSeparator()
            self.bold = self.toolbar.addAction('B')
            self.bold.setCheckable(True)
            self.bold.triggered.connect(lambda checked: self.change_char('bold',checked))
            self.italic = self.toolbar.addAction('I')
            self.italic.setCheckable(True)
            self.italic.triggered.connect(lambda checked: self.change_char('italic',checked))
            self.underline = self.toolbar.addAction('U')
            self.underline.setCheckable(True)
            self.underline.triggered.connect(lambda checked: self.change_char('underline',checked))
            self.strike = self.toolbar.addAction('S')
            self.strike.setCheckable(True)
            self.strike.triggered.connect(lambda checked: self.change_char('strike',checked))
            for name, alignment in [('Left',Qt.AlignLeft),('Center',Qt.AlignHCenter),
                                     ('Right',Qt.AlignRight),('Justify',Qt.AlignJustify)]:
                self.toolbar.addAction(name, lambda _checked=False,a=alignment: self.editor.setAlignment(a))
            self.toolbar.addSeparator()
            self.toolbar.addAction('Bullets',self.bullet_list)
            self.toolbar.addAction('Numbers',self.numbered_list)
            self.toolbar.addAction('Color',self.choose_color)
            root.addWidget(self.editor,1)
            self.status = QLabel(self)
            self.status.setContentsMargins(5,2,5,2)
            root.addWidget(self.status)
            self.editor.cursorPositionChanged.connect(self.cursor_update)
            self.editor.textChanged.connect(self.cursor_update)
            self.editor.document().modificationChanged.connect(self.update_title)
            self.cursor_update()
            self.update_title()
            QTimer.singleShot(0,self.install_parent_close_handler)

        def install_parent_close_handler(self):
            p = self.parentWidget()
            while p is not None and not isinstance(p,QMdiSubWindow): p=p.parentWidget()
            if p is not None:
                self._mdi_parent = p
                p.installEventFilter(self)
                self.update_title()

        def eventFilter(self, watched, event):
            if watched is self._mdi_parent and event.type() == QEvent.Close:
                if not self.may_close(closing=True):
                    event.ignore()
                    return True
            return super().eventFilter(watched,event)

        def closeEvent(self,event):
            if self.may_close(closing=True):event.accept()
            else:event.ignore()

        def may_close(self, closing=False):
            if self._confirmed or not self.editor.document().isModified():return True
            answer=QMessageBox.question(self,'WordPad','Save changes to the document?',
                QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
            if answer==QMessageBox.Cancel:return False
            if answer==QMessageBox.Save and not self.save_document():return False
            self._confirmed=closing
            return True

        def update_title(self,*_):
            title = (Path(self.file_path).name if self.file_path else 'Document')+' - WordPad'
            if self.editor.document().isModified(): title='*'+title
            self.setWindowTitle(title)
            if self._mdi_parent is not None:self._mdi_parent.setWindowTitle(title)

        def cursor_update(self,*_):
            c=self.editor.textCursor()
            self.status.setText('Ln %d, Col %d    Words: %d    Characters: %d' % (
                c.blockNumber()+1,c.positionInBlock()+1,
                len(self.editor.toPlainText().split()),len(self.editor.toPlainText())))
            fmt=self.editor.currentCharFormat()
            self.bold.blockSignals(True);self.italic.blockSignals(True)
            self.underline.blockSignals(True);self.strike.blockSignals(True)
            self.bold.setChecked(fmt.fontWeight()>=QFont.Bold)
            self.italic.setChecked(fmt.fontItalic())
            self.underline.setChecked(fmt.fontUnderline())
            self.strike.setChecked(fmt.fontStrikeOut())
            for action in (self.bold,self.italic,self.underline,self.strike):action.blockSignals(False)
            self.size_spinner.blockSignals(True)
            if fmt.fontPointSize()>0:self.size_spinner.setValue(round(fmt.fontPointSize()))
            self.size_spinner.blockSignals(False)
            self.font_combo.blockSignals(True)
            if fmt.fontFamily():self.font_combo.setCurrentFont(QFont(fmt.fontFamily()))
            self.font_combo.blockSignals(False)
            self.update_title()

        def apply_format(self,delta):
            cursor=self.editor.textCursor()
            cursor.mergeCharFormat(delta)
            self.editor.mergeCurrentCharFormat(delta)
            self.editor.setFocus()

        def change_char(self,kind,value):
            fmt=QTextCharFormat()
            if kind=='bold':fmt.setFontWeight(QFont.Bold if value else QFont.Normal)
            elif kind=='italic':fmt.setFontItalic(value)
            elif kind=='underline':fmt.setFontUnderline(value)
            elif kind=='strike':fmt.setFontStrikeOut(value)
            self.apply_format(fmt)

        def apply_font(self,font):
            fmt=QTextCharFormat();fmt.setFontFamily(font.family());self.apply_format(fmt)

        def apply_font_size(self,size):
            fmt=QTextCharFormat();fmt.setFontPointSize(size);self.apply_format(fmt)

        def choose_color(self):
            col=QColorDialog.getColor(self.editor.textColor(),self,'Text Color')
            if col.isValid():
                fmt=QTextCharFormat();fmt.setForeground(col);self.apply_format(fmt)

        def _list(self,style):
            cursor=self.editor.textCursor()
            cursor.createList(style)
            self.editor.setFocus()

        def bullet_list(self):self._list(QTextListFormat.ListDisc)
        def numbered_list(self):self._list(QTextListFormat.ListDecimal)

        def insert_picture(self):
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:
                name=bridge.open_dialog('open',[('Images',['*.png','*.jpg','*.jpeg','*.gif','*.bmp'])])
            else:
                name,_=QFileDialog.getOpenFileName(self,'Insert Picture',str(Path.home()),
                        'Images (*.png *.jpg *.jpeg *.gif *.bmp)')
            if not name:return
            try:
                picture = bridge.read_bytes(name) if bridge is not None else Path(name).read_bytes()
                if len(picture)>4*1024*1024:
                    raise ValueError('Image exceeds 4 MiB')
                image=QImage.fromData(picture)
                if image.isNull():raise ValueError('Cannot decode image')
                import uuid
                tag = 'pythonbde-img-' + uuid.uuid4().hex
                extension = Path(name).suffix.lower()
                mime = 'image/png' if extension == '.png' else ('image/gif' if extension == '.gif' else
                       'image/bmp' if extension == '.bmp' else 'image/jpeg')
                self._images[tag] = (mime, picture)
                self.editor.document().addResource(QTextDocument.ImageResource, QUrl(tag), image)
                self.editor.textCursor().insertImage(tag)
            except (OSError,ValueError) as exc:
                QMessageBox.warning(self,'WordPad',str(exc))

        def insert_date(self):
            formats=['dd.MM.yyyy','dd.MM.yyyy hh:mm','ddd, dd. MMMM yyyy', 'hh:mm:ss']
            fmt,ok=QInputDialog.getItem(self,'Date and Time','Format:',formats,0,False)
            if ok:self.editor.insertPlainText(QDateTime.currentDateTime().toString(fmt))

        def new_document(self):
            if not self.may_close():return False
            self._confirmed=False
            self.editor.clear()
            self._images.clear()
            self.editor.document().setModified(False)
            self.file_path=None
            self.update_title()
            return True

        def open_document(self):
            if not self.may_close():return False
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:
                path=bridge.open_dialog('open',[('WordPad Documents',['*.rtf','*.html','*.htm','*.odt','*.txt']),
                                                ('All Files',['*'])])
            else:
                path,_=QFileDialog.getOpenFileName(self,'Open',str(Path.home()),
                 'WordPad Documents (*.rtf *.html *.htm *.odt *.txt);;All Files (*)')
            if not path:
                self._confirmed=False
                return False
            try:
                raw=bridge.read_bytes(path) if bridge is not None else Path(path).read_bytes()
                if len(raw)>MAX_DOCUMENT_BYTES:raise ValueError('File exceeds 16 MiB')
                suffix=Path(path).suffix.lower()
                if suffix=='.rtf':self.editor.setHtml(rtf_to_html(raw))
                elif suffix in ('.html','.htm'):
                    self.editor.setHtml(raw.decode('utf-8-sig'))
                elif suffix=='.odt':
                    self.editor.setHtml(odt_to_html(raw))
                else:
                    if raw.startswith(b'\xff\xfe'): txt=raw[2:].decode('utf-16-le')
                    elif raw.startswith(b'\xfe\xff'):txt=raw[2:].decode('utf-16-be')
                    else:txt=raw.decode('utf-8-sig')
                    self.editor.setPlainText(txt)
                self.file_path=path
                self._images.clear()
                self._confirmed=False
                self.editor.document().setModified(False)
                self.update_title()
                return True
            except (OSError,UnicodeError,ValueError) as exc:
                QMessageBox.critical(self,'WordPad',f'Could not open file:\n{exc}')
                return False

        def save_document(self):
            if not self.file_path:return self.save_as()
            try:
                suffix=Path(self.file_path).suffix.lower()
                if suffix=='.rtf':
                    if self._images:
                        choice=QMessageBox.warning(self,'WordPad',
                            'RTF export supports text formatting but not embedded pictures. '
                            'Save as HTML to preserve pictures, or continue without them?',
                            QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel)
                        if choice!=QMessageBox.Save:return False
                    data=document_to_rtf(self.editor.document())
                elif suffix in ('.html','.htm'):
                    content=self.editor.toHtml()
                    for tag,(mime,raw) in self._images.items():
                        content=content.replace('src="'+tag+'"',
                            'src="data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')+'"')
                    data=content.encode('utf-8')
                elif suffix=='.txt':data=self.editor.toPlainText().encode('utf-8')
                elif suffix=='.odt':
                    # Qt5 supports ODF export but no native ODF reader.
                    fmt=QTextDocumentWriter.supportedDocumentFormats()
                    if b'ODF' not in [bytes(item).upper() for item in fmt]:
                        raise ValueError('ODT export is unavailable in this Qt build')
                    bridge=getattr(self,'remote_files',None)
                    if bridge is not None:
                        from PyQt5.QtCore import QBuffer,QIODevice
                        output=QBuffer()
                        output.open(QIODevice.WriteOnly)
                        writer=QTextDocumentWriter(output,b'ODF')
                        if not writer.write(self.editor.document()):
                            raise OSError('ODT export failed')
                        bridge.write_bytes(self.file_path,bytes(output.data()))
                    else:
                        writer=QTextDocumentWriter(self.file_path,b'ODF')
                        if not writer.write(self.editor.document()):
                            raise OSError('ODT export failed')
                    self.editor.document().setModified(False)
                    self.update_title()
                    return True
                else:raise ValueError('Choose .rtf, .html, .odt or .txt')
                bridge=getattr(self,'remote_files',None)
                if bridge is not None:
                    bridge.write_bytes(self.file_path,data)
                else:
                    atomic_save(self.file_path,data)
                self.editor.document().setModified(False)
                self.update_title()
                return True
            except (OSError,UnicodeError,ValueError) as exc:
                QMessageBox.critical(self,'WordPad',f'Could not save document:\n{exc}')
                return False

        def save_as(self):
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:
                name=bridge.open_dialog('save',[('Rich Text Format',['*.rtf']), ('HTML Document',['*.html']),
                                                ('Plain Text',['*.txt']), ('OpenDocument Text',['*.odt'])])
                filter_name=['*.rtf','*.html','*.txt','*.odt'][0]
            else:
                name,filter_name=QFileDialog.getSaveFileName(self,'Save As',
                self.file_path or str(Path.home()/'Document.rtf'),
                'Rich Text Format (*.rtf);;HTML Document (*.html);;Plain Text (*.txt);;OpenDocument Text (*.odt)')
            if not name:return False
            if not Path(name).suffix:
                ext=('.rtf' if '*.rtf' in filter_name else '.html' if '*.html' in filter_name
                     else '.odt' if '*.odt' in filter_name else '.txt')
                name+=ext
            old=self.file_path
            self.file_path=name
            if self.save_document():return True
            self.file_path=old
            return False

        def show_find(self):
            dialog=RichFindDialog(self)
            dialog.exec_()

        def find_next(self,needle,flags):
            if not needle:return False
            self.last_find=needle
            if self.editor.find(needle,flags):return True
            cursor=self.editor.textCursor();cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            if self.editor.find(needle,flags):return True
            QMessageBox.information(self,'WordPad',f'Cannot find: {needle}')
            return False

        def print_document(self):
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:
                bridge.print_text(self.editor.toHtml(), 'Print WordPad', rich=True)
                return
            try:
                from PyQt5.QtPrintSupport import QPrinter,QPrintDialog
                printer=QPrinter(QPrinter.HighResolution)
                if QPrintDialog(printer,self).exec_()==QDialog.Accepted:
                    self.editor.document().print_(printer)
            except Exception as exc:
                QMessageBox.warning(self,'WordPad',f'Printing unavailable:\n{exc}')

        def exit_app(self):
            if self._mdi_parent is not None:self._mdi_parent.close()
            else:self.close()

        def about(self):
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:
                bridge.about('About WordPad','PythonBDE WordPad\n(c) 2026 by Jens Kallup - paule32')
                return
            QMessageBox.about(self,'About WordPad',
                'PythonBDE WordPad\nRich text editor (.cpy remote application)\n'
                '(c) 2026 by Jens Kallup - paule32\n'
                'RTF compatibility covers common text and paragraph formatting.')

    return WordPadWidget(parent)
