import json
from pathlib import Path
from typing import Any, Dict

from app_runtime import bundled_file, writable_app_dir

DEFAULT_SETTINGS_PATH = bundled_file("config", "default_settings.json")
AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES: Dict[str, float] = {
    "easy": 0.70,
    "medium": 0.85,
    "hard": 1.00,
}


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_default_settings() -> Dict[str, Any]:
    return _read_json(DEFAULT_SETTINGS_PATH)


def get_applied_settings_path() -> Path:
    """Return the writable settings override path."""
    return writable_app_dir() / "applied_settings.json"


def load_applied_settings() -> Dict[str, Any]:
    applied_settings_path = get_applied_settings_path()
    if not applied_settings_path.exists():
        return {}
    return _read_json(applied_settings_path)


def load_effective_settings() -> Dict[str, Any]:
    settings = load_default_settings()
    settings.update(load_applied_settings())
    return settings


def save_applied_settings(settings: Dict[str, Any]) -> None:
    default_settings = load_default_settings()
    overrides = {key: value for key, value in settings.items() if default_settings.get(key) != value}

    if not overrides:
        reset_applied_settings()
        return

    applied_settings_path = get_applied_settings_path()
    with applied_settings_path.open("w", encoding="utf-8") as handle:
        json.dump(overrides, handle, indent=2)
        handle.write("\n")


def reset_applied_settings() -> None:
    applied_settings_path = get_applied_settings_path()
    if applied_settings_path.exists():
        applied_settings_path.unlink()
