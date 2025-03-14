import sys
from PyQt6.QtWidgets import QApplication
from src.qt_gui import NewsScraperGUI

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NewsScraperGUI()
    window.show()
    sys.exit(app.exec())
