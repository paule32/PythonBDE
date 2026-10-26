"""Sample trusted module: calculator (basic arithmetic, no eval)."""
from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout


def create_widget(parent):
    box = QWidget(parent)
    layout = QVBoxLayout(box)
    layout.addWidget(QLabel('Add two numbers:'))
    first = QLineEdit(box)
    first.setPlaceholderText('First number')
    second = QLineEdit(box)
    second.setPlaceholderText('Second number')
    output = QLabel('', box)
    button = QPushButton('Add', box)

    def calculate():
        try:
            output.setText(str(float(first.text()) + float(second.text())))
        except ValueError:
            output.setText('Please enter valid numbers')

    button.clicked.connect(calculate)
    for widget in (first, second, button, output):
        layout.addWidget(widget)
    return box
