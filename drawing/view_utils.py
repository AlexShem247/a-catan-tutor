from typing import TYPE_CHECKING

from PyQt6.QtCore import pyqtBoundSignal, QEventLoop, QTimer

if TYPE_CHECKING:
    from drawing.View import View


def select_blocking(view: "View", signal: pyqtBoundSignal, draw_fn, *args, **kwargs):
    """Block execution until the signal emits a value, then return that value."""
    loop = QEventLoop()
    selected = None

    def on_selected(obj):
        nonlocal selected
        selected = obj
        loop.quit()

    # Disconnect all previous handlers safely
    try:
        signal.disconnect()
    except TypeError:
        pass

    # Connect the new handler
    signal.connect(on_selected)

    draw_fn(*args, **kwargs)

    loop.exec()

    # Clean up
    try:
        signal.disconnect(on_selected)
    except TypeError:
        pass

    view.canvas.clear_interactives()

    return selected


def ai_time_delay(seconds: int):
    if seconds > 0:
        loop = QEventLoop()

        QTimer.singleShot(int(seconds * 1000), loop.quit)

        loop.exec()
