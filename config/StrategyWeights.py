from contextlib import contextmanager
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class StrategyWeights:
    # Initial placement weights
    INIT_PLACE_YIELD: float = 1.0  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY: float = 0.5  # Value of having diverse resources initially
    INIT_PLACE_BLOCK: float = 0.3  # Penalty if initial settlement doesn't block opponent expansion

    # Building action utility weights
    BUILD_SELF_UTILITY: float = 1.0  # Importance of advancing own plan (reducing ETW)
    BUILD_OPPONENT_UTILITY: float = 0.5  # Importance of delaying or interfering with opponents
    BUILD_SPECIAL_UTILITY: float = 0.3  # Importance of special objectives (Longest Road, Largest Army)
    OPPONENT_INTERFERENCE_LEADING: float = 0.8  # How much leading player is weighted when calculating interference

    # Longest Road utility weights
    LR_BASE: float = 0.2  # Baseline value of Longest Road progress
    LR_PHASE: float = 0.6  # Weight of game progress (early vs late)
    LR_DISTANCE: float = 1.0  # Weight of closeness to claiming Longest Road
    LR_CONTEST: float = 0.8  # Weight of competition for Longest Road

    # Largest Army utility weights
    LA_BASE: float = 0.2  # Baseline value for Largest Army
    LA_PHASE: float = 0.6  # Weight for game phase
    LA_KNIGHT_DIST: float = 1.0  # Weight for closeness to claiming Largest Army
    LA_CONTEST: float = 0.8  # Weight for contest with other players

    # Robber targeting weights
    ROBBER_OWN_HEX_PENALTY: float = 0.5  # Penalty multiplier for placing robber on own hexes

    # Longest Road configuration
    LR_MIN_ROAD_LENGTH: int = 5  # Minimum road segments needed to claim Longest Road
    LR_UTILITY_MULTIPLIER: float = 2.0  # Utility multiplier per road segment when close to LR
    LR_ROAD_THRESHOLD: int = 4  # Minimum road length before considering LR utility

    # Largest Army configuration
    LA_MIN_KNIGHTS: int = 3  # Minimum knights needed to claim Largest Army
    LA_ARMY_THRESHOLD: int = 2  # Minimum army size before considering LA utility

    # Time discount factor
    TIME_DISCOUNT_RATE: float = 0.1  # Discount rate for future actions (higher = prefer immediate gains)

    # Settlement strategy
    MAX_SETTLEMENTS_FOR_CITY_UPGRADE: int = 2  # Max settlements to consider for city upgrade
    MIN_CANDIDATES_FOR_ROAD: int = 3  # Min candidate actions before considering road building
    MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE: int = 5  # Don't buy knights if army size exceeds this
    START_VERTEX_EXPANSION_BONUS: float = 0.05  # Small bonus for vertices with multiple outward road expansion options.
    ATTENTION_LR_VP_THRESHOLD: int = 7  # VP below which revealing Longest Road is considered "too early"

    # Knight evaluation
    KNIGHT_DEFICIT_THRESHOLD: int = 2  # Knight deficit for reduced value
    LOW_KNIGHT_VALUE: float = 0.1  # Value when far from the largest army
    HIGH_KNIGHT_VALUE: float = 2.0  # Value when claiming the largest army
    MEDIUM_KNIGHT_VALUE: float = 0.5  # Value when maintaining the largest army
    MIN_EXPECTED_VP_FOR_KNIGHT: float = 0.2  # Minimum expected VP to consider knight purchase

    # ETW (Estimated Time to Win) strategy
    ETW_NO_ACTION_PENALTY: float = 50.0  # Penalty added when no actions available
    ETW_MISSING_POINT_PENALTY: float = 10.0  # Penalty per missing victory point

    # Player Trades configuration
    LAMBDA_RISK_LEADER: float = 0.5
    # Risk-aversion weight for player trades: limits how much we are willing to help leader
    LAMBDA_RISK_BASE: float = 0.3
    # Risk-aversion weight for player trades: limits how much we are willing to help an opponent
    MAX_PLAYER_TRADE_GIVE_RATIO: int = 4  # Maximum cards we are willing to give for one in a player trade
    MIN_TRADE_ACCEPT_PROB: float = 0.1  # Minimum estimated acceptance probability for proposing a trade
    ACCEPT_ETW_WEIGHT: float = 1.0  # How strongly opponent benefit drives acceptance
    ACCEPT_COST_WEIGHT: float = 0.5  # Penalty per card the opponent gives
    ACCEPT_HISTORY_WEIGHT: float = 0.3  # Influence of past acceptance behaviour
    CLOSE_OPPONENT_VP_GAP: int = 2  # Opponent is considered close if within this VP gap of the agent
    TRADE_LEADER_PENALTY: float = 0.5  # Small bias against trading with the current leader

    # Attention management
    ATTENTION_LR_EARLY_PENALTY: float = 15.0
    # Discourages claiming Longest Road too early to avoid signalling leadership.
    DEV_CLOSE_THRESHOLD: float = 0.08  # Dev card allowed if close in utility to best build.
    DIVERSION_BOOST: float = 1.25  # Robber diversion boost when tied for the VP lead.

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(field.name for field in fields(cls))

    @contextmanager
    def applied(self):
        old_values = {name: getattr(type(self), name) for name in self.field_names()}
        for name in self.field_names():
            setattr(type(self), name, getattr(self, name))
        try:
            yield self
        finally:
            for name, value in old_values.items():
                setattr(type(self), name, value)


