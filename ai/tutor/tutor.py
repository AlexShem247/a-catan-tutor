from enum import Enum, auto


class TutorStage(Enum):
    # Opening
    INITIAL_SETTLEMENT = auto()
    INITIAL_ROAD = auto()

    # Main turn flow
    TURN_ACTION = auto()
    TRADE_DECISION = auto()
    TRADE_RESPONSE = auto()

    # Special events
    ROBBER_PLACEMENT = auto()
    ROBBER_STEAL_TARGET = auto()
    DISCARD_RESOURCES = auto()

    # Development-card specific choices
    YEAR_OF_PLENTY = auto()
    MONOPOLY = auto()
    ROAD_BUILDING = auto()


TUTOR_STAGE_CONTENT: dict[TutorStage, dict] = {
    TutorStage.INITIAL_SETTLEMENT: {
        "title": "Opening placement",
        "focus": [
            "Prioritise strong production numbers",
            "Aim for good resource coverage",
            "Keep future road expansion in mind",
        ]
    },
    TutorStage.INITIAL_ROAD: {
        "title": "Opening road placement",
        "focus": [
            "Point toward strong future settlement spots",
            "Preserve access to useful resources or ports",
            "Avoid blocking your own expansion routes",
        ]
    },
    TutorStage.TURN_ACTION: {
        "title": "Your turn",
        "focus": [
            "Check what your roll unlocked before spending resources",
            "Prioritise the action that improves your position fastest",
            "Keep enough flexibility for trades, expansion, or defence",
        ]
    },
    TutorStage.TRADE_DECISION: {
        "title": "Trade decision",
        "focus": [
            "Trade to improve your next important build, not just to swap cards",
            "Be careful not to give strong opponents exactly what they need",
            "Compare player trades against bank or port alternatives",
        ]
    },
    TutorStage.TRADE_RESPONSE: {
        "title": "Responding to a trade",
        "focus": [
            "Accept only if the deal improves your position clearly",
            "Consider what the other player gains as well as what you gain",
            "Reject trades that help an opponent more than they help you",
        ]
    },
    TutorStage.ROBBER_PLACEMENT: {
        "title": "Robber placement",
        "focus": [
            "Block strong production, especially high-probability tiles",
            "Try to slow the player in the strongest position",
            "Avoid hurting your own future production if possible",
        ]
    },
    TutorStage.ROBBER_STEAL_TARGET: {
        "title": "Choosing who to steal from",
        "focus": [
            "Prefer opponents who are strong or likely to hold useful resources",
            "A steal can slow an opponent as well as help you",
            "If several choices are similar, favour the player posing the biggest threat",
        ]
    },
    TutorStage.DISCARD_RESOURCES: {
        "title": "Discarding resources",
        "focus": [
            "Keep the resources that preserve your strongest build options",
            "Try not to break an important near-term plan",
            "Discard surplus or less flexible resources first when possible",
        ]
    },
    TutorStage.YEAR_OF_PLENTY: {
        "title": "Year of Plenty",
        "focus": [
            "Choose resources that complete your strongest immediate action",
            "If no build is available now, take resources that improve your next turn",
            "Think about whether tempo or flexibility matters more here",
        ]
    },
    TutorStage.MONOPOLY: {
        "title": "Monopoly",
        "focus": [
            "Choose the resource type most concentrated among opponents",
            "A strong monopoly can disrupt opponents as well as help you",
            "Use it when the gain is large or when it unlocks an important build",
        ]
    },
    TutorStage.ROAD_BUILDING: {
        "title": "Road Building",
        "focus": [
            "Use the free roads to improve expansion, not just to add length",
            "Look for roads that open strong settlement locations",
            "Consider whether the roads also improve Longest Road pressure",
        ]
    },
}
