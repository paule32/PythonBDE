"""PythonBDE Sheets v0.6.0: formula engine, workbook IO and signed transport."""
import io
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

from pythonbde.remote_apps.spreadsheet import (
    Workbook, FormulaFailure, col_index, col_name, cell_address, parse_address,
    import_csv, export_csv, import_xlsx, export_xlsx, shift_formula,
)
from pythonbde.cpy_modules import (
    MODULE_FILES, MODULE_IDS, MODULE_TITLES, MAX_CPY_EVENT_BYTES,
    compiled_module_package, ModuleSigner, verify_and_load,
)
from pythonbde.start_menu import DEFAULT_MENU, validate_menu

class EngineTests(unittest.TestCase):
    def setUp(self): self.w=Workbook()

    def test_coordinates(self):
        for n in range(256):
            self.assertEqual(n,col_index(col_name(n)))
            self.assertEqual((99,n),parse_address(cell_address(99,n)))
        for value in ('A0','0A','XFE1','A4097','A-2'):
            with self.assertRaises(ValueError):parse_address(value)

    def test_numbers_and_operators(self):
        for f,ans in [('=0.1+0.2','0.3'),('=2+3*4','14'),('=(2+3)*4','20'),
                      ('=2^3','8'),('=5/2','2.5'),('=-2+3','1'),
                      ('=5%','0.05'),('=1=1','TRUE'),('=4>5','FALSE')]:
            with self.subTest(f=f):
                self.w.put('A1',f)
                self.assertEqual(ans,str(self.w.value('A1')) if not isinstance(self.w.value('A1'),bool) else str(self.w.value('A1')).upper())

    def test_aggregate_functions(self):
        self.w.put('A1','2');self.w.put('A2','4');self.w.put('A3','hello')
        tests={'SUM(A1:A3)':Decimal(6),'AVERAGE(A1:A3)':Decimal(3),
               'MIN(A1:A2)':Decimal(2),'MAX(A1:A2)':Decimal(4),
               'COUNT(A1:A3)':Decimal(2),'COUNTA(A1:A3)':Decimal(3)}
        for fn,ans in tests.items():
            with self.subTest(fn=fn):
                self.w.put('B1','='+fn)
                self.assertEqual(ans,self.w.value('B1'))

    def test_functions_and_strings(self):
        cases={'IF(2>1,"yes","no")':'yes','LEFT("Hello",2)':'He',
               'RIGHT("Hello",2)':'lo','MID("Hello",2,3)':'ell',
               'LEN("Hello")':Decimal(5),'ROUND(12.345,2)':Decimal('12.34'),
               'ABS(-6)':Decimal(6),'INT(2.9)':Decimal(2),
               'CONCAT("a","b")':'ab','"hello"&" world"':'hello world',
               'NOT(TRUE)':False,'AND(TRUE,TRUE)':True,
               'OR(FALSE,TRUE)':True,
               'IFERROR(1/0,0)':Decimal(0),
               'IF(1=1,5,1/0)':Decimal(5),
               'IF(1=0,1/0,6)':Decimal(6)}
        for expr,expected in cases.items():
            with self.subTest(expr=expr):
                self.w.put('B1','='+expr)
                self.assertEqual(expected,self.w.value('B1'))

    def test_cross_sheet_and_cyclic_formulas(self):
        self.w.add_sheet('Sales Data')
        self.w.put('A1','7')
        self.w.add_sheet('Report')
        self.w.put('A1',"='Sales Data'!A1*2")
        self.assertEqual(Decimal(14),self.w.value('A1'))
        self.w.put('B1','=C1')
        self.w.put('C1','=B1')
        self.assertEqual('#CYCLE!',self.w.value('B1'))

    def test_errors(self):
        for expr,err in [('=1/0','#DIV/0!'),('=FOO(1)','#NAME?'),
                         ('=A99999','#NAME?'),('=1+"hello"','#VALUE!'),
                         ('=SUM(A1:D4000)','#LIMIT!')]:
            with self.subTest(expr=expr):
                self.w.put('B1',expr)
                self.assertEqual(err,self.w.value('B1'))

    def test_relative_absolute_shifts(self):
        self.assertEqual('=B2+$C$4+D$7+$E10',shift_formula('=A1+$C$4+C$7+$E9',1,1))
        self.assertEqual('=SUM(B2:B5)',shift_formula('=SUM(A1:A4)',1,1))
        self.assertEqual('="A1"&B2',shift_formula('="A1"&A1',1,1))

    def test_worksheets_and_rename(self):
        self.w.add_sheet('Data')
        self.w.put('A1','12')
        self.w.add_sheet('Result')
        self.w.put('A1','=Data!A1')
        self.w.rename_sheet('Data','Items')
        self.assertEqual(Decimal(12),self.w.value('A1'))
        with self.assertRaises(ValueError):self.w.add_sheet('Items')
        self.w.delete_sheet('Items')
        self.assertEqual('#REF!',self.w.value('A1'))

    def test_json_roundtrip(self):
        self.w.put('A1','=SUM(2,5)',fmt={'bold':True,'foreground':'#FF0000'})
        self.w.add_sheet('Second')
        other=Workbook.from_json(self.w.to_json())
        self.assertEqual(2,len(other.sheets))
        self.assertEqual('=SUM(2,5)',other.sheet('Sheet1').raw('A1'))
        self.assertTrue(other.sheet('Sheet1').style('A1')['bold'])
        with self.assertRaises(ValueError):Workbook.from_json(b'{}')

    def test_csv(self):
        w=import_csv(b'Name,Price\r\nAlpha,12.50\r\nBeta,5\r\n')
        self.assertEqual('Alpha',w.sheet().raw('A2'))
        self.assertIn(b'Beta,5',export_csv(w))
        w=import_csv(b'A\tB\n1\t2\n','\t')
        self.assertEqual('2',w.sheet().raw('B2'))

    def test_xlsx(self):
        self.w.put('A1','12')
        self.w.put('A2','14')
        self.w.put('A3','=SUM(A1:A2)')
        self.w.put('B1','Product & Sales')
        self.w.put('C1',"'00123")
        self.w.add_sheet('Costs')
        self.w.put('A1','10')
        binary=export_xlsx(self.w)
        with zipfile.ZipFile(io.BytesIO(binary)) as z:
            self.assertIn('xl/worksheets/sheet1.xml',z.namelist())
        back=import_xlsx(binary)
        self.assertEqual(2,len(back.sheets))
        self.assertEqual('=SUM(A1:A2)',back.sheet('Sheet1').raw('A3'))
        self.assertEqual(Decimal(26),back.value('A3','Sheet1'))
        self.assertEqual('Product & Sales',back.sheet('Sheet1').raw('B1'))
        self.assertEqual("'00123",back.sheet('Sheet1').raw('C1'))
        with self.assertRaises((ValueError,zipfile.BadZipFile)):
            import_xlsx(b'bad')

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):self.w.add_sheet('A/B')
        with self.assertRaises(ValueError):self.w.put('A1','X'*8193)
        with self.assertRaises(ValueError):self.w.put('BAA1','X')

