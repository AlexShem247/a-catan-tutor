from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional, List, Tuple

from ai.actions import ActionType
from ai.tutor.explanations import ActionExplanation
from ai.tutor.move_quality import move_quality_label
from game.PlayerAssets import Buildable


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
class TutorFeedbackExplanation:
    title: str
    concise_html: str
    detailed_html: str
    move_quality_label: str
    board_snapshot: BoardStateSnapshot
    visual_build_plan: List[Tuple[Any, Any, Any]]

    @classmethod
    def from_action_scores(
            cls,
            title: str,
            actual_label: str,
            actual_score: float,
            best_label: str,
            best_score: float,
            game_state: Any,
            detailed_html: Optional[str] = None,
    ) -> "TutorFeedbackExplanation":
        gap = best_score - actual_score
        concise_html = (
            f"<b>Your move:</b> {actual_label} ({actual_score:.4f})"
            f"<br><b>Tutor move:</b> {best_label} ({best_score:.4f})"
            f"<br><b>Difference:</b> {gap:.4f}"
        )
        return cls(
            title=title,
            concise_html=concise_html,
            detailed_html=detailed_html or "This feature has not been implemented yet.",
            move_quality_label=move_quality_label(actual_score),
            board_snapshot=BoardStateSnapshot.from_game(game_state),
            visual_build_plan=[],
        )

    @classmethod
    def from_action_explanations(
            cls,
            actual_explanation: Optional[ActionExplanation],
            best_explanation: Optional[ActionExplanation],
            game_state: Any,
            detailed_html: Optional[str] = None,
    ) -> Optional["TutorFeedbackExplanation"]:
        if actual_explanation is None or best_explanation is None:
            return None

        actual_title, _ = actual_explanation.generate_text_concise()
        best_title, _ = best_explanation.generate_text_concise()
        gap = best_explanation.move_quality - actual_explanation.move_quality
        concise_html = (
            f"<b>Your move:</b> {actual_title} ({actual_explanation.move_quality:.4f})"
            f"<br><b>Tutor move:</b> {best_title} ({best_explanation.move_quality:.4f})"
            f"<br><b>Difference:</b> {gap:.4f}"
        )
        return cls(
            title=actual_title,
            concise_html=concise_html,
            detailed_html=detailed_html or "This feature has not been implemented yet.",
            move_quality_label=actual_explanation.move_quality_label,
            board_snapshot=BoardStateSnapshot.from_game(game_state),
            visual_build_plan=[],
        )

    def render_html(self, detailed: bool = False) -> str:
        return self.detailed_html if detailed else self.concise_html

    def set_visual_build(self, buildable: Any, position: Any, player_number: Any):
        if buildable == Buildable.DEVELOPMENT_CARD:
            self.visual_build_plan = []
            return
        self.visual_build_plan = [(buildable, position, player_number)]
