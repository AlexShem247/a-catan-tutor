from typing import Optional


def clamp_confidence(confidence: Optional[float]) -> float:
    if confidence is None:
        return 0.0
    return max(0.0, min(1.0, float(confidence)))


def confidence_label(confidence: float) -> str:
    confidence = clamp_confidence(confidence)
    if confidence >= 0.7:
        return "Excellent"
    if confidence >= 0.4:
        return "Good"
    return "Okay"


def confidence_from_ratio(chosen_value: float, max_value: float) -> float:
    if max_value <= 0.0:
        return 1.0 if chosen_value >= max_value else 0.0
    return clamp_confidence(chosen_value / max_value)


def confidence_from_margin(best_value: float, second_value: Optional[float], worst_value: Optional[float] = None)\
        -> float:
    if second_value is None:
        return 0.0

    margin = max(0.0, best_value - second_value)
    if worst_value is None:
        scale = max(abs(best_value), abs(second_value), 1e-6)
        return clamp_confidence(margin / scale)

    spread = max(0.0, best_value - worst_value)
    if spread <= 1e-6:
        return 0.0
    return clamp_confidence(margin / spread)


def initial_settlement_confidence(chosen_vertex_utility: float, max_vertex_utility: float) -> float:
    return confidence_from_ratio(chosen_vertex_utility, max_vertex_utility)


def initial_road_expansion_confidence(target_vertex_utility: float, max_legal_vertex_utility: float) -> float:
    return confidence_from_ratio(target_vertex_utility, max_legal_vertex_utility)


def initial_road_connection_confidence(valid_connection_edges: int) -> float:
    if valid_connection_edges <= 0:
        return 0.0
    return clamp_confidence(1.0 / float(valid_connection_edges))


def initial_road_flexible_confidence() -> float:
    return 0.3


def forced_choice_confidence(clearly_beneficial: bool = False) -> float:
    return 0.7 if clearly_beneficial else 0.5
