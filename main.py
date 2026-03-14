from __future__ import annotations

import sys
import os

# Add src directory to path so sibling packages resolve correctly
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont

from config import AppConfig, ConfigError
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Load config
    try:
        config = AppConfig.load()
    except ConfigError as e:
        # Show error dialog before any window opens
        msg = QMessageBox()
        msg.setWindowTitle("Configuration Error")
        msg.setText(str(e))
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()
        sys.exit(1)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
