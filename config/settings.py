import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "default_settings.json"
APPLIED_SETTINGS_PATH = CONFIG_DIR / "applied_settings.json"
AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES: dict[str, float] = {
    "easy": 0.70,
    "medium": 0.85,
    "hard": 1.00,
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_default_settings() -> dict[str, Any]:
    return _read_json(DEFAULT_SETTINGS_PATH)


def load_applied_settings() -> dict[str, Any]:
    if not APPLIED_SETTINGS_PATH.exists():
        return {}
    return _read_json(APPLIED_SETTINGS_PATH)


def load_effective_settings() -> dict[str, Any]:
    settings = load_default_settings()
    settings.update(load_applied_settings())
    return settings


def save_applied_settings(settings: dict[str, Any]) -> None:
    default_settings = load_default_settings()
    overrides = {key: value for key, value in settings.items() if default_settings.get(key) != value}

    if not overrides:
        reset_applied_settings()
        return

    with APPLIED_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(overrides, handle, indent=2)
        handle.write("\n")


def reset_applied_settings() -> None:
    if APPLIED_SETTINGS_PATH.exists():
        APPLIED_SETTINGS_PATH.unlink()
