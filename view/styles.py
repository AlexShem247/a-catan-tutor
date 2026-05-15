from config.view_constants import (ENDGAME_BADGE_BORDER_RADIUS_PX, ENDGAME_BADGE_FONT_WEIGHT, ENDGAME_BADGE_PADDING,
                                   ENDGAME_FEEDBACK_CARD_BORDER_RADIUS_PX, ENDGAME_FEEDBACK_CARD_PADDING,
                                   ENDGAME_RANK_CARD_BORDER_RADIUS_PX, ENDGAME_RANK_CARD_DEFAULT_BACKGROUND_COLOR,
                                   ENDGAME_RANK_CARD_DEFAULT_BORDER_COLOR, ENDGAME_RANK_CARD_DEFAULT_BORDER_WIDTH_PX,
                                   ENDGAME_RANK_CARD_FONT_WEIGHT, ENDGAME_RANK_CARD_PADDING,
                                   ENDGAME_RANK_CARD_SELECTED_BACKGROUND_COLOR, ENDGAME_RANK_CARD_SELECTED_BORDER_COLOR,
                                   ENDGAME_RANK_CARD_SELECTED_BORDER_WIDTH_PX, PLAYER_BADGE_BORDER_RADIUS_PX,
                                   PLAYER_BADGE_FONT_WEIGHT)


def player_badge_stylesheet(
    colour: str,
    vertical_padding_px: int,
    horizontal_padding_px: int,
    font_size_px: int | None = None,
) -> str:
    font_size_style = f"font-size: {font_size_px}px;" if font_size_px is not None else ""
    return (f"background-color: {colour};"
            "color: black;"
            f"font-weight: {PLAYER_BADGE_FONT_WEIGHT};"
            f"border-radius: {PLAYER_BADGE_BORDER_RADIUS_PX}px;"
            f"padding: {vertical_padding_px}px {horizontal_padding_px}px;"
            f"{font_size_style}")


def endgame_badge_stylesheet(label: str) -> str:
    badge_base = (f"border-radius: {ENDGAME_BADGE_BORDER_RADIUS_PX}px; "
                  f"padding: {ENDGAME_BADGE_PADDING}; "
                  f"font-weight: {ENDGAME_BADGE_FONT_WEIGHT};")
    styles = {
        "Poor": f"background: #fee2e2; color: #991b1b; {badge_base}",
        "Okay": f"background: #fef3c7; color: #92400e; {badge_base}",
        "Good": f"background: #dcfce7; color: #166534; {badge_base}",
        "Excellent": f"background: #dbeafe; color: #1d4ed8; {badge_base}",
    }
    return styles.get(
        label,
        f"background: #e5e7eb; color: #374151; {badge_base}",
    )


def endgame_feedback_card_stylesheet() -> str:
    return ("QPushButton#endgameFeedbackCard {"
            "background: #e5e7eb;"
            "border: 1px solid #d1d5db;"
            f"border-radius: {ENDGAME_FEEDBACK_CARD_BORDER_RADIUS_PX}px;"
            f"padding: {ENDGAME_FEEDBACK_CARD_PADDING};"
            "text-align: left;"
            "}"
            "QPushButton#endgameFeedbackCard:hover {"
            "background: #ffffff;"
            "border: 1px solid #9ca3af;"
            "}")


def endgame_feedback_title_stylesheet() -> str:
    return "font-weight: 600; color: #111827;"


def endgame_feedback_score_stylesheet() -> str:
    return "color: #374151;"


def endgame_feedback_body_stylesheet() -> str:
    return "color: #111827;"


def endgame_feedback_empty_stylesheet() -> str:
    return "color: #6b7280;"


def tutor_feedback_action_stylesheet(colour: str) -> str:
    return f"font-weight: bold; color: {colour};"


def tutor_feedback_explanation_stylesheet(colour: str) -> str:
    return ("QTextEdit {"
            "background: transparent;"
            "border: none;"
            f"color: {colour};"
            "}")


def endgame_rank_card_stylesheet(selected: bool) -> str:
    background = (ENDGAME_RANK_CARD_SELECTED_BACKGROUND_COLOR
                  if selected else ENDGAME_RANK_CARD_DEFAULT_BACKGROUND_COLOR)
    border_colour = (ENDGAME_RANK_CARD_SELECTED_BORDER_COLOR if selected else ENDGAME_RANK_CARD_DEFAULT_BORDER_COLOR)
    border_width = (ENDGAME_RANK_CARD_SELECTED_BORDER_WIDTH_PX
                    if selected else ENDGAME_RANK_CARD_DEFAULT_BORDER_WIDTH_PX)
    return ("QPushButton#rankCard {"
            f"background: {background.name()};"
            f"border: {border_width}px solid {border_colour.name()};"
            f"border-radius: {ENDGAME_RANK_CARD_BORDER_RADIUS_PX}px;"
            f"padding: {ENDGAME_RANK_CARD_PADDING};"
            "text-align: left;"
            f"font-weight: {ENDGAME_RANK_CARD_FONT_WEIGHT};"
            "}")