class RemoteIntegrationTests(unittest.TestCase):
    def test_menu_and_file(self):
        self.assertIn('spreadsheet',MODULE_IDS)
        self.assertEqual('spreadsheet.py',MODULE_FILES['spreadsheet'])
        self.assertEqual('PythonBDE Sheets',MODULE_TITLES['spreadsheet'])
        validate_menu(DEFAULT_MENU)
        items=DEFAULT_MENU[0]['children'][0]['children']
        self.assertEqual(1,sum(i['id']=='spreadsheet' for i in items))

    def test_signed_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            signer=ModuleSigner(Path(temp)/'users.dbf')
            event=signer.event('spreadsheet','session-1','request-1')
            self.assertLess(len(json.dumps(event).encode()),MAX_CPY_EVENT_BYTES)
            manifest,module=verify_and_load(event,signer.public_path)
            self.assertEqual('spreadsheet',manifest['id'])
            self.assertTrue(callable(module.create_widget))
            book=module.Workbook(); book.put('A1','=1+2'); self.assertEqual(Decimal(3),book.value('A1'))

    def test_remote_vfs_contract(self):
        src=Path(__file__).resolve().parents[1].joinpath('pythonbde/remote_apps/spreadsheet.py').read_text()
        for marker in ('remote_files','bridge.open_dialog','bridge.read_bytes','bridge.write_bytes',
                       'QTableWidget','QTabBar','QMenuBar','FormulaParser','QMdiSubWindow'):
            self.assertIn(marker,src)
        self.assertNotIn('QFileDialog.get',src)

if __name__=='__main__':unittest.main()
