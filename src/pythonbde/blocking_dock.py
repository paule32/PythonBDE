"""Qt5 Blocking-Manager: links Regeln, rechts Bearbeitungsformular, unten Audit-Log."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
    QMenu, QMessageBox, QPlainTextEdit, QFileDialog,
)

from .blocking import TYPES, FIELDS, rule_label, BlockingError

# 'Block Domain' heißt nur der Hauptmenüeintrag; der Tree-Knoten ist 'Domain Blocking'.
NEW_BUTTONS = {
    TYPES[0]: 'IP-Range-Block', TYPES[1]: 'Port-Range-Block',
    TYPES[2]: 'IP-Block', TYPES[3]: 'Port-Block',
    TYPES[4]: 'Domain-Block', TYPES[5]: 'User-Block',
}
FIELD_LABELS = {
    TYPES[0]: ('Start IPv4', 'End IPv4'),
    TYPES[1]: ('Start Port (Client)', 'End Port (Client)'),
    TYPES[2]: ('IPv4 Address',), TYPES[3]: ('Client Source Port',),
    TYPES[4]: ('DNS Domain',), TYPES[5]: ('Username',),
}


class BlockingDock(QDockWidget):
    def __init__(self, window):
        super().__init__('Blocking', window)
        self.setObjectName('PythonBDEBlockingDock')
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.window = window
        self.current_type = TYPES[0]
        self.current_id = None
        base = QWidget(self)
        self.setWidget(base)
        layout = QVBoxLayout(base)
        layout.setContentsMargins(4, 4, 4, 4)
        self.vertical = QSplitter(Qt.Vertical, base)
        upper = QWidget(self.vertical)
        upper_lay = QVBoxLayout(upper)
        upper_lay.setContentsMargins(2, 2, 2, 2)
        # Buttons sind nach Typ gruppiert, nicht als endlose horizontale Reihe.
        for choices in (TYPES[:3], TYPES[3:]):
            row = QHBoxLayout()
            for category in choices:
                btn = QPushButton(NEW_BUTTONS[category])
                btn.clicked.connect(lambda checked=False, cat=category: self.new_rule(cat))
                row.addWidget(btn)
            row.addStretch(1)
            upper_lay.addLayout(row)

        self.horizontal = QSplitter(Qt.Horizontal, upper)
        self.tree = QTreeWidget(self.horizontal)
        self.tree.setHeaderLabel('Blocking Rules')
        self.tree.setMinimumWidth(190)
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.horizontal.addWidget(self.tree)

        right = QWidget(self.horizontal)
        right_lay = QVBoxLayout(right)
        self.heading = QLabel('IP Range Blocking')
        right_lay.addWidget(self.heading)
        self.form = QFormLayout()
        self.form_rows = []
        # Immer zwei Felder vorhalten. Einzelregeln zeigen nur das erste Feld.
        for _ in range(2):
            label = QLabel('')
            edit = QLineEdit()
            self.form.addRow(label, edit)
            self.form_rows.append((label, edit))
        right_lay.addLayout(self.form)
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        right_lay.addWidget(self.explanation)
        actions = QHBoxLayout()
        self.save_button = QPushButton('Save')
        self.delete_button = QPushButton('Delete')
        self.save_button.clicked.connect(self.save_rule)
        self.delete_button.clicked.connect(self.delete_rule)
        actions.addWidget(self.save_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        right_lay.addLayout(actions)
        right_lay.addStretch(1)
        self.horizontal.addWidget(right)
        self.horizontal.setStretchFactor(0, 1)
        self.horizontal.setStretchFactor(1, 3)
        self.horizontal.setSizes([260, 640])
        upper_lay.addWidget(self.horizontal)
        self.vertical.addWidget(upper)

        log_box = QWidget(self.vertical)
        log_lay = QVBoxLayout(log_box)
        log_lay.setContentsMargins(3, 3, 3, 3)
        log_lay.addWidget(QLabel('Server Logging (neueste zuerst)'))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        log_lay.addWidget(self.log_text)
        log_controls = QHBoxLayout()
        save_log = QPushButton('Save As ...')
        clear_log = QPushButton('Clear Text')
        save_log.clicked.connect(self.save_log)
        clear_log.clicked.connect(self.clear_log)
        log_controls.addWidget(save_log)
        log_controls.addWidget(clear_log)
        log_controls.addStretch(1)
        log_lay.addLayout(log_controls)
        self.vertical.addWidget(log_box)
        self.vertical.setStretchFactor(0, 3)
        self.vertical.setStretchFactor(1, 2)
        self.vertical.setSizes([380, 220])
        layout.addWidget(self.vertical)
        self.window.log.callbacks.append(self._append_log)
        self.refresh()
        self._render_log()

    def _append_log(self, line):
        if self.isVisible():
            self._render_log()

    def _render_log(self):
        self.log_text.setPlainText('\n'.join(self.window.log.entries))
        self.log_text.verticalScrollBar().setValue(0)

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Log As', 'python_bde_export.log',
                                              'Logs (*.log *.txt);;All Files (*)')
        if path:
            try:
                Path(path).write_text(self.log_text.toPlainText() + '\n', encoding='utf-8')
            except OSError as err:
                QMessageBox.warning(self, 'Log Export', str(err))

    def clear_log(self):
        self.window.log.clear_view()
        for panel in self.window.log_panels:
            panel._render_log()

    def refresh(self, selected_id=None):
        if selected_id is None:
            selected_id = self.current_id
        self.tree.blockSignals(True)
        self.tree.clear()
        roots = {}
        selected_node = None
        for category in TYPES:
            root = QTreeWidgetItem(self.tree, [category])
            root.setData(0, Qt.UserRole, (category, None))
            roots[category] = root
        for rule in self.window.server.blocking.listing():
            leaf = QTreeWidgetItem(roots[rule['type']], [rule_label(rule)])
            leaf.setData(0, Qt.UserRole, (rule['type'], rule['id']))
            if rule['id'] == selected_id:
                selected_node = leaf
        for root in roots.values():
            root.setExpanded(True)
        self.tree.blockSignals(False)
        if selected_node:
            self.tree.setCurrentItem(selected_node)
        elif not self.current_id:
            self._display_form(self.current_type, {})
        else:
            self.new_rule(self.current_type)

    def _display_form(self, category, values):
        self.current_type = category
        self.heading.setText(category)
        labels = FIELD_LABELS[category]
        for i, (label, widget) in enumerate(self.form_rows):
            show = i < len(labels)
            label.setVisible(show)
            widget.setVisible(show)
            if show:
                key = FIELDS[category][i]
                label.setText(labels[i])
                widget.setText(str(values.get(key, '')))
        if category in (TYPES[1], TYPES[3]):
            self.explanation.setText('Hinweis: Quellport des Clients. TCP-Clientports sind meist dynamisch; kein Filter für den Server-Listenport.')
        elif category == TYPES[4]:
            self.explanation.setText('DNS wird asynchron zu IPv4-Adressen aufgelöst und regelmäßig aktualisiert. Noch nicht aufgelöste Domains können nicht blockiert werden.')
        else:
            self.explanation.setText('Block wird bei jeder neuen Login-Anfrage geprüft. Bereits verbundene Sitzungen bleiben bestehen.')
        self.delete_button.setEnabled(bool(self.current_id))

    def new_rule(self, category):
        self.current_id = None
        self.current_type = category
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(None)
        self.tree.blockSignals(False)
        self._display_form(category, {})
        self.form_rows[0][1].setFocus()

    def _selected(self, current, _previous):
        if current is None:
            return
        category, ident = current.data(0, Qt.UserRole)
        self.current_id = ident
        data = self.window.server.blocking.rules.get(ident) if ident else None
        self._display_form(category, data['values'] if data else {})

    def _tree_menu(self, position):
        node = self.tree.itemAt(position)
        if node is None:
            return
        category, ident = node.data(0, Qt.UserRole)
        menu = QMenu(self)
        create_action = menu.addAction(NEW_BUTTONS[category])
        delete_action = None
        if ident:
            menu.addSeparator()
            delete_action = menu.addAction('Delete')
        chosen = menu.exec_(self.tree.viewport().mapToGlobal(position))
        if chosen == create_action:
            self.new_rule(category)
        elif chosen == delete_action:
            self.tree.setCurrentItem(node)
            self.delete_rule()

    def save_rule(self):
        category = self.current_type
        values = {field: self.form_rows[i][1].text().strip()
                  for i, field in enumerate(FIELDS[category])}
        try:
            rule = self.window.server.blocking.upsert(category, values, self.current_id)
            self.current_id = rule['id']
            self.window.server.refresh_blocked_domains()
            self.window.record(200, f'Blocking rule saved: {category} ({rule_label(rule)})')
            self.refresh(rule['id'])
        except (BlockingError, OSError, ValueError) as err:
            self.window.record(400, f'Blocking rule not saved: {category} ({err})')
            QMessageBox.warning(self, 'Blocking', str(err))

    def delete_rule(self):
        if not self.current_id:
            return
        rule = self.window.server.blocking.rules.get(self.current_id)
        if not rule:
            return
        if QMessageBox.question(self, 'Delete Blocking Rule',
                                f"Regel '{rule_label(rule)}' wirklich löschen?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.window.server.blocking.delete(self.current_id)
            self.window.server.refresh_blocked_domains()
            self.window.record(200, f"Blocking rule deleted: {rule['type']} ({rule_label(rule)})")
            self.current_id = None
            self.refresh()
        except (BlockingError, OSError) as err:
            QMessageBox.warning(self, 'Blocking', str(err))
