"""PythonBDE Sheets -- Excel-like, signed remote .cpy application.

One-file module by design: published as signed CPython bytecode by cpy_modules.
Pure-Python workbook/formula engine; Qt5 is imported only by create_widget().
Remote files are accessed via the session-bound RemoteFiles bridge, never local
QFileDialog when running inside the RPC desktop.

Supported: arithmetic/comparison/text formulas, ranges/functions, multiple
sheets, formats, CSV/TSV, basic XLSX round trip. It is not Excel itself.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

MAX_ROWS = 4096
MAX_COLS = 256
MAX_CELLS = 80000
MAX_RANGE = 10000
MAX_SHEETS = 32
MAX_XLSX_BYTES = 16 * 1024 * 1024
ERRORS = {'#REF!', '#DIV/0!', '#VALUE!', '#NAME?', '#NUM!', '#CYCLE!', '#LIMIT!', '#N/A'}
CELL_RE = re.compile(r'^\$?([A-Za-z]{1,3})\$?([1-9]\d{0,6})$')
REF_RE = re.compile(r'(\$?)([A-Za-z]{1,3})(\$?)([1-9]\d{0,6})')
SHEET_RE = re.compile(r'^[^\\/*?:\[\]]{1,31}$')
XML_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
XML_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def col_name(index):
    if not isinstance(index, int) or index < 0 or index >= MAX_COLS:
        raise ValueError('Invalid column index')
    s = ''
    while index >= 0:
        index, rem = divmod(index, 26)
        s = chr(65 + rem) + s
        index -= 1
    return s


def col_index(name):
    value = 0
    for ch in name.upper():
        if ch < 'A' or ch > 'Z':
            raise ValueError('Invalid column')
        value = value * 26 + (ord(ch) - 64)
    if not 1 <= value <= MAX_COLS:
        raise ValueError('Column outside supported range')
    return value - 1


def parse_address(address):
    match = CELL_RE.fullmatch(str(address).strip())
    if not match:
        raise ValueError('Invalid cell address')
    row = int(match.group(2)) - 1
    if row >= MAX_ROWS:
        raise ValueError('Row outside supported range')
    return row, col_index(match.group(1))


def cell_address(row, col):
    if not 0 <= row < MAX_ROWS:
        raise ValueError('Row outside supported range')
    return f'{col_name(col)}{row+1}'


def shift_formula(formula, row_delta, col_delta):
    """Excel-style formula fill: shift relative references, preserve $ locks.

    Strings and sheet-name quoted literals are skipped; a token boundary stops
    replacing e.g. function identifiers containing digits.
    """
    if not isinstance(formula, str) or not formula.startswith('='):
        return formula
    pattern = re.compile(r'(?<![A-Za-z0-9_.])(\$?)([A-Za-z]{1,3})(\$?)([1-9]\d{0,6})(?![A-Za-z0-9_.])')
    result = []
    pos = 0
    in_string = False
    while pos < len(formula):
        ch = formula[pos]
        if ch == '"':
            if in_string and pos+1 < len(formula) and formula[pos+1] == '"':
                result.append('""'); pos += 2; continue
            in_string = not in_string
            result.append(ch); pos += 1; continue
        if in_string:
            result.append(ch); pos += 1; continue
        match = pattern.match(formula, pos)
        if not match:
            result.append(ch); pos += 1; continue
        try:
            new_col = col_index(match.group(2)) + (0 if match.group(1) else col_delta)
            new_row = int(match.group(4))-1 + (0 if match.group(3) else row_delta)
            replacement = f'{match.group(1)}{col_name(new_col)}{match.group(3)}{new_row+1}'
            if new_row < 0 or new_row >= MAX_ROWS: replacement = '#REF!'
        except ValueError:
            replacement = '#REF!'
        result.append(replacement)
        pos = match.end()
    return ''.join(result)


class FormulaFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def as_number(x):
    if x is None or x == '': return Decimal(0)
    if isinstance(x, bool): return Decimal(int(x))
    if isinstance(x, Decimal): return x
    if isinstance(x, (int, float)):
        if isinstance(x, float) and not math.isfinite(x): raise FormulaFailure('#NUM!')
        return Decimal(str(x))
    if isinstance(x, str) and x.startswith('#') and x in ERRORS:
        raise FormulaFailure(x)
    try:
        return Decimal(str(x).strip())
    except (InvalidOperation, ValueError):
        raise FormulaFailure('#VALUE!')


def display_value(value):
    if value is None: return ''
    if isinstance(value, bool): return 'TRUE' if value else 'FALSE'
    if isinstance(value, Decimal):
        if not value.is_finite(): return '#NUM!'
        return format(value.normalize(), 'f') if value != 0 else '0'
    return str(value)


class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}   # A1 -> {'v': text, 'fmt': dict}
        self.widths = {}

    def put(self, address, raw, fmt=None):
        address = address.upper().replace('$', '')
        parse_address(address)
        if raw is None: raw = ''
        raw = str(raw)
        if len(raw) > 8192: raise ValueError('Cell content is too long')
        existing = self.cells.get(address, {})
        formatting = copy.deepcopy(fmt if fmt is not None else existing.get('fmt', {}))
        if raw == '' and not formatting:
            self.cells.pop(address, None)
        else:
            self.cells[address] = {'v': raw, 'fmt': formatting}

    def raw(self, address):
        return self.cells.get(address.upper().replace('$', ''), {}).get('v', '')

    def style(self, address):
        return self.cells.get(address.upper().replace('$', ''), {}).get('fmt', {})


class Workbook:
    """Sparse spreadsheet with a bounded, recursion-safe recalculation engine."""
    def __init__(self):
        self.sheets = [Sheet('Sheet1')]
        self.active = 0

    def sheet(self, name=None):
        if name is None: return self.sheets[self.active]
        for sheet in self.sheets:
            if sheet.name.casefold() == str(name).casefold(): return sheet
        raise FormulaFailure('#REF!')

    def add_sheet(self, name=None):
        if len(self.sheets) >= MAX_SHEETS: raise ValueError('Too many sheets')
        if name is None:
            n = 1
            while any(s.name.casefold() == f'Sheet{n}'.casefold() for s in self.sheets): n += 1
            name = f'Sheet{n}'
        self._check_sheet_name(name)
        sheet = Sheet(name)
        self.sheets.append(sheet)
        self.active = len(self.sheets) - 1
        return sheet

    def _check_sheet_name(self, name, except_sheet=None):
        if not isinstance(name, str) or not SHEET_RE.fullmatch(name) or name.startswith("'") or name.endswith("'"):
            raise ValueError('Invalid sheet name')
        if any(s is not except_sheet and s.name.casefold() == name.casefold() for s in self.sheets):
            raise ValueError('Sheet name already exists')

    def rename_sheet(self, old, new):
        target = self.sheet(old)
        self._check_sheet_name(new, target)
        target.name = new
        # Update formula references for direct quoted/unquoted sheet references.
        old_token = f"'{old.replace(chr(39), chr(39)*2)}'!"
        new_token = f"'{new.replace(chr(39), chr(39)*2)}'!"
        for sh in self.sheets:
            for item in sh.cells.values():
                if item['v'].startswith('='):
                    item['v'] = re.sub(re.escape(old_token), lambda _: new_token, item['v'], flags=re.I)
                    item['v'] = re.sub(r'(?<![A-Za-z0-9_])'+re.escape(old)+r'!', lambda _: new_token, item['v'], flags=re.I)

    def delete_sheet(self, name):
        if len(self.sheets) <= 1: raise ValueError('Workbook requires at least one sheet')
        idx = self.sheets.index(self.sheet(name))
        self.sheets.pop(idx)
        self.active = min(self.active, len(self.sheets)-1)

    def put(self, address, raw, sheet=None, fmt=None):
        target = self.sheet(sheet)
        if address.upper() not in target.cells and sum(len(s.cells) for s in self.sheets) >= MAX_CELLS:
            raise ValueError('Workbook cell limit exceeded')
        target.put(address, raw, fmt)

    def value(self, address, sheet=None):
        cache = {}
        try:
            return self._value(self.sheet(sheet), address, set(), cache)
        except FormulaFailure as exc:
            return exc.code

    def _value(self, sheet, address, visiting, cache):
        address = address.upper().replace('$', '')
        try: parse_address(address)
        except ValueError: raise FormulaFailure('#REF!')
        key = (sheet.name.casefold(), address)
        if key in cache: return cache[key]
        if key in visiting: raise FormulaFailure('#CYCLE!')
        if len(visiting) >= 150: raise FormulaFailure('#LIMIT!')
        visiting.add(key)
        try:
            raw = sheet.raw(address)
            if raw.startswith('='):
                result = FormulaParser(self, sheet, raw[1:], visiting, cache).parse()
            elif raw.startswith("'"):
                result = raw[1:]
            elif not raw:
                result = None
            elif raw.upper() in ('TRUE', 'FALSE'):
                result = raw.upper() == 'TRUE'
            else:
                try: result = Decimal(raw.strip())
                except InvalidOperation: result = raw
            cache[key] = result
            return result
        finally:
            visiting.remove(key)

    def evaluated(self, sheet=None):
        target = self.sheet(sheet)
        cache = {}
        result = {}
        for address in target.cells:
            try: result[address] = self._value(target, address, set(), cache)
            except FormulaFailure as exc: result[address] = exc.code
        return result

    def serialize(self):
        return {'format': 'pythonbde-sheets/1', 'active': self.active,
                'sheets': [{'name': s.name, 'cells': s.cells, 'widths': s.widths} for s in self.sheets]}

    def to_json(self):
        return json.dumps(self.serialize(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    @classmethod
    def from_json(cls, data):
        payload = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
        if not isinstance(payload, dict) or payload.get('format') != 'pythonbde-sheets/1':
            raise ValueError('Unsupported workbook format')
        entries = payload.get('sheets')
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_SHEETS:
            raise ValueError('Invalid worksheet list')
        w = cls(); w.sheets = []
        for obj in entries:
            if not isinstance(obj, dict): raise ValueError('Invalid sheet')
            w._check_sheet_name(obj.get('name'))
            s = w.add_sheet(obj['name'])
            cells = obj.get('cells', {})
            if not isinstance(cells, dict) or len(cells) > MAX_CELLS:
                raise ValueError('Invalid cells')
            for address, record in cells.items():
                if not isinstance(record, dict) or not isinstance(record.get('v'), str):
                    raise ValueError('Invalid cell entry')
                style = record.get('fmt', {})
                if not isinstance(style, dict): raise ValueError('Invalid cell formatting')
                w.put(address, record['v'], s.name, style)
            widths = obj.get('widths', {})
            if isinstance(widths, dict):
                s.widths = {str(k): max(30, min(500, int(v))) for k, v in widths.items() if str(k).isdigit()}
        w.active = max(0, min(int(payload.get('active', 0)), len(w.sheets)-1))
        return w


TOKEN = re.compile(r'''\s*(?:(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)|(?P<text>"(?:[^"]|"")*")|(?P<quoted>'(?:[^']|'')*')|(?P<symbol><=|>=|<>|[+*/^&=<>(),;:!%\-])|(?P<word>\$?[A-Za-z_][\w.$]*))''')


class FormulaParser:
    """Recursive-descent grammar, no eval/exec, bounded recursion and ranges."""
    def __init__(self, workbook, sheet, expression, visiting, cache):
        self.wb = workbook; self.sheet = sheet
        self.visiting = visiting; self.cache = cache
        self.tokens = []
        at = 0
        if len(expression) > 8192: raise FormulaFailure('#LIMIT!')
        while at < len(expression):
            match = TOKEN.match(expression, at)
            if not match: raise FormulaFailure('#NAME?')
            kind = match.lastgroup
            self.tokens.append((kind, match.group(kind)))
            at = match.end()
            if len(self.tokens) > 1000: raise FormulaFailure('#LIMIT!')
        self.tokens.append(('eof', ''))
        self.pos = 0
        self.depth = 0

    def peek(self): return self.tokens[self.pos][1]
    def kind(self): return self.tokens[self.pos][0]
    def consume(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token[1]
    def accept(self, symbol):
        if self.peek() == symbol:
            self.consume(); return True
        return False
    def expect(self, symbol):
        if not self.accept(symbol): raise FormulaFailure('#VALUE!')

    def parse(self):
        out = self.comparison()
        if self.kind() != 'eof': raise FormulaFailure('#VALUE!')
        if isinstance(out, RangeValues): raise FormulaFailure('#VALUE!')
        return out

    def comparison(self):
        a = self.concat()
        while self.peek() in ('=', '<>', '<', '>', '<=', '>='):
            op = self.consume(); b = self.concat()
            if isinstance(a, RangeValues) or isinstance(b, RangeValues): raise FormulaFailure('#VALUE!')
            try: a1, b1 = as_number(a), as_number(b)
            except FormulaFailure:
                a1, b1 = display_value(a).lower(), display_value(b).lower()
            a = {'=':a1==b1,'<>':a1!=b1,'<':a1<b1,'>':a1>b1,'<=':a1<=b1,'>=':a1>=b1}[op]
        return a

    def concat(self):
        a = self.add()
        while self.accept('&'):
            b = self.add()
            a = display_value(a) + display_value(b)
        return a

    def add(self):
        a = self.mul()
        while self.peek() in ('+', '-'):
            op = self.consume(); b = self.mul()
            a = as_number(a) + as_number(b) if op == '+' else as_number(a) - as_number(b)
        return a

    def mul(self):
        a = self.power()
        while self.peek() in ('*', '/'):
            op = self.consume(); b = self.power()
            a1, b1 = as_number(a), as_number(b)
            if op == '/' and b1 == 0: raise FormulaFailure('#DIV/0!')
            try: a = a1 * b1 if op == '*' else a1 / b1
            except (InvalidOperation, OverflowError): raise FormulaFailure('#NUM!')
        return a

    def power(self):
        a = self.unary()
        if self.accept('^'):
            b = self.power()
            try: a = as_number(a) ** as_number(b)
            except (InvalidOperation, OverflowError, ZeroDivisionError): raise FormulaFailure('#NUM!')
        return a

    def unary(self):
        if self.accept('+'): return as_number(self.unary())
        if self.accept('-'): return -as_number(self.unary())
        a = self.atom()
        if self.accept('%'): return as_number(a) / Decimal(100)
        return a

    def atom(self):
        if self.accept('('):
            self.depth += 1
            if self.depth > 75: raise FormulaFailure('#LIMIT!')
            a = self.comparison(); self.expect(')'); self.depth -= 1
            return a
        kind = self.kind()
        if kind == 'number':
            return Decimal(self.consume())
        if kind == 'text':
            return self.consume()[1:-1].replace('""', '"')
        if kind not in ('word', 'quoted'):
            raise FormulaFailure('#NAME?')
        word = self.consume()
        if word.upper() == 'TRUE': return True
        if word.upper() == 'FALSE': return False
        if self.accept('('):
            args = []
            if not self.accept(')'):
                while True:
                    try:
                        args.append(self.comparison())
                    except FormulaFailure as error:
                        # Defer failures so IF/IFERROR can select a valid branch.
                        args.append(error.code)
                    if self.accept(')'): break
                    if not (self.accept(',') or self.accept(';')): raise FormulaFailure('#VALUE!')
                    if len(args) > 1000: raise FormulaFailure('#LIMIT!')
            return self.function(word.upper(), args)
        target = self.sheet
        if self.accept('!'):
            sheetname = word[1:-1].replace("''", "'") if kind == 'quoted' else word
            target = self.wb.sheet(sheetname)
            if self.kind() != 'word': raise FormulaFailure('#REF!')
            word = self.consume()
        try: r1, c1 = parse_address(word)
        except ValueError: raise FormulaFailure('#NAME?')
        if self.accept(':'):
            if self.kind() != 'word': raise FormulaFailure('#REF!')
            end = self.consume()
            try: r2, c2 = parse_address(end)
            except ValueError: raise FormulaFailure('#REF!')
            if r1 > r2 or c1 > c2: raise FormulaFailure('#REF!')
            if (r2-r1+1)*(c2-c1+1) > MAX_RANGE: raise FormulaFailure('#LIMIT!')
            values = []
            for row in range(r1,r2+1):
                for col in range(c1,c2+1):
                    values.append(self.wb._value(target, cell_address(row,col), self.visiting, self.cache))
            return RangeValues(values)
        return self.wb._value(target, cell_address(r1,c1), self.visiting, self.cache)

    def function(self, name, args):
        values = [v for a in args for v in (a.values if isinstance(a, RangeValues) else [a])]
        if name == 'IFERROR' and len(args) == 2:
            return args[1] if isinstance(args[0], str) and args[0] in ERRORS else args[0]
        if name == 'IF' and len(args) in (2, 3):
            branch = args[1] if bool(args[0]) else (args[2] if len(args)==3 else False)
            if isinstance(branch,str) and branch in ERRORS: raise FormulaFailure(branch)
            return branch
        if any(isinstance(v, str) and v in ERRORS for v in values):
            raise FormulaFailure(next(v for v in values if isinstance(v, str) and v in ERRORS))
        try:
            if name in ('SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT', 'COUNTA'):
                if name == 'COUNTA': return Decimal(sum(v is not None and v != '' for v in values))
                nums = []
                for v in values:
                    if v is None or v == '': continue
                    try: nums.append(as_number(v))
                    except FormulaFailure: continue  # Excel-like aggregate range text semantics
                if name == 'COUNT': return Decimal(len(nums))
                if name == 'SUM': return sum(nums, Decimal(0))
                if not nums: return Decimal(0)
                if name == 'AVERAGE': return sum(nums, Decimal(0)) / len(nums)
                if name == 'MIN': return min(nums)
                if name == 'MAX': return max(nums)
            if name == 'ABS' and len(args)==1: return abs(as_number(args[0]))
            if name == 'ROUND' and len(args) in (1,2):
                digits = int(as_number(args[1])) if len(args)==2 else 0
                if not -20 <= digits <= 20: raise FormulaFailure('#NUM!')
                return as_number(args[0]).quantize(Decimal(10)**(-digits))
            if name == 'INT' and len(args)==1: return as_number(args[0]) // 1
            if name == 'SQRT' and len(args)==1:
                a=as_number(args[0]); return a.sqrt() if a>=0 else '#NUM!'
            if name == 'LEN' and len(args)==1: return Decimal(len(display_value(args[0])))
            if name == 'LEFT' and len(args) in (1,2): return display_value(args[0])[:int(as_number(args[1])) if len(args)==2 else 1]
            if name == 'RIGHT' and len(args) in (1,2):
                n=int(as_number(args[1])) if len(args)==2 else 1
                return display_value(args[0])[-n:] if n>0 else ''
            if name == 'MID' and len(args)==3:
                p=int(as_number(args[1])); n=int(as_number(args[2])); return display_value(args[0])[max(0,p-1):max(0,p-1)+max(0,n)]
            if name in ('CONCAT', 'CONCATENATE'): return ''.join(display_value(v) for v in values)
            if name == 'AND': return all(bool(v) for v in values)
            if name == 'OR': return any(bool(v) for v in values)
            if name == 'NOT' and len(args)==1: return not bool(args[0])
            if name == 'TODAY' and not args: return date.today().isoformat()
            if name == 'NOW' and not args: return datetime.now().isoformat(sep=' ', timespec='seconds')
        except (InvalidOperation, ValueError, OverflowError, ZeroDivisionError, TypeError):
            raise FormulaFailure('#VALUE!')
        raise FormulaFailure('#NAME?')


class RangeValues:
    def __init__(self, values): self.values = values


def import_csv(contents, delimiter=','):
    if isinstance(contents, bytes):
        text = contents.decode('utf-8-sig')
    else: text = contents
    workbook = Workbook()
    for r, values in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
        if r >= MAX_ROWS: raise ValueError('CSV exceeds row limit')
        if len(values) > MAX_COLS: raise ValueError('CSV exceeds column limit')
        for c, raw in enumerate(values):
            if raw: workbook.put(cell_address(r, c), raw)
    return workbook


def export_csv(workbook, delimiter=','):
    sheet = workbook.sheet()
    rows = [parse_address(key) for key in sheet.cells]
    if not rows: return b''
    max_r, max_c = max(r for r,c in rows), max(c for r,c in rows)
    if (max_r+1)*(max_c+1) > MAX_CELLS: raise ValueError('CSV export range too large')
    out=io.StringIO(newline='')
    writer=csv.writer(out,delimiter=delimiter,lineterminator='\r\n')
    for r in range(max_r+1):
        writer.writerow([sheet.raw(cell_address(r,c)) for c in range(max_c+1)])
    return out.getvalue().encode('utf-8-sig')


def export_xlsx(workbook):
    """Small, standards-based OOXML workbook (formulas kept, no macros)."""
    out = io.BytesIO()
    content_types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                     '<Default Extension="xml" ContentType="application/xml"/>',
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    for index in range(len(workbook.sheets)):
        content_types.append(f'<Override PartName="/xl/worksheets/sheet{index+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    content_types.append('</Types>')
    book = [f'<workbook xmlns="{XML_MAIN}" xmlns:r="{XML_REL}"><sheets>']
    book_rels = [f'<Relationships xmlns="{PACKAGE_REL}">']
    for index, sheet in enumerate(workbook.sheets, 1):
        book.append(f'<sheet name="{xml_escape(sheet.name, {chr(34): "&quot;"})}" sheetId="{index}" r:id="rId{index}"/>')
        book_rels.append(f'<Relationship Id="rId{index}" Type="{XML_REL}/worksheet" Target="worksheets/sheet{index}.xml"/>')
    book.append('</sheets><calcPr calcId="0" fullCalcOnLoad="1"/></workbook>')
    book_rels.append(f'<Relationship Id="rIdStyles" Type="{XML_REL}/styles" Target="styles.xml"/>')
    book_rels.append('</Relationships>')
    relationships = (f'<Relationships xmlns="{PACKAGE_REL}"><Relationship Id="rId1" Type="{XML_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    # Styles: default + a basic bold style. More complex formats survive in .pysheet.
    styles = f'''<styleSheet xmlns="{XML_MAIN}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>'''
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('[Content_Types].xml', ''.join(content_types))
        z.writestr('_rels/.rels', relationships)
        z.writestr('xl/workbook.xml', ''.join(book))
        z.writestr('xl/_rels/workbook.xml.rels', ''.join(book_rels))
        z.writestr('xl/styles.xml', styles)
        for idx, sheet in enumerate(workbook.sheets, 1):
            rows = {}
            for addr, cell in sheet.cells.items():
                row, col = parse_address(addr)
                rows.setdefault(row, []).append((col, addr, cell))
            parts = [f'<worksheet xmlns="{XML_MAIN}"><sheetData>']
            for row in sorted(rows):
                parts.append(f'<row r="{row+1}">')
                for col, addr, record in sorted(rows[row]):
                    raw = record['v']; bold = 1 if record.get('fmt', {}).get('bold') else 0
                    attr = f'r="{addr}" s="{bold}"'
                    if raw.startswith('='):
                        parts.append(f'<c {attr}><f>{xml_escape(raw[1:])}</f></c>')
                    elif raw.startswith("'"):
                        val = xml_escape(raw[1:])
                        parts.append(f'<c {attr} t="inlineStr"><is><t>{val}</t></is></c>')
                    else:
                        try: val = Decimal(raw)
                        except InvalidOperation: val = None
                        if val is not None and val.is_finite():
                            parts.append(f'<c {attr}><v>{xml_escape(raw)}</v></c>')
                        else:
                            val = xml_escape(raw)
                            parts.append(f'<c {attr} t="inlineStr"><is><t>{val}</t></is></c>')
                parts.append('</row>')
            parts.append('</sheetData></worksheet>')
            z.writestr(f'xl/worksheets/sheet{idx}.xml', ''.join(parts))
    data = out.getvalue()
    if len(data) > MAX_XLSX_BYTES:
        raise ValueError('Workbook exceeds 16 MiB limit')
    return data


def import_xlsx(data):
    if not isinstance(data, bytes) or len(data)>MAX_XLSX_BYTES:
        raise ValueError('Invalid XLSX size')
    workbook=Workbook()
    workbook.sheets=[]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = z.infolist()
        if len(members)>400 or sum(x.file_size for x in members)>32*1024*1024:
            raise ValueError('XLSX too large')
        if any(x.file_size>16*1024*1024 for x in members):
            raise ValueError('XLSX member too large')
        names=set(z.namelist())
        if 'xl/workbook.xml' not in names:
            raise ValueError('Invalid XLSX: workbook missing')
        root = ET.fromstring(z.read('xl/workbook.xml'))
        ns = {'s': XML_MAIN, 'r': XML_REL}
        rels = {}
        if 'xl/_rels/workbook.xml.rels' in names:
            relroot=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            for elem in relroot:
                rid=elem.attrib.get('Id')
                target=elem.attrib.get('Target','')
                if not target.startswith('/') and '..' not in target.split('/'):
                    rels[rid]='xl/' + target.lstrip('/')
                elif target.startswith('/xl/'):
                    rels[rid]=target.lstrip('/')
        strings=[]
        if 'xl/sharedStrings.xml' in names:
            sroot=ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in sroot.findall(f'{{{XML_MAIN}}}si'):
                strings.append(''.join(elem.text or '' for elem in si.iter(f'{{{XML_MAIN}}}t')))
                if len(strings)>MAX_CELLS: raise ValueError('Too many shared strings')
        nodes=root.find('s:sheets',ns)
        if nodes is None or len(nodes)==0 or len(nodes)>MAX_SHEETS:
            raise ValueError('Invalid XLSX sheet count')
        for idx, item in enumerate(nodes,1):
            name=item.get('name',f'Sheet{idx}')
            workbook._check_sheet_name(name)
            sheet=workbook.add_sheet(name)
            rid=item.get(f'{{{XML_REL}}}id')
            path=rels.get(rid, f'xl/worksheets/sheet{idx}.xml')
            if path not in names: raise ValueError('Missing XLSX worksheet')
            tree=ET.fromstring(z.read(path))
            for node in tree.findall('.//s:sheetData/s:row/s:c',ns):
                addr=node.get('r','')
                try: parse_address(addr)
                except ValueError: continue  # ignore Excel ranges beyond limited editor viewport
                formula=node.find('s:f',ns)
                if formula is not None and formula.text is not None:
                    raw='='+formula.text
                elif node.get('t') == 'inlineStr':
                    raw=''.join(n.text or '' for n in node.findall('.//s:is/s:t',ns))
                else:
                    value=node.find('s:v',ns)
                    raw=value.text if value is not None and value.text is not None else ''
                    if node.get('t')=='s' and raw:
                        try: raw=strings[int(raw)]
                        except (IndexError,ValueError): raise ValueError('Bad XLSX string index')
                    elif node.get('t')=='b': raw='TRUE' if raw=='1' else 'FALSE'
                    elif node.get('t') in ('str','e'): raw = "'"+raw
                # Preserve text-looking numbers (including leading zeros) as text.
                if raw and node.get('t') in ('inlineStr','s','str') and not raw.startswith("'"):
                    try:
                        Decimal(raw.strip())
                        raw = "'" + raw
                    except InvalidOperation:
                        if raw.upper() in ('TRUE','FALSE') or raw.startswith('='):
                            raw = "'" + raw
                if raw: workbook.put(addr,raw,sheet.name)
    workbook.active=0
    return workbook


def create_widget(parent):
    from PyQt5.QtCore import Qt, QEvent, QTimer, QRectF
    from PyQt5.QtGui import QColor, QFont, QBrush, QPen, QKeySequence, QPainter
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QToolBar, QMenuBar,
        QAction, QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
        QTableWidgetItem, QHeaderView, QTabBar, QInputDialog, QMessageBox,
        QFontComboBox, QSpinBox, QStyledItemDelegate, QColorDialog,
        QMdiSubWindow, QDialog, QDialogButtonBox, QTextEdit, QAbstractItemView,
        QFrame, QMenu,
    )

    class RawDelegate(QStyledItemDelegate):
        def __init__(self, table, owner):
            super().__init__(table)
            self.owner = owner

        def setEditorData(self, editor, index):
            if isinstance(editor, QLineEdit):
                if self.owner is not None:
                    editor.setText(self.owner.raw_for_index(index.row(),index.column()))
                    return
            super().setEditorData(editor,index)

    class ChartWidget(QWidget):
        def __init__(self, points, title, parent=None):
            super().__init__(parent)
            self.points = points
            self.title = title
            self.setMinimumSize(300,230)
        def paintEvent(self,event):
            painter = QPainter(self)
            try:
                painter.setRenderHint(QPainter.Antialiasing)
                painter.fillRect(self.rect(), QColor('#FFFFFF'))
                painter.setPen(QColor('#24324B'))
                painter.setFont(QFont('Arial',11,QFont.Bold))
                painter.drawText(20,24,self.title)
                rect = QRectF(55,50,max(60,self.width()-80),max(60,self.height()-100))
                painter.setPen(QPen(QColor('#9BA7B7'),1))
                painter.drawLine(int(rect.left()),int(rect.bottom()),int(rect.right()),int(rect.bottom()))
                painter.drawLine(int(rect.left()),int(rect.top()),int(rect.left()),int(rect.bottom()))
                if not self.points: return
                values=[val for _,val in self.points]
                low=min(0.0,min(values)); high=max(0.0,max(values))
                if high-low<1e-12: high=low+1
                step=rect.width()/len(values)
                for i,(label,val) in enumerate(self.points):
                    bar_left=rect.left()+i*step+max(1,step*.12)
                    zero=rect.bottom() - (0-low)/(high-low)*rect.height()
                    top=rect.bottom() - (val-low)/(high-low)*rect.height()
                    xw=max(2,step*.75)
                    painter.fillRect(QRectF(bar_left,min(top,zero),xw,max(1,abs(zero-top))),QColor('#3278BE'))
                    painter.setPen(QColor('#1D3557'))
                    painter.setFont(QFont('Arial',8))
                    painter.drawText(QRectF(bar_left,rect.bottom()+6,step,25),Qt.AlignLeft,label[:9])
            finally:
                painter.end()

    class SpreadsheetWidget(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.wb = Workbook()
            self.filename = None
            self.dirty = False
            self._loading = False
            self._mdi = None
            self._allow_close = False
            self.undo_stack = []
            self.redo_stack = []
            self.current_find = ''
            self.setMinimumSize(410,300)
            self.setWindowTitle('Book1 - PythonBDE Sheets')
            layout=QVBoxLayout(self)
            layout.setContentsMargins(1,1,1,1)
            layout.setSpacing(1)

            self.menu=QMenuBar(self); self.menu.setNativeMenuBar(False)
            layout.setMenuBar(self.menu)
            mfile=self.menu.addMenu('&File')
            medit=self.menu.addMenu('&Edit')
            mview=self.menu.addMenu('&View')
            minsert=self.menu.addMenu('&Insert')
            mformat=self.menu.addMenu('F&ormat')
            mdata=self.menu.addMenu('&Data')
            mformula=self.menu.addMenu('F&ormulas')
            mhelp=self.menu.addMenu('&Help')

            def action(menu,text,callback,shortcut=None,checkable=False):
                a=QAction(text,self); a.setCheckable(checkable)
                if shortcut: a.setShortcut(QKeySequence(shortcut))
                a.triggered.connect(callback); menu.addAction(a)
                return a
            action(mfile,'New Workbook',self.new_book,'Ctrl+N')
            action(mfile,'Open...',self.open_book,'Ctrl+O')
            action(mfile,'Save',self.save_book,'Ctrl+S')
            action(mfile,'Save As...',self.save_as,'Ctrl+Shift+S')
            mfile.addSeparator()
            action(mfile,'Print Preview',self.preview,'Ctrl+P')
            action(mfile,'Close',self.exit_editor)
            action(medit,'Undo',self.undo,'Ctrl+Z')
            action(medit,'Redo',self.redo,'Ctrl+Y')
            medit.addSeparator()
            action(medit,'Cut',self.cut,'Ctrl+X')
            action(medit,'Copy',self.copy,'Ctrl+C')
            action(medit,'Paste',self.paste,'Ctrl+V')
            action(medit,'Clear Contents',self.clear_cells,'Delete')
            action(medit,'Find...',self.find,'Ctrl+F')
            action(medit,'Go To...',self.goto_dialog,'Ctrl+G')
            action(mview,'Recalculate',self.refresh,'F9')
            action(mview,'Zoom In',lambda:self.set_zoom(1))
            action(mview,'Zoom Out',lambda:self.set_zoom(-1))
            action(minsert,'New Worksheet',self.new_sheet,'Shift+F11')
            action(minsert,'Rename Worksheet',self.rename_sheet)
            action(minsert,'Delete Worksheet',self.delete_sheet)
            action(minsert,'Column Chart from selection',self.chart)
            action(mformat,'Bold',lambda:self.toggle_format('bold'),'Ctrl+B')
            action(mformat,'Italic',lambda:self.toggle_format('italic'),'Ctrl+I')
            action(mformat,'Underline',lambda:self.toggle_format('underline'),'Ctrl+U')
            for label,value in [('General','general'),('Number','number'),('Currency','currency'),('Percent','percent')]:
                action(mformat,'Format as '+label,lambda checked=False,v=value:self.set_number_format(v))
            action(mdata,'Sort selection ascending',lambda:self.sort_selection(False))
            action(mdata,'Sort selection descending',lambda:self.sort_selection(True))
            action(mdata,'Fill Down',self.fill_down,'Ctrl+D')
            action(mdata,'Fill Right',self.fill_right,'Ctrl+R')
            action(mformula,'AutoSum',self.autosum,'Alt+=')
            action(mformula,'Function Reference',self.functions_help)
            action(mhelp,'About PythonBDE Sheets',self.about)

            self.toolbar=QToolBar('Spreadsheet',self)
            self.toolbar.setMovable(False)
            self.toolbar.setIconSize(__import__('PyQt5.QtCore',fromlist=['QSize']).QSize(16,16))
            layout.addWidget(self.toolbar)
            for label,method in [('New',self.new_book),('Open',self.open_book),('Save',self.save_book),
                                 ('Copy',self.copy),('Paste',self.paste),('Undo',self.undo),('Redo',self.redo)]:
                self.toolbar.addAction(label,method)
            self.toolbar.addSeparator()
            self.font_family=QFontComboBox(self)
            self.font_family.setMaximumWidth(150)
            self.font_family.setCurrentFont(QFont('Arial'))
            self.toolbar.addWidget(self.font_family)
            self.font_family.currentFontChanged.connect(lambda font:self.set_format('family',font.family()))
            self.font_size=QSpinBox(self); self.font_size.setRange(6,48); self.font_size.setValue(10)
            self.font_size.setMaximumWidth(58)
            self.toolbar.addWidget(self.font_size)
            self.font_size.valueChanged.connect(lambda n:self.set_format('size',n))
            self.toolbar.addSeparator()
            for text,method in [('B',lambda:self.toggle_format('bold')),
                                ('I',lambda:self.toggle_format('italic')),
                                ('U',lambda:self.toggle_format('underline')),
                                ('◀',lambda:self.set_format('align','left')),
                                ('≡',lambda:self.set_format('align','center')),
                                ('▶',lambda:self.set_format('align','right')),
                                ('Fill',self.background_color),('A',self.foreground_color),
                                ('Σ',self.autosum)]:
                self.toolbar.addAction(text,method)
            self.toolbar.addSeparator()
            self.style_combo=QComboBox(self)
            for text,v in [('General','general'),('Number','number'),('Currency','currency'),('Percent','percent')]:
                self.style_combo.addItem(text,v)
            self.style_combo.setMaximumWidth(100)
            self.style_combo.currentIndexChanged.connect(lambda _:self.set_number_format(self.style_combo.currentData()))
            self.toolbar.addWidget(self.style_combo)

            formula_row=QHBoxLayout()
            self.namebox=QLineEdit('A1',self); self.namebox.setMaximumWidth(95)
            self.namebox.returnPressed.connect(self.goto_name)
            formula_row.addWidget(self.namebox)
            formula_row.addWidget(QLabel('fx',self))
            self.formula=QLineEdit(self)
            self.formula.setPlaceholderText('Type a value or a formula, for example =SUM(A1:A10)')
            self.formula.returnPressed.connect(self.commit_formula)
            formula_row.addWidget(self.formula,1)
            layout.addLayout(formula_row)

            self.grid=QTableWidget(256,64,self)
            self.grid.setHorizontalHeaderLabels([col_name(x) for x in range(64)])
            self.grid.verticalHeader().setDefaultSectionSize(23)
            self.grid.horizontalHeader().setDefaultSectionSize(90)
            self.grid.horizontalHeader().setMinimumSectionSize(30)
            self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.grid.setSelectionBehavior(QAbstractItemView.SelectItems)
            self.grid.setItemDelegate(RawDelegate(self.grid,self))
            self.grid.itemChanged.connect(self.item_changed)
            self.grid.currentCellChanged.connect(self.current_changed)
            self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
            self.grid.customContextMenuRequested.connect(self.grid_context)
            layout.addWidget(self.grid,1)

            sheet_row=QHBoxLayout()
            add=QPushButton('+',self); add.setMaximumWidth(30); add.clicked.connect(self.new_sheet)
            sheet_row.addWidget(add)
            self.tabs=QTabBar(self)
            self.tabs.setExpanding(False)
            self.tabs.setMovable(False)
            self.tabs.currentChanged.connect(self.switch_sheet)
            self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
            self.tabs.customContextMenuRequested.connect(self.sheet_context)
            sheet_row.addWidget(self.tabs,1)
            layout.addLayout(sheet_row)
            self.status=QLabel('Ready    |    Sheet1    |    256 rows × 64 columns',self)
            self.status.setContentsMargins(5,2,5,2)
            layout.addWidget(self.status)
            self._sync_tabs()
            self.grid.setCurrentCell(0,0)
            self.refresh()
            QTimer.singleShot(0,self.watch_mdi)

        def watch_mdi(self):
            p=self.parentWidget()
            while p is not None and not isinstance(p, QMdiSubWindow): p=p.parentWidget()
            if p:
                self._mdi=p
                p.installEventFilter(self)
                self.update_title()

        def eventFilter(self,source,event):
            if source is self._mdi and event.type()==QEvent.Close:
                if not self.ask_save():
                    event.ignore(); return True
            return super().eventFilter(source,event)

        def closeEvent(self,event):
            if self.ask_save(): event.accept()
            else: event.ignore()

        def update_title(self):
            name=self.filename.rsplit('/',1)[-1] if self.filename else 'Book1'
            title=('*' if self.dirty else '')+name+' - PythonBDE Sheets'
            self.setWindowTitle(title)
            if self._mdi:self._mdi.setWindowTitle(title)

        def _checkpoint(self):
            self.undo_stack.append(self.wb.to_json())
            self.undo_stack=self.undo_stack[-30:]
            self.redo_stack.clear()

        def _changed(self):
            self.dirty=True
            self.update_title()
            self.status.setText(f'Modified    |    {self.wb.sheet().name}    |    {len(self.wb.sheet().cells)} cells')

        def selection(self):
            indexes=self.grid.selectedIndexes()
            if not indexes:
                return [(self.grid.currentRow(),self.grid.currentColumn())]
            return [(i.row(),i.column()) for i in indexes]

        def raw_for_index(self,row,col):
            return self.wb.sheet().raw(cell_address(row,col))

        def _text(self,value,style):
            nformat=style.get('number','general')
            if isinstance(value,Decimal):
                if nformat=='currency': return f'{value:,.2f} €'
                if nformat=='number': return f'{value:,.2f}'
                if nformat=='percent': return f'{value*100:.2f}%'
            return display_value(value)

        def _style_item(self,item,style):
            font=QFont(style.get('family','Arial'),int(style.get('size',10)))
            font.setBold(bool(style.get('bold',False)))
            font.setItalic(bool(style.get('italic',False)))
            font.setUnderline(bool(style.get('underline',False)))
            item.setFont(font)
            item.setTextAlignment({'left':Qt.AlignLeft,'center':Qt.AlignHCenter,
                                   'right':Qt.AlignRight}.get(style.get('align','right'),Qt.AlignRight)|Qt.AlignVCenter)
            if style.get('background'):item.setBackground(QColor(style['background']))
            else:item.setData(Qt.BackgroundRole,None)
            if style.get('foreground'):item.setForeground(QColor(style['foreground']))
            else:item.setData(Qt.ForegroundRole,None)

        def _show_cell(self,address,values):
            row,col=parse_address(address)
            if row>=self.grid.rowCount() or col>=self.grid.columnCount():return
            raw=self.wb.sheet().raw(address)
            style=self.wb.sheet().style(address)
            item=self.grid.item(row,col)
            if item is None:
                item=QTableWidgetItem()
                self.grid.setItem(row,col,item)
            item.setText(self._text(values.get(address,None),style))
            item.setToolTip(raw if raw.startswith('=') else '')
            self._style_item(item,style)

        def refresh(self,*_):
            self._loading=True
            self.grid.blockSignals(True)
            try:
                self.grid.clearContents()
                vals=self.wb.evaluated()
                for address in self.wb.sheet().cells:
                    self._show_cell(address,vals)
                for col,width in self.wb.sheet().widths.items():
                    idx=int(col)
                    if 0<=idx<self.grid.columnCount():self.grid.setColumnWidth(idx,width)
            finally:
                self.grid.blockSignals(False)
                self._loading=False
            self.current_changed(self.grid.currentRow(),self.grid.currentColumn(),-1,-1)

        def item_changed(self,item):
            if self._loading:return
            address=cell_address(item.row(),item.column())
            raw=item.text()
            if self.wb.sheet().raw(address)==raw:return
            self._checkpoint()
            self.wb.put(address,raw)
            self._changed()
            self.refresh()

        def current_changed(self,row,col,prevrow,prevcol):
            if row<0 or col<0:return
            addr=cell_address(row,col)
            self.namebox.setText(addr)
            self.formula.setText(self.wb.sheet().raw(addr))
            style=self.wb.sheet().style(addr)
            self.font_family.blockSignals(True);self.font_size.blockSignals(True);self.style_combo.blockSignals(True)
            try:
                self.font_family.setCurrentFont(QFont(style.get('family','Arial')))
                self.font_size.setValue(int(style.get('size',10)))
                idx=self.style_combo.findData(style.get('number','general'))
                self.style_combo.setCurrentIndex(max(0,idx))
            finally:
                self.font_family.blockSignals(False);self.font_size.blockSignals(False);self.style_combo.blockSignals(False)

        def _ensure_visible(self,row,col):
            if row>=self.grid.rowCount():
                self.grid.setRowCount(min(MAX_ROWS,max(row+1,self.grid.rowCount()+128)))
            if col>=self.grid.columnCount():
                self.grid.setColumnCount(min(MAX_COLS,max(col+1,self.grid.columnCount()+16)))
                self.grid.setHorizontalHeaderLabels([col_name(x) for x in range(self.grid.columnCount())])
            self.grid.setCurrentCell(row,col)
            self.grid.scrollToItem(self.grid.item(row,col) or self._empty_item(row,col))

        def _empty_item(self,row,col):
            existing=self.grid.item(row,col)
            if existing:return existing
            item=QTableWidgetItem('')
            self.grid.blockSignals(True)
            self.grid.setItem(row,col,item)
            self.grid.blockSignals(False)
            return item

        def goto_name(self):
            try:
                row,col=parse_address(self.namebox.text())
                self._ensure_visible(row,col)
                self.grid.setFocus()
            except ValueError as ex:
                self.alert(str(ex))

        def goto_dialog(self):
            val,ok=QInputDialog.getText(self,'Go To','Cell:',text=self.namebox.text())
            if ok:self.namebox.setText(val);self.goto_name()

        def commit_formula(self):
            row,col=self.grid.currentRow(),self.grid.currentColumn()
            if row<0:return
            self._checkpoint()
            self.wb.put(cell_address(row,col),self.formula.text())
            self._changed();self.refresh();self.grid.setFocus()

        def _sync_tabs(self):
            self.tabs.blockSignals(True)
            try:
                while self.tabs.count():self.tabs.removeTab(0)
                for s in self.wb.sheets:self.tabs.addTab(s.name)
                self.tabs.setCurrentIndex(self.wb.active)
            finally:self.tabs.blockSignals(False)

        def switch_sheet(self,index):
            if self._loading or index<0 or index>=len(self.wb.sheets):return
            self.wb.active=index
            self.refresh()
            self.status.setText('Worksheet: '+self.wb.sheet().name)

        def new_sheet(self):
            try:
                self._checkpoint();self.wb.add_sheet();self._sync_tabs();self._changed();self.refresh()
            except ValueError as ex:self.alert(str(ex))

        def rename_sheet(self):
            old=self.wb.sheet().name
            val,ok=QInputDialog.getText(self,'Rename Sheet','Name:',text=old)
            if ok:
                try:
                    self._checkpoint();self.wb.rename_sheet(old,val);self._sync_tabs();self._changed();self.refresh()
                except ValueError as ex:self.alert(str(ex))

        def delete_sheet(self):
            if len(self.wb.sheets)==1:return self.alert('Cannot delete the last worksheet.')
            if QMessageBox.question(self,'Delete Sheet','Delete current worksheet?',QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
            self._checkpoint();self.wb.delete_sheet(self.wb.sheet().name);self._sync_tabs();self._changed();self.refresh()

        def sheet_context(self,point):
            menu=QMenu(self)
            menu.addAction('New Worksheet',self.new_sheet)
            menu.addAction('Rename Worksheet',self.rename_sheet)
            menu.addAction('Delete Worksheet',self.delete_sheet)
            menu.exec_(self.tabs.mapToGlobal(point))

        def grid_context(self,point):
            menu=QMenu(self)
            for label,fn in [('Cut',self.cut),('Copy',self.copy),('Paste',self.paste),
                             ('Clear Contents',self.clear_cells),('Fill Down',self.fill_down),
                             ('Fill Right',self.fill_right),('AutoSum',self.autosum)]:
                menu.addAction(label,fn)
            menu.exec_(self.grid.viewport().mapToGlobal(point))

        def set_format(self,key,value):
            if self._loading:return
            cells=self.selection()
            if not cells:return
            self._checkpoint()
            for row,col in cells:
                addr=cell_address(row,col)
                style=copy.deepcopy(self.wb.sheet().style(addr))
                style[key]=value
                self.wb.put(addr,self.wb.sheet().raw(addr),fmt=style)
            self._changed();self.refresh()

        def toggle_format(self,key):
            cells=self.selection()
            if cells:
                addr=cell_address(*cells[0]);self.set_format(key,not self.wb.sheet().style(addr).get(key,False))

        def set_number_format(self,name):
            if name:self.set_format('number',name)

        def background_color(self):
            color=QColorDialog.getColor(QColor('#FFFFFF'),self,'Cell Fill Color')
            if color.isValid():self.set_format('background',color.name())

        def foreground_color(self):
            color=QColorDialog.getColor(QColor('#000000'),self,'Text Color')
            if color.isValid():self.set_format('foreground',color.name())

        def copy(self):
            coords=self.selection()
            if not coords:return
            top=min(r for r,c in coords); bottom=max(r for r,c in coords)
            left=min(c for r,c in coords);right=max(c for r,c in coords)
            if (bottom-top+1)*(right-left+1)>MAX_RANGE:
                return self.alert('Selection is too large to copy')
            rows=[]
            for row in range(top,bottom+1):
                rows.append('\t'.join(self.wb.sheet().raw(cell_address(row,col)) for col in range(left,right+1)))
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText('\n'.join(rows))

        def cut(self):
            self.copy();self.clear_cells()

        def paste(self):
            from PyQt5.QtWidgets import QApplication
            text=QApplication.clipboard().text()
            if not text:return
            rows=list(csv.reader(io.StringIO(text),delimiter='\t'))
            r0,c0=self.grid.currentRow(),self.grid.currentColumn()
            if r0<0:return
            if sum(len(row) for row in rows)>MAX_RANGE:return self.alert('Paste area too large')
            self._checkpoint()
            try:
                for r,row in enumerate(rows):
                    for c,raw in enumerate(row):
                        if r0+r<MAX_ROWS and c0+c<MAX_COLS:
                            self.wb.put(cell_address(r0+r,c0+c),raw)
            except ValueError as ex:return self.alert(str(ex))
            self._changed();self.refresh()

        def clear_cells(self):
            cells=self.selection()
            if not cells:return
            self._checkpoint()
            for row,col in cells:self.wb.put(cell_address(row,col),'')
            self._changed();self.refresh()

        def _rect(self):
            coords=self.selection()
            return min(r for r,c in coords),max(r for r,c in coords),min(c for r,c in coords),max(c for r,c in coords)

        def fill_down(self):
            r1,r2,c1,c2=self._rect()
            if r1==r2:return
            self._checkpoint()
            for col in range(c1,c2+1):
                raw=self.wb.sheet().raw(cell_address(r1,col))
                for row in range(r1+1,r2+1):
                    self.wb.put(cell_address(row,col),shift_formula(raw,row-r1,0))
            self._changed();self.refresh()

        def fill_right(self):
            r1,r2,c1,c2=self._rect()
            if c1==c2:return
            self._checkpoint()
            for row in range(r1,r2+1):
                raw=self.wb.sheet().raw(cell_address(row,c1))
                for col in range(c1+1,c2+1):
                    self.wb.put(cell_address(row,col),shift_formula(raw,0,col-c1))
            self._changed();self.refresh()

        def autosum(self):
            row,col=self.grid.currentRow(),self.grid.currentColumn()
            if row<0:return
            start=max(0,row-10)
            target=cell_address(row,col)
            if row>0:formula=f'=SUM({cell_address(start,col)}:{cell_address(row-1,col)})'
            elif col>0:formula=f'=SUM({cell_address(row,0)}:{cell_address(row,col-1)})'
            else:formula='=SUM(0)'
            self._checkpoint();self.wb.put(target,formula);self._changed();self.refresh()

        def sort_selection(self,reverse):
            r1,r2,c1,c2=self._rect()
            if r1==r2:return
            self._checkpoint()
            sh=self.wb.sheet()
            records=[[copy.deepcopy(sh.cells.get(cell_address(r,c), {'v':'','fmt':{}})) for c in range(c1,c2+1)] for r in range(r1,r2+1)]
            def key(record):
                v=record[0]['v']
                try:return (0,Decimal(v))
                except InvalidOperation:return (1,v.casefold())
            records.sort(key=key,reverse=reverse)
            for i,row in enumerate(records):
                for j,record in enumerate(row):
                    sh.put(cell_address(r1+i,c1+j),record['v'],record['fmt'])
            self._changed();self.refresh()

        def find(self):
            text,ok=QInputDialog.getText(self,'Find','Find:',text=self.current_find)
            if not ok or not text:return
            self.current_find=text
            start=self.grid.currentRow()*MAX_COLS+self.grid.currentColumn()+1
            found=[]
            for addr,item in self.wb.sheet().cells.items():
                if text.casefold() in item['v'].casefold():
                    row,col=parse_address(addr)
                    found.append((row*MAX_COLS+col,row,col))
            if found:
                found.sort()
                for linear,row,col in found:
                    if linear>=start:self._ensure_visible(row,col);return
                self._ensure_visible(found[0][1],found[0][2]);return
            self.alert('No matching cells found.')

        def undo(self):
            if not self.undo_stack:return
            self.redo_stack.append(self.wb.to_json())
            self.wb=Workbook.from_json(self.undo_stack.pop())
            self._sync_tabs();self._changed();self.refresh()

        def redo(self):
            if not self.redo_stack:return
            self.undo_stack.append(self.wb.to_json())
            self.wb=Workbook.from_json(self.redo_stack.pop())
            self._sync_tabs();self._changed();self.refresh()

        def set_zoom(self,step):
            size=max(16,min(50,self.grid.verticalHeader().defaultSectionSize()+step*2))
            self.grid.verticalHeader().setDefaultSectionSize(size)
            self.grid.horizontalHeader().setDefaultSectionSize(max(50,90+(size-23)*3))

        def chart(self):
            r1,r2,c1,c2=self._rect()
            points=[]
            for row in range(r1,min(r2+1,r1+40)):
                label=self.wb.sheet().raw(cell_address(row,c1)) or str(row+1)
                val=self.wb.value(cell_address(row,min(c2,c1+1)))
                try:points.append((label,float(as_number(val))))
                except FormulaFailure:continue
            if not points:return self.alert('Select labels and numeric data for a chart.')
            widget=ChartWidget(points,'Column chart')
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:
                bridge._open_mdi(widget,'Chart - PythonBDE Sheets',500,360)
            else:
                widget.setParent(self);widget.show()

        def _filters(self):
            return [('Excel Workbook (*.xlsx)',['*.xlsx']),
                    ('PythonBDE Workbook (*.pysheet)',['*.pysheet']),
                    ('CSV files (*.csv)',['*.csv']),('TSV files (*.tsv)',['*.tsv'])]

        def ask_save(self):
            if self._allow_close or not self.dirty:return True
            answer=QMessageBox.question(self,'PythonBDE Sheets',
                'Save changes to this workbook?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,
                QMessageBox.Save)
            if answer==QMessageBox.Cancel:return False
            if answer==QMessageBox.Save and not self.save_book():return False
            return True

        def new_book(self):
            if not self.ask_save():return
            self.wb=Workbook();self.filename=None;self.dirty=False
            self.undo_stack=[];self.redo_stack=[]
            self._sync_tabs();self.refresh();self.update_title()

        def open_book(self):
            if not self.ask_save():return
            bridge=getattr(self,'remote_files',None)
            if bridge is None:return self.alert('Remote filesystem is not available')
            path=bridge.open_dialog('open',self._filters())
            if not path:return
            try:
                data=bridge.read_bytes(path)
                suffix=path.rsplit('.',1)[-1].lower()
                if suffix=='xlsx':wb=import_xlsx(data)
                elif suffix=='pysheet':wb=Workbook.from_json(data)
                elif suffix in ('csv','tsv'):wb=import_csv(data,'\t' if suffix=='tsv' else ',')
                else:raise ValueError('Unsupported file extension')
                self.wb=wb;self.filename=path;self.dirty=False
                self.undo_stack=[];self.redo_stack=[]
                self._sync_tabs();self.refresh();self.update_title()
            except (OSError,ValueError,KeyError,zipfile.BadZipFile,UnicodeError) as ex:self.alert('Open failed: '+str(ex))

        def save_book(self):
            if not self.filename:return self.save_as()
            bridge=getattr(self,'remote_files',None)
            if bridge is None:self.alert('Remote filesystem is not available');return False
            try:
                suffix=self.filename.rsplit('.',1)[-1].lower()
                if suffix=='xlsx':content=export_xlsx(self.wb)
                elif suffix=='pysheet':content=self.wb.to_json()
                elif suffix in ('csv','tsv'):content=export_csv(self.wb,'\t' if suffix=='tsv' else ',')
                else:raise ValueError('Unsupported format')
                bridge.write_bytes(self.filename,content)
                self.dirty=False;self.update_title()
                self.status.setText('Saved: '+self.filename)
                return True
            except (OSError,ValueError,RuntimeError) as ex:
                self.alert('Save failed: '+str(ex));return False

        def save_as(self):
            bridge=getattr(self,'remote_files',None)
            if bridge is None:self.alert('Remote filesystem is not available');return False
            path=bridge.open_dialog('save',self._filters())
            if not path:return False
            old=self.filename;self.filename=path
            if self.save_book():return True
            self.filename=old;return False

        def preview(self):
            sh=self.wb.sheet()
            pairs=[]
            for addr in sorted(sh.cells,key=parse_address)[:100]:
                pairs.append(addr+' : '+display_value(self.wb.value(addr)))
            lines='\n'.join(pairs) or '(empty sheet)'
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:bridge.print_text(lines,'Print PythonBDE Sheets')
            else:self.alert('Print preview is only available inside the remote desktop')

        def about(self):
            bridge=getattr(self,'remote_files',None)
            text=('PythonBDE Sheets v0.6.0\n'
                  'Remote spreadsheet application\n'
                  '(c) 2026 by Jens Kallup - paule32\n'
                  'Multiple sheets, formulas, formatting, CSV, XLSX and virtual files.')
            if bridge is not None:bridge.about('About PythonBDE Sheets',text)
            else:QMessageBox.information(self,'About PythonBDE Sheets',text)

        def functions_help(self):
            self.alert('Functions: SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, IF, IFERROR, '
                       'ROUND, ABS, INT, SQRT, LEN, LEFT, RIGHT, MID, CONCAT, '
                       'AND, OR, NOT, TODAY, NOW.\n'
                       'Cell references: A1, $A$1, A1:B10, Sheet2!A1. '
                       'Supported operators: + - * / ^ & = <> < > <= >=')

        def alert(self,text):
            bridge=getattr(self,'remote_files',None)
            if bridge is not None:bridge.alert(text,'PythonBDE Sheets')
            else:QMessageBox.warning(self,'PythonBDE Sheets',str(text))

        def exit_editor(self):
            if self._mdi:self._mdi.close()
            else:self.close()

    return SpreadsheetWidget(parent)
