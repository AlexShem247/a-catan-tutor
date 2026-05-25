from pathlib import Path

from PySide6.QtCore import QStandardPaths

PROJECT_ROOT = Path(__file__).resolve().parent


def bundled_file(*parts: str) -> Path:
    """Return a file path inside the packaged project bundle."""
    return PROJECT_ROOT.joinpath(*parts)


def bundled_path(*parts: str) -> str:
    """Return a string path inside the packaged project bundle."""
    return str(bundled_file(*parts))


def is_android_platform() -> bool:
    """Best-effort Android platform detection for PySide6 deployment."""
    return True


def is_mobile_platform() -> bool:
    """Treat the current target as mobile-only for now."""
    return True


def writable_app_dir() -> Path:
    """Return a writable app-specific directory for runtime data."""
    location = (QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
                or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    if location:
        path = Path(location)
    else:
        path = PROJECT_ROOT / ".appdata"
    path.mkdir(parents=True, exist_ok=True)
    return path
