from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Tuple

from ai.actions import Action, ActionType
from ai.tutor.move_quality import clamp_move_quality, move_quality_label, tutor_move_quality_label
from game.PlayerAssets import Buildable
from game.Resources import ResourceCount


class ReasonType(Enum):
    FASTEST_PROGRESS = auto()
    QUICK_TO_EXECUTE = auto()
    IMPROVES_PRODUCTION = auto()
    IMPROVES_RESOURCE_DIVERSITY = auto()
    ENABLES_EXPANSION = auto()
    ADVANCES_LONGEST_ROAD = auto()
    ADVANCES_LARGEST_ARMY = auto()
    SLOWS_LEADING_OPPONENT = auto()
    REQUIRES_TRADE = auto()
    HIDDEN_VALUE = auto()
    AVOIDS_EARLY_ATTENTION = auto()
    HEURISTIC_CHOICE = auto()


class ReasonLabel(Enum):
    PLAN_SETTLEMENT_VALUE = auto()
    PLAN_CITY_VALUE = auto()
    PLAN_ROAD_VALUE = auto()
    QUICK_GENERIC = auto()
    QUICK_PLANNED_BUILD = auto()
    QUICK_PLANNED_DEV_BUY = auto()
    QUICK_PLANNED_DEV_PLAY = auto()
    QUICK_PLANNED_FOLLOW_UP = auto()
    QUICK_KNIGHT = auto()
    QUICK_ROAD_BUILDING = auto()
    QUICK_YEAR_OF_PLENTY = auto()
    QUICK_MONOPOLY = auto()
    SLOWS_LEADER = auto()
    ADVANCES_LONGEST_ROAD = auto()
    ADVANCES_LARGEST_ARMY = auto()
    REQUIRES_TRADE = auto()
    HIDDEN_DEV_VALUE = auto()
    EARLY_ATTENTION_RISK = auto()
    NO_IMMEDIATE_ACTION = auto()
    PRE_ROLL_NO_DEV_PLAY = auto()
    INIT_EARLY_PRODUCTION = auto()
    INIT_RESOURCE_DIVERSITY = auto()
    INIT_HIGH_FREQUENCY = auto()
    INIT_PORT_ACCESS = auto()
    INIT_COMPLEMENTS_FIRST = auto()
    INIT_ROAD_CONNECTION = auto()
    INIT_ROAD_TO_SETTLEMENT = auto()
    INIT_ROAD_TO_BALANCE = auto()
    INIT_ROAD_FLEXIBLE = auto()
    TRADE_PARTNER_BEST_ETW = auto()
    TRADE_PARTNER_COUNTER_VALUE = auto()
    TRADE_PARTNER_SAFE_OPPONENT = auto()
    TRADE_RESPONSE_ACCEPT_VALUE = auto()
    TRADE_RESPONSE_COUNTER_VALUE = auto()
    TRADE_RESPONSE_REJECT_NO_GAIN = auto()
    TRADE_RESPONSE_REJECT_RISK = auto()
    ROBBER_BLOCKS_KEY_HEX = auto()
    ROBBER_TARGETS_THREAT = auto()
    ROBBER_AVOIDS_OWN_HEX = auto()
    DISCARD_PROTECTS_PLAN = auto()
    DISCARD_USES_SURPLUS = auto()
    YOP_FILLS_SHORTFALL = auto()
    YOP_SUPPORTS_FOLLOW_UP = auto()
    YOP_FLEXIBLE_PICK = auto()
    MONOPOLY_HIGHEST_DEMAND = auto()
    MONOPOLY_FLEXIBLE_PICK = auto()


class ExplanationTemplate(Enum):
    INITIAL_SETTLEMENT = auto()
    INITIAL_ROAD = auto()
    TRADE_PARTNER = auto()
    TRADE_RESPONSE = auto()
    ROBBER_TARGET = auto()
    DISCARD_RESOURCES = auto()
    YEAR_OF_PLENTY_RESOURCES = auto()
    MONOPOLY_RESOURCE = auto()


