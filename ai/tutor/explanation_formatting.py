from typing import Any, Dict, List

from ai.actions import Action, ActionType
from game.PlayerAssets import DevelopmentCardType

from ai.tutor.explanations import (
    ActionExplanation,
    CandidateExplanation,
    ExplanationTemplate,
    Reason,
    ReasonLabel,
    ReasonType,
    RoadExplanationKind,
)


def capitalise(text: str) -> str:
    if not text:
        return ""
    return text[0].upper() + text[1:]


def describe_reason(explanation: ActionExplanation, reason: Reason, detail: bool = True) -> str:
    if detail:
        return reason_to_detail_phrase(explanation, reason)
    return normalise_reason_label(reason_label_text(reason))


def explanation_template(explanation: ActionExplanation) -> Any:
    return explanation.metadata.get("template") or explanation.chosen_candidate.metadata.get("template")


def action_to_text(action: Action, short: bool = True) -> str:
    if action.type == ActionType.ROLL:
        return "roll the dice"
    if action.type == ActionType.END_TURN:
        return "end the turn"
    if action.type == ActionType.BUY_DEV_CARD:
        return "buy a development card"
    if action.type == ActionType.PLAY_DEV_CARD:
        payload = action.payload
        if hasattr(payload, "name"):
            return f"play a {display_name(payload)} card"
        return "play a development card"
    if action.type == ActionType.TRADE_WITH_BANK:
        if short:
            return "trade with the bank"
        return bank_trade_text(action)
    if action.type == ActionType.TRADE_WITH_PLAYER:
        if short:
            return "propose a trade"
        return player_trade_text(action)
    if action.type == ActionType.BUILD:
        return build_text(action)
    return "take this action"


def strongest_plan_focus_phrase(explanation: ActionExplanation) -> str:
    action = explanation.chosen_action
    if action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
        next_phrase = plan_action_phrase(explanation.chosen_candidate.next_plan[0])
        if next_phrase:
            return f"saving resources for {next_phrase}"
        return "saving resources for the next planned action"
    return plan_action_phrase(action)


def sorted_reasons(reasons: List[Reason]) -> List[Reason]:
    return sorted(reasons, key=lambda reason: reason.value, reverse=True)


def top_reason_sentence(reasons: List[Reason], limit: int = 2) -> str:
    top = sorted_reasons(reasons)[:limit]
    return reason_sentence_from_ordered(top)


def trade_concise_reason(candidate: CandidateExplanation, limit: int = 2) -> str:
    ordered: List[Reason] = []
    ordered.extend(reason for reason in candidate.reasons_for if reason.type == ReasonType.REQUIRES_TRADE)
    ordered.extend(
        reason for reason in sorted_reasons(candidate.reasons_for) if reason.type != ReasonType.REQUIRES_TRADE
    )
    return reason_sentence_from_ordered(ordered[:limit])


def reason_sentence_from_ordered(reasons: List[Reason]) -> str:
    labels = [normalise_reason_label(reason_label_text(reason)) for reason in reasons if reason.label]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def normalise_reason_label(label: str) -> str:
    if not label:
        return ""
    label = label.strip()
    if not label:
        return ""
    return label[0].lower() + label[1:]


def reason_label_text(reason: Reason) -> str:
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
        follow_up_text = follow_up_action_text(follow_up_action)
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


def reason_to_detail_phrase(explanation: ActionExplanation, reason: Reason) -> str:
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
        return normalise_reason_label(reason_label_text(reason))
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
        plan_phrase = strongest_plan_focus_phrase(explanation)
        if plan_phrase:
            return f"it supports {plan_phrase}"
        return "it fits the strongest available plan"
    return normalise_reason_label(reason_label_text(reason))


def final_benefit_text(explanation: ActionExplanation, candidate: CandidateExplanation) -> str:
    card_benefit = development_card_benefit_text(candidate)
    if card_benefit:
        return card_benefit

    top_reasons = [
        reason for reason in sorted_reasons(candidate.reasons_for)
        if reason.type != ReasonType.REQUIRES_TRADE
    ][:3]
    if not top_reasons:
        return "This final move is the strongest option here."

    reason_phrases = [reason_to_detail_phrase(explanation, reason) for reason in top_reasons]
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


def resource_count_text(resource_count: Dict[Any, int]) -> str:
    if not resource_count:
        return ""
    parts: List[str] = []
    for resource, amount in resource_count.items():
        if amount <= 0:
            continue
        name = getattr(resource, "name", str(resource)).upper()
        parts.append(f"<b>{amount} {name}</b>")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def trade_exchange_text(payment: Dict[Any, int], buying: Dict[Any, int]) -> str:
    pay_text = resource_count_text(payment)
    receive_text = resource_count_text(buying)
    if pay_text and receive_text:
        return f"give {pay_text} for {receive_text}"
    if receive_text:
        return f"receive {receive_text}"
    if pay_text:
        return f"give {pay_text}"
    return ""


def vertex_intersection_text(vertex: Any) -> str:
    if vertex is None or not getattr(vertex, "hexes", None):
        return "the available tiles"
    descriptions = [
        hex_description(hex_tile)
        for hex_tile in sorted(
            [hex_tile for hex_tile in vertex.hexes if getattr(hex_tile, "resource", None) is not None],
            key=lambda hex_tile: dice_probability(hex_tile.production_number),
            reverse=True,
        )
    ]
    if not descriptions:
        return "the available tiles"
    if len(descriptions) == 1:
        return descriptions[0]
    if len(descriptions) == 2:
        return f"{descriptions[0]} and {descriptions[1]}"
    return ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"


def plan_action_phrase(action: Any) -> str:
    if not isinstance(action, Action):
        return ""
    if action.type == ActionType.BUILD and isinstance(action.payload, tuple) and len(action.payload) >= 1:
        buildable = action.payload[0]
        if hasattr(buildable, "name"):
            build_name = buildable.name.lower()
            if build_name == "city":
                return "upgrading to a city"
            article = "an" if build_name[:1] in "aeiou" else "a"
            return f"building {article} {build_name}"
    if action.type == ActionType.BUY_DEV_CARD:
        return "buying a development card"
    if action.type == ActionType.PLAY_DEV_CARD:
        return "playing a development card"
    if action.type == ActionType.TRADE_WITH_BANK:
        return "making a bank trade"
    if action.type == ActionType.TRADE_WITH_PLAYER:
        return "making a player trade"
    if action.type == ActionType.END_TURN:
        return "ending the turn"
    if action.type == ActionType.ROLL:
        return "rolling the dice"
    return ""


def follow_up_action_text(action: Any) -> str:
    if not isinstance(action, Action):
        return ""
    if action.type == ActionType.BUILD and isinstance(action.payload, tuple) and len(action.payload) >= 1:
        buildable = action.payload[0]
        article = "a"
        if hasattr(buildable, "name"):
            article = "an" if buildable.name.lower()[0] in "aeiou" else "a"
        return (
            f"the next thing we want to build: {article} "
            f"{buildable.name.lower()}"
        )
    if action.type == ActionType.BUY_DEV_CARD:
        return "the next thing we want to do: buy a development card"
    if action.type == ActionType.PLAY_DEV_CARD:
        return "the next thing we want to do: play a development card"
    if action.type == ActionType.TRADE_WITH_BANK:
        return "the next thing we want to do: make a bank trade"
    if action.type == ActionType.TRADE_WITH_PLAYER:
        return "the next thing we want to do: make a player trade"
    return "the next thing we want to do"


def trade_detail_sentence_from_reasons(explanation: ActionExplanation, reasons: List[Reason]) -> str:
    if not reasons:
        return "This is the best trade available here."
    phrases = [reason_to_detail_phrase(explanation, reason) for reason in reasons[:3]]
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


def detail_sentence_from_reasons(explanation: ActionExplanation, reasons: List[Reason]) -> str:
    if not reasons:
        return "This is the strongest available setup choice here."
    phrases = [reason_to_detail_phrase(explanation, reason) for reason in reasons[:3]]
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


def discard_protected_plan_text(explanation: ActionExplanation) -> str:
    protected_action = explanation.chosen_candidate.metadata.get("protected_action")
    if not isinstance(protected_action, Action):
        return ""
    if protected_action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
        trade_target_resources = explanation.chosen_candidate.metadata.get("trade_target_resources", [])
        trade_follow_up_action = explanation.chosen_candidate.metadata.get("trade_follow_up_action")
        resource_text = resource_list_text(trade_target_resources)
        if isinstance(trade_follow_up_action, Action):
            follow_up_text = follow_up_action_text(trade_follow_up_action)
            if resource_text and follow_up_text:
                return (
                    f"This keeps your plan to trade for {resource_text} available "
                    f"so you can work toward {follow_up_text}."
                )
        if resource_text:
            return f"This keeps your plan to trade for {resource_text} available."
    next_text = follow_up_action_text(protected_action)
    if next_text:
        return f"This keeps your stronger follow-up plan available: {next_text}."
    return ""


def initial_road_target_sentence(explanation: ActionExplanation) -> str:
    target_vertex = explanation.chosen_candidate.metadata.get("target_vertex")
    kind = explanation.chosen_candidate.metadata.get("road_explanation_kind")
    if kind == RoadExplanationKind.CONNECTION:
        return "Place your road back toward your other settlement to keep the opening connected."
    if kind == RoadExplanationKind.EXPANSION and target_vertex is not None:
        return (
            f"Place your road so you can expand toward the "
            f"{vertex_intersection_text(target_vertex)} settlement spot."
        )
    return "Place your road where it keeps your opening flexible."


def end_turn_concise_reason(candidate: CandidateExplanation) -> str:
    next_step = candidate.next_plan[0]
    next_step_text = action_to_text(next_step, short=False)
    return f"end turn so we can save resources for {next_step_text}"


def bank_trade_text(action: Action) -> str:
    payload = action.payload
    if not isinstance(payload, tuple) or len(payload) != 2:
        return "trade with the bank"
    selling, buying = payload
    sell_text = resource_count_text(selling)
    buy_text = resource_count_text(buying)
    if sell_text and buy_text:
        return f"trade {sell_text} with the bank for {buy_text}"
    return "trade with the bank"


def player_trade_text(action: Action) -> str:
    payload = action.payload
    if not isinstance(payload, tuple) or len(payload) != 2:
        return "propose a player trade"
    selling, buying = payload
    sell_text = resource_count_text(selling)
    buy_text = resource_count_text(buying)
    if sell_text and buy_text:
        return f"offer {sell_text} in exchange for {buy_text}"
    return "propose a player trade"


def build_text(action: Action) -> str:
    payload = action.payload
    if not isinstance(payload, tuple) or len(payload) < 1:
        return "build"
    buildable = payload[0]
    if not hasattr(buildable, "name"):
        return "build"
    return f"build a {highlight_buildable(buildable.name.upper())}"


def display_name(value: Any) -> str:
    name = getattr(value, "name", str(value))
    return name.replace("_", " ").title()


def resource_list_text(resources: List[Any]) -> str:
    names = [f"<b>{getattr(resource, 'name', str(resource)).upper()}</b>" for resource in resources]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def hex_description(hex_tile: Any) -> str:
    name = getattr(getattr(hex_tile, "type", None), "name", "tile").lower()
    if name.endswith("s"):
        name = name[:-1]
    if getattr(hex_tile, "production_number", None) in (6, 8):
        return f"high-yield {name}"
    return name


def port_reason_text(port: Any) -> str:
    if port is None:
        return ""
    if getattr(port, "name", "") == "THREE_TO_ONE":
        label = "a 3:1 port"
    else:
        label = f"the {port.name.replace('_', ' ').title()} port"
    return f"It also keeps {label} available if you want extra trading flexibility later."


def dice_probability(number: Any) -> float:
    probs = {
        2: 1 / 36, 3: 2 / 36, 4: 3 / 36, 5: 4 / 36, 6: 5 / 36,
        8: 5 / 36, 9: 4 / 36, 10: 3 / 36, 11: 2 / 36, 12: 1 / 36,
    }
    return probs.get(number, 0.0)


def position_text(pos: Any) -> str:
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


def gerund_phrase(action: Action, action_text: str) -> str:
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


def trade_opening_text(plan: List[Action]) -> str:
    if len(plan) < 2:
        return ""
    first_action = plan[0]
    if first_action.type not in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
        return ""
    first_text = action_to_text(first_action, short=False)
    target_name = buildable_name(plan[-1])
    if target_name:
        article = "an" if target_name[0].lower() in "aeiou" else "a"
        return (
            f"The plan starts by {gerund_phrase(first_action, first_text)} "
            f"to save up for {article} {target_name.lower()}."
        )
    return f"The plan starts by {gerund_phrase(first_action, first_text)}."


def plan_linking_text(plan: List[Action]) -> str:
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
                    return (
                        "The earlier steps matter because they support a stronger city "
                        "upgrade at the end of the plan."
                    )
                if name == "road":
                    return "The earlier steps matter because they improve your position before committing to that road."
    if final_action.type == ActionType.BUY_DEV_CARD:
        return "The earlier steps matter because they make it easier to invest in a flexible longer-term option."
    if final_action.type == ActionType.PLAY_DEV_CARD:
        return "The earlier steps matter because they prepare the position before using the card effect."
    return "The earlier steps matter because they make the final move stronger than taking it in isolation."


def buildable_name(action: Action) -> str:
    if action.type != ActionType.BUILD:
        return ""
    payload = action.payload
    if not isinstance(payload, tuple) or len(payload) < 1:
        return ""
    buildable = payload[0]
    if not hasattr(buildable, "name"):
        return ""
    return buildable.name


def plan_timing_text(candidate: CandidateExplanation) -> str:
    if candidate.etb <= 0:
        return ""
    if candidate.etb <= 2:
        return "This is a plan that should become available quite quickly."
    if candidate.etb <= 5:
        return "This is a realistic plan to work toward over the next few turns."
    if candidate.etb <= 9:
        return "This is more of a medium-term plan, but it offers a strong payoff."
    return "This is a slower plan, but it was still judged to give the best long-term payoff."


def development_card_benefit_text(candidate: CandidateExplanation) -> str:
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


def highlight_buildable(name: str) -> str:
    return f"<b>{name}</b>"
