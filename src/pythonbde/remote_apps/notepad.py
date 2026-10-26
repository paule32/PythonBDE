"""Sample trusted module: Notepad – edits in memory, no remote file writes."""
from PyQt5.QtWidgets import QPlainTextEdit


def create_widget(parent):
    editor = QPlainTextEdit(parent)
    editor.setPlaceholderText('Notepad – remote compiled PythonBDE module')
    return editor
