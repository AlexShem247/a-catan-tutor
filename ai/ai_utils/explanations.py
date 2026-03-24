from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List

from ai.ai_utils.actions import Action, ActionType


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


@dataclass
class Reason:
    type: ReasonType
    label: str
    value: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateExplanation:
    action: Action
    full_plan: List[Action]

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

    confidence: float = 0.0
    confidence_label: str = "medium"

    assumptions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def generate_text_concise(self) -> str:
        """Return a short explanation suitable for live gameplay."""
        action_text = self._action_to_text(self.chosen_candidate.action)
        reason_text = self._top_reason_sentence(self.chosen_candidate.reasons_for, limit=2)

        if reason_text:
            text = f"{action_text}. {reason_text}."
        else:
            text = f"{action_text}."

        return text

    def generate_text_comparative(self) -> str:
        """Return an explanation contrasting the chosen action with alternatives."""
        chosen = self.chosen_candidate
        action_text = self._action_to_text(chosen.action)
        reason_text = self._top_reason_sentence(chosen.reasons_for, limit=2)

        if reason_text:
            text = f"I recommend {action_text.lower()} because {reason_text}."
        else:
            text = f"I recommend {action_text.lower()}."

        if self.alternatives:
            best_alt = max(self.alternatives, key=lambda c: c.utility_total)
            alt_text = self._action_to_text(best_alt.action)

            chosen_gap = chosen.utility_total - best_alt.utility_total
            if chosen_gap > 0:
                text += f" A strong alternative was {alt_text.lower()}, " \
                        f"but it gave less overall value in this position."
            else:
                text += f" A strong alternative was {alt_text.lower()}, and this was a close decision."

        return text

    def generate_text_teaching(self) -> str:
        """Return a more tutor-like explanation with strategic interpretation."""
        chosen = self.chosen_candidate
        action_text = self._action_to_text(chosen.action)

        parts: List[str] = [f"I recommend {action_text.lower()}.", self._strategic_intro(chosen.action)]

        top_reasons = self._sorted_reasons(chosen.reasons_for)[:3]
        if top_reasons:
            reason_sentences = [self._reason_to_teaching_text(r) for r in top_reasons]
            parts.extend(reason_sentences)

        if self.alternatives:
            best_alt = max(self.alternatives, key=lambda c: c.utility_total)
            alt_text = self._action_to_text(best_alt.action)
            parts.append(f"An alternative was {alt_text.lower()}, but it was less suitable in this state.")

        if self.assumptions:
            parts.append(f"This recommendation is based on {self.assumptions[0].lower()}.")

        return " ".join(p for p in parts if p)

    def _action_to_text(self, action: Action) -> str:
        """Convert an Action into a short human-readable phrase."""
        if action.type == ActionType.ROLL:
            return "Roll the dice"

        if action.type == ActionType.END_TURN:
            return "End your turn"

        if action.type == ActionType.BUY_DEV_CARD:
            return "Buy a development card"

        if action.type == ActionType.PLAY_DEV_CARD:
            payload = action.payload
            if hasattr(payload, "name"):
                return f"Play a {payload.name.lower()} card"
            return "Play a development card"

        if action.type == ActionType.TRADE_WITH_BANK:
            return "Trade with the bank"

        if action.type == ActionType.TRADE_WITH_PLAYER:
            return "Propose a player trade"

        if action.type == ActionType.BUILD:
            payload = action.payload
            if isinstance(payload, tuple) and len(payload) >= 1:
                buildable = payload[0]
                if hasattr(buildable, "name"):
                    return f"Build a {buildable.name.lower()}"
            return "Build"

        return "Take this action"

    def _sorted_reasons(self, reasons: List[Reason]) -> List[Reason]:
        """Return reasons sorted by descending importance."""
        return sorted(reasons, key=lambda r: r.value, reverse=True)

    def _top_reason_sentence(self, reasons: List[Reason], limit: int = 2) -> str:
        """Return the top reasons joined into a single sentence fragment."""
        top = self._sorted_reasons(reasons)[:limit]
        labels = [self._reason_label_to_phrase(r.label) for r in top if r.label]

        if not labels:
            return ""

        if len(labels) == 1:
            return labels[0]

        if len(labels) == 2:
            return f"{labels[0]} and {labels[1]}"

        return ", ".join(labels[:-1]) + f", and {labels[-1]}"

    def _reason_label_to_phrase(self, label: str) -> str:
        """Normalise a reason label into a sentence-friendly phrase."""
        if not label:
            return ""

        label = label.strip()
        if not label:
            return ""

        first = label[0].lower() + label[1:]
        return first

    def _strategic_intro(self, action: Action) -> str:
        """Return a tutor-style strategic description of the action type."""
        if action.type == ActionType.BUILD:
            return "This is a strategic building decision that affects both your current position" \
                   " and your future development."

        if action.type == ActionType.BUY_DEV_CARD:
            return "Development cards can create hidden value and add flexibility to your longer-term plan."

        if action.type == ActionType.PLAY_DEV_CARD:
            return "Playing a development card is useful when its immediate effect improves" \
                   " your position more than waiting."

        if action.type == ActionType.TRADE_WITH_BANK:
            return "Bank trades are useful when converting surplus resources into ones that unblock stronger plans."

        if action.type == ActionType.TRADE_WITH_PLAYER:
            return "Player trades are useful when they accelerate your plan without helping an opponent too much."

        if action.type == ActionType.ROLL:
            return "No stronger pre-roll action was preferred, so progressing the turn is best."

        if action.type == ActionType.END_TURN:
            return "No available action provided enough value to justify spending resources or changing position."

        return ""

    def _reason_to_teaching_text(self, reason: Reason) -> str:
        """Convert a structured reason into a slightly more educational sentence."""
        if reason.type == ReasonType.FASTEST_PROGRESS:
            return "This action was preferred because it improves your expected progress toward winning more" \
                   " than the other available options."

        if reason.type == ReasonType.QUICK_TO_EXECUTE:
            return "It is also attractive because it can be completed relatively quickly with" \
                   " your expected resource flow."

        if reason.type == ReasonType.IMPROVES_PRODUCTION:
            return "Improving production matters because stronger resource income supports more future options."

        if reason.type == ReasonType.IMPROVES_RESOURCE_DIVERSITY:
            return "Resource diversity is valuable because it reduces dependence on a narrow set of dice outcomes."

        if reason.type == ReasonType.ENABLES_EXPANSION:
            return "This move also helps expansion, which can improve future settlement opportunities."

        if reason.type == ReasonType.ADVANCES_LONGEST_ROAD:
            return "It contributes toward Longest Road, which can become an efficient source of extra victory points."

        if reason.type == ReasonType.ADVANCES_LARGEST_ARMY:
            return "It contributes toward Largest Army, which can become an important tempo swing later in the game."

        if reason.type == ReasonType.SLOWS_LEADING_OPPONENT:
            return "A further advantage is that it slows the current leading opponent, reducing their momentum."

        if reason.type == ReasonType.REQUIRES_TRADE:
            return "This recommendation depends on using a trade to make the preferred plan feasible."

        if reason.type == ReasonType.HIDDEN_VALUE:
            return "This option has hidden value because its full benefit depends on uncertain future outcomes."

        if reason.type == ReasonType.AVOIDS_EARLY_ATTENTION:
            return "It also avoids attracting unnecessary early attention from opponents."

        if reason.type == ReasonType.HEURISTIC_CHOICE:
            return "This decision comes from a simpler heuristic rule rather than a deeper comparative evaluation."

        return self._reason_label_to_phrase(reason.label).capitalize() + "."
