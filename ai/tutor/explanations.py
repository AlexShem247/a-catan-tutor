from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Tuple

from ai.actions import Action, ActionType
from game.PlayerAssets import Buildable, DevelopmentCardType
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


def capitalise(text: str) -> str:
    if not text:
        return ""
    return text[0].upper() + text[1:]


def confidence_label(confidence: float) -> str:
    if confidence >= 15.0:
        return "high"
    if confidence >= 5.0:
        return "medium"
    return "low"


@dataclass
class ActionExplanation:
    chosen_action: Action
    chosen_candidate: CandidateExplanation
    alternatives: List[CandidateExplanation] = field(default_factory=list)

    confidence: float = 0.0
    confidence_label: str = "medium"

    assumptions: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def generate_text_concise(self) -> Tuple[str, str]:
        template = self._explanation_template()
        if template == ExplanationTemplate.INITIAL_SETTLEMENT:
            return self._initial_settlement_concise()
        if template == ExplanationTemplate.INITIAL_ROAD:
            return self._initial_road_concise()
        if template == ExplanationTemplate.TRADE_PARTNER:
            return self._trade_partner_concise()
        if template == ExplanationTemplate.TRADE_RESPONSE:
            return self._trade_response_concise()
        if template == ExplanationTemplate.ROBBER_TARGET:
            return self._robber_target_concise()
        if template == ExplanationTemplate.DISCARD_RESOURCES:
            return self._discard_resources_concise()
        if template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
            return self._year_of_plenty_concise()
        if template == ExplanationTemplate.MONOPOLY_RESOURCE:
            return self._monopoly_resource_concise()

        action_text = capitalise(self._action_to_text(self.chosen_candidate.action, short=True))
        if self.chosen_candidate.action.type == ActionType.END_TURN and self.chosen_candidate.next_plan:
            reason_text = self._end_turn_concise_reason(self.chosen_candidate)
        elif self.chosen_candidate.action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            reason_text = self._trade_concise_reason(self.chosen_candidate, limit=2)
        else:
            reason_text = self._top_reason_sentence(self.chosen_candidate.reasons_for, limit=2)
        return action_text.title(), capitalise(reason_text) if reason_text else ""

    def generate_text_detail(self) -> str:
        template = self._explanation_template()
        if template == ExplanationTemplate.INITIAL_SETTLEMENT:
            return self._initial_settlement_detail()
        if template == ExplanationTemplate.INITIAL_ROAD:
            return self._initial_road_detail()
        if template == ExplanationTemplate.TRADE_PARTNER:
            return self._trade_partner_detail()
        if template == ExplanationTemplate.TRADE_RESPONSE:
            return self._trade_response_detail()
        if template == ExplanationTemplate.ROBBER_TARGET:
            return self._robber_target_detail()
        if template == ExplanationTemplate.DISCARD_RESOURCES:
            return self._discard_resources_detail()
        if template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
            return self._year_of_plenty_detail()
        if template == ExplanationTemplate.MONOPOLY_RESOURCE:
            return self._monopoly_resource_detail()

        candidate = self.chosen_candidate
        plan = candidate.full_plan

        if candidate.action.type == ActionType.END_TURN and candidate.next_plan:
            return self._end_turn_plan_text(candidate)

        if not plan:
            return "There is no clear plan for this move."

        if len(plan) == 1:
            action_text = self._action_to_text(plan[0], short=False)
            opening = f"The idea is to {action_text}."
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
                parts.append(f"After that, the next step is to {mid_text}.")

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
            parts.append(f"The current milestone after saving is {final_text}.")

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
        next_step_text = self._action_to_text(next_step, short=False)
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
                return f"play a {self._display_name(payload)} card"
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
            return self._build_text(action)

        return "take this action"

    def _explanation_template(self) -> Any:
        return self.metadata.get("template") or self.chosen_candidate.metadata.get("template")

    def _build_text(self, action: Action) -> str:
        payload = action.payload
        if not isinstance(payload, tuple) or len(payload) < 1:
            return "build"

        buildable = payload[0]

        if not hasattr(buildable, "name"):
            return "build"

        build_name = buildable.name.upper()
        return f"build a {self._highlight_buildable(build_name)}"

    def _display_name(self, value: Any) -> str:
        name = getattr(value, "name", str(value))
        return name.replace("_", " ").title()

    def _initial_settlement_concise(self) -> Tuple[str, str]:
        vertex = self.chosen_candidate.metadata.get("target_vertex")
        intersection = self._vertex_intersection_text(vertex)
        return "Place A Settlement Here", f"Place your settlement at the intersection of {intersection}."

    def _initial_road_concise(self) -> Tuple[str, str]:
        return "Place A Road Here", self._initial_road_target_sentence()

    def _initial_settlement_detail(self) -> str:
        vertex = self.chosen_candidate.metadata.get("target_vertex")
        parts = [
            f"The idea is to place your settlement at the intersection of {self._vertex_intersection_text(vertex)}."
        ]
        port = self.chosen_candidate.metadata.get("port")
        port_text = self._port_reason_text(port)
        if port_text:
            parts.append(port_text)
        parts.append(self._detail_sentence_from_reasons(self.chosen_candidate.reasons_for))
        return "<br><br>".join(parts)

    def _initial_road_detail(self) -> str:
        parts = [f"The idea is to {self._initial_road_target_sentence().lower()}",
                 self._detail_sentence_from_reasons(self.chosen_candidate.reasons_for)]
        return "<br><br>".join(parts)

    def _initial_road_target_sentence(self) -> str:
        target_vertex = self.chosen_candidate.metadata.get("target_vertex")
        kind = self.chosen_candidate.metadata.get("road_explanation_kind")
        if kind == RoadExplanationKind.CONNECTION:
            return "Place your road back toward your other settlement to keep the opening connected."
        if kind == RoadExplanationKind.EXPANSION and target_vertex is not None:
            return (f"Place your road so you can expand toward the "
                    f"{self._vertex_intersection_text(target_vertex)} settlement spot.")
        return "Place your road where it keeps your opening flexible."

    def _trade_partner_concise(self) -> Tuple[str, str]:
        partner_name = self.chosen_candidate.metadata.get("partner_name", "this player")
        payment = self.chosen_candidate.metadata.get("payment")
        buying = self.chosen_candidate.metadata.get("buying")
        exchange = self._trade_exchange_text(payment, buying)
        if exchange:
            return "Choose This Trade Partner", f"Trade with {partner_name}: {exchange}."
        return "Choose This Trade Partner", f"Trade with {partner_name}."

    def _trade_partner_detail(self) -> str:
        partner_name = self.chosen_candidate.metadata.get("partner_name", "this player")
        payment = self.chosen_candidate.metadata.get("payment")
        buying = self.chosen_candidate.metadata.get("buying")
        if self.alternatives:
            opening = f"The best trade partner is {partner_name}."
        else:
            opening = f"Trade with {partner_name}."
        exchange = self._trade_exchange_text(payment, buying)
        if exchange:
            opening += f" The trade would be {exchange}."

        reasons = self._trade_detail_sentence_from_reasons(self.chosen_candidate.reasons_for)
        parts = [opening, reasons]
        return "<br><br>".join(part for part in parts if part)

    def _trade_response_concise(self) -> Tuple[str, str]:
        decision = self.chosen_candidate.metadata.get("decision")
        opponent_name = self.chosen_candidate.metadata.get("opponent_name", "the other player")
        offered = self.chosen_candidate.metadata.get("selling_to_us")
        requested = self.chosen_candidate.metadata.get("payment")

        if decision == "accept":
            exchange = self._trade_exchange_text(requested, offered)
            return "Accept This Trade", f"Accept {opponent_name}'s trade: {exchange}."
        if decision == "counter":
            counter_payment = self.chosen_candidate.metadata.get("counter_payment")
            exchange = self._trade_exchange_text(counter_payment, offered)
            return "Counter This Trade", f"Counter {opponent_name} with {exchange}."
        return "Reject This Trade", f"Reject {opponent_name}'s offer."

    def _trade_response_detail(self) -> str:
        decision = self.chosen_candidate.metadata.get("decision")
        opponent_name = self.chosen_candidate.metadata.get("opponent_name", "the other player")
        offered = self.chosen_candidate.metadata.get("selling_to_us")
        requested = self.chosen_candidate.metadata.get("payment")
        counter_payment = self.chosen_candidate.metadata.get("counter_payment")

        if decision == "accept":
            opening = f"Accept the trade from {opponent_name}."
            exchange = self._trade_exchange_text(requested, offered)
            if exchange:
                opening += f" The exchange is {exchange}."
        elif decision == "counter":
            opening = f"Counter the trade from {opponent_name}."
            if counter_payment:
                exchange = self._trade_exchange_text(counter_payment, offered)
                opening += f" Ask for {exchange} instead."
        else:
            opening = f"Reject the trade from {opponent_name}."
            exchange = self._trade_exchange_text(requested, offered)
            if exchange:
                opening += f" The offered exchange is {exchange}."

        reasons = self._trade_detail_sentence_from_reasons(self.chosen_candidate.reasons_for)
        parts = [opening, reasons]
        return "<br><br>".join(part for part in parts if part)

    def _trade_detail_sentence_from_reasons(self, reasons: List[Reason]) -> str:
        if not reasons:
            return "This is the best trade available here."
        phrases = [self._reason_to_detail_phrase(reason) for reason in reasons[:3]]
        phrases = [phrase for phrase in phrases if phrase]
        if not phrases:
            return "This is the best trade available here."
        if len(phrases) == 1:
            joined = phrases[0]
        elif len(phrases) == 2:
            joined = f"{phrases[0]} and {phrases[1]}"
        else:
            joined = ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
        return f"This is better because {joined}."

    def _robber_target_concise(self) -> Tuple[str, str]:
        target_player = self.chosen_candidate.metadata.get("target_player_name")
        if target_player:
            return "Move The Robber Here", f"Move the robber to this tile and steal from {target_player} if possible."
        return "Move The Robber Here", "Move the robber to this tile."

    def _robber_target_detail(self) -> str:
        parts = []
        target_player = self.chosen_candidate.metadata.get("target_player_name")
        if target_player:
            parts.append(f"Move the robber to the highlighted tile and target {target_player} if possible.")
        else:
            parts.append("Move the robber to the highlighted tile.")
        parts.append(self._detail_sentence_from_reasons(self.chosen_candidate.reasons_for))
        return "<br><br>".join(part for part in parts if part)

    def _discard_resources_concise(self) -> Tuple[str, str]:
        discard = self.chosen_candidate.metadata.get("discard_resources", {})
        discard_text = self._resource_count_text(discard)
        if discard_text:
            return "Discard These Resources", f"Discard {discard_text}."
        return "Discard These Resources", "Discard the highlighted resources."

    def _discard_resources_detail(self) -> str:
        discard = self.chosen_candidate.metadata.get("discard_resources", {})
        discard_text = self._resource_count_text(discard)
        protected_plan = self._discard_protected_plan_text()
        parts = []
        if discard_text:
            parts.append(f"Discard {discard_text}.")
        else:
            parts.append("Discard the highlighted resources.")
        if protected_plan:
            parts.append(protected_plan)
        parts.append(self._detail_sentence_from_reasons(self.chosen_candidate.reasons_for))
        return "<br><br>".join(part for part in parts if part)

    def _year_of_plenty_concise(self) -> Tuple[str, str]:
        selected = self.chosen_candidate.metadata.get("selected_resources", {})
        selected_text = self._resource_count_text(selected)
        if selected_text:
            return "Take These Resources", f"Take {selected_text} from the bank."
        return "Take These Resources", "Take the highlighted resources from the bank."

    def _year_of_plenty_detail(self) -> str:
        selected = self.chosen_candidate.metadata.get("selected_resources", {})
        selected_text = self._resource_count_text(selected)
        primary_action = self.chosen_candidate.metadata.get("primary_action")
        follow_up_action = self.chosen_candidate.metadata.get("follow_up_action")
        supports_follow_up = bool(self.chosen_candidate.metadata.get("supports_follow_up"))
        already_had_next_step = bool(self.chosen_candidate.metadata.get("already_had_next_step"))
        parts = []
        if selected_text:
            parts.append(f"Take {selected_text} from the bank.")
        else:
            parts.append("Take the highlighted resources from the bank.")

        primary_text = self._follow_up_action_text(primary_action)
        follow_up_text = self._follow_up_action_text(follow_up_action)
        if supports_follow_up and follow_up_text:
            parts.append(f"This supports {follow_up_text}.")
        elif already_had_next_step:
            if primary_text and follow_up_text and primary_text != follow_up_text:
                parts.append(
                    f"We already have enough resources for {primary_text}. "
                    f"These picks prepare {follow_up_text}."
                )
            elif primary_text:
                parts.append(
                    f"We already have enough resources for {primary_text}. "
                    "These picks prepare what comes after that."
                )
            elif follow_up_text:
                parts.append(
                    "We already have enough resources for the next step. "
                    f"These picks prepare {follow_up_text}."
                )
        elif follow_up_text:
            parts.append(f"These resources work toward {follow_up_text}.")
        else:
            parts.append("These resources improve your resource balance for the next plan step.")

        parts.append(self._detail_sentence_from_reasons(self.chosen_candidate.reasons_for))
        return "<br><br>".join(part for part in parts if part)

    def _monopoly_resource_concise(self) -> Tuple[str, str]:
        selected_resource = self.chosen_candidate.metadata.get("selected_resource")
        resource_name = getattr(selected_resource, "name", "resource").replace("_", " ").upper()
        return "Choose This Resource", f"Choose <b>{resource_name}</b> for Monopoly."

    def _monopoly_resource_detail(self) -> str:
        selected_resource = self.chosen_candidate.metadata.get("selected_resource")
        resource_name = getattr(selected_resource, "name", "resource").replace("_", " ").upper()
        parts = [f"Choose <b>{resource_name}</b> as the Monopoly resource.",
                 self._detail_sentence_from_reasons(self.chosen_candidate.reasons_for)]
        return "<br><br>".join(part for part in parts if part)

    def _discard_protected_plan_text(self) -> str:
        protected_action = self.chosen_candidate.metadata.get("protected_action")
        if not isinstance(protected_action, Action):
            return ""

        if protected_action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            trade_target_resources = self.chosen_candidate.metadata.get("trade_target_resources", [])
            trade_follow_up_action = self.chosen_candidate.metadata.get("trade_follow_up_action")
            resource_text = self._resource_list_text(trade_target_resources)
            if isinstance(trade_follow_up_action, Action):
                follow_up_text = self._follow_up_action_text(trade_follow_up_action)
                if resource_text and follow_up_text:
                    return (f"This keeps your plan to trade for {resource_text} available "
                            f"so you can work toward {follow_up_text}.")
            if resource_text:
                return f"This keeps your plan to trade for {resource_text} available."

        next_text = self._follow_up_action_text(protected_action)
        if next_text:
            return f"This keeps your stronger follow-up plan available: {next_text}."
        return ""

    def _follow_up_action_text(self, action: Any) -> str:
        if not isinstance(action, Action):
            return ""
        if action.type == ActionType.BUILD and isinstance(action.payload, tuple) and len(action.payload) >= 1:
            buildable = action.payload[0]
            if hasattr(buildable, "name"):
                article = "an" if buildable.name.lower()[0] in "aeiou" else "a"
                return f"the next thing we want to build: {article} {buildable.name.lower()}"
        if action.type == ActionType.BUY_DEV_CARD:
            return "the next thing we want to do: buy a development card"
        if action.type == ActionType.PLAY_DEV_CARD:
            return "the next thing we want to do: play a development card"
        if action.type == ActionType.TRADE_WITH_BANK:
            return "the next thing we want to do: make a bank trade"
        if action.type == ActionType.TRADE_WITH_PLAYER:
            return "the next thing we want to do: make a player trade"
        return "the next thing we want to do"

    def _resource_list_text(self, resources: List[Any]) -> str:
        names = [f"<b>{getattr(resource, 'name', str(resource)).upper()}</b>" for resource in resources]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return ", ".join(names[:-1]) + f", and {names[-1]}"

    def _vertex_intersection_text(self, vertex: Any) -> str:
        if vertex is None or not getattr(vertex, "hexes", None):
            return "the available tiles"
        descriptions = [self._hex_description(hex_tile) for hex_tile in sorted(
            [hex_tile for hex_tile in vertex.hexes if getattr(hex_tile, "resource", None) is not None],
            key=lambda hex_tile: self._dice_probability(hex_tile.production_number), reverse=True
        )]
        if not descriptions:
            return "the available tiles"
        if len(descriptions) == 1:
            return descriptions[0]
        if len(descriptions) == 2:
            return f"{descriptions[0]} and {descriptions[1]}"
        return ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"

    def _hex_description(self, hex_tile: Any) -> str:
        name = getattr(getattr(hex_tile, "type", None), "name", "tile").lower()
        if name.endswith("s"):
            name = name[:-1]
        if getattr(hex_tile, "production_number", None) in (6, 8):
            return f"high-yield {name}"
        return name

    def _port_reason_text(self, port: Any) -> str:
        if port is None:
            return ""
        if getattr(port, "name", "") == "THREE_TO_ONE":
            label = "a 3:1 port"
        else:
            label = f"the {port.name.replace('_', ' ').title()} port"
        return f"It also keeps {label} available if you want extra trading flexibility later."

    def _detail_sentence_from_reasons(self, reasons: List[Reason]) -> str:
        if not reasons:
            return "This is the strongest available setup choice here."
        phrases = [self._reason_to_detail_phrase(reason) for reason in reasons[:3]]
        phrases = [phrase for phrase in phrases if phrase]
        if not phrases:
            return "This is the strongest available setup choice here."
        if len(phrases) == 1:
            joined = phrases[0]
        elif len(phrases) == 2:
            joined = f"{phrases[0]} and {phrases[1]}"
        else:
            joined = ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
        return f"This is strong because {joined}."

    def _dice_probability(self, number: Any) -> float:
        probs = {
            2: 1 / 36, 3: 2 / 36, 4: 3 / 36, 5: 4 / 36, 6: 5 / 36,
            8: 5 / 36, 9: 4 / 36, 10: 3 / 36, 11: 2 / 36, 12: 1 / 36,
        }
        return probs.get(number, 0.0)

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

            name = getattr(resource, "name", str(resource)).upper()
            formatted = f"<b>{amount} {name}</b>"
            parts.append(formatted)

        if not parts:
            return ""

        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        return ", ".join(parts[:-1]) + f", and {parts[-1]}"

    def _trade_exchange_text(self, payment: Dict[Any, int], buying: Dict[Any, int]) -> str:
        pay_text = self._resource_count_text(payment)
        receive_text = self._resource_count_text(buying)
        if pay_text and receive_text:
            return f"give {pay_text} for {receive_text}"
        if receive_text:
            return f"receive {receive_text}"
        if pay_text:
            return f"give {pay_text}"
        return ""

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
                        return action_text.replace("build", "building", 1)

        if action.type == ActionType.BUY_DEV_CARD:
            return "buying a development card"

        if action.type == ActionType.PLAY_DEV_CARD:
            return action_text.replace("play", "playing", 1)

        if action.type == ActionType.TRADE_WITH_BANK:
            return action_text.replace("trade", "trading", 1)

        if action.type == ActionType.TRADE_WITH_PLAYER:
            if action_text.startswith("offer "):
                return f"offering {action_text[len('offer '):]}"
            return action_text.replace("propose", "proposing", 1)

        if action.type == ActionType.ROLL:
            return "rolling the dice"

        if action.type == ActionType.END_TURN:
            return "ending the turn"

        return action_text

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
            return (
                f"The plan starts by {self._gerund_phrase(first_action, first_text)} "
                f"to save up for {article} {target_name.lower()}."
            )

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
                        return f"The earlier steps matter because they create access to that settlement opportunity."
                    if name == "city":
                        return (f"The earlier steps matter because they support a stronger city "
                                f"upgrade at the end of the plan.")
                    if name == "road":
                        return (f"The earlier steps matter because they improve your position before "
                                f"committing to that road.")

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

        return buildable.name

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
        labels = [self._normalise_reason_label(self._reason_label_text(r)) for r in reasons if r.label]

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

    def _reason_label_text(self, reason: Reason) -> str:
        label = reason.label
        metadata = reason.metadata

        if label == ReasonLabel.PLAN_SETTLEMENT_VALUE:
            return "Leads to a valuable settlement and improves your position"
        if label == ReasonLabel.PLAN_CITY_VALUE:
            return "Upgrades a strong location and improves future production"
        if label == ReasonLabel.PLAN_ROAD_VALUE:
            return "Improves your road network and opens future expansion"
        if label == ReasonLabel.QUICK_GENERIC:
            return "Can be executed relatively quickly"
        if label == ReasonLabel.QUICK_PLANNED_BUILD:
            return f"Gets to the planned {metadata.get('build_name', 'build')} relatively quickly"
        if label == ReasonLabel.QUICK_PLANNED_DEV_BUY:
            return "Gets to the planned development-card purchase relatively quickly"
        if label == ReasonLabel.QUICK_PLANNED_DEV_PLAY:
            return "Sets up the planned card play relatively quickly"
        if label == ReasonLabel.QUICK_PLANNED_FOLLOW_UP:
            return "Gets to the planned follow-up relatively quickly"
        if label == ReasonLabel.QUICK_KNIGHT:
            return "Uses the Knight to move the robber and grow your army"
        if label == ReasonLabel.QUICK_ROAD_BUILDING:
            return "Uses Road Building for an immediate two-road swing"
        if label == ReasonLabel.QUICK_YEAR_OF_PLENTY:
            return "Uses Year Of Plenty to take the exact 2 resources you need"
        if label == ReasonLabel.QUICK_MONOPOLY:
            return "Uses Monopoly for a potentially large resource swing"
        if label == ReasonLabel.SLOWS_LEADER:
            return "Slows the current leading opponent"
        if label == ReasonLabel.ADVANCES_LONGEST_ROAD:
            return "Advances progress toward Longest Road"
        if label == ReasonLabel.ADVANCES_LARGEST_ARMY:
            return "Advances progress toward Largest Army"
        if label == ReasonLabel.REQUIRES_TRADE:
            return "Uses a trade to make the preferred plan feasible"
        if label == ReasonLabel.HIDDEN_DEV_VALUE:
            return "Has hidden strategic value through development-card outcomes"
        if label == ReasonLabel.EARLY_ATTENTION_RISK:
            return "May expose an early lead and attract attention"
        if label == ReasonLabel.NO_IMMEDIATE_ACTION:
            return "No legal immediate action was worth taking before saving more resources"
        if label == ReasonLabel.PRE_ROLL_NO_DEV_PLAY:
            return "No beneficial pre-roll development-card play was identified"
        if label == ReasonLabel.INIT_EARLY_PRODUCTION:
            return "it improves your early production"
        if label == ReasonLabel.INIT_RESOURCE_DIVERSITY:
            return "it improves your resource diversity"
        if label == ReasonLabel.INIT_HIGH_FREQUENCY:
            return "it puts you on strong high-frequency numbers right away"
        if label == ReasonLabel.INIT_PORT_ACCESS:
            port = metadata.get("port")
            if port is None:
                port_name = "port"
            elif getattr(port, "name", "") == "THREE_TO_ONE":
                port_name = "a 3:1 port"
            else:
                port_name = f"the {port.name.replace('_', ' ').title()} port"
            return f"it keeps {port_name} access in play"
        if label == ReasonLabel.INIT_COMPLEMENTS_FIRST:
            return "it complements your first settlement with missing resources"
        if label == ReasonLabel.INIT_ROAD_CONNECTION:
            return "it keeps your two starting settlements better connected"
        if label == ReasonLabel.INIT_ROAD_TO_SETTLEMENT:
            return "it opens a route toward a strong follow-up settlement"
        if label == ReasonLabel.INIT_ROAD_TO_BALANCE:
            return "it points your network toward more balanced future resources"
        if label == ReasonLabel.INIT_ROAD_FLEXIBLE:
            return "it keeps your road network flexible"
        if label == ReasonLabel.TRADE_PARTNER_BEST_ETW:
            return "it gives the strongest trade improvement for your position"
        if label == ReasonLabel.TRADE_PARTNER_COUNTER_VALUE:
            return "the counter-offer keeps more of your own resources while staying worthwhile"
        if label == ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT:
            return "it avoids giving too much help to a dangerous opponent"
        if label == ReasonLabel.TRADE_RESPONSE_ACCEPT_VALUE:
            return "it improves your plan more than refusing the trade"
        if label == ReasonLabel.TRADE_RESPONSE_COUNTER_VALUE:
            return "a smaller payment keeps the trade useful without giving away too much"
        if label == ReasonLabel.TRADE_RESPONSE_REJECT_NO_GAIN:
            return "waiting is better than accepting this trade as offered"
        if label == ReasonLabel.TRADE_RESPONSE_REJECT_RISK:
            return "the trade helps a dangerous opponent too much"
        if label == ReasonLabel.ROBBER_BLOCKS_KEY_HEX:
            return "it blocks an important opposing resource tile"
        if label == ReasonLabel.ROBBER_TARGETS_THREAT:
            return "it pressures the most dangerous opponent on that tile"
        if label == ReasonLabel.ROBBER_AVOIDS_OWN_HEX:
            return "it avoids hurting your own production more than necessary"
        if label == ReasonLabel.DISCARD_PROTECTS_PLAN:
            return "it protects the resources needed for your best next plan"
        if label == ReasonLabel.DISCARD_USES_SURPLUS:
            return "it throws away surplus resources first"
        if label == ReasonLabel.YOP_FILLS_SHORTFALL:
            return "it gives you the missing resources for your best next plan"
        if label == ReasonLabel.YOP_SUPPORTS_FOLLOW_UP:
            follow_up_action = metadata.get("follow_up_action")
            follow_up_text = self._follow_up_action_text(follow_up_action)
            if follow_up_text.startswith("the next thing we want to build: "):
                return f"it moves you closer to {follow_up_text[len('the next thing we want to build: '):]}"
            if follow_up_text:
                return f"it supports {follow_up_text}"
            return "it supports your next follow-up plan"
        if label == ReasonLabel.YOP_FLEXIBLE_PICK:
            return "there is no clear priority resource, so flexibility is more valuable here"
        if label == ReasonLabel.MONOPOLY_HIGHEST_DEMAND:
            return "it is the resource most opponents are likely to need next"
        if label == ReasonLabel.MONOPOLY_FLEXIBLE_PICK:
            return "no single resource stood out, so this is a flexible monopoly guess"

        return str(label)

    def _final_benefit_text(self, candidate: CandidateExplanation) -> str:
        card_benefit = self._development_card_benefit_text(candidate)
        if card_benefit:
            return card_benefit

        top_reasons = [
            reason for reason in self._sorted_reasons(candidate.reasons_for)
            if reason.type != ReasonType.REQUIRES_TRADE
        ][:3]

        if not top_reasons:
            return "This final move is the strongest option here."

        reason_phrases = [self._reason_to_detail_phrase(reason) for reason in top_reasons]
        reason_phrases = [phrase for phrase in reason_phrases if phrase]

        if not reason_phrases:
            return "This final move is the strongest option here."

        if len(reason_phrases) == 1:
            joined = reason_phrases[0]
        elif len(reason_phrases) == 2:
            joined = f"{reason_phrases[0]} and {reason_phrases[1]}"
        else:
            joined = ", ".join(reason_phrases[:-1]) + f", and {reason_phrases[-1]}"

        return f"This is strong because {joined}."

    def _development_card_benefit_text(self, candidate: CandidateExplanation) -> str:
        if candidate.action.type != ActionType.PLAY_DEV_CARD:
            return ""

        card_type = candidate.action.payload

        if card_type == DevelopmentCardType.KNIGHT:
            if any(reason.type == ReasonType.ADVANCES_LARGEST_ARMY for reason in candidate.reasons_for):
                return (
                    "This is strong because playing the Knight moves the robber now "
                    "and strengthens your push toward Largest Army."
                )
            return (
                "This is strong because playing the Knight moves the robber now and "
                "adds to your army count for future Largest Army pressure."
            )

        if card_type == DevelopmentCardType.ROAD_BUILDING:
            return (
                "This is strong because Road Building creates an immediate two-road "
                "swing and can open new expansion lines without spending resources."
            )

        if card_type == DevelopmentCardType.YEAR_OF_PLENTY:
            return (
                "This is strong because Year of Plenty turns the card into the exact "
                "two resources you need right now."
            )

        if card_type == DevelopmentCardType.MONOPOLY:
            return (
                "This is strong because Monopoly can create a large resource swing if "
                "opponents are holding the resource you call."
            )

        return ""

    def _reason_to_detail_phrase(self, reason: Reason) -> str:
        if reason.label in (
                ReasonLabel.INIT_EARLY_PRODUCTION,
                ReasonLabel.INIT_RESOURCE_DIVERSITY,
                ReasonLabel.INIT_HIGH_FREQUENCY,
                ReasonLabel.INIT_PORT_ACCESS,
                ReasonLabel.INIT_COMPLEMENTS_FIRST,
                ReasonLabel.INIT_ROAD_CONNECTION,
                ReasonLabel.INIT_ROAD_TO_SETTLEMENT,
                ReasonLabel.INIT_ROAD_TO_BALANCE,
                ReasonLabel.INIT_ROAD_FLEXIBLE,
                ReasonLabel.TRADE_PARTNER_BEST_ETW,
                ReasonLabel.TRADE_PARTNER_COUNTER_VALUE,
                ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT,
                ReasonLabel.TRADE_RESPONSE_ACCEPT_VALUE,
                ReasonLabel.TRADE_RESPONSE_COUNTER_VALUE,
                ReasonLabel.TRADE_RESPONSE_REJECT_NO_GAIN,
                ReasonLabel.TRADE_RESPONSE_REJECT_RISK,
                ReasonLabel.ROBBER_BLOCKS_KEY_HEX,
                ReasonLabel.ROBBER_TARGETS_THREAT,
                ReasonLabel.ROBBER_AVOIDS_OWN_HEX,
                ReasonLabel.DISCARD_PROTECTS_PLAN,
                ReasonLabel.DISCARD_USES_SURPLUS,
                ReasonLabel.YOP_FILLS_SHORTFALL,
                ReasonLabel.YOP_SUPPORTS_FOLLOW_UP,
                ReasonLabel.YOP_FLEXIBLE_PICK,
                ReasonLabel.MONOPOLY_HIGHEST_DEMAND,
                ReasonLabel.MONOPOLY_FLEXIBLE_PICK,
        ):
            return self._normalise_reason_label(self._reason_label_text(reason))

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

        return self._normalise_reason_label(self._reason_label_text(reason))

    def _highlight_buildable(self, name: str) -> str:
        return f"<b>{name}</b>"

    def get_visual_build_plan(self) -> List[Tuple]:
        """Return the planned build actions to visualise, in execution order."""
        custom_plan = self.metadata.get("visual_plan") or self.chosen_candidate.metadata.get("visual_plan")
        if isinstance(custom_plan, list):
            return custom_plan

        source_plan = self.chosen_candidate.full_plan

        if self.chosen_action.type == ActionType.END_TURN and self.chosen_candidate.next_plan:
            source_plan = self.chosen_candidate.next_plan

        return [action.payload for action in source_plan if action.type == ActionType.BUILD and
                action.payload[0] != Buildable.DEVELOPMENT_CARD]
