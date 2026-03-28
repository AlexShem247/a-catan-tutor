from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Tuple

from ai.ai_utils.actions import Action, ActionType
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

    confidence: float = 0.0
    confidence_label: str = "medium"

    assumptions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def generate_text_concise(self) -> Tuple[str, str]:
        action_text = self._action_to_text(self.chosen_candidate.action, short=True)
        if self.chosen_candidate.action.type == ActionType.END_TURN and self.chosen_candidate.next_plan:
            reason_text = self._end_turn_concise_reason(self.chosen_candidate)
        elif self.chosen_candidate.action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            reason_text = self._trade_concise_reason(self.chosen_candidate, limit=2)
        else:
            reason_text = self._top_reason_sentence(self.chosen_candidate.reasons_for, limit=2)
        return action_text.title(), reason_text.capitalize() if reason_text else ""

    def generate_text_detail(self) -> str:
        candidate = self.chosen_candidate
        plan = candidate.full_plan

        if candidate.action.type == ActionType.END_TURN and candidate.next_plan:
            return self._end_turn_plan_text(candidate)

        if not plan:
            return "There is no clear plan for this move."

        if len(plan) == 1:
            action_text = self._action_to_text(plan[0], short=False)
            opening = f"The idea is to {action_text.lower()}."
            benefit = self._final_benefit_text(candidate)
            closing = self._plan_timing_text(candidate)

            parts = [opening, benefit]
            if closing:
                parts.append(closing)

            return "<br><br>".join(parts)

        parts: List[str] = []

        trade_opening = self._trade_opening_text(plan)
        if trade_opening:
            parts.append(trade_opening)
        else:
            first_step = self._action_to_text(plan[0], short=False)
            parts.append(f"The plan starts by {self._gerund_phrase(plan[0], first_step)}.")

        for i in range(1, len(plan)):
            current = plan[i]

            if i == len(plan) - 1:
                final_text = self._action_to_text(current, short=False)
                parts.append(f"That sets up the final step: {final_text}.")
            else:
                mid_text = self._action_to_text(current, short=False)
                parts.append(f"After that, the next step is to {mid_text.lower()}.")

        if not trade_opening:
            link_text = self._plan_linking_text(plan)
            if link_text:
                parts.append(link_text)

        parts.append(self._final_benefit_text(candidate))

        timing = self._plan_timing_text(candidate)
        if timing:
            parts.append(timing)

        return "<br><br>".join(p for p in parts if p)

    def _end_turn_plan_text(self, candidate: CandidateExplanation) -> str:
        next_plan = candidate.next_plan
        next_step = next_plan[0]
        next_step_text = self._action_to_text(next_step, short=False)
        parts = [f"The best immediate move is to end the turn and keep saving for this plan: {next_step_text}."]

        final_action = next_plan[-1]
        if final_action != next_step:
            final_text = self._action_to_text(final_action, short=False)
            parts.append(f"The current milestone after saving is {final_text.lower()}.")

        waiting_text = self._resource_count_text(candidate.waiting_resources)
        if waiting_text:
            parts.append(f"The resources still missing for that plan are {waiting_text}.")

        benefit = self._final_benefit_text(candidate)
        if benefit:
            parts.append(benefit)

        timing = self._plan_timing_text(candidate)
        if timing:
            parts.append(timing)

        return "<br><br>".join(parts)

    def _end_turn_concise_reason(self, candidate: CandidateExplanation) -> str:
        next_step = candidate.next_plan[0]
        next_step_text = self._action_to_text(next_step, short=False).lower()
        return f"end turn so we can save resources for {next_step_text}"

    def _action_to_text(self, action: Action, short: bool = True) -> str:
        if action.type == ActionType.ROLL:
            return "roll the dice"

        if action.type == ActionType.END_TURN:
            return "end the turn"

        if action.type == ActionType.BUY_DEV_CARD:
            return "buy a development card"

        if action.type == ActionType.PLAY_DEV_CARD:
            payload = action.payload
            if hasattr(payload, "name"):
                return f"play a {payload.name.lower()} card"
            return "play a development card"

        if action.type == ActionType.TRADE_WITH_BANK:
            if short:
                return "trade with the bank"
            return self._bank_trade_text(action)

        if action.type == ActionType.TRADE_WITH_PLAYER:
            if short:
                return "propose a trade"
            return self._player_trade_text(action)

        if action.type == ActionType.BUILD:
            return self._build_text(action, short=short)

        return "take this action"

    def _build_text(self, action: Action, short: bool = True) -> str:
        payload = action.payload
        if not isinstance(payload, tuple) or len(payload) < 1:
            return "build"

        buildable = payload[0]
        position = payload[1] if len(payload) > 1 else None

        if not hasattr(buildable, "name"):
            return "build"

        build_name = buildable.name.lower()

        if short or position is None:
            if build_name == "road":
                return "build a road"
            if build_name == "settlement":
                return "build a settlement"
            if build_name == "city":
                return "build a city"
            return f"build a {build_name}"

        pos_text = self._position_text(position)

        if build_name == "road":
            return f"build a road {pos_text}"
        if build_name == "settlement":
            return f"build a settlement {pos_text}"
        if build_name == "city":
            return f"build a city {pos_text}"

        return f"build a {build_name} {pos_text}"

    def _bank_trade_text(self, action: Action) -> str:
        payload = action.payload
        if not isinstance(payload, tuple) or len(payload) != 2:
            return "trade with the bank"

        selling, buying = payload
        sell_text = self._resource_count_text(selling)
        buy_text = self._resource_count_text(buying)

        if sell_text and buy_text:
            return f"trade {sell_text} with the bank for {buy_text}"
        return "trade with the bank"

    def _player_trade_text(self, action: Action) -> str:
        payload = action.payload
        if not isinstance(payload, tuple) or len(payload) != 2:
            return "propose a player trade"

        selling, buying = payload
        sell_text = self._resource_count_text(selling)
        buy_text = self._resource_count_text(buying)

        if sell_text and buy_text:
            return f"offer {sell_text} in exchange for {buy_text}"
        return "propose a player trade"

    def _resource_count_text(self, rc: Dict[Any, int]) -> str:
        if not rc:
            return ""

        parts: List[str] = []
        for resource, amount in rc.items():
            if amount <= 0:
                continue

            name = getattr(resource, "name", str(resource)).lower()
            if amount == 1:
                parts.append(f"1 {name}")
            else:
                parts.append(f"{amount} {name}")

        if not parts:
            return ""

        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        return ", ".join(parts[:-1]) + f", and {parts[-1]}"

    def _position_text(self, pos: Any) -> str:
        if pos is None:
            return ""

        raw = str(pos).strip()
        if not raw:
            return ""

        lowered = raw.lower()

        if lowered.startswith("path"):
            return f"toward {raw}"
        if lowered.startswith("empty"):
            return f"at {raw}"

        return f"at {raw}"

    def _gerund_phrase(self, action: Action, action_text: str) -> str:
        if action.type == ActionType.BUILD:
            payload = action.payload
            if isinstance(payload, tuple) and len(payload) >= 1:
                buildable = payload[0]
                if hasattr(buildable, "name"):
                    name = buildable.name.lower()
                    if name in ("road", "settlement", "city"):
                        return action_text.lower().replace("build", "building", 1)

        if action.type == ActionType.BUY_DEV_CARD:
            return "buying a development card"

        if action.type == ActionType.PLAY_DEV_CARD:
            return action_text.lower().replace("play", "playing", 1)

        if action.type == ActionType.TRADE_WITH_BANK:
            return action_text.lower().replace("trade", "trading", 1)

        if action.type == ActionType.TRADE_WITH_PLAYER:
            if action_text.lower().startswith("offer "):
                return f"offering {action_text[len('offer '):].lower()}"
            return action_text.lower().replace("propose", "proposing", 1)

        if action.type == ActionType.ROLL:
            return "rolling the dice"

        if action.type == ActionType.END_TURN:
            return "ending the turn"

        return action_text.lower()

    def _trade_opening_text(self, plan: List[Action]) -> str:
        if len(plan) < 2:
            return ""

        first_action = plan[0]
        if first_action.type not in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            return ""

        first_text = self._action_to_text(first_action, short=False)
        target_name = self._buildable_name(plan[-1])

        if target_name:
            article = "an" if target_name[0].lower() in "aeiou" else "a"
            return (f"The plan starts by {self._gerund_phrase(first_action, first_text)} to save up for"
                    f" {article} {target_name}.")

        return f"The plan starts by {self._gerund_phrase(first_action, first_text)}."

    def _plan_linking_text(self, plan: List[Action]) -> str:
        if not plan:
            return ""

        final_action = plan[-1]

        if final_action.type == ActionType.BUILD:
            payload = final_action.payload
            if isinstance(payload, tuple) and len(payload) >= 1:
                buildable = payload[0]
                if hasattr(buildable, "name"):
                    name = buildable.name.lower()

                    if name == "settlement":
                        return "The earlier steps matter because they create access to that settlement opportunity."
                    if name == "city":
                        return ("The earlier steps matter because they support a stronger upgrade at the end of the "
                                "plan.")
                    if name == "road":
                        return ("The earlier steps matter because they improve your position before committing to that "
                                "road.")

        if final_action.type == ActionType.BUY_DEV_CARD:
            return "The earlier steps matter because they make it easier to invest in a flexible longer-term option."

        if final_action.type == ActionType.PLAY_DEV_CARD:
            return "The earlier steps matter because they prepare the position before using the card effect."

        return "The earlier steps matter because they make the final move stronger than taking it in isolation."

    def _buildable_name(self, action: Action) -> str:
        if action.type != ActionType.BUILD:
            return ""

        payload = action.payload
        if not isinstance(payload, tuple) or len(payload) < 1:
            return ""

        buildable = payload[0]
        if not hasattr(buildable, "name"):
            return ""

        return buildable.name.lower()

    def _plan_timing_text(self, candidate: CandidateExplanation) -> str:
        if candidate.etb <= 0:
            return ""

        if candidate.etb <= 2:
            return "This is a plan that should become available quite quickly."
        if candidate.etb <= 5:
            return "This is a realistic plan to work toward over the next few turns."
        if candidate.etb <= 9:
            return "This is more of a medium-term plan, but it offers a strong payoff."
        return "This is a slower plan, but it was still judged to give the best long-term payoff."

    def _sorted_reasons(self, reasons: List[Reason]) -> List[Reason]:
        return sorted(reasons, key=lambda r: r.value, reverse=True)

    def _top_reason_sentence(self, reasons: List[Reason], limit: int = 2) -> str:
        top = self._sorted_reasons(reasons)[:limit]
        return self._reason_sentence_from_ordered(top)

    def _reason_sentence_from_ordered(self, reasons: List[Reason]) -> str:
        labels = [self._normalise_reason_label(r.label) for r in reasons if r.label]

        if not labels:
            return ""

        if len(labels) == 1:
            return labels[0]

        if len(labels) == 2:
            return f"{labels[0]} and {labels[1]}"

        return ", ".join(labels[:-1]) + f", and {labels[-1]}"

    def _trade_concise_reason(self, candidate: CandidateExplanation, limit: int = 2) -> str:
        ordered: List[Reason] = []
        ordered.extend(
            reason for reason in candidate.reasons_for
            if reason.type == ReasonType.REQUIRES_TRADE
        )
        ordered.extend(
            reason for reason in self._sorted_reasons(candidate.reasons_for)
            if reason.type != ReasonType.REQUIRES_TRADE
        )
        return self._reason_sentence_from_ordered(ordered[:limit])

    def _normalise_reason_label(self, label: str) -> str:
        if not label:
            return ""
        label = label.strip()
        if not label:
            return ""
        return label[0].lower() + label[1:]

    def _final_benefit_text(self, candidate: CandidateExplanation) -> str:
        top_reasons = [
            reason for reason in self._sorted_reasons(candidate.reasons_for)
            if reason.type != ReasonType.REQUIRES_TRADE
        ][:3]

        if not top_reasons:
            return "This final move is the strongest option here."

        reason_phrases = [self._reason_to_detail_phrase(reason) for reason in top_reasons]

        if len(reason_phrases) == 1:
            joined = reason_phrases[0]
        elif len(reason_phrases) == 2:
            joined = f"{reason_phrases[0]} and {reason_phrases[1]}"
        else:
            joined = ", ".join(reason_phrases[:-1]) + f", and {reason_phrases[-1]}"

        return f"This is strong because {joined}."

    def _reason_to_detail_phrase(self, reason: Reason) -> str:
        if reason.type == ReasonType.FASTEST_PROGRESS:
            return "it gives the best overall progress"

        if reason.type == ReasonType.QUICK_TO_EXECUTE:
            return "it can be reached fairly quickly"

        if reason.type == ReasonType.IMPROVES_PRODUCTION:
            return "it improves future resource production"

        if reason.type == ReasonType.IMPROVES_RESOURCE_DIVERSITY:
            return "it improves resource balance"

        if reason.type == ReasonType.ENABLES_EXPANSION:
            return "it opens up future expansion"

        if reason.type == ReasonType.ADVANCES_LONGEST_ROAD:
            return "it strengthens progress toward Longest Road"

        if reason.type == ReasonType.ADVANCES_LARGEST_ARMY:
            return "it strengthens progress toward Largest Army"

        if reason.type == ReasonType.SLOWS_LEADING_OPPONENT:
            return "it also slows the current leader"

        if reason.type == ReasonType.REQUIRES_TRADE:
            return ""

        if reason.type == ReasonType.HIDDEN_VALUE:
            return "it adds useful hidden value"

        if reason.type == ReasonType.AVOIDS_EARLY_ATTENTION:
            return "it avoids drawing too much early attention"

        if reason.type == ReasonType.HEURISTIC_CHOICE:
            return "it fits the strongest available plan"

        return self._normalise_reason_label(reason.label)
