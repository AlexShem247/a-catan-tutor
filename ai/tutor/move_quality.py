import math
from typing import Any, Mapping, Optional

from config.move_quality_constants import (
    FORCED_CHOICE_BENEFICIAL_QUALITY,
    FORCED_CHOICE_DEFAULT_QUALITY,
    INITIAL_ROAD_FLEXIBLE_QUALITY,
    LOGISTIC_CLAMP_MAX,
    LOGISTIC_CLAMP_MIN,
    MOVE_QUALITY_EXCELLENT_THRESHOLD,
    MOVE_QUALITY_GOOD_THRESHOLD,
    MOVE_QUALITY_OKAY_THRESHOLD,
)
from config.performance_constants import EPSILON


def _stable_logistic(score: float) -> float:
    """Compute a numerically stable logistic value."""
    clamped_score = max(LOGISTIC_CLAMP_MIN, min(LOGISTIC_CLAMP_MAX, score))
    return 1.0 / (1.0 + math.exp(-clamped_score))


def clamp_move_quality(move_quality: Optional[float]) -> float:
    """Clamp a move-quality score into the supported range."""
    if move_quality is None:
        return 0.0
    return max(0.0, min(1.0, float(move_quality)))


def move_quality_label(move_quality: float) -> str:
    """Return the user-facing label for a move-quality score."""
    move_quality = clamp_move_quality(move_quality)
    if move_quality >= MOVE_QUALITY_EXCELLENT_THRESHOLD:
        return "Excellent"
    if move_quality >= MOVE_QUALITY_GOOD_THRESHOLD:
        return "Good"
    if move_quality >= MOVE_QUALITY_OKAY_THRESHOLD:
        return "Okay"
    return "Poor"


def tutor_move_quality_label(move_quality: float) -> str:
    """Return the tutor-facing label for a move-quality score."""
    label = move_quality_label(move_quality)
    return "Okay" if label == "Poor" else label


def move_quality_from_ratio(chosen_value: float, max_value: float) -> float:
    """Convert a score ratio into a move-quality value."""
    if max_value <= 0.0:
        return 1.0 if chosen_value >= max_value else 0.0
    return clamp_move_quality(chosen_value / max_value)


def move_quality_from_margin(best_value: float, second_value: Optional[float],
                             worst_value: Optional[float] = None) -> float:
    """Convert a margin between options into a move-quality value."""
    if second_value is None:
        return 0.0
    margin = max(0.0, best_value - second_value)
    if worst_value is None:
        scale = max(abs(best_value), abs(second_value), EPSILON)
        return clamp_move_quality(margin / scale)
    spread = max(0.0, best_value - worst_value)
    if spread <= EPSILON:
        return 0.0
    return clamp_move_quality(margin / spread)


def opening_move_quality(chosen_utility: float, max_utility: float) -> float:
    """Calculate move quality for an opening choice."""
    q = move_quality_from_ratio(chosen_utility, max_utility)
    return q ** 1.2  # slight compression


def initial_settlement_move_quality(chosen_vertex_utility: float, max_vertex_utility: float) -> float:
    """Calculate move quality for an opening settlement choice."""
    return opening_move_quality(chosen_vertex_utility, max_vertex_utility)


def initial_road_expansion_move_quality(target_vertex_utility: float, max_legal_vertex_utility: float) -> float:
    """Calculate move quality for an opening road expansion choice."""
    return opening_move_quality(target_vertex_utility, max_legal_vertex_utility)


def initial_road_connection_move_quality(valid_connection_edges: int) -> float:
    """Calculate move quality for an opening road connection choice."""
    if valid_connection_edges <= 0:
        return 0.0
    return clamp_move_quality(1.0 / float(valid_connection_edges)) ** 1.2


def initial_road_flexible_move_quality() -> float:
    """Return the move quality for a flexible opening road choice."""
    return INITIAL_ROAD_FLEXIBLE_QUALITY


def forced_choice_move_quality(clearly_beneficial: bool = False) -> float:
    """Return the move quality for a forced choice."""
    return FORCED_CHOICE_BENEFICIAL_QUALITY if clearly_beneficial else FORCED_CHOICE_DEFAULT_QUALITY


def robber_move_quality(
        opponent_production_blocked: float,
        steal_value: float,
        self_harm: float,
        leader_vp_ratio: float = 0.0) -> float:
    """Calculate move quality for a robber choice."""
    blocked = max(0.0, opponent_production_blocked) * (1.0 + max(0.0, leader_vp_ratio))
    numerator = blocked + 0.5 * max(0.0, steal_value) - max(0.0, self_harm)
    denominator = max(blocked + 0.5 * max(0.0, steal_value), EPSILON)
    robber_score = max(0.0, numerator / denominator)
    # reduce exponent to prevent early saturation
    q = 1.0 - math.exp(-1.5 * robber_score)
    return clamp_move_quality(q ** 1.2)


def discard_move_quality(
        discard: Mapping[Any, int],
        current_resources: Mapping[Any, float],
        plan_relevance: Optional[Mapping[Any, float]] = None) -> float:
    """Calculate move quality for a discard choice."""
    penalty = 0.0
    total_value = 0.0
    plan_relevance = plan_relevance or {}
    for resource, resource_count in current_resources.items():
        base_value = 1.0 + float(plan_relevance.get(resource, 0.0))
        scarcity_adjusted_value = base_value / (1.0 + max(0.0, float(resource_count)))
        total_value += float(resource_count) * scarcity_adjusted_value
        penalty += float(discard.get(resource, 0.0)) * scarcity_adjusted_value
    discard_score = max(0.0, 1.0 - penalty / (total_value + EPSILON))
    return clamp_move_quality(discard_score ** 1.3)  # compress slightly


def year_of_plenty_move_quality(
        etw_gain: float,
        utility_gain: float,
        enables_immediate_build: bool = False) -> float:
    """Calculate move quality for a Year of Plenty choice."""
    score = (1.0 - math.exp(-3.0 * max(0.0, etw_gain))) + 0.25 * (1.0 - math.exp(-max(0.0, utility_gain) / 10.0))
    if enables_immediate_build:
        score += 0.15
    return clamp_move_quality(score ** 1.1)


def monopoly_move_quality(
        total_resource_count: float,
        self_gain_efficiency: float,
        leader_share: float = 0.0) -> float:
    """Calculate move quality for a Monopoly choice."""
    score = (1.0 - math.exp(-max(0.0, total_resource_count) / 6.0)) * (
        1.0 - math.exp(-max(0.0, self_gain_efficiency) / 10.0)
    )
    score *= 1.0 + max(0.0, leader_share)
    return clamp_move_quality(score ** 1.1)


def trade_partner_move_quality(
        self_gain: float,
        opponent_gain: float,
        partner_is_leader: bool = False) -> float:
    """Calculate move quality for a trade-partner choice."""
    adjusted_opponent_gain = max(0.0, opponent_gain) * (1.5 if partner_is_leader else 1.0)
    trade_score = (max(0.0, self_gain) - 0.7 * adjusted_opponent_gain) / max(max(0.0, self_gain), EPSILON)
    q = _stable_logistic(5.0 * (trade_score - 0.2))
    return clamp_move_quality(q ** 1.2)


def strategic_turn_move_quality(
        candidate: Any,
        second_utility: Optional[float] = None,
        worst_utility: Optional[float] = None) -> float:
    """Calculate move quality for a strategic turn choice."""
    etw_before = max(0.0, float(getattr(candidate, "etw_before", 0.0) or 0.0))
    etw_after = float(getattr(candidate, "etw_after", etw_before) or etw_before)
    etw_delta = max(0.0, float(getattr(candidate, "etw_delta", etw_before - etw_after) or 0.0))
    utility_total = max(0.0, float(getattr(candidate, "utility_total", 0.0) or 0.0))
    absolute_score = 0.0
    if etw_before > EPSILON:
        reduction_ratio = etw_delta / etw_before
        absolute_score = 1.0 - math.exp(-3.0 * reduction_ratio)  # reduced exponent
    utility_score = 0.0
    if utility_total > 0.0:
        utility_score = 1.0 - math.exp(-utility_total / 20.0)
    relative_score = move_quality_from_margin(utility_total, second_utility, worst_utility)
    if absolute_score > 0.0:
        score = 0.55 * absolute_score + 0.25 * utility_score + 0.20 * relative_score
    elif utility_score > 0.0:
        score = 0.65 * utility_score + 0.35 * relative_score
    else:
        score = relative_score
    # final global compression; slightly stronger to avoid over-rewarding merely acceptable turns
    score = max(0.0, min(1.0, (score ** 1.35)))
    return clamp_move_quality(score)
