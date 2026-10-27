"""Notepad and WordPad remote .cpy regression tests (GUI needs native Qt)."""
import base64
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from pythonbde.cpy_modules import MODULE_IDS, MODULE_FILES, MODULE_TITLES, ModuleSigner, compiled_module_package, verify_and_load
from pythonbde.start_menu import DEFAULT_MENU, validate_menu

ROOT = Path(__file__).resolve().parents[1]


def load_source(module):
    filename = ROOT / 'pythonbde' / 'remote_apps' / f'{module}.py'
    spec = importlib.util.spec_from_file_location('pythonbde_'+module+'_tests', filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


notepad = load_source('notepad')
wordpad = load_source('wordpad')


class NotepadCodecTests(unittest.TestCase):
    def test_utf8_and_bom_round_trip(self):
        for encoding, expected in [('utf-8', b'hello'), ('utf-8-sig', b'\xef\xbb\xbf'),
                                   ('utf-16-le', b'\xff\xfe'), ('utf-16-be', b'\xfe\xff')]:
            with self.subTest(encoding=encoding):
                blob = notepad.encode_text('hello\nÜnicode', encoding, '\r\n')
                self.assertTrue(blob.startswith(expected))
                text, recovered, newline = notepad.decode_text(blob)
                self.assertEqual(encoding, recovered)
                self.assertEqual('\r\n', newline)
                self.assertEqual('hello\r\nÜnicode', text)

    def test_cp1252_fallback_and_line_endings(self):
        text, encoding, newline = notepad.decode_text('Öffnen\rText'.encode('cp1252'))
        self.assertEqual(('Öffnen\rText','cp1252','\r'), (text, encoding, newline))
        self.assertEqual('Öffnen\rText'.encode('cp1252'), notepad.encode_text(text,encoding,newline))

    def test_atomic_save_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'file.txt'
            notepad.atomic_save(path,b'hello')
            notepad.atomic_save(path,b'world')
            self.assertEqual(b'world', path.read_bytes())
            with self.assertRaises(ValueError):notepad.atomic_save(path,b'X'*(notepad.MAX_TEXT_BYTES+10))
            self.assertEqual(b'world',path.read_bytes())


class WordPadFormatTests(unittest.TestCase):
    def test_rtf_escape_unicode_and_control_chars(self):
        escaped = wordpad.rtf_escape('Grüße {me} \\ 😀')
        self.assertIn('\\u252?', escaped)
        self.assertIn('\\{me\\}', escaped)
        self.assertIn('\\\\',escaped)
        self.assertIn('\\u-10179?\\u-8704?', escaped)

    def test_rtf_import_alignment_bold_color_and_paragraphs(self):
        source = b'{\\rtf1\\ansi{\\fonttbl{\\f0\\fnil Arial;}}{\\colortbl ;\\red255\\green0\\blue0;}' \
                 b'\\pard\\qc {\\b1\\fs28\\cf1 Hello}\\par ' \
                 b'\\pard\\ql World\\par}'
        output = wordpad.rtf_to_html(source)
        self.assertIn('text-align:center',output)
        self.assertIn('font-weight:bold',output)
        self.assertIn('color:#ff0000',output)
        self.assertIn('Hello',output)
        self.assertIn('World',output)
        self.assertNotIn('fonttbl',output)

    def test_rtf_escapes_and_unknown_binary_groups(self):
        source = b'{\\rtf1\\ansi{\\pict\\pngblip AAAA} A \\u228? \\{text\\}\\par}'
        output = wordpad.rtf_to_html(source)
        self.assertIn('A ä {text}',output)
        self.assertNotIn('AAAA',output)

    def test_rtf_not_rtf_or_oversize_rejected(self):
        with self.assertRaises(ValueError):wordpad.rtf_to_html(b'not rtf')
        with self.assertRaises(ValueError):wordpad.rtf_to_html(b'Z'*(wordpad.MAX_DOCUMENT_BYTES+1))

    def test_odt_basic_text_and_invalid_package(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('content.xml', '<office:document-content '
                'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
                '<office:body><office:text><text:p>Hallo &amp; Welt</text:p>'
                '<text:p>Absatz 2</text:p></office:text></office:body></office:document-content>')
        output = wordpad.odt_to_html(buffer.getvalue())
        self.assertIn('Hallo &amp; Welt', output)
        self.assertIn('Absatz 2', output)
        with self.assertRaises((zipfile.BadZipFile,ValueError)):
            wordpad.odt_to_html(b'not a zip')


class SignedEditorIntegration(unittest.TestCase):
    def test_module_mapping_and_start_menu(self):
        for name in ('notepad','wordpad'):
            self.assertIn(name,MODULE_IDS)
            self.assertEqual(name+'.py',MODULE_FILES[name])
            self.assertEqual({'notepad':'Notepad','wordpad':'WordPad'}[name],MODULE_TITLES[name])
        items = validate_menu(DEFAULT_MENU)
        accessories = items[0]['children'][0]['children']
        self.assertEqual(1, sum(i['id']=='notepad' for i in accessories))
        self.assertEqual(1, sum(i['id']=='wordpad' for i in accessories))

    def test_published_modules_signed_and_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            signer = ModuleSigner(Path(tmp)/'users.dbf')
            for name in ('notepad','wordpad'):
                with self.subTest(module=name):
                    packet = signer.event(name,'session-7','req-1')
                    manifest, module = verify_and_load(packet,signer.public_path)
                    self.assertEqual(name,manifest['id'])
                    self.assertTrue(callable(module.create_widget))
                    self.assertLess(len(compiled_module_package(name)), 32*1024)

    def test_gui_controls_are_present(self):
        notepad_src=(ROOT/'pythonbde/remote_apps/notepad.py').read_text('utf8')
        wordpad_src=(ROOT/'pythonbde/remote_apps/wordpad.py').read_text('utf8')
        for label in ('New','Open...','Save As...','Print...','Find...', 'Replace...', 'Word Wrap', 'QPlainTextEdit'):
            self.assertIn(label,notepad_src)
        for label in ('QTextEdit','QFontComboBox','QSpinBox','QColorDialog', 'Bulleted List',
                      'Numbered List','WordPad', 'insert_picture','document_to_rtf'):
            self.assertIn(label,wordpad_src)


if __name__=='__main__':unittest.main()
