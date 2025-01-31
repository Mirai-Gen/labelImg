from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class LightWidget(QSpinBox):

    def __init__(self, title, value=50):
        super(LightWidget, self).__init__()
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setRange(0, 100)
        self.setSuffix(' %')
        self.setValue(value)
        self.setToolTip(title)
        self.setStatusTip(self.toolTip())
        self.setAlignment(Qt.AlignCenter)

    def minimumSizeHint(self):
        height = super(LightWidget, self).minimumSizeHint().height()
        fm = QFontMetrics(self.font())
        width = fm.horizontalAdvance(str(self.maximum()))
        return QSize(width, height)

    def color(self):
        if self.value() == 50:
            return None

        strength = int(self.value()/100 * 255 + 0.5)
        return QColor(strength, strength, strength)

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    widget = LightWidget("Hola")
    widget.show()
    sys.exit(app.exec())