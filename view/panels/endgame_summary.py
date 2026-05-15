import math
from typing import Dict, List, Tuple

from ai.tutor.feedback import TutorDecisionType, TutorFeedbackExplanation
from ai.tutor.move_quality import move_quality_label
from controllers.GameController import PlayerScoreSnapshot
from game.Player import Player, PlayerNumber
from game.PlayerAssets import DevelopmentCardType
from view.rich_text import player_breakdown_html, strip_html_to_plain_text


def get_player_victory_breakdown(player: Player) -> Dict[str, int]:
    return {
        "settlements": len(player.settlements),
        "cities": len(player.cities) * 2,
        "longest_road": 2 if player.has_longest_road else 0,
        "largest_army": 2 if player.has_largest_army else 0,
        "victory_cards": len(
            [card for card in player.development_cards if card.card_type == DevelopmentCardType.VICTORY_POINT]),
    }


def format_player_breakdown_text(player: Player) -> str:
    breakdown = get_player_victory_breakdown(player)
    total_vp = player.calc_victory_points()[1]
    return (f"{player.name} - {total_vp} VP\n\n"
            f"Cities: {breakdown['cities']} pts\n"
            f"Settlements: {breakdown['settlements']} pts\n"
            f"Longest Road: {breakdown['longest_road']} pts\n"
            f"Largest Army: {breakdown['largest_army']} pts\n"
            f"Victory Card Points: {breakdown['victory_cards']} pts")


def format_player_breakdown_html(player: Player) -> str:
    return player_breakdown_html(player.name, get_player_victory_breakdown(player))


def format_player_ranking_summary(player: Player) -> str:
    summary_parts: List[str] = []
    city_count = len(player.cities)
    if city_count:
        summary_parts.append(f"C:{city_count}")
    settlement_count = len(player.settlements)
    if settlement_count:
        summary_parts.append(f"S:{settlement_count}")
    if player.has_longest_road:
        summary_parts.append("LR")
    if player.has_largest_army:
        summary_parts.append("LA")
    vp_card_count = get_player_victory_breakdown(player)["victory_cards"]
    if vp_card_count:
        summary_parts.append(f"VC:{vp_card_count}")
    return " ".join(summary_parts)


def strip_html(text: str) -> str:
    return strip_html_to_plain_text(text)


def compact_feedback_action(action_text: str) -> str:
    cleaned = " ".join((action_text or "").split()).strip()
    if not cleaned:
        return "Move"
    replacements = {
        "ending the turn": "End Turn",
        "building a road": "Built Road",
        "building a settlement": "Built Settlement",
        "upgrading to a city": "Built City",
        "buying a development card": "Bought Development Card",
        "playing a development card": "Played Development Card",
        "making a bank trade": "Bank Trade",
        "making a player trade": "Player Trade",
        "move the robber": "Robber Placement",
        "discard resources": "Discarded Resources",
    }
    lowered = cleaned.lower()
    if lowered in replacements:
        return replacements[lowered]
    return cleaned.title()


def feedback_card_title(feedback: TutorFeedbackExplanation) -> str:
    turn_num = getattr(feedback.board_snapshot.game_state, "round_num", 0)
    action_text = compact_feedback_action(feedback.assessment.your_move or feedback.title)
    return f"Turn {turn_num} - {action_text}"


def endgame_feedback_filter_state_from_owner(owner) -> Dict[str, bool]:

    def is_checked(label: str) -> bool:
        checkbox = owner.feedback_filter_checkboxes.get(label)
        return checkbox.isChecked() if checkbox is not None else False

    return {
        "poor": is_checked("biggest mistakes"),
        "okay": is_checked("okay moves"),
        "good": is_checked("good moves"),
        "excellent": is_checked("excellent moves"),
    }


def replay_feedback_player_name(feedback: TutorFeedbackExplanation) -> str:
    human_player = next((player for player in feedback.board_snapshot.get_all_players() if player.is_human), None)
    if human_player is not None:
        return human_player.name
    players = feedback.board_snapshot.get_all_players()
    return players[0].name if players else "Player"


def format_replay_feedback_details(feedback: TutorFeedbackExplanation, total_turns: int) -> Dict[str, str]:
    turn_num = getattr(feedback.board_snapshot.game_state, "round_num", 0)
    player_name = replay_feedback_player_name(feedback)
    action_text = feedback.assessment.your_move or feedback.title
    move_context = getattr(feedback.assessment, "move_context", "")
    if move_context:
        action_text += f"\n{move_context}"
    score_text = f"Score: {feedback.assessment.internal_score:.2f} | Gap: +{feedback.assessment.score_gap:.2f}"
    tutor_feedback = feedback.assessment.judgment_sentence.strip()

    if feedback.assessment.better_move and (feedback.assessment.better_move.strip().lower()
                                            != action_text.strip().lower()):
        advice_text = f"Better move: {feedback.assessment.better_move}"
        better_move_context = getattr(feedback.assessment, "better_move_context", "")
        if better_move_context:
            advice_text += f"\n{better_move_context}"
        if feedback.assessment.tip:
            advice_text += f"\nTakeaway: {feedback.assessment.tip}"
    elif feedback.assessment.tip:
        advice_text = feedback.assessment.tip
    else:
        advice_text = strip_html(feedback.history_summary)

    return {
        "turn_and_player": f"Turn {turn_num} - {player_name}",
        "action": f"Action: {action_text}",
        "badge": feedback.label,
        "score": score_text,
        "tutor_feedback": f"Tutor feedback: {tutor_feedback}",
        "advice": advice_text,
        "turn_label": f"Turn {turn_num} / {max(total_turns, turn_num)}",
    }


def outcome_performance_score(final_snapshot: PlayerScoreSnapshot | None) -> float | None:
    if final_snapshot is None:
        return None
    final_vp = max(0, final_snapshot.total_vp)
    return max(0.0, min(float(final_vp) / 10.0, 1.0))


def outcome_strength_line(final_snapshot: PlayerScoreSnapshot | None) -> str | None:
    outcome_score = outcome_performance_score(final_snapshot)
    if outcome_score is None or final_snapshot is None:
        return None
    if final_snapshot.total_vp >= 10:
        return f"Game result (converted decisions into {final_snapshot.total_vp} VP)"
    return None


def outcome_weakness_line(final_snapshot: PlayerScoreSnapshot | None, leader_vp: int | None) -> str | None:
    outcome_score = outcome_performance_score(final_snapshot)
    if outcome_score is None or final_snapshot is None:
        return None
    if final_snapshot.total_vp <= 4:
        return f"Game result (finished on only {final_snapshot.total_vp} VP)"
    if leader_vp is not None and final_snapshot.total_vp <= leader_vp - 3:
        return "Game result (fell too far behind the leader)"
    return None


def performance_category(feedback: TutorFeedbackExplanation) -> str:
    decision_type = feedback.assessment.decision_type
    move_text = (feedback.assessment.your_move or "").lower()
    if decision_type == TutorDecisionType.ROBBER:
        return "robber"
    if decision_type == TutorDecisionType.DISCARD:
        return "discard"
    if decision_type in {TutorDecisionType.TRADE_PARTNER, TutorDecisionType.TRADE_RESPONSE}:
        return "trade"
    if decision_type in {TutorDecisionType.YEAR_OF_PLENTY, TutorDecisionType.MONOPOLY}:
        return "dev_cards"
    if decision_type in {TutorDecisionType.OPENING_SETTLEMENT, TutorDecisionType.OPENING_ROAD}:
        return "opening"
    if "ending the turn" in move_text:
        return "turn_timing"
    if any(text in move_text for text in ("building a settlement", "building a road", "upgrading to a city")):
        return "builds"
    return "planning"


def performance_line(category: str, score: float, positive: bool) -> str:
    if positive:
        lines = {
            "robber": "Robber placement (consistent high-quality choices)",
            "discard": "Discard decisions (protected key resources well)",
            "trade": "Trade decisions (found efficient exchanges)",
            "dev_cards": "Development card usage (timed card value well)",
            "opening": "Opening placements (set up a stable start)",
            "turn_timing": "Turn timing (rarely wasted turns)",
            "builds": "Build choices (kept city and settlement timing on track)",
            "planning": "Main-turn planning (kept useful lines open)",
        }
        return lines.get(category, "General play (steady decisions)")

    lines = {
        "robber": "Robber placement (missed stronger blocks or steals)",
        "discard": "Discard decisions (lost key resources multiple times)",
        "trade": "Trade decisions (gave up too much value)",
        "dev_cards": "Development card usage (left card value on the table)",
        "opening": "Opening placements (gave up some early efficiency)",
        "turn_timing": "Turn timing (ended turns with stronger lines still available)",
        "builds": "Missed builds (delayed cities or settlements)",
        "planning": "Main-turn planning (stronger follow-up lines were available)",
    }
    default_line = "General play (several decisions could be tightened)"
    if score < 0.25 and category == "turn_timing":
        return "Turn timing (gave away full turns of tempo)"
    return lines.get(category, default_line)


def overall_performance_summary(
    feedback_items: List[TutorFeedbackExplanation],
    final_snapshot: PlayerScoreSnapshot | None = None,
    leader_vp: int | None = None,
) -> Dict[str, str]:
    if not feedback_items:
        return {
            "turn_and_player": "",
            "action": "Your Performance",
            "badge": "N/A",
            "score": "Overall: N/A",
            "tutor_feedback": "Strengths:\n- No tutor feedback history was recorded.",
            "advice": "Weaknesses:\n- No tutor feedback history was recorded.",
            "turn_label": "Game Summary",
        }

    weighted_quality = sum(item.assessment.internal_score for item in feedback_items) / len(feedback_items)
    vp_score = None if final_snapshot is None else max(0.0, min(float(final_snapshot.total_vp) / 10.0, 1.0))
    win_bonus = None if final_snapshot is None else (1 if final_snapshot.total_vp >= 10 else 0.0)
    overall_score = weighted_quality
    if vp_score is not None and win_bonus is not None:
        overall_score = max(0.0, min(1.0, 0.3 * weighted_quality + 0.6 * vp_score + 0.1 * win_bonus))
    overall_label = move_quality_label(overall_score)
    category_scores: Dict[str, List[float]] = {}
    for feedback in feedback_items:
        category = performance_category(feedback)
        category_scores.setdefault(category, []).append(feedback.assessment.internal_score)

    ranked_categories = sorted(
        ((category, sum(scores) / len(scores), len(scores)) for category, scores in category_scores.items()),
        key=lambda item: (item[1], item[2]),
        reverse=True,
    )
    strengths = [
        performance_line(category, score, True) for category, score, _count in ranked_categories if score >= 0.6
    ][:2]
    weaknesses = [
        performance_line(category, score, False)
        for category, score, _count in sorted(ranked_categories, key=lambda item: (item[1], -item[2])) if score < 0.55
    ][:2]

    if not strengths:
        strengths = [performance_line(category, score, True) for category, score, _count in ranked_categories[:2]]
    if not weaknesses:
        fallback = sorted(ranked_categories, key=lambda item: (item[1], -item[2]))
        weaknesses = [performance_line(category, score, False) for category, score, _count in fallback[:2]]

    outcome_strength = outcome_strength_line(final_snapshot)
    if outcome_strength and outcome_strength not in strengths:
        strengths = [outcome_strength, *strengths][:2]

    outcome_weakness = outcome_weakness_line(final_snapshot, leader_vp)
    if outcome_weakness and outcome_weakness not in weaknesses:
        weaknesses = [outcome_weakness, *weaknesses][:2]

    score_text = f"Overall: {overall_label} ({overall_score:.2f})"
    if vp_score is not None and win_bonus is not None:
        score_text = (f"Overall: {overall_label} ({overall_score:.2f})"
                      f" | Moves {weighted_quality:.2f}"
                      f" | VP {vp_score:.2f}"
                      f" | Win {float(win_bonus):.2f}")

    return {
        "turn_and_player": "",
        "action": "Your Performance",
        "badge": overall_label,
        "score": score_text,
        "tutor_feedback": "Strengths:\n" + "\n".join(f"- {line}" for line in strengths),
        "advice": "Weaknesses:\n" + "\n".join(f"- {line}" for line in weaknesses),
        "turn_label": "Game Summary",
    }


def format_endgame_players(names: List[str]) -> str:
    if not names:
        return "No one"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def describe_round_vp_events(
    previous_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot] | None,
    current_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot],
    player_names: Dict[PlayerNumber, str],
) -> List[str]:
    if previous_snapshot is None:
        return []
    events: List[str] = []
    for player_number in sorted(current_snapshot.keys(), key=lambda number: number.value):
        previous = previous_snapshot[player_number]
        current = current_snapshot[player_number]
        player_name = player_names[player_number]

        city_gain = current.cities - previous.cities
        if city_gain > 0:
            events.append(f"- {player_name} built a city" if city_gain ==
                          1 else f"- {player_name} built {city_gain} cities")

        settlement_gain = current.settlements - previous.settlements
        if settlement_gain > 0:
            events.append(f"- {player_name} built a settlement" if settlement_gain ==
                          1 else f"- {player_name} built {settlement_gain} settlements")

        hidden_vp_gain = current.hidden_vp_cards - previous.hidden_vp_cards
        if hidden_vp_gain > 0:
            events.append(f"- {player_name} bought a Victory Point card" if hidden_vp_gain ==
                          1 else f"- {player_name} bought {hidden_vp_gain} Victory Point cards")

        if not previous.has_longest_road and current.has_longest_road:
            events.append(f"- {player_name} gained Longest Road")
        elif previous.has_longest_road and not current.has_longest_road:
            events.append(f"- {player_name} lost Longest Road")

        if not previous.has_largest_army and current.has_largest_army:
            events.append(f"- {player_name} gained Largest Army")
        elif previous.has_largest_army and not current.has_largest_army:
            events.append(f"- {player_name} lost Largest Army")

    return events


def join_reasons(reasons: List[str]) -> str:
    if len(reasons) == 1:
        return reasons[0]
    if len(reasons) == 2:
        return f"{reasons[0]} and {reasons[1]}"
    return f"{', '.join(reasons[:-1])}, and {reasons[-1]}"


def score_swing_reasons(previous: PlayerScoreSnapshot, current: PlayerScoreSnapshot) -> List[str]:
    reasons: List[str] = []
    if not previous.has_longest_road and current.has_longest_road:
        reasons.append("gained Longest Road")
    if not previous.has_largest_army and current.has_largest_army:
        reasons.append("gained Largest Army")
    if current.cities > previous.cities:
        reasons.append("upgraded to a city")
    elif current.settlements > previous.settlements:
        reasons.append("built a settlement")
    hidden_vp_delta = current.hidden_vp_cards - previous.hidden_vp_cards
    if hidden_vp_delta > 0:
        reasons.append(f"picked up {hidden_vp_delta} hidden VP")
    return reasons


