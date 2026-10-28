"""Weekly time-window QDockWidget with a mouse-drag-paintable timeline."""
from __future__ import annotations
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (QAbstractItemView, QButtonGroup, QDockWidget, QHBoxLayout,
                             QLabel, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from .time_windows import (DAYS, TYPES, SLOTS_PER_DAY, empty_schedule,
                           load_schedule, save_schedule, set_slot, slot_label,
                           time_window_path)

# Selected cells use a category color, with readable contrast in both themes.
COLORS = ('#2A8654', '#A16D24', '#236F9C')


class TimeWindowDock(QDockWidget):
    """Three fixed category rows, plus a read-only unassigned-time row below."""

    def __init__(self, main):
        super().__init__('Time Window', main)
        self.setObjectName('PythonBDETimeWindowDock')
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.main = main
        self.path = time_window_path(main.users.store.path)
        self.days = load_schedule(self.path)
        self.day = DAYS[0]
        self.dirty = False
        self.painting = False
        self.paint_value = ''

        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(QLabel('Select a weekday, then click or drag over 15-minute slots (00:00–24:00).'))
        days_row = QHBoxLayout()
        self.day_group = QButtonGroup(self)
        self.day_group.setExclusive(True)
        self.day_buttons = []
        for day in DAYS:
            button = QPushButton(day)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, d=day: self.select_day(d))
            self.day_group.addButton(button)
            self.day_buttons.append(button)
            days_row.addWidget(button)
        self.day_buttons[0].setChecked(True)
        layout.addLayout(days_row)
        layout.addWidget(QLabel('Fixed rows: Work-Time / Maintaine-Time / Free-Time. '
                                'Unassigned shows slots not allocated to any row.'))

        self.table = QTableWidget(4, SLOTS_PER_DAY, self)
        self.table.setObjectName('PythonBDETimeWindowGrid')
        self.table.setHorizontalHeaderLabels([f'{i // 4:02d}:{(i % 4) * 15:02d}'
                                               for i in range(SLOTS_PER_DAY)])
        self.table.setVerticalHeaderLabels([*TYPES, 'Unassigned'])
        self.table.horizontalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setDefaultSectionSize(49)
        self.table.verticalHeader().setMinimumSectionSize(35)
        self.table.verticalHeader().setFixedWidth(120)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.cellPressed.connect(self.begin_paint)
        self.table.cellEntered.connect(self.continue_paint)
        self.table.setMinimumHeight(260)
        layout.addWidget(self.table, 1)

        control = QHBoxLayout()
        self.save_button = QPushButton('Save Time Windows')
        self.clear_button = QPushButton('Clear Selected Day')
        self.save_button.clicked.connect(self.save)
        self.clear_button.clicked.connect(self.clear_day)
        self.modified_label = QLabel('Saved')
        control.addWidget(self.save_button)
        control.addWidget(self.clear_button)
        control.addWidget(self.modified_label)
        control.addStretch(1)
        layout.addLayout(control)
        self.setWidget(holder)
        self.refresh_grid()

    def select_day(self, day):
        self.day = day
        self.refresh_grid()

    def _set_color(self, item, active, row):
        if row == 3:
            item.setBackground(QBrush(QColor('#586377') if active else QColor('#26313D')))
        elif active:
            item.setBackground(QBrush(QColor(COLORS[row])))
        else:
            item.setBackground(QBrush(QColor('#E8EBEF' if row % 2 == 0 else '#CFD8DF')))

    def refresh_grid(self):
        self.table.setUpdatesEnabled(False)
        try:
            for column, value in enumerate(self.days[self.day]):
                for row in range(4):
                    item = self.table.item(row, column)
                    if item is None:
                        item = QTableWidgetItem('')
                        self.table.setItem(row, column, item)
                    item.setToolTip(f'{self.day}: {slot_label(column)} – '
                                    + ([*TYPES, 'Unassigned'][row]))
                    self._set_color(item, value == (TYPES[row] if row < 3 else ''), row)
        finally:
            self.table.setUpdatesEnabled(True)

    def _paint_cell(self, row, column):
        if row >= 3 or column < 0:
            return
        set_slot(self.days, self.day, column, self.paint_value)
        value = self.days[self.day][column]
        for index in range(4):
            self._set_color(self.table.item(index, column),
                            value == (TYPES[index] if index < 3 else ''), index)
        self.dirty = True
        self.modified_label.setText('Unsaved changes')

    def begin_paint(self, row, column):
        if row >= 3:
            return
        self.painting = True
        self.paint_value = '' if self.days[self.day][column] == TYPES[row] else TYPES[row]
        self._paint_cell(row, column)

    def continue_paint(self, row, column):
        if self.painting and row < 3:
            self._paint_cell(row, column)

    def eventFilter(self, target, event):
        if target is self.table.viewport() and event.type() == QEvent.MouseButtonRelease:
            self.painting = False
        return super().eventFilter(target, event)

    def clear_day(self):
        if QMessageBox.question(self, 'Time Window', f'Clear all entries for {self.day}?',
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.days[self.day] = [''] * SLOTS_PER_DAY
        self.dirty = True
        self.modified_label.setText('Unsaved changes')
        self.refresh_grid()

    def save(self):
        try:
            save_schedule(self.path, self.days)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Time Window', str(exc))
            return False
        self.dirty = False
        self.modified_label.setText('Saved')
        self.main.record(200, 'Time windows saved')
        return True

    def closeEvent(self, event):
        if self.dirty:
            answer = QMessageBox.question(
                self, 'Time Window', 'Save changed time windows?',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Save and not self.save():
                event.ignore()
                return
            if answer == QMessageBox.Discard:
                self.days = load_schedule(self.path)
                self.dirty = False
        super().closeEvent(event)