class RoadExplanationKind(Enum):
    CONNECTION = auto()
    EXPANSION = auto()
    FLEXIBLE = auto()


class AssumptionCode(Enum):
    PRE_ROLL_DEV_ONLY = auto()
    NO_CANDIDATE_ACTION = auto()
    FILTERED_CANDIDATES = auto()
    EXPECTED_PRODUCTION = auto()
    LEGALITY_AND_AFFORDABILITY = auto()


@dataclass
class Reason:
    type: ReasonType
    label: Any
    value: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateExplanation:
    action: Action
    full_plan: List[Action]
    next_plan: List[Action] = field(default_factory=list)
    waiting_resources: ResourceCount = field(default_factory=dict)

    etb: float = 0.0
    etw_before: float = 0.0
    etw_after: float = 0.0
    etw_delta: float = 0.0

    utility_total: float = 0.0
    utility_self: float = 0.0
    utility_opponent: float = 0.0
    utility_special: float = 0.0
    utility_attention: float = 0.0

    expected_vp_gain: float = 0.0

    reasons_for: List[Reason] = field(default_factory=list)
    reasons_against: List[Reason] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionExplanation:
    chosen_action: Action
    chosen_candidate: CandidateExplanation
    alternatives: List[CandidateExplanation] = field(default_factory=list)

    move_quality: float = 0.0

    assumptions: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.move_quality = clamp_move_quality(self.move_quality)

    @property
    def move_quality_label(self) -> str:
        """Return the user-facing label for the move quality."""
        return move_quality_label(self.move_quality)

    @property
    def tutor_move_quality_label(self) -> str:
        """Return the tutor-facing label for the move quality."""
        return tutor_move_quality_label(self.move_quality)

    def generate_text_concise(self) -> Tuple[str, str]:
        """Generate the concise explanation text."""
        from ai.tutor.explanation_text import generate_text_concise

        return generate_text_concise(self)

    def generate_text_detail(self) -> str:
        """Generate the detailed explanation text."""
        from ai.tutor.explanation_text import generate_text_detail

        return generate_text_detail(self)

    def describe_action(self, action: Action | None = None, short: bool = True) -> str:
        """Describe the action for display."""
        from ai.tutor.explanation_formatting import action_to_text

        return action_to_text(action or self.chosen_action, short=short)

    def describe_reason(self, reason: Reason, detail: bool = True) -> str:
        """Describe a reason for display."""
        from ai.tutor.explanation_formatting import describe_reason

        return describe_reason(self, reason, detail)

    def strongest_plan_focus_phrase(self) -> str:
        """Return the strongest-plan focus phrase."""
        from ai.tutor.explanation_formatting import strongest_plan_focus_phrase

        return strongest_plan_focus_phrase(self)

    def sorted_reasons_for(self) -> List[Reason]:
        """Return the supporting reasons sorted for display."""
        from ai.tutor.explanation_formatting import sorted_reasons

        return sorted_reasons(self.chosen_candidate.reasons_for)

    def sorted_reasons_against(self) -> List[Reason]:
        """Return the opposing reasons sorted for display."""
        from ai.tutor.explanation_formatting import sorted_reasons

        return sorted_reasons(self.chosen_candidate.reasons_against)

    def get_visual_build_plan(self) -> List[Tuple]:
        """Return the visual build plan for the explanation."""
        custom_plan = self.metadata.get("visual_plan") or self.chosen_candidate.metadata.get("visual_plan")
        if isinstance(custom_plan, list):
            return custom_plan

        source_plan = self.chosen_candidate.full_plan
        if self.chosen_action.type == ActionType.END_TURN and self.chosen_candidate.next_plan:
            source_plan = self.chosen_candidate.next_plan

        return [
            action.payload for action in source_plan
            if action.type == ActionType.BUILD and action.payload[0] != Buildable.DEVELOPMENT_CARD
        ]