def build_lead_change_label(
    history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
    player_names: Dict[PlayerNumber, str],
) -> str:
    leaders_by_round: List[Tuple[int, List[PlayerNumber], int]] = []
    for round_num, snapshot in history:
        top_score = max(player.total_vp for player in snapshot.values())
        leaders = sorted(
            [player_number for player_number, player in snapshot.items() if player.total_vp == top_score],
            key=lambda player_number: player_number.value,
        )
        leaders_by_round.append((round_num, leaders, top_score))

    final_round, final_leaders, _ = leaders_by_round[-1]
    first_round, _, _ = leaders_by_round[0]
    if len(final_leaders) == 1:
        final_leader = final_leaders[0]
        sole_lead_round = next(round_num for round_num, leaders, _ in reversed(leaders_by_round)
                               if leaders != [final_leader]) if any(
                                   leaders != [final_leader] for _, leaders, _ in leaders_by_round[:-1]) else None
        if sole_lead_round is None:
            return f"{player_names[final_leader]} led from Round {first_round} to the finish."
        held_from_round = sole_lead_round + 1
        return (f"{player_names[final_leader]} took the lead in Round {held_from_round} "
                f"and held it through Round {final_round}.")

    final_names = [player_names[player_number] for player_number in final_leaders]
    return (f"The game finished level at the top in Round {final_round} with "
            f"{format_endgame_players(final_names)} sharing the lead.")


def build_biggest_swing_label(
    history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
    player_names: Dict[PlayerNumber, str],
) -> str:
    best_round: int | None = None
    best_player: PlayerNumber | None = None
    best_delta = 0
    best_reasons: List[str] = []
    for index in range(1, len(history)):
        round_num, current_snapshot = history[index]
        _, previous_snapshot = history[index - 1]
        for player_number, current in current_snapshot.items():
            previous = previous_snapshot[player_number]
            delta = current.total_vp - previous.total_vp
            if delta <= 0:
                continue
            reasons = score_swing_reasons(previous, current)
            if delta > best_delta:
                best_round = round_num
                best_player = player_number
                best_delta = delta
                best_reasons = reasons

    if best_round is None or best_player is None:
        return "No player gained victory points between recorded rounds."
    if best_reasons:
        return (f"Round {best_round}: {player_names[best_player]} "
                f"{join_reasons(best_reasons)} and jumped by {best_delta} VP.")
    return f"Round {best_round}: {player_names[best_player]} made the biggest move, gaining {best_delta} VP."


def build_closest_moment_label(
    history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
    player_names: Dict[PlayerNumber, str],
) -> str:
    best_round = history[0][0]
    best_gap = math.inf
    best_top_score = -1
    best_leaders: List[PlayerNumber] = []
    best_runner_up: PlayerNumber | None = None
    best_runner_up_score = -1

    for round_num, snapshot in history:
        ranked = sorted(snapshot.items(), key=lambda item: (item[1].total_vp, -item[0].value), reverse=True)
        top_score = ranked[0][1].total_vp
        leaders = [player_number for player_number, player in ranked if player.total_vp == top_score]
        if len(leaders) > 1:
            second_score = top_score
            gap = 0
        else:
            second_score = ranked[1][1].total_vp if len(ranked) > 1 else top_score
            gap = top_score - second_score
        runner_up = ranked[len(leaders)][0] if len(leaders) < len(ranked) else None
        if (gap < best_gap or (gap == best_gap and top_score > best_top_score)
                or (gap == best_gap and top_score == best_top_score and round_num > best_round)):
            best_round = round_num
            best_gap = gap
            best_top_score = top_score
            best_leaders = leaders
            best_runner_up = runner_up
            best_runner_up_score = second_score

    if best_gap == 0:
        leader_names = [player_names[player_number] for player_number in best_leaders]
        return f"Round {best_round}: {format_endgame_players(leader_names)} were tied at {best_top_score} VP."
    if best_runner_up is None:
        return f"Round {best_round}: {player_names[best_leaders[0]]} stood alone at {best_top_score} VP."
    return (f"Round {best_round}: {player_names[best_leaders[0]]} led "
            f"{player_names[best_runner_up]} {best_top_score}-{best_runner_up_score}.")


def summarise_endgame_review_labels(
    history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
    players: List[Player],
) -> Tuple[str, str, str]:
    if not history:
        fallback = "No round history recorded."
        return fallback, fallback, fallback
    player_names = {player.player_number: player.name for player in players}
    return (
        build_lead_change_label(history, player_names),
        build_biggest_swing_label(history, player_names),
        build_closest_moment_label(history, player_names),
    )
