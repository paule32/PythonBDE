"""Pure arithmetic + signed module transport tests for the Calculator v0.5.4."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from pythonbde.cpy_modules import (
    MAX_CPY_BYTES, MAX_CPY_MEMBER_BYTES, MODULE_IDS,
    ModuleSigner, compiled_module_package, verify_and_load,
)

ROOT = Path(__file__).resolve().parents[1]
CALC_SOURCE = ROOT / 'pythonbde' / 'remote_apps' / 'calculator.py'
spec = importlib.util.spec_from_file_location('calculator_test_module', CALC_SOURCE)
calculator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calculator)
CalculatorEngine = calculator.CalculatorEngine


def sequence(*keys, mode='standard'):
    engine = CalculatorEngine()
    engine.set_mode(mode)
    for key in keys:
        engine.press(key)
    return engine


class CalculatorCore(unittest.TestCase):
    def test_precise_decimal_arithmetic(self):
        e = sequence('0','.','1','+','0','.','2','=')
        self.assertEqual('0.3', e.display_text())
        self.assertEqual(None, e.error)

    def test_chain_and_repeat_equals(self):
        e = sequence('2','+','3','=','=', '=')
        self.assertEqual('11', e.display_text())
        self.assertEqual(3, len(e.history))
        chained = sequence('2','+','3','*','4','=')
        self.assertEqual('20', chained.display_text())

    def test_clear_entry_all_clear_backspace(self):
        e = sequence('1','2','Back','3')
        self.assertEqual('13', e.display_text())
        e.press('CE')
        self.assertEqual('0', e.display_text())
        e.press('5')
        e.press('C')
        self.assertEqual('0', e.display_text())
        self.assertIsNone(e.pending)

    def test_memory_mr_mc_and_subtract(self):
        e = sequence('2','5','MS','C','MR')
        self.assertEqual('25',e.display_text())
        self.assertTrue(e.memory_set)
        e.press('5');e.press('M-');e.press('MR')
        self.assertEqual('20',e.display_text())
        e.press('MC')
        self.assertFalse(e.memory_set)

    def test_percent_addition_and_unary(self):
        self.assertEqual('220', sequence('2','0','0','+','1','0','%','=').display_text())
        self.assertEqual('0.25', sequence('2','5','%').display_text())

    def test_errors_and_recovery(self):
        e = sequence('8','/','0','=')
        self.assertIn('Division by zero',e.display_text())
        e.press('4')
        self.assertEqual('4', e.display_text())
        e.press('±')
        e.press('sqrt')
        self.assertIn('Invalid input',e.display_text())
        e.press('C')
        self.assertEqual('0',e.display_text())

    def test_scientific_functions(self):
        e = sequence('9','sqrt', mode='scientific')
        self.assertEqual('3',e.display_text())
        e = sequence('5','n!', mode='scientific')
        self.assertEqual('120',e.display_text())
        e = sequence('1','0','0','log', mode='scientific')
        self.assertEqual('2',e.display_text())
        e = sequence('2','^','8','=', mode='scientific')
        self.assertEqual('256',e.display_text())
        e = sequence('9','0','sin', mode='scientific')
        self.assertAlmostEqual(1,float(e.display_text()),places=12)
        e = sequence('1','asin', mode='scientific')
        self.assertAlmostEqual(90,float(e.display_text()),places=12)
        e = CalculatorEngine()
        e.set_mode('scientific');e.set_angle_mode('RAD')
        self.assertEqual('0',e.press('sin'))

    def test_programmer_hex_and_bitwise_word_width(self):
        e = CalculatorEngine()
        e.set_mode('programmer')
        e.set_word_bits(8)
        e.set_radix(16)
        for key in ('F','F','and','0','F','='):
            e.press(key)
        self.assertEqual('F',e.display_text())
        e.set_radix(10)
        self.assertEqual('15',e.display_text())
        e.press('C')  # C in programmer HEX is a digit, not clear.
        self.assertEqual('15',e.display_text())  # DEC rejects hex digits
        e.set_radix(16)
        e.press('C')
        self.assertEqual('C',e.display_text())
        e.press('AC')
        self.assertEqual('0',e.display_text())
        e.press('F');e.press('F');e.set_radix(10)
        self.assertEqual('-1',e.display_text())

    def test_programmer_shift_and_not(self):
        e = sequence('1','<<','3','=',mode='programmer')
        self.assertEqual('8', e.display_text())
        e.press('not')
        self.assertEqual('-9',e.display_text())
        e = sequence('1','<<','9','9','=',mode='programmer')
        self.assertIn('Shift',e.display_text())

    def test_paste_rejects_non_numbers_and_non_finite(self):
        e = CalculatorEngine()
        for text in ('__import__("os")', '1+2', 'NaN', 'Infinity', '1'*101, '1e99999999'):
            with self.subTest(text=text), self.assertRaises(calculator.CalculatorError):
                e.input_text(text)
        e.input_text('1,25')
        self.assertEqual('1.25',e.display_text())

    def test_history_is_bounded(self):
        e = CalculatorEngine()
        for i in range(120):
            e.press('1');e.press('+');e.press('2');e.press('=')
        self.assertEqual(100,len(e.history))
        self.assertTrue(all(len(x)==2 for x in e.history))


class CalculatorRemotePackaging(unittest.TestCase):
    def test_calculator_is_allowlisted(self):
        self.assertIn('calculator',MODULE_IDS)

    def test_compiled_bytecode_fits_split_limits(self):
        raw = compiled_module_package('calculator')
        self.assertLess(len(raw),MAX_CPY_BYTES)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertLess(sum(i.file_size for i in archive.infolist()),MAX_CPY_MEMBER_BYTES)
            self.assertGreater(archive.getinfo('module.pyc').file_size,32*1024)

    def test_sign_verify_and_run_pure_engine_without_pyqt(self):
        with tempfile.TemporaryDirectory() as temp:
            signer = ModuleSigner(Path(temp) / 'users.dbf')
            packet = signer.event('calculator','client-7','m123')
            manifest, mod = verify_and_load(packet, signer.public_path)
            self.assertEqual('Calculator', manifest['title'])
            self.assertEqual('7', mod.CalculatorEngine().press('7'))
            self.assertTrue(callable(mod.create_widget))

    def test_uncompressed_zip_member_limit_remains_enforced(self):
        from pythonbde.cpy_modules import _signature_input
        import base64
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            signer = ModuleSigner(Path(temp) / 'users.dbf')
            pkt = signer.event('calculator','client-7','m1')
            original = base64.b64decode(pkt['cpy'])
            with zipfile.ZipFile(io.BytesIO(original)) as archive:
                manifest = archive.read('manifest.json')
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json',manifest)
                archive.writestr('module.pyc',b'X'*(MAX_CPY_MEMBER_BYTES+1))
            raw=buf.getvalue()
            pkt['cpy']=base64.b64encode(raw).decode()
            pkt['sha256']=hashlib.sha256(raw).hexdigest()
            pkt['signature']=base64.b64encode(signer.private_key.sign(
                _signature_input('calculator','client-7','m1',raw))).decode()
            with self.assertRaisesRegex(ValueError, 'member size'):
                verify_and_load(pkt,signer.public_path)

    def test_gui_factory_provides_standard_scientific_programmer_and_history(self):
        source = CALC_SOURCE.read_text('utf8')
        for name in ('QMenuBar', 'QGridLayout', 'QStackedWidget', 'QPlainTextEdit',
                     'QShortcut', 'copy_result', 'paste_result', 'set_mode',
                     'set_radix', 'set_angle', "'Scientific'", "'Programmer'", 'MC', 'sqrt'):
            with self.subTest(name=name):
                self.assertIn(name, source)


if __name__ == '__main__':
    unittest.main()
