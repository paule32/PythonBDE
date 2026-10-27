"""PythonBDE Calculator -- signed remote .cpy application.

A classic Windows Calculator-inspired, original Qt5 implementation.  This is
ONE source file deliberately: cpy_modules.compiled_module_package() publishes
one signed bytecode module, not a Python package hierarchy.

CalculatorEngine has no Qt dependencies and can be tested before remote loading.
The publisher must be trusted: signed Python bytecode is NOT sandboxed.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, DivisionByZero, Overflow, localcontext
import math
import operator


class CalculatorError(ValueError):
    """A mathematical or input error visible in the calculator's display."""


class CalculatorEngine:
    """Stateful calculator, with no eval/exec or dynamic expression parsing.

    Windows-style sequential operations and repeated '=' are supported.  The
    scientific view adds precedence-free functions like the classic Calc.
    Decimal keeps basic arithmetic precise (e.g. 0.1 + 0.2 == 0.3).
    """

    MAX_INPUT_DIGITS = 48
    MAX_HISTORY = 100
    MODES = ('standard', 'scientific', 'programmer')
    BINARY_OPERATORS = ('+', '-', '*', '/', '^', 'mod', 'and', 'or', 'xor', '<<', '>>')
    UNARY_OPERATORS = ('±', '%', 'sqrt', '1/x', 'x²', 'x³', 'n!', 'sin', 'cos', 'tan',
                       'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh', 'ln', 'log',
                       'exp', '10^x', '2^x', 'abs', 'not')

    def __init__(self):
        self.mode = 'standard'
        self.angle_mode = 'DEG'
        self.radix = 10
        self.word_bits = 64
        self.memory = Decimal(0)
        self.memory_set = False
        self.history = []
        self.reset()

    def reset(self):
        self.entry = '0'
        self.accumulator = None
        self.pending = None
        self.waiting = False
        self.last_operation = None
        self.expression = ''
        self.error = None
        self.start_new_on_digit = False

    def clear_entry(self):
        self.error = None
        self.entry = '0'
        self.waiting = False
        self.start_new_on_digit = False

    def _value(self):
        if self.error:
            raise CalculatorError(self.error)
        try:
            if self.mode == 'programmer':
                return Decimal(int(self.entry, self.radix))
            return Decimal(self.entry)
        except (InvalidOperation, ValueError) as exc:
            raise CalculatorError('Invalid number') from exc

    def _set_value(self, value):
        if not isinstance(value, Decimal):
            value = Decimal(value)
        if not value.is_finite():
            raise CalculatorError('Result is not finite')
        if value and abs(value.adjusted()) > 10000:
            raise CalculatorError('Number out of range')
        if self.mode == 'programmer':
            number = int(value)
            if Decimal(number) != value:
                raise CalculatorError('Integer required')
            number = self._word_signed(number)
            if self.radix == 10:
                self.entry = str(number)
            else:
                self.entry = format(number & self._mask(),
                                    {16: 'X', 8: 'o', 2: 'b'}[self.radix]).upper()
        else:
            self.entry = str(+value)
        self.error = None
        self.start_new_on_digit = False

    def _mask(self):
        return (1 << self.word_bits) - 1

    def _word_signed(self, x):
        number = int(x) & self._mask()
        return number - (1 << self.word_bits) if number & (1 << (self.word_bits-1)) else number

    def display_text(self):
        if self.error:
            return 'Error: ' + self.error
        if self.mode == 'programmer':
            # Keep the input casing, but omit leading zeros from computed values.
            return self.entry.upper()
        try:
            number = Decimal(self.entry)
        except InvalidOperation:
            return self.entry
        # While typing, preserve decimal separator and trailing zeroes.
        if not self.waiting or self.entry in ('-', '-0.', '0.'):
            return self.entry
        if number == 0:
            return '0' if not self.entry.startswith('-') else '-0'
        with localcontext() as context:
            context.prec = 24
            rounded = +number
        if abs(rounded) >= Decimal('1e20') or abs(rounded) < Decimal('1e-12'):
            return format(rounded.normalize(), '.16E').replace('E+', 'E')
        rendered = format(rounded, 'f')
        return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered

    def _input_digit(self, digit):
        if digit not in '0123456789ABCDEF':
            return
        if self.mode != 'programmer' and digit not in '0123456789':
            return
        if self.mode == 'programmer' and int(digit, 16) >= self.radix:
            return
        if self.waiting or self.start_new_on_digit:
            self.entry = digit
            self.start_new_on_digit = False
            self.waiting = False
            if self.pending is None:
                self.last_operation = None
                self.expression = ''
            return
        if len(self.entry.replace('.', '').replace('-', '').replace('E', '')) >= self.MAX_INPUT_DIGITS:
            return
        if self.entry in ('0', '-0'):
            self.entry = ('-' if self.entry.startswith('-') else '') + digit
        else:
            self.entry += digit

    def _binary(self, operation, lhs, rhs):
        with localcontext() as ctx:
            ctx.prec = 50
            try:
                if operation == '+': result = lhs + rhs
                elif operation == '-': result = lhs - rhs
                elif operation == '*': result = lhs * rhs
                elif operation == '/':
                    if rhs == 0: raise CalculatorError('Division by zero')
                    result = lhs / rhs
                elif operation == '^':
                    if abs(rhs) > 10000: raise CalculatorError('Exponent too large')
                    result = lhs ** rhs
                elif operation == 'mod':
                    if rhs == 0: raise CalculatorError('Division by zero')
                    result = lhs % rhs
                elif operation in ('and','or','xor','<<','>>'):
                    x, y = int(lhs), int(rhs)
                    if operation in ('<<','>>') and not 0 <= y <= 63:
                        raise CalculatorError('Shift must be 0..63')
                    function = {'and': operator.and_, 'or':operator.or_, 'xor':operator.xor,
                                '<<':operator.lshift, '>>':operator.rshift}[operation]
                    result = Decimal(self._word_signed(function(x, y)))
                else: raise CalculatorError('Unknown operation')
                if not result.is_finite(): raise CalculatorError('Result is not finite')
                return result
            except (InvalidOperation, DivisionByZero, Overflow, OverflowError) as exc:
                raise CalculatorError('Invalid calculation') from exc

    def _angle_to_radians(self, x):
        multiplier = {'DEG': math.pi / 180, 'RAD': 1.0, 'GRAD': math.pi / 200}[self.angle_mode]
        return float(x) * multiplier

    def _radians_to_angle(self, x):
        multiplier = {'DEG': 180 / math.pi, 'RAD': 1.0, 'GRAD': 200 / math.pi}[self.angle_mode]
        return Decimal(str(x * multiplier))

    def _unary(self, op, value):
        with localcontext() as ctx:
            ctx.prec = 50
            try:
                if op == '±': return -value
                if op == '%':
                    if self.pending in ('+', '-'): return self.accumulator * value / Decimal(100)
                    return value / Decimal(100)
                if op == 'sqrt':
                    if value < 0: raise CalculatorError('Invalid input for sqrt')
                    return value.sqrt()
                if op == '1/x':
                    if value == 0: raise CalculatorError('Division by zero')
                    return 1 / value
                if op == 'x²': return value * value
                if op == 'x³': return value * value * value
                if op == 'abs': return abs(value)
                if op == 'n!':
                    if value != int(value) or not 0 <= value <= 1000:
                        raise CalculatorError('Factorial requires integer 0..1000')
                    return Decimal(math.factorial(int(value)))
                if op == 'not': return Decimal(self._word_signed(~int(value)))
                if op == 'ln':
                    if value <= 0: raise CalculatorError('Log requires positive number')
                    return value.ln()
                if op == 'log':
                    if value <= 0: raise CalculatorError('Log requires positive number')
                    return value.log10()
                if op == 'exp':
                    if abs(value) > 500: raise CalculatorError('Exponent too large')
                    return value.exp()
                if op == '10^x':
                    if abs(value) > 500: raise CalculatorError('Exponent too large')
                    return Decimal(10) ** value
                if op == '2^x':
                    if abs(value) > 500: raise CalculatorError('Exponent too large')
                    return Decimal(2) ** value
                if op in ('sin','cos','tan','asin','acos','atan','sinh','cosh','tanh'):
                    x = float(value)
                    if op in ('sin','cos','tan'):
                        radians = self._angle_to_radians(value)
                        if op == 'tan' and abs(math.cos(radians)) < 1e-14:
                            raise CalculatorError('Tan undefined')
                        answer = getattr(math, op)(radians)
                    elif op in ('asin','acos','atan'):
                        if op in ('asin','acos') and not -1 <= x <= 1:
                            raise CalculatorError('Trig domain error')
                        return self._radians_to_angle(getattr(math, {'asin':'asin','acos':'acos','atan':'atan'}[op])(x))
                    else:
                        answer = getattr(math, op)(x)
                    return Decimal(str(answer))
                raise CalculatorError('Unknown function')
            except (InvalidOperation, DivisionByZero, OverflowError, ValueError) as exc:
                if isinstance(exc, CalculatorError): raise
                raise CalculatorError('Invalid calculation') from exc

    def _record(self, expression, value):
        text = str(value)
        self.history.insert(0, (expression, text))
        del self.history[self.MAX_HISTORY:]

    def set_mode(self, mode):
        if mode not in self.MODES: raise ValueError('Unknown calculator mode')
        if mode == self.mode: return
        try: value = self._value()
        except CalculatorError: value = Decimal(0)
        self.mode = mode
        self.radix = 10
        self.reset()
        self._set_value(Decimal(int(value)) if mode == 'programmer' else value)
        self.waiting = True

    def set_angle_mode(self, mode):
        if mode not in ('DEG','RAD','GRAD'): raise ValueError('Unknown angle unit')
        self.angle_mode = mode

    def set_radix(self, radix):
        if radix not in (2,8,10,16): raise ValueError('Unsupported radix')
        if self.mode != 'programmer': raise ValueError('Requires Programmer mode')
        value = self._value()
        self.radix = radix
        self._set_value(value)
        self.waiting = True

    def set_word_bits(self, width):
        if width not in (8,16,32,64): raise ValueError('Unsupported word width')
        value = self._value()
        self.word_bits = width
        self._set_value(value)
        self.waiting = True

    def input_text(self, text):
        """Paste a single number; never evaluate pasted expressions."""
        candidate = str(text).strip().replace(',', '.')
        if not candidate or len(candidate) > 100: raise CalculatorError('Invalid pasted number')
        try:
            value = (Decimal(int(candidate, self.radix)) if self.mode == 'programmer'
                     else Decimal(candidate))
        except (InvalidOperation, ValueError) as exc:
            raise CalculatorError('Invalid pasted number') from exc
        if not value.is_finite(): raise CalculatorError('Invalid pasted number')
        self._set_value(value)
        self.waiting = False
        self.start_new_on_digit = False

    def press(self, key):
        """Process a virtual or physical key, never raising for math errors."""
        key = str(key)
        if key == 'AC' or (key == 'C' and self.mode != 'programmer'):
            self.reset()
            return self.display_text()
        if key == 'CE':
            self.clear_entry()
            return self.display_text()
        if self.error:
            if key in '0123456789ABCDEF' and len(key) == 1:
                self.reset()
            else:
                return self.display_text()
        try:
            if len(key) == 1 and key in '0123456789ABCDEF':
                self._input_digit(key)
            elif key == '.':
                if self.mode == 'programmer': return self.display_text()
                if self.waiting or self.start_new_on_digit:
                    self.entry = '0.'
                    self.start_new_on_digit = False
                    self.waiting = False
                elif '.' not in self.entry and 'E' not in self.entry.upper():
                    self.entry += '.'
            elif key in ('Back', '⌫'):
                if not self.waiting:
                    self.entry = self.entry[:-1] or '0'
                    if self.entry in ('-', ''): self.entry = '0'
            elif key in ('MC', 'MR', 'MS', 'M+', 'M-'):
                if key == 'MC':
                    self.memory = Decimal(0); self.memory_set = False
                elif key == 'MR':
                    self._set_value(self.memory)
                    self.waiting = False
                    self.start_new_on_digit = True
                elif key == 'MS':
                    self.memory = self._value(); self.memory_set = True
                elif key == 'M+':
                    self.memory += self._value(); self.memory_set = True
                elif key == 'M-':
                    self.memory -= self._value(); self.memory_set = True
            elif key in ('π', 'e'):
                self._set_value(Decimal(str(math.pi if key == 'π' else math.e)))
                self.waiting = False
            elif key in self.UNARY_OPERATORS:
                before = self._value()
                answer = self._unary(key, before)
                self._set_value(answer)
                self.expression = '{}({})'.format(key, before)
                self.waiting = self.pending is None
                if self.pending is None: self._record(self.expression, answer)
            elif key in self.BINARY_OPERATORS:
                current = self._value()
                if self.pending is not None and not self.waiting:
                    current = self._binary(self.pending, self.accumulator, current)
                    self._set_value(current)
                self.accumulator = current
                self.pending = key
                self.last_operation = None
                self.waiting = True
                self.expression = f'{current} {key}'
            elif key in ('=', 'Enter'):
                if self.pending is not None:
                    rhs = self.accumulator if self.waiting else self._value()
                    lhs, operation = self.accumulator, self.pending
                    result = self._binary(operation, lhs, rhs)
                    self._set_value(result)
                    self.expression = f'{lhs} {operation} {rhs} ='
                    self._record(self.expression, result)
                    self.last_operation = (operation, rhs)
                    self.pending = None
                    self.accumulator = None
                    self.waiting = True
                elif self.last_operation is not None:
                    operation, rhs = self.last_operation
                    lhs = self._value()
                    result = self._binary(operation, lhs, rhs)
                    self._set_value(result)
                    self.expression = f'{lhs} {operation} {rhs} ='
                    self._record(self.expression, result)
                    self.waiting = True
            else:
                raise CalculatorError('Unknown key')
        except (CalculatorError, InvalidOperation, DivisionByZero, OverflowError, ZeroDivisionError) as exc:
            self.error = str(exc) if isinstance(exc, CalculatorError) else 'Invalid calculation'
            self.pending = None
            self.accumulator = None
            self.waiting = True
        return self.display_text()


