import re
from typing import TYPE_CHECKING, Any, Dict

from PySide6.QtWidgets import QWidget

from config.settings import (load_default_settings, load_effective_settings, reset_applied_settings,
                             save_applied_settings)

if TYPE_CHECKING:
    from view.MainWindow import MainWindow


class SettingsPanel:

    def __init__(self, window: "MainWindow"):
        self.window = window

    def current_settings_from_ui(self) -> Dict[str, Any]:
        """Read the currently selected settings from the UI."""
        difficulty = "medium"
        if self.window.settings_window.easy_difficulty_radio.isChecked():
            difficulty = "easy"
        elif self.window.settings_window.hard_difficulty_radio.isChecked():
            difficulty = "hard"

        return {
            "font_size": self.window.settings_window.font_size_spinbox.value(),
            "ai_difficulty": difficulty,
        }

    def load_settings_into_ui(self) -> None:
        """Load persisted settings into the UI."""
        settings = load_effective_settings()
        self.window.settings_window.font_size_spinbox.blockSignals(True)
        self.window.settings_window.font_size_spinbox.setValue(int(settings["font_size"]))
        self.window.settings_window.font_size_spinbox.blockSignals(False)
        self.update_font_size_label()
        self.preview_font_size_label(int(settings["font_size"]))
        self.apply_font_size(int(settings["font_size"]))

        difficulty_buttons = {
            "easy": self.window.settings_window.easy_difficulty_radio,
            "medium": self.window.settings_window.medium_difficulty_radio,
            "hard": self.window.settings_window.hard_difficulty_radio,
        }
        difficulty_buttons.get(
            settings["ai_difficulty"],
            self.window.settings_window.medium_difficulty_radio,
        ).setChecked(True)

    def save_settings(self) -> None:
        """Save the current settings and apply them."""
        settings = self.current_settings_from_ui()
        save_applied_settings(settings)
        self.apply_font_size(int(settings["font_size"]))

    def reset_settings_to_default(self) -> None:
        """Reset settings to their default values."""
        reset_applied_settings()
        defaults = load_default_settings()
        self.window.settings_window.font_size_spinbox.setValue(int(defaults["font_size"]))
        difficulty_buttons = {
            "easy": self.window.settings_window.easy_difficulty_radio,
            "medium": self.window.settings_window.medium_difficulty_radio,
            "hard": self.window.settings_window.hard_difficulty_radio,
        }
        difficulty_buttons.get(
            defaults["ai_difficulty"],
            self.window.settings_window.medium_difficulty_radio,
        ).setChecked(True)
        self.update_font_size_label()
        self.preview_font_size_label(int(defaults["font_size"]))
        self.apply_font_size(int(defaults["font_size"]))

    def preview_font_size(self, value: int) -> None:
        """Preview the selected font size in the UI."""
        self.update_font_size_label()
        self.preview_font_size_label(value)

    def close_settings_window(self) -> None:
        """Close the settings window."""
        self.window.go_back()

    def capture_font_baselines(self) -> None:
        """Capture baseline font and size values for rescaling."""
        roots = [
            self.window,
            self.window.main_menu,
            self.window.tutor_menu,
            self.window.resource_selector_widget,
            self.window.trade_designer_widget,
            self.window.select_trade_widget,
            self.window.trade_manager_widget,
            self.window.development_manager_widget,
            self.window.results_menu,
            self.window.endgame_review_menu,
            self.window.start_menu,
            self.window.rule_window,
            self.window.settings_window,
        ]
        for root in roots:
            for widget in [root, *root.findChildren(QWidget)]:
                font = widget.font()
                point_size = font.pointSize()
                if point_size > 0 and widget.property("basePointSize") is None:
                    widget.setProperty("basePointSize", point_size)
                if widget.property("baseMinimumHeight") is None:
                    widget.setProperty("baseMinimumHeight", widget.minimumHeight())
                if widget.property("baseMaximumHeight") is None:
                    widget.setProperty("baseMaximumHeight", widget.maximumHeight())
        self.capture_static_rich_text_baselines()

    def capture_static_rich_text_baselines(self) -> None:
        """Capture the baseline HTML for static rich text widgets."""
        for widget in (self.window.start_menu.textEdit, self.window.rule_window.textEdit):
            if widget.property("baseHtml") is None:
                widget.setProperty("baseHtml", widget.toHtml())

    def apply_font_size(self, value: int) -> None:
        """Apply the selected font size across the UI."""
        delta = value - 10
        roots = [
            self.window,
            self.window.main_menu,
            self.window.tutor_menu,
            self.window.resource_selector_widget,
            self.window.trade_designer_widget,
            self.window.select_trade_widget,
            self.window.trade_manager_widget,
            self.window.development_manager_widget,
            self.window.results_menu,
            self.window.endgame_review_menu,
            self.window.start_menu,
            self.window.rule_window,
            self.window.settings_window,
        ]
        for root in roots:
            for widget in [root, *root.findChildren(QWidget)]:
                base_point_size = widget.property("basePointSize")
                if base_point_size is None:
                    continue
                font = widget.font()
                font.setPointSize(max(1, int(base_point_size) + delta))
                widget.setFont(font)
        self.adjust_widget_heights()
        self.apply_static_rich_text_font_size(delta)

    def apply_static_rich_text_font_size(self, delta: int) -> None:
        """Apply the font-size adjustment to static rich text widgets."""
        for widget in (self.window.start_menu.textEdit, self.window.rule_window.textEdit):
            base_html = widget.property("baseHtml")
            if not base_html:
                continue
            adjusted_html = re.sub(
                r"font-size:([0-9]+)pt",
                lambda match: f"font-size:{max(1, int(match.group(1)) + delta)}pt",
                str(base_html),
            )
            cursor = widget.textCursor()
            widget.setHtml(adjusted_html)
            widget.setTextCursor(cursor)

    def adjust_widget_heights(self) -> None:
        """Adjust widget heights after font scaling changes."""
        roots = [
            self.window,
            self.window.main_menu,
            self.window.tutor_menu,
            self.window.resource_selector_widget,
            self.window.trade_designer_widget,
            self.window.select_trade_widget,
            self.window.trade_manager_widget,
            self.window.development_manager_widget,
            self.window.results_menu,
            self.window.endgame_review_menu,
            self.window.start_menu,
            self.window.rule_window,
            self.window.settings_window,
        ]
        unrestricted_max_height = 16777215
        for root in roots:
            for widget in [root, *root.findChildren(QWidget)]:
                base_min_height = widget.property("baseMinimumHeight")
                if base_min_height is not None and int(base_min_height) > 0:
                    widget.setMinimumHeight(max(int(base_min_height), widget.sizeHint().height()))

                base_max_height = widget.property("baseMaximumHeight")
                if base_max_height is not None and 0 < int(base_max_height) < unrestricted_max_height:
                    widget.setMaximumHeight(max(int(base_max_height), widget.sizeHint().height()))

    def update_font_size_label(self) -> None:
        """Reset the settings font-size label text."""
        self.window.settings_window.font_size_label.setText("Font Size")

    def preview_font_size_label(self, value: int) -> None:
        """Preview the scaled font-size label styling."""
        base_point_size = self.window.settings_window.font_size_label.property("basePointSize")
        if base_point_size is None:
            return
        font = self.window.settings_window.font_size_label.font()
        font.setPointSize(max(1, int(base_point_size) + (value - 10)))
        self.window.settings_window.font_size_label.setFont(font)
