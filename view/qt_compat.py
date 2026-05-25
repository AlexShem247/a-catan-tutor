import warnings
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget


def load_ui(path: str) -> QWidget:
    """Load a Qt Designer .ui file using PySide6."""
    ui_file = QFile(str(Path(path)))
    if not ui_file.open(QIODevice.OpenModeFlag.ReadOnly):
        raise FileNotFoundError(f"Unable to open UI file: {path}")

    try:
        widget = QUiLoader().load(ui_file)
    finally:
        ui_file.close()

    if widget is None:
        raise RuntimeError(f"Unable to load UI file: {path}")
    return widget


def disconnect_signal(signal, slot=None) -> None:
    """Disconnect a Qt signal while suppressing PySide6 no-op warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            if slot is None:
                signal.disconnect()
            else:
                signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass
