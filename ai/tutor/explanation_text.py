from typing import List, Tuple

from ai.actions import Action, ActionType
from ai.tutor.explanation_formatting import (action_to_text, capitalise, detail_sentence_from_reasons,
                                             end_turn_concise_reason, explanation_template, final_benefit_text,
                                             follow_up_action_text, gerund_phrase, initial_road_target_sentence,
                                             plan_linking_text, plan_timing_text, port_reason_text,
                                             resource_count_text, top_reason_sentence, trade_concise_reason,
                                             trade_detail_sentence_from_reasons,
                                             trade_exchange_text, trade_opening_text, vertex_intersection_text)
from ai.tutor.explanations import ActionExplanation, CandidateExplanation, ExplanationTemplate
from game.Resources import Resource


def generate_text_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate the concise explanation text."""
    template = explanation_template(explanation)
    if template == ExplanationTemplate.INITIAL_SETTLEMENT:
        return initial_settlement_concise(explanation)
    if template == ExplanationTemplate.INITIAL_ROAD:
        return initial_road_concise(explanation)
    if template == ExplanationTemplate.TRADE_PARTNER:
        return trade_partner_concise(explanation)
    if template == ExplanationTemplate.TRADE_RESPONSE:
        return trade_response_concise(explanation)
    if template == ExplanationTemplate.ROBBER_TARGET:
        return robber_target_concise(explanation)
    if template == ExplanationTemplate.DISCARD_RESOURCES:
        return discard_resources_concise(explanation)
    if template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
        return year_of_plenty_concise(explanation)
    if template == ExplanationTemplate.MONOPOLY_RESOURCE:
        return monopoly_resource_concise(explanation)
    if explanation.chosen_candidate.action.type == ActionType.BUY_DEV_CARD:
        return buy_development_card_concise(explanation)

    action_text = capitalise(action_to_text(explanation.chosen_candidate.action, short=True))
    if explanation.chosen_candidate.action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
        reason_text = end_turn_concise_reason(explanation.chosen_candidate)
    elif explanation.chosen_candidate.action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
        reason_text = trade_concise_reason(explanation.chosen_candidate, limit=2)
    else:
        reason_text = top_reason_sentence(explanation.chosen_candidate.reasons_for, limit=2)
    return action_text.title(), capitalise(reason_text) if reason_text else ""


def generate_text_detail(explanation: ActionExplanation) -> str:
    """Generate the detailed explanation text."""
    template = explanation_template(explanation)
    if template == ExplanationTemplate.INITIAL_SETTLEMENT:
        return initial_settlement_detail(explanation)
    if template == ExplanationTemplate.INITIAL_ROAD:
        return initial_road_detail(explanation)
    if template == ExplanationTemplate.TRADE_PARTNER:
        return trade_partner_detail(explanation)
    if template == ExplanationTemplate.TRADE_RESPONSE:
        return trade_response_detail(explanation)
    if template == ExplanationTemplate.ROBBER_TARGET:
        return robber_target_detail(explanation)
    if template == ExplanationTemplate.DISCARD_RESOURCES:
        return discard_resources_detail(explanation)
    if template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
        return year_of_plenty_detail(explanation)
    if template == ExplanationTemplate.MONOPOLY_RESOURCE:
        return monopoly_resource_detail(explanation)
    if explanation.chosen_candidate.action.type == ActionType.BUY_DEV_CARD:
        return buy_development_card_detail(explanation)

    candidate = explanation.chosen_candidate
    plan = candidate.full_plan

    if candidate.action.type == ActionType.END_TURN and candidate.next_plan:
        return end_turn_plan_text(explanation, candidate)
    if not plan:
        return "There is no clear plan for this move."
    if len(plan) == 1:
        action_text = action_to_text(plan[0], short=False)
        opening = f"The idea is to {action_text}."
        benefit = final_benefit_text(explanation, candidate)
        closing = plan_timing_text(candidate)
        parts = [opening, benefit]
        if closing:
            parts.append(closing)
        return "<br><br>".join(parts)

    parts: List[str] = []
    trade_opening = trade_opening_text(plan)
    if trade_opening:
        parts.append(trade_opening)
    else:
        first_step = action_to_text(plan[0], short=False)
        parts.append(f"The plan starts by {gerund_phrase(plan[0], first_step)}.")

    for i in range(1, len(plan)):
        current = plan[i]
        if i == len(plan) - 1:
            parts.append(f"That sets up the final step: {action_to_text(current, short=False)}.")
        else:
            parts.append(f"After that, the next step is to {action_to_text(current, short=False)}.")

    if not trade_opening:
        link_text = plan_linking_text(plan)
        if link_text:
            parts.append(link_text)

    parts.append(final_benefit_text(explanation, candidate))
    timing = plan_timing_text(candidate)
    if timing:
        parts.append(timing)
    return "<br><br>".join(part for part in parts if part)


def end_turn_plan_text(explanation: ActionExplanation, candidate: CandidateExplanation) -> str:
    """Describe the follow-up plan after ending the turn."""
    next_plan = candidate.next_plan
    next_step = next_plan[0]
    next_step_text = action_to_text(next_step, short=False)
    parts = [f"The best immediate move is to end the turn and keep saving for this plan: {next_step_text}."]

    final_action = next_plan[-1]
    if final_action != next_step:
        parts.append(f"The current milestone after saving is {action_to_text(final_action, short=False)}.")

    waiting_text = resource_count_text(candidate.waiting_resources)
    if waiting_text:
        parts.append(f"The resources still missing for that plan are {waiting_text}.")

    benefit = final_benefit_text(explanation, candidate)
    if benefit:
        parts.append(benefit)

    timing = plan_timing_text(candidate)
    if timing:
        parts.append(timing)
    return "<br><br>".join(parts)


def initial_settlement_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for an opening settlement explanation."""
    vertex = explanation.chosen_candidate.metadata.get("target_vertex")
    intersection = vertex_intersection_text(vertex)
    return "Place A Settlement Here", f"Place your settlement at the intersection of {intersection}."


def initial_road_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for an opening road explanation."""
    return "Place A Road Here", initial_road_target_sentence(explanation)


def initial_settlement_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for an opening settlement explanation."""
    vertex = explanation.chosen_candidate.metadata.get("target_vertex")
    parts = [f"The idea is to place your settlement at the intersection of {vertex_intersection_text(vertex)}."]
    port_text = port_reason_text(explanation.chosen_candidate.metadata.get("port"))
    if port_text:
        parts.append(port_text)
    parts.append(detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for))
    return "<br><br>".join(parts)


def initial_road_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for an opening road explanation."""
    parts = [
        f"The idea is to {initial_road_target_sentence(explanation).lower()}",
        detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for),
    ]
    return "<br><br>".join(parts)


def trade_partner_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a trade-partner explanation."""
    partner_name = explanation.chosen_candidate.metadata.get("partner_name", "this player")
    exchange = trade_exchange_text(
        explanation.chosen_candidate.metadata.get("payment"),
        explanation.chosen_candidate.metadata.get("buying"),
    )
    if exchange:
        return "Choose This Trade Partner", f"Trade with {partner_name}: {exchange}."
    return "Choose This Trade Partner", f"Trade with {partner_name}."


def trade_partner_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a trade-partner explanation."""
    partner_name = explanation.chosen_candidate.metadata.get("partner_name", "this player")
    if explanation.alternatives:
        opening = f"The best trade partner is {partner_name}."
    else:
        opening = f"Trade with {partner_name}."
    exchange = trade_exchange_text(
        explanation.chosen_candidate.metadata.get("payment"),
        explanation.chosen_candidate.metadata.get("buying"),
    )
    if exchange:
        opening += f" The trade would be {exchange}."
    reasons = trade_detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for)
    return "<br><br>".join(part for part in [opening, reasons] if part)


def trade_response_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a trade-response explanation."""
    decision = explanation.chosen_candidate.metadata.get("decision")
    opponent_name = explanation.chosen_candidate.metadata.get("opponent_name", "the other player")
    offered = explanation.chosen_candidate.metadata.get("selling_to_us")
    requested = explanation.chosen_candidate.metadata.get("payment")
    if decision == "accept":
        return "Accept This Trade", f"Accept {opponent_name}'s trade: {trade_exchange_text(requested, offered)}."
    if decision == "counter":
        counter_payment = explanation.chosen_candidate.metadata.get("counter_payment")
        return "Counter This Trade", f"Counter {opponent_name} with {trade_exchange_text(counter_payment, offered)}."
    return "Reject This Trade", f"Reject {opponent_name}'s offer."


def trade_response_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a trade-response explanation."""
    decision = explanation.chosen_candidate.metadata.get("decision")
    opponent_name = explanation.chosen_candidate.metadata.get("opponent_name", "the other player")
    offered = explanation.chosen_candidate.metadata.get("selling_to_us")
    requested = explanation.chosen_candidate.metadata.get("payment")
    counter_payment = explanation.chosen_candidate.metadata.get("counter_payment")

    if decision == "accept":
        opening = f"Accept the trade from {opponent_name}."
        exchange = trade_exchange_text(requested, offered)
        if exchange:
            opening += f" The exchange is {exchange}."
    elif decision == "counter":
        opening = f"Counter the trade from {opponent_name}."
        if counter_payment:
            opening += f" Ask for {trade_exchange_text(counter_payment, offered)} instead."
    else:
        opening = f"Reject the trade from {opponent_name}."
        exchange = trade_exchange_text(requested, offered)
        if exchange:
            opening += f" The offered exchange is {exchange}."

    reasons = trade_detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for)
    return "<br><br>".join(part for part in [opening, reasons] if part)


def robber_target_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a robber explanation."""
    target_player = explanation.chosen_candidate.metadata.get("target_player_name")
    if target_player:
        return (
            "Move The Robber Here",
            f"Move the robber to this tile and steal from {target_player} if possible.",
        )
    return "Move The Robber Here", "Move the robber to this tile."


def robber_target_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a robber explanation."""
    parts = []
    target_player = explanation.chosen_candidate.metadata.get("target_player_name")
    if target_player:
        parts.append(f"Move the robber to the highlighted tile and target {target_player} if possible.")
    else:
        parts.append("Move the robber to the highlighted tile.")
    parts.append(detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for))
    return "<br><br>".join(part for part in parts if part)


def discard_resources_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a discard explanation."""
    discard_text = resource_count_text(explanation.chosen_candidate.metadata.get("discard_resources", {}))
    if not discard_text:
        return "Discard These Resources", "Discard the highlighted resources."
    flexibility_reason = _discard_flexibility_reason(explanation)
    return "Discard These Resources", f"Discard {discard_text}. {flexibility_reason}"


def discard_resources_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a discard explanation."""
    discard_text = resource_count_text(explanation.chosen_candidate.metadata.get("discard_resources", {}))
    parts = [f"Discard {discard_text}." if discard_text else "Discard the highlighted resources.",
             _discard_flexibility_reason(explanation), _discard_mix_reason(explanation)]

    return "<br><br>".join(part for part in parts if part)


def year_of_plenty_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a Year of Plenty explanation."""
    selected_text = resource_count_text(explanation.chosen_candidate.metadata.get("selected_resources", {}))
    if selected_text:
        return "Take These Resources", f"Take {selected_text} from the bank."
    return "Take These Resources", "Take the highlighted resources from the bank."


def year_of_plenty_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a Year of Plenty explanation."""
    selected_text = resource_count_text(explanation.chosen_candidate.metadata.get("selected_resources", {}))
    primary_action = explanation.chosen_candidate.metadata.get("primary_action")
    follow_up_action = explanation.chosen_candidate.metadata.get("follow_up_action")
    supports_follow_up = bool(explanation.chosen_candidate.metadata.get("supports_follow_up"))
    already_had_next_step = bool(explanation.chosen_candidate.metadata.get("already_had_next_step"))
    parts = [
        f"Take {selected_text} from the bank." if selected_text else "Take the highlighted resources from the bank."
    ]

    primary_text = follow_up_action_text(primary_action)
    follow_up_text = follow_up_action_text(follow_up_action)
    if supports_follow_up and follow_up_text:
        parts.append(f"This supports {follow_up_text}.")
    elif already_had_next_step:
        if primary_text and follow_up_text and primary_text != follow_up_text:
            parts.append(f"We already have enough resources for {primary_text}. "
                         f"These picks prepare {follow_up_text}.")
        elif primary_text:
            parts.append(f"We already have enough resources for {primary_text}. "
                         "These picks prepare what comes after that.")
        elif follow_up_text:
            parts.append("We already have enough resources for the next step. "
                         f"These picks prepare {follow_up_text}.")
    elif follow_up_text:
        parts.append(f"These resources work toward {follow_up_text}.")
    else:
        parts.append("These resources improve your resource balance for the next plan step.")

    parts.append(detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for))
    return "<br><br>".join(part for part in parts if part)


def monopoly_resource_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a Monopoly explanation."""
    selected_resource = explanation.chosen_candidate.metadata.get("selected_resource")
    resource_name = getattr(selected_resource, "name", "resource").replace("_", " ").upper()
    return "Choose This Resource", f"Choose <b>{resource_name}</b> for Monopoly."


def monopoly_resource_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a Monopoly explanation."""
    selected_resource = explanation.chosen_candidate.metadata.get("selected_resource")
    resource_name = getattr(selected_resource, "name", "resource").replace("_", " ").upper()
    parts = [
        f"Choose <b>{resource_name}</b> as the Monopoly resource.",
        detail_sentence_from_reasons(explanation, explanation.chosen_candidate.reasons_for),
    ]
    return "<br><br>".join(part for part in parts if part)


def buy_development_card_concise(explanation: ActionExplanation) -> Tuple[str, str]:
    """Generate concise text for a development-card purchase explanation."""
    candidate = explanation.chosen_candidate
    vp_prob = float(candidate.metadata.get("dev_card_vp_probability", 0.0) or 0.0)
    knight_prob = float(candidate.metadata.get("dev_card_knight_probability", 0.0) or 0.0)
    progress_prob = float(candidate.metadata.get("dev_card_progress_probability", 0.0) or 0.0)

    if vp_prob >= 0.12 and knight_prob >= 0.25 and progress_prob >= 0.15:
        return (
            "Buy A Development Card",
            "It provides access to hidden victory points, Knight cards for Largest Army pressure, and progress cards, "
            "creating multiple routes to future victory.",
        )
    if knight_prob >= 0.25:
        return (
            "Buy A Development Card",
            "Knight cards contribute toward Largest Army while victory point cards can directly advance your score.",
        )
    return (
        "Buy A Development Card",
        "Rather than committing to a single board expansion plan, a development card keeps several strategic options "
        "available.",
    )


def buy_development_card_detail(explanation: ActionExplanation) -> str:
    """Generate detailed text for a development-card purchase explanation."""
    candidate = explanation.chosen_candidate
    vp_prob = float(candidate.metadata.get("dev_card_vp_probability", 0.0) or 0.0)
    knight_prob = float(candidate.metadata.get("dev_card_knight_probability", 0.0) or 0.0)
    progress_prob = float(candidate.metadata.get("dev_card_progress_probability", 0.0) or 0.0)
    army_distance = int(candidate.metadata.get("dev_card_largest_army_distance", 99) or 99)
    alternative = explanation.alternatives[0].action if explanation.alternatives else None

    parts = ["Buy a development card."]
    strategic_parts: List[str] = []
    if vp_prob >= 0.12:
        strategic_parts.append("it keeps hidden victory points live as a way to increase your score without revealing "
                               "that plan on the board")
    if knight_prob >= 0.25:
        if army_distance <= 2:
            strategic_parts.append("Knight cards matter because they create a live route toward Largest Army")
        else:
            strategic_parts.append("Knight cards still add robber control and a credible alternative victory route")
    if progress_prob >= 0.15:
        strategic_parts.append("progress cards add strategic flexibility by supporting several different follow-up "
                               "plans")

    if strategic_parts:
        if len(strategic_parts) == 1:
            joined = strategic_parts[0]
        elif len(strategic_parts) == 2:
            joined = f"{strategic_parts[0]}, and {strategic_parts[1]}"
        else:
            joined = ", ".join(strategic_parts[:-1]) + f", and {strategic_parts[-1]}"
        parts.append(f"This is strong because {joined}.")
    else:
        parts.append("This is strong because it keeps several strategic options available instead of locking you into "
                     "a single immediate board plan.")

    if alternative is not None:
        parts.append(
            f"It is preferable to {action_to_text(alternative, short=False)} here because the card keeps alternative "
            f"victory routes available instead of committing immediately to one visible expansion line."
        )

    timing = plan_timing_text(candidate)
    if timing:
        parts.append(timing)
    return "<br><br>".join(part for part in parts if part)


def _discard_flexibility_reason(explanation: ActionExplanation) -> str:
    """Build a presentation-oriented discard explanation."""
    current_resources = explanation.chosen_candidate.metadata.get("current_resources", {})
    discard_resources = explanation.chosen_candidate.metadata.get("discard_resources", {})
    kept_resources = explanation.chosen_candidate.metadata.get("kept_resources", {})
    discarded_surplus = explanation.chosen_candidate.metadata.get("discarded_surplus_resources", {})

    discarded_resource, discarded_amount = _largest_resource_entry(discard_resources)
    current_amount = int(current_resources.get(discarded_resource, 0)) if discarded_resource is not None else 0
    kept_types = sum(1 for amount in kept_resources.values() if int(amount) > 0) if isinstance(kept_resources, dict) \
        else 0

    if discarded_resource is not None and discarded_amount > 0 and current_amount >= max(3, discarded_amount * 2):
        resource_name = discarded_resource.name.replace("_", " ").title()
        return (
            f"{resource_name} is heavily overrepresented in this hand, so removing it preserves a more flexible set "
            f"of resources."
        )

    if isinstance(discarded_surplus, dict) and sum(int(amount) for amount in discarded_surplus.values()) > 0:
        return "This removes the largest surplus while keeping a broader mix of resources available."

    if kept_types >= 3:
        return "This keeps the hand more balanced and preserves flexibility across several future options."

    return ("The discarded cards provide the least additional value compared with the other resources currently being "
            "held.")


def _discard_mix_reason(explanation: ActionExplanation) -> str:
    """Add a supporting sentence for discard explanations."""
    kept_resources = explanation.chosen_candidate.metadata.get("kept_resources", {})
    discard_resources = explanation.chosen_candidate.metadata.get("discard_resources", {})
    kept_types = sum(1 for amount in kept_resources.values() if int(amount) > 0) if isinstance(kept_resources, dict) \
        else 0
    discarded_resource, _ = _largest_resource_entry(discard_resources)

    if kept_types >= 3:
        return ("The remaining hand still covers a broader mix of resource types, which is more useful than "
                "concentrating further into one resource.")
    if discarded_resource is not None:
        resource_name = discarded_resource.name.replace("_", " ").lower()
        return f"That makes {resource_name} the most expendable resource in relative terms."
    return ""


def _largest_resource_entry(resources: object) -> tuple[Resource | None, int]:
    """Return the largest resource entry from a resource-count mapping."""
    if not isinstance(resources, dict):
        return None, 0
    best_resource: Resource | None = None
    best_amount = 0
    for resource, amount in resources.items():
        if not isinstance(resource, Resource):
            continue
        amount_int = int(amount)
        if amount_int > best_amount:
            best_resource = resource
            best_amount = amount_int
    return best_resource, best_amount