def create_widget(parent):
    """Entry point called by the signed .cpy MDI loader (PyQt5 only here)."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont, QKeySequence
    from PyQt5.QtWidgets import (
        QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
        QGridLayout, QStackedWidget, QMenuBar, QAction, QApplication,
        QPlainTextEdit, QShortcut, QMessageBox, QSizePolicy,
    )

    class CalculatorWidget(QWidget):
        """Classic Windows Calculator-inspired MDI app, keyboard enabled."""

        def __init__(self, parent):
            super().__init__(parent)
            self.engine = CalculatorEngine()
            self.buttons = {}
            self.setObjectName('PythonBDECalculator')
            self.setMinimumSize(310, 385)
            self.setFocusPolicy(Qt.StrongFocus)
            # Match the selected emulated desktop, independently of host OS.
            desktop_mode = getattr(parent.window(), 'mode', 'winXP')
            old_style = desktop_mode == 'win95'
            bg = '#c0c0c0' if old_style else '#d6e5f7'
            face = '#d5d5d5' if old_style else '#edf3fa'
            edge = '#707070' if old_style else '#8ca8cc'
            self.setStyleSheet('''
                QWidget#PythonBDECalculator { background: %s; color: #172b44; }
                QMenuBar { background: %s; color: #172b44; }
                QPushButton { background: %s; color: #142744;
                              border: 2px outset %s; border-radius: %spx;
                              font-weight: bold; padding: 2px; }
                QPushButton:pressed { border: 2px inset %s; background: #bdcae0; }
                QPushButton:disabled { color: #888; }
                QLineEdit#CalcDisplay { background: #fffef8; color: #061c36;
                                       border: 2px inset %s; padding: 3px; }
                QPlainTextEdit#CalcHistory { background:#fffef8; color:#172b44; }
            ''' % (bg, bg, face, edge, 0 if old_style else 4, edge, edge))
            root = QVBoxLayout(self)
            root.setSpacing(5)
            root.setContentsMargins(8, 8, 8, 8)

            bar = QMenuBar(self)
            bar.setNativeMenuBar(False)  # menus live inside remote MDI window
            menu_edit = bar.addMenu('Edit')
            menu_view = bar.addMenu('View')
            menu_help = bar.addMenu('Help')
            def menu_action(menu, label, handler, shortcut=None):
                act = QAction(label, self)
                act.triggered.connect(handler)
                if shortcut: act.setShortcut(QKeySequence(shortcut))
                menu.addAction(act)
                return act
            menu_action(menu_edit, 'Copy', self.copy_result, 'Ctrl+C')
            menu_action(menu_edit, 'Paste', self.paste_result, 'Ctrl+V')
            menu_edit.addSeparator()
            menu_action(menu_edit, 'Clear History', self.clear_history)
            self.mode_actions = {}
            for mode, name in [('standard','Standard'), ('scientific','Scientific'),
                               ('programmer','Programmer')]:
                act = menu_action(menu_view, name, lambda _checked=False, m=mode: self.set_mode(m))
                act.setCheckable(True)
                self.mode_actions[mode] = act
            menu_view.addSeparator()
            self.history_action = menu_action(menu_view, 'History', self.toggle_history, 'Ctrl+H')
            self.history_action.setCheckable(True)
            menu_action(menu_help, 'About Calculator', self.show_about)
            root.setMenuBar(bar)

            self.expression = QLabel('', self)
            self.expression.setObjectName('CalcExpression')
            self.expression.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.expression.setMinimumHeight(18)
            root.addWidget(self.expression)
            self.result = QLineEdit('0', self)
            self.result.setReadOnly(True)
            self.result.setObjectName('CalcDisplay')
            self.result.setAlignment(Qt.AlignRight)
            self.result.setFont(QFont('Consolas', 18, QFont.Bold))
            self.result.setMinimumHeight(46)
            self.result.setFocusPolicy(Qt.NoFocus)
            root.addWidget(self.result)
            self.memory_indicator = QLabel('', self)
            self.memory_indicator.setMinimumHeight(16)
            root.addWidget(self.memory_indicator)
            self.pages = QStackedWidget(self)
            root.addWidget(self.pages, 1)
            self._make_standard()
            self._make_scientific()
            self._make_programmer()
            self.history_box = QPlainTextEdit(self)
            self.history_box.setObjectName('CalcHistory')
            self.history_box.setReadOnly(True)
            self.history_box.setMaximumHeight(120)
            self.history_box.hide()
            root.addWidget(self.history_box)

            for text, key in [('0','0'),('1','1'),('2','2'),('3','3'),('4','4'),
                              ('5','5'),('6','6'),('7','7'),('8','8'),('9','9'),
                              ('.','.'), ('+','+'), ('-','-'), ('*','*'), ('/','/'),
                              ('=','Return'), ('=','Enter'), ('Back','Backspace'),
                              ('CE','Delete'), ('C','Escape')]:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda val=text: self.press(val))
            for letter in 'ABCDEF':
                shortcut = QShortcut(QKeySequence(letter), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(
                    lambda v=letter: self.press(v) if self.engine.mode == 'programmer' or v == 'C' else None)
            comma = QShortcut(QKeySequence(','), self)
            comma.setContext(Qt.WidgetWithChildrenShortcut)
            comma.activated.connect(lambda: self.press('.'))
            self.set_mode('standard')

        def _button(self, grid, row, col, label, code=None, span=1):
            btn = QPushButton(label, self)
            btn.setObjectName('Calc_' + ''.join(c for c in (code or label) if c.isalnum()))
            btn.setMinimumHeight(31)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            btn.clicked.connect(lambda _checked=False, k=code or label: self.press(k))
            grid.addWidget(btn, row, col, 1, span)
            self.buttons.setdefault(label, []).append(btn)
            return btn

        def _page(self, rows):
            page = QWidget(self)
            layout = QGridLayout(page)
            layout.setSpacing(4)
            layout.setContentsMargins(0, 0, 0, 0)
            for i, row in enumerate(rows):
                for j, name in enumerate(row):
                    if name:
                        self._button(layout, i, j, name)
            self.pages.addWidget(page)
            return page

        def _make_standard(self):
            self._page([
                ['MC','MR','MS','M+','M-'],
                ['Back','CE','C','±','sqrt'],
                ['7','8','9','/','%'],
                ['4','5','6','*','1/x'],
                ['1','2','3','-','x²'],
                ['0','.','=','+','x³'],
            ])

        def _make_scientific(self):
            page = QWidget(self)
            self.pages.addWidget(page)
            layout = QVBoxLayout(page)
            layout.setSpacing(3)
            layout.setContentsMargins(0, 0, 0, 0)
            angle = QHBoxLayout()
            self.angle_buttons = {}
            for name in ('DEG','RAD','GRAD'):
                button = QPushButton(name, page)
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, v=name: self.set_angle(v))
                angle.addWidget(button)
                self.angle_buttons[name] = button
            layout.addLayout(angle)
            rows = [
                ['sin','cos','tan','asin','acos','atan'],
                ['sinh','cosh','tanh','π','e','n!'],
                ['ln','log','exp','10^x','2^x','x²'],
                ['MC','MR','MS','M+','M-','Back'],
                ['7','8','9','/','CE','C'],
                ['4','5','6','*','sqrt','1/x'],
                ['1','2','3','-','x^y','mod'],
                ['0','.','=','+','±','%'],
            ]
            grid = QGridLayout()
            grid.setSpacing(3)
            for i,row in enumerate(rows):
                for j,name in enumerate(row):
                    self._button(grid, i, j, name, {'x^y':'^'}.get(name))
            layout.addLayout(grid, 1)
            self.set_angle('DEG')

        def _make_programmer(self):
            page = QWidget(self)
            self.pages.addWidget(page)
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0,0,0,0)
            self.radix_buttons = {}
            radix_row = QHBoxLayout()
            for name,radix in [('HEX',16),('DEC',10),('OCT',8),('BIN',2)]:
                button = QPushButton(name, page)
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, b=radix: self.set_radix(b))
                radix_row.addWidget(button)
                self.radix_buttons[radix] = button
            layout.addLayout(radix_row)
            self.width_buttons = {}
            width_row = QHBoxLayout()
            for name,bits in [('QWORD',64),('DWORD',32),('WORD',16),('BYTE',8)]:
                button = QPushButton(name, page)
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, b=bits: self.set_width(b))
                width_row.addWidget(button)
                self.width_buttons[bits] = button
            layout.addLayout(width_row)
            self.prog_digits = {}
            grid = QGridLayout()
            grid.setSpacing(3)
            rows = [
                ['MC','MR','MS','M+','M-','Back','CE','C'],
                ['A','B','C','D','E','F','and','or'],
                ['7','8','9','/','<<','>>','xor','not'],
                ['4','5','6','*','mod','±','', ''],
                ['1','2','3','-','','','',''],
                ['0','=','+','','','','',''],
            ]
            for i,row in enumerate(rows):
                for j,name in enumerate(row):
                    if name:
                        # 'C' in hex mode is digit, while C in memory row means clear;
                        # distinguish using an explicit binding.
                        code = 'AC' if i == 0 and name == 'C' else name
                        btn = self._button(grid, i, j, name, code)
                        if i == 1 and name in 'ABCDEF':
                            self.prog_digits[name] = btn
            layout.addLayout(grid, 1)

        def set_mode(self, mode):
            self.engine.set_mode(mode)
            self.pages.setCurrentIndex(CalculatorEngine.MODES.index(mode))
            for key,act in self.mode_actions.items(): act.setChecked(key == mode)
            self._sync_programmer_controls()
            self.refresh()

        def set_angle(self, unit):
            self.engine.set_angle_mode(unit)
            for name,button in self.angle_buttons.items(): button.setChecked(name == unit)

        def set_radix(self, base):
            self.engine.set_radix(base)
            self._sync_programmer_controls()
            self.refresh()

        def set_width(self, bits):
            self.engine.set_word_bits(bits)
            self._sync_programmer_controls()
            self.refresh()

        def _sync_programmer_controls(self):
            for base,btn in self.radix_buttons.items():
                btn.setChecked(base == self.engine.radix)
            for bits,btn in self.width_buttons.items():
                btn.setChecked(bits == self.engine.word_bits)
            for digit,btn in self.prog_digits.items():
                btn.setEnabled(int(digit, 16) < self.engine.radix)

        def press(self, key):
            self.engine.press(key)
            self.refresh()

        def refresh(self):
            self.result.setText(self.engine.display_text())
            self.expression.setText(self.engine.expression)
            self.memory_indicator.setText('M' if self.engine.memory_set else '')
            self.result.setToolTip(self.engine.entry)
            if self.history_box.isVisible():
                self.history_box.setPlainText('\n'.join(
                    f'{expression}  {value}' for expression,value in self.engine.history))

        def clear_history(self):
            self.engine.history.clear()
            self.refresh()

        def toggle_history(self):
            visible = not self.history_box.isVisible()
            self.history_box.setVisible(visible)
            self.history_action.setChecked(visible)
            self.refresh()

        def copy_result(self):
            QApplication.clipboard().setText(self.engine.display_text())

        def paste_result(self):
            try:
                self.engine.input_text(QApplication.clipboard().text())
            except CalculatorError as exc:
                self.engine.error = str(exc)
            self.refresh()

        def show_about(self):
            bridge = getattr(self, 'remote_files', None)
            if bridge is not None:
                bridge.about('About Calculator', 'PythonBDE Calculator\n(c) 2026 by Jens Kallup - paule32')
                return
            QMessageBox.about(self, 'About Calculator',
                              'PythonBDE Calculator\nClassic standard, scientific and programmer modes.\n'
                              '(c) 2026 by Jens Kallup - paule32')

    return CalculatorWidget(parent)