EVO_STRATEGY_WEIGHTS = StrategyWeights(
    INIT_PLACE_YIELD=0.8090391218465477,
    INIT_PLACE_DIVERSITY=0.06925169328869862,
    INIT_PLACE_BLOCK=0.7079829520890228,

    BUILD_SELF_UTILITY=0.5558697691576708,
    BUILD_OPPONENT_UTILITY=0.0,
    BUILD_SPECIAL_UTILITY=0.6246965115967429,
    OPPONENT_INTERFERENCE_LEADING=1.269757406841495,

    LR_BASE=0.8262124766408883,
    LR_PHASE=0.19094981657062948,
    LR_DISTANCE=1.2161574063984448,
    LR_CONTEST=0.3933398590546677,

    LA_BASE=0.2281765141760816,
    LA_PHASE=0.9368919737497734,
    LA_KNIGHT_DIST=0.9979010080964699,
    LA_CONTEST=0.0,

    ROBBER_OWN_HEX_PENALTY=0.5350214735744845,

    LR_MIN_ROAD_LENGTH=5,
    LR_UTILITY_MULTIPLIER=1.4918710718709927,
    LR_ROAD_THRESHOLD=4,

    LA_MIN_KNIGHTS=4,
    LA_ARMY_THRESHOLD=1,

    TIME_DISCOUNT_RATE=1.2403938710277025,

    MAX_SETTLEMENTS_FOR_CITY_UPGRADE=2,
    MIN_CANDIDATES_FOR_ROAD=3,
    MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE=5,
    START_VERTEX_EXPANSION_BONUS=0.28169387753580094,
    ATTENTION_LR_VP_THRESHOLD=7,

    KNIGHT_DEFICIT_THRESHOLD=2,
    LOW_KNIGHT_VALUE=0.2571382591709136,
    HIGH_KNIGHT_VALUE=2.4553324046428946,
    MEDIUM_KNIGHT_VALUE=0.4478427439484143,
    MIN_EXPECTED_VP_FOR_KNIGHT=0.19350416156068828,

    ETW_NO_ACTION_PENALTY=49.7205845700767,
    ETW_MISSING_POINT_PENALTY=9.953790870877215,

    LAMBDA_RISK_LEADER=0.9438252157227857,
    LAMBDA_RISK_BASE=0.6891581327736052,
    MAX_PLAYER_TRADE_GIVE_RATIO=5,
    MIN_TRADE_ACCEPT_PROB=0.3324369299988479,
    ACCEPT_ETW_WEIGHT=0.29012260538301715,
    ACCEPT_COST_WEIGHT=0.4525020535064614,
    ACCEPT_HISTORY_WEIGHT=0.24497757341489124,
    CLOSE_OPPONENT_VP_GAP=3,
    TRADE_LEADER_PENALTY=0.34258950128283605,

    ATTENTION_LR_EARLY_PENALTY=15.276679632229282,
    DEV_CLOSE_THRESHOLD=-0.9715123961561473,
    DIVERSION_BOOST=1.1346294592642947,
)

ORIGINAL_STRATEGY_WEIGHTS = StrategyWeights(
    INIT_PLACE_YIELD=1.0,
    INIT_PLACE_DIVERSITY=0.5,
    INIT_PLACE_BLOCK=0.3,

    BUILD_SELF_UTILITY=1.0,
    BUILD_OPPONENT_UTILITY=0.5,
    BUILD_SPECIAL_UTILITY=0.3,
    OPPONENT_INTERFERENCE_LEADING=0.8,

    LR_BASE=0.2,
    LR_PHASE=0.6,
    LR_DISTANCE=1.0,
    LR_CONTEST=0.8,

    LA_BASE=0.2,
    LA_PHASE=0.6,
    LA_KNIGHT_DIST=1.0,
    LA_CONTEST=0.8,

    ROBBER_OWN_HEX_PENALTY=0.5,

    LR_MIN_ROAD_LENGTH=5,
    LR_UTILITY_MULTIPLIER=2.0,
    LR_ROAD_THRESHOLD=4,

    LA_MIN_KNIGHTS=3,
    LA_ARMY_THRESHOLD=2,

    TIME_DISCOUNT_RATE=0.1,

    MAX_SETTLEMENTS_FOR_CITY_UPGRADE=2,
    MIN_CANDIDATES_FOR_ROAD=3,
    MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE=5,
    START_VERTEX_EXPANSION_BONUS=0.05,
    ATTENTION_LR_VP_THRESHOLD=7,

    KNIGHT_DEFICIT_THRESHOLD=2,
    LOW_KNIGHT_VALUE=0.1,
    HIGH_KNIGHT_VALUE=2.0,
    MEDIUM_KNIGHT_VALUE=0.5,
    MIN_EXPECTED_VP_FOR_KNIGHT=0.2,

    ETW_NO_ACTION_PENALTY=50.0,
    ETW_MISSING_POINT_PENALTY=10.0,

    LAMBDA_RISK_LEADER=0.5,
    LAMBDA_RISK_BASE=0.3,
    MAX_PLAYER_TRADE_GIVE_RATIO=4,
    MIN_TRADE_ACCEPT_PROB=0.1,
    ACCEPT_ETW_WEIGHT=1.0,
    ACCEPT_COST_WEIGHT=0.5,
    ACCEPT_HISTORY_WEIGHT=0.3,
    CLOSE_OPPONENT_VP_GAP=2,
    TRADE_LEADER_PENALTY=0.5,

    ATTENTION_LR_EARLY_PENALTY=15.0,
    DEV_CLOSE_THRESHOLD=0.08,
    DIVERSION_BOOST=1.25,
)
