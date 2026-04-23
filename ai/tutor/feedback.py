from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from html import escape
from typing import Any, List, Optional, Tuple

from game.PlayerAssets import Buildable


def move_quality_colour(label: str) -> str:
    if label == "Excellent":
        return "#248f24"
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
class BoardStateSnapshot:
    game_state: Any

    @classmethod
    def from_game(cls, game_state: Any) -> "BoardStateSnapshot":
        return cls(deepcopy(game_state))

    def get_ports(self):
        return self.game_state.get_ports()

    def get_all_edges(self):
        return self.game_state.get_all_edges()

    def get_all_vertices(self):
        return self.game_state.get_all_vertices()

    def get_all_hexes(self):
        return self.game_state.get_all_hexes()

    def get_bank_resources(self):
        return self.game_state.bank_resources

    def get_development_deck(self):
        return self.game_state.development_deck

    def get_all_players(self):
        return self.game_state.players


@dataclass
class TutorAssessment:
    decision_type: TutorDecisionType
    internal_score: float
    best_internal_score: float
    label: str
    judgment_sentence: str
    your_move: str
    better_move: Optional[str] = None
    top_strengths: List[str] = field(default_factory=list)
    top_weaknesses: List[str] = field(default_factory=list)
    better_move_reasons: List[str] = field(default_factory=list)
    tip: str = ""

    @staticmethod
    def _normalise_display_text(text: str) -> str:
        return " ".join(text.split()).strip().lower()

    @classmethod
    def _dedupe_display_texts(cls, texts: List[str]) -> List[str]:
        deduped: List[str] = []
        seen = set()
        for text in texts:
            if not text:
                continue
            key = cls._normalise_display_text(text)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        return deduped

    def concise_html(self) -> str:
        label_colour = move_quality_colour(self.label)
        parts = [
            f"<span style=\"color: {label_colour};\"><b>{escape(self.label)}.</b></span> "
            f"{escape(self.judgment_sentence)}"
        ]
        if (self.better_move and self._normalise_display_text(self.better_move) !=
                self._normalise_display_text(self.your_move)):
            parts.append(f"<b>Better move:</b> {escape(self.better_move)}")
        return "<br>".join(parts)

    def detailed_html(self) -> str:
        parts = [f"<b>Your move:</b> {escape(self.your_move)}"]
        if (self.better_move and self._normalise_display_text(self.better_move) !=
                self._normalise_display_text(self.your_move)):
            parts.append(f"<b>Better move:</b> {escape(self.better_move)}")

        reasons = self._dedupe_display_texts([
            *self.top_strengths[:1],
            *self.top_weaknesses[:1],
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
        better_text = f" Better move: {self.better_move}" if self.better_move else ""
        return f"[{self.label}] {self.judgment_sentence}{better_text}"

    @property
    def score_gap(self) -> float:
        return max(0.0, self.best_internal_score - self.internal_score)


@dataclass
class TutorFeedbackExplanation:
    title: str
    concise_html: str
    detailed_html: str
    label: str
    board_snapshot: BoardStateSnapshot
    visual_build_plan: List[Tuple[Any, Any, Any]]
    recommended_visual_plan: List[Tuple[Any, Any]]
    history_summary: str
    assessment: TutorAssessment

    @classmethod
    def from_assessment(
            cls,
            title: str,
            assessment: TutorAssessment,
            game_state: Any,
            visual_build_plan: Optional[List[Tuple[Any, Any, Any]]] = None,
    ) -> "TutorFeedbackExplanation":
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
        return self.detailed_html if detailed else self.concise_html

    def set_visual_build(self, buildable: Any, position: Any, player_number: Any):
        if buildable == Buildable.DEVELOPMENT_CARD:
            self.visual_build_plan = []
            return
        self.visual_build_plan = [(buildable, position, player_number)]

    def set_recommended_visual_plan(self, visual_plan: List[Tuple[Any, Any]]):
        self.recommended_visual_plan = list(visual_plan)
