class StrategyWeights:
    # Initial placement weights
    INIT_PLACE_YIELD = 0.8090  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY = 0.0693  # Value of having diverse resources initially
    INIT_PLACE_BLOCK = 0.7078  # Penalty if initial settlement doesn't block opponent expansion

    # Building action utility weights
    BUILD_SELF_UTILITY = 0.5559  # Importance of advancing own plan (reducing ETW)
    BUILD_OPPONENT_UTILITY = 0.2267  # Importance of delaying or interfering with opponents
    BUILD_SPECIAL_UTILITY = 0.6247  # Importance of special objectives (Longest Road, Largest Army)
    OPPONENT_INTERFERENCE_LEADING = 1.2698  # Leader weight in interference calculation

    # Longest Road utility weights
    LR_BASE = 0.8262  # Baseline value of Longest Road progress
    LR_PHASE = 0.1909  # Weight of game progress (early vs late)
    LR_DISTANCE = 1.2162  # Weight of closeness to claiming Longest Road
    LR_CONTEST = 0.3933  # Weight of competition for Longest Road

    # Largest Army utility weights
    LA_BASE = 0.2282  # Baseline value for Largest Army
    LA_PHASE = 0.9369  # Weight for game phase
    LA_KNIGHT_DIST = 0.9979  # Weight for closeness to claiming Largest Army
    LA_CONTEST = 0.6067  # Weight for contest with other players

    # Robber targeting weights
    ROBBER_OWN_HEX_PENALTY = 0.5350  # Penalty multiplier for placing robber on own hexes

    # Longest Road configuration
    LR_MIN_ROAD_LENGTH = 5  # Minimum road segments needed to claim Longest Road
    LR_UTILITY_MULTIPLIER = 1.4919  # Utility multiplier per road segment when close to LR
    LR_ROAD_THRESHOLD = 4  # Minimum road length before considering LR utility

    # Largest Army configuration
    LA_MIN_KNIGHTS = 4  # Minimum knights needed to claim Largest Army
    LA_ARMY_THRESHOLD = 1  # Minimum army size before considering LA utility

    # Time discount factor
    TIME_DISCOUNT_RATE = 1.2404  # Discount rate for future actions (higher = prefer immediate gains)

    # Settlement strategy
    MAX_SETTLEMENTS_FOR_CITY_UPGRADE = 2  # Max settlements to consider for city upgrade
    MIN_CANDIDATES_FOR_ROAD = 3  # Min candidate actions before considering road building
    MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE = 5  # Don't buy knights if army size exceeds this
    START_VERTEX_EXPANSION_BONUS = 0.2817  # Bonus for high-expansion vertices
    ATTENTION_LR_VP_THRESHOLD = 7  # VP below which revealing Longest Road is considered "too early"

    # Knight evaluation
    KNIGHT_DEFICIT_THRESHOLD = 2  # Knight deficit for reduced value
    LOW_KNIGHT_VALUE = 0.2571  # Value when far from the largest army
    HIGH_KNIGHT_VALUE = 2.4553  # Value when claiming the largest army
    MEDIUM_KNIGHT_VALUE = 0.4478  # Value when maintaining the largest army
    MIN_EXPECTED_VP_FOR_KNIGHT = 0.1935  # Minimum expected VP to consider knight purchase

    # ETW (Estimated Time to Win) strategy
    ETW_NO_ACTION_PENALTY = 49.7206  # Penalty added when no actions available
    ETW_MISSING_POINT_PENALTY = 9.9538  # Penalty per missing victory point

    # Player Trades configuration
    LAMBDA_RISK_LEADER = 0.9438  # Trade risk weight against helping the leader
    LAMBDA_RISK_BASE = 0.6892  # Trade risk weight against helping opponents
    MAX_PLAYER_TRADE_GIVE_RATIO = 5  # Maximum cards we are willing to give for one in a player trade
    MIN_TRADE_ACCEPT_PROB = 0.3324  # Minimum estimated acceptance probability for proposing a trade
    ACCEPT_ETW_WEIGHT = 0.2901  # How strongly opponent benefit drives acceptance
    ACCEPT_COST_WEIGHT = 0.4525  # Penalty per card the opponent gives
    ACCEPT_HISTORY_WEIGHT = 0.2450  # Influence of past acceptance behaviour
    CLOSE_OPPONENT_VP_GAP = 3  # Opponent is considered close if within this VP gap of the agent
    TRADE_LEADER_PENALTY = 0.3426  # Small bias against trading with the current leader

    # Attention management
    ATTENTION_LR_EARLY_PENALTY = 15.2767  # Penalty for claiming Longest Road too early
    DEV_CLOSE_THRESHOLD = -0.9715  # Dev card allowed if close in utility to best build.
    DIVERSION_BOOST = 1.1346  # Robber diversion boost when tied for the VP lead.
