import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from html import escape
from typing import Any

from game.PlayerAssets import Buildable
from view.canvas.board_display_source import BoardDisplaySource


def move_quality_colour(label: str) -> str:
    """Return the display colour for a move-quality label."""
    if label == "Excellent":
        return "#2563eb"
    if label == "Good":
        return "#89b538"
    if label == "Poor":
        return "#b34700"
    return "#666666"


class TutorDecisionType(Enum):
    OPENING_SETTLEMENT = auto()
    OPENING_ROAD = auto()
    ROBBER = auto()
    DISCARD = auto()
    TRADE_RESPONSE = auto()
    TRADE_PARTNER = auto()
    YEAR_OF_PLENTY = auto()
    MONOPOLY = auto()
    MAIN_TURN = auto()


@dataclass
class BoardStateSnapshot(BoardDisplaySource):
    game_state: Any

    @classmethod
    def from_game(cls, game_state: Any) -> "BoardStateSnapshot":
        """Create a board snapshot from the current game state."""
        return cls(deepcopy(game_state))

    def get_ports(self):
        """Return the ports from the stored board state."""
        return self.game_state.get_ports()

    def get_all_edges(self):
        """Return the edges from the stored board state."""
        return self.game_state.get_all_edges()

    def get_all_vertices(self):
        """Return the vertices from the stored board state."""
        return self.game_state.get_all_vertices()

    def get_all_hexes(self):
        """Return the hexes from the stored board state."""
        return self.game_state.get_all_hexes()

    def get_bank_resources(self):
        """Return the bank resources from the stored board state."""
        return self.game_state.bank_resources

    def get_development_deck(self):
        """Return the development deck from the stored board state."""
        return self.game_state.development_deck

    def get_all_players(self):
        """Return the players from the stored board state."""
        return self.game_state.players


@dataclass
class TutorAssessment:
    decision_type: TutorDecisionType
    internal_score: float
    best_internal_score: float
    label: str
    judgment_sentence: str
    your_move: str
    move_context: str = ""
    better_move: str | None = None
    better_move_context: str = ""
    top_strengths: list[str] = field(default_factory=list)
    top_weaknesses: list[str] = field(default_factory=list)
    better_move_reasons: list[str] = field(default_factory=list)
    tip: str = ""

    @staticmethod
    def _normalise_display_text(text: str) -> str:
        """Normalise display text for comparison."""
        return " ".join(text.split()).strip().lower()

    @classmethod
    def _reason_core_text(cls, text: str) -> str:
        """Extract the canonical comparison text for a reason."""
        text = cls._normalise_display_text(re.sub(r"<[^>]+>", "", text or ""))
        for prefix in (
                "you miss out because ",
                "you miss out on a line that ",
                "you miss out on ",
        ):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        suffix = ", which is currently the strongest plan"
        if text.endswith(suffix):
            text = text[:-len(suffix)]
        return text.rstrip(".!?")

    @classmethod
    def _dedupe_display_texts(cls, texts: list[str]) -> list[str]:
        """Remove duplicate display texts while preserving order."""
        deduped: list[str] = []
        seen = set()
        for text in texts:
            if not text:
                continue
            key = cls._reason_core_text(text)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        return deduped

    def concise_html(self) -> str:
        """Render the concise assessment HTML."""
        label_colour = move_quality_colour(self.label)
        parts = [
            f"<span style=\"color: {label_colour};\"><b>{escape(self.label)}.</b></span> "
            f"{escape(self.judgment_sentence)}"
        ]
        if self.move_context:
            parts.append(f"<b>Resources:</b> {escape(self.move_context)}")
        if (self.better_move
                and self._normalise_display_text(self.better_move) != self._normalise_display_text(self.your_move)):
            parts.append(f"<b>Better move:</b> {escape(self.better_move)}")
            if self.better_move_context:
                parts.append(f"<b>Better move resources:</b> {escape(self.better_move_context)}")
        return "<br>".join(parts)

    def detailed_html(self) -> str:
        """Render the detailed assessment HTML."""
        parts = [f"<b>Your move:</b> {escape(self.your_move)}"]
        if self.move_context:
            parts.append(f"<b>Resources:</b> {escape(self.move_context)}")
        if (self.better_move
                and self._normalise_display_text(self.better_move) != self._normalise_display_text(self.your_move)):
            parts.append(f"<b>Better move:</b> {escape(self.better_move)}")
            if self.better_move_context:
                parts.append(f"<b>Better move resources:</b> {escape(self.better_move_context)}")

        reasons = self._dedupe_display_texts([
            *self.top_strengths[:1],
            *self.top_weaknesses[:1],
        ])
        if len(reasons) < 2:
            reasons = self._dedupe_display_texts([
                *reasons,
                *self.better_move_reasons[:1],
            ])
        if not reasons:
            reasons.append("This matched the tutor's preferred line.")
        reason_items = "".join(f"<li>&nbsp;{escape(reason)}</li>" for reason in reasons[:3])
        parts.append(f"<b>Why:</b><ul>{reason_items}</ul>")

        if self.tip:
            # Append to last element instead of adding a new one
            parts[-1] += f" <b>Takeaway:</b> {escape(self.tip)}"

        return "<br>".join(parts)

    def history_summary(self) -> str:
        """Summarise the assessment for history display."""
        better_text = f" Better move: {self.better_move}" if self.better_move else ""
        return f"[{self.label}] {self.judgment_sentence}{better_text}"

    @property
    def score_gap(self) -> float:
        """Return the score gap between the chosen and best moves."""
        return max(0.0, self.best_internal_score - self.internal_score)


@dataclass
class TutorFeedbackExplanation:
    title: str
    concise_html: str
    detailed_html: str
    label: str
    board_snapshot: BoardStateSnapshot
    visual_build_plan: list[tuple[Any, Any, Any]]
    recommended_visual_plan: list[tuple[Any, Any]]
    history_summary: str
    assessment: TutorAssessment

    @classmethod
    def from_assessment(
        cls,
        title: str,
        assessment: TutorAssessment,
        game_state: Any,
        visual_build_plan: list[tuple[Any, Any, Any]] | None = None,
    ) -> "TutorFeedbackExplanation":
        """Create a feedback explanation from an assessment."""
        return cls(
            title=title,
            concise_html=assessment.concise_html(),
            detailed_html=assessment.detailed_html(),
            label=assessment.label,
            board_snapshot=BoardStateSnapshot.from_game(game_state),
            visual_build_plan=list(visual_build_plan or []),
            recommended_visual_plan=[],
            history_summary=assessment.history_summary(),
            assessment=assessment,
        )

    def render_html(self, detailed: bool = False) -> str:
        """Render the selected feedback HTML variant."""
        return self.detailed_html if detailed else self.concise_html

    def set_visual_build(self, buildable: Any, position: Any, player_number: Any):
        """Store the visual build highlight for the feedback."""
        if buildable == Buildable.DEVELOPMENT_CARD:
            self.visual_build_plan = []
            return
        self.visual_build_plan = [(buildable, position, player_number)]

    def set_recommended_visual_plan(self, visual_plan: list[tuple[Any, Any]]):
        """Store the recommended visual plan for the feedback."""
        self.recommended_visual_plan = list(visual_plan)
