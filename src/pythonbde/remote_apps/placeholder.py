"""Non-privileged visual placeholder for an approved Start menu action.

Only identifiers that are included in server-side MODULE_FILES may load this.
These entries intentionally do NOT launch programs, open local files or execute
shell commands; that requires separately designed and authorized RPC endpoints.
"""
from PyQt5.QtWidgets import QPlainTextEdit


def create_widget(parent):
    output = QPlainTextEdit(parent)
    output.setReadOnly(True)
    output.setPlainText(MODULE_TITLE + '\n\nPythonBDE remote demonstration module.\n'
                        'Additional functionality will be added in a future version.')
    return output
