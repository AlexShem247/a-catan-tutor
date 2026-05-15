import re
from html import escape, unescape
from typing import Iterable, Mapping

from config.view_constants import TUTOR_ICON, TUTOR_WINDOW_ICON_SIZE_PX, TUTOR_WINDOW_TITLE_ICON_PADDING_LEFT_PX


def tutor_window_title_html(icon_path: str = TUTOR_ICON) -> str:
    return ("<html><body><table cellpadding='0' cellspacing='0'><tr>"
            f"<td valign='middle'><img src='{icon_path}' width='{TUTOR_WINDOW_ICON_SIZE_PX}' "
            f"height='{TUTOR_WINDOW_ICON_SIZE_PX}'></td>"
            f"<td valign='middle' style='padding-left:{TUTOR_WINDOW_TITLE_ICON_PADDING_LEFT_PX}px;'>"
            "<span style='font-weight:700;'>Tutor Window</span></td>"
            "</tr></table></body></html>")


def player_breakdown_html(player_name: str, breakdown: Mapping[str, int]) -> str:
    breakdown_text = (f"Cities: {breakdown['cities']} pts<br />"
                      f"Settlements: {breakdown['settlements']} pts<br />"
                      f"Longest Road: {breakdown['longest_road']} pts<br />"
                      f"Largest Army: {breakdown['largest_army']} pts<br />"
                      f"Victory Card Points: {breakdown['victory_cards']} pts")
    return ("<html><head/><body>"
            "<p style=\"margin: 0;\"><span style=\"font-weight: 600;\">"
            f"Selected: {escape(player_name)} breakdown ▼"
            "</span><br />"
            f"{breakdown_text}"
            "</p></body></html>")


def winner_title_html(
    winner_name: str,
    winner_total_vp: int,
) -> str:
    return ("<html><head/><body><p style=\"margin: 0;\">"
            f"<span style=\"font-weight:700;\">Winner: {escape(winner_name)}</span><br/>"
            f"{winner_total_vp} victory points"
            "</p></body></html>")


def concise_explanation_html(
    concise_explanation: str,
    quality_label: str,
    move_quality_colour_value: str,
) -> str:
    return (f"{concise_explanation}"
            "<br><br><b>Move Quality:</b> "
            f"<span style=\"color: {move_quality_colour_value};\"><b>{escape(quality_label)}</b></span>")


def tutor_focus_html(focus_points: Iterable[str]) -> str:
    focus_items = "".join(f"<li>{escape(point)}</li>" for point in focus_points)
    return f"<b>What matters here:</b><ul>{focus_items}</ul>"


def strip_html_to_plain_text(text: str) -> str:
    cleaned = unescape(text or "")
    cleaned = cleaned.replace("<br/>", "\n").replace("<br />", "\n").replace("<br>", "\n")
    cleaned = cleaned.replace("</p>", "\n").replace("</li>", "\n")
    cleaned = cleaned.replace("<li>", "- ")
    cleaned = cleaned.replace("<ul>", "").replace("</ul>", "")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)
