class StrategyWeights:
    # Initial placement weights
    INIT_PLACE_YIELD = 1.0  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY = 0.5  # Value of having diverse resources initially
    INIT_PLACE_BLOCK = 0.3  # Penalty if initial settlement doesn't block opponent expansion

    # Building action utility weights
    BUILD_SELF_UTILITY = 1.0  # Importance of advancing own plan (reducing ETW)
    BUILD_OPPONENT_UTILITY = 0.5  # Importance of delaying or interfering with opponents
    BUILD_SPECIAL_UTILITY = 0.3  # Importance of special objectives (Longest Road, Largest Army)
    OPPONENT_INTERFERENCE_LEADING = 0.8  # How much leading player is weighted when calculating interference

    # Longest Road utility weights
    LR_BASE = 0.2  # Baseline value of Longest Road progress
    LR_PHASE = 0.6  # Weight of game progress (early vs late)
    LR_DISTANCE = 1.0  # Weight of closeness to claiming Longest Road
    LR_CONTEST = 0.8  # Weight of competition for Longest Road

    # Largest Army utility weights
    LA_BASE = 0.2  # Baseline value for Largest Army
    LA_PHASE = 0.6  # Weight for game phase
    LA_KNIGHT_DIST = 1.0  # Weight for closeness to claiming Largest Army
    LA_CONTEST = 0.8  # Weight for contest with other players

    # Robber targeting weights
    ROBBER_OWN_HEX_PENALTY = 0.5  # Penalty multiplier for placing robber on own hexes

    # Longest Road configuration
    LR_MIN_ROAD_LENGTH = 5  # Minimum road segments needed to claim Longest Road
    LR_UTILITY_MULTIPLIER = 2.0  # Utility multiplier per road segment when close to LR
    LR_ROAD_THRESHOLD = 4  # Minimum road length before considering LR utility

    # Largest Army configuration
    LA_MIN_KNIGHTS = 3  # Minimum knights needed to claim Largest Army
    LA_ARMY_THRESHOLD = 2  # Minimum army size before considering LA utility

    # Time discount factor
    TIME_DISCOUNT_RATE = 0.1  # Discount rate for future actions (higher = prefer immediate gains)

    # Settlement strategy
    MAX_SETTLEMENTS_FOR_CITY_UPGRADE = 2  # Max settlements to consider for city upgrade
    MIN_CANDIDATES_FOR_ROAD = 3  # Min candidate actions before considering road building
    MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE = 5  # Don't buy knights if army size exceeds this

    # Knight evaluation
    KNIGHT_DEFICIT_THRESHOLD = 2  # Knight deficit for reduced value
    LOW_KNIGHT_VALUE = 0.1  # Value when far from the largest army
    HIGH_KNIGHT_VALUE = 2.0  # Value when claiming the largest army
    MEDIUM_KNIGHT_VALUE = 0.5  # Value when maintaining the largest army
    MIN_EXPECTED_VP_FOR_KNIGHT = 0.2  # Minimum expected VP to consider knight purchase

    # ETW (Estimated Time to Win) strategy
    ETW_NO_ACTION_PENALTY = 50.0  # Penalty added when no actions available
    ETW_MISSING_POINT_PENALTY = 10.0  # Penalty per missing victory point

    # Player Trades configuration
    LAMBDA_RISK_LEADER = 0.5  # Risk-aversion weight for player trades: limits how much we are willing to help leader
    LAMBDA_RISK_BASE = 0.3  # Risk-aversion weight for player trades: limits how much we are willing to help an opponent
    MAX_PLAYER_TRADE_GIVE_RATIO = 4  # Maximum cards we are willing to give for one in a player trade
    MIN_TRADE_ACCEPT_PROB = 0.1  # Minimum estimated acceptance probability for proposing a trade
    ACCEPT_ETW_WEIGHT = 1.0  # How strongly opponent benefit drives acceptance
    ACCEPT_COST_WEIGHT = 0.5  # Penalty per card the opponent gives
    ACCEPT_HISTORY_WEIGHT = 0.3  # Influence of past acceptance behaviour
