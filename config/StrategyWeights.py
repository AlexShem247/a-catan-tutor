class StrategyWeights:
    # Initial placement weights
    INIT_PLACE_YIELD = 0.8090391218465477  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY = 0.06925169328869862  # Value of having diverse resources initially
    INIT_PLACE_BLOCK = 0.7079829520890228  # Penalty if initial settlement doesn't block opponent expansion

    # Building action utility weights
    BUILD_SELF_UTILITY = 0.5558697691576708  # Importance of advancing own plan (reducing ETW)
    BUILD_OPPONENT_UTILITY = 0.0  # Importance of delaying or interfering with opponents
    BUILD_SPECIAL_UTILITY = 0.6246965115967429  # Importance of special objectives (Longest Road, Largest Army)
    OPPONENT_INTERFERENCE_LEADING = 1.269757406841495  # Leader weight in interference calculation

    # Longest Road utility weights
    LR_BASE = 0.8262124766408883  # Baseline value of Longest Road progress
    LR_PHASE = 0.19094981657062948  # Weight of game progress (early vs late)
    LR_DISTANCE = 1.2161574063984448  # Weight of closeness to claiming Longest Road
    LR_CONTEST = 0.3933398590546677  # Weight of competition for Longest Road

    # Largest Army utility weights
    LA_BASE = 0.2281765141760816  # Baseline value for Largest Army
    LA_PHASE = 0.9368919737497734  # Weight for game phase
    LA_KNIGHT_DIST = 0.9979010080964699  # Weight for closeness to claiming Largest Army
    LA_CONTEST = 0.0  # Weight for contest with other players

    # Robber targeting weights
    ROBBER_OWN_HEX_PENALTY = 0.5350214735744845  # Penalty multiplier for placing robber on own hexes

    # Longest Road configuration
    LR_MIN_ROAD_LENGTH = 5  # Minimum road segments needed to claim Longest Road
    LR_UTILITY_MULTIPLIER = 1.4918710718709927  # Utility multiplier per road segment when close to LR
    LR_ROAD_THRESHOLD = 4  # Minimum road length before considering LR utility

    # Largest Army configuration
    LA_MIN_KNIGHTS = 4  # Minimum knights needed to claim Largest Army
    LA_ARMY_THRESHOLD = 1  # Minimum army size before considering LA utility

    # Time discount factor
    TIME_DISCOUNT_RATE = 1.2403938710277025  # Discount rate for future actions (higher = prefer immediate gains)

    # Settlement strategy
    MAX_SETTLEMENTS_FOR_CITY_UPGRADE = 2  # Max settlements to consider for city upgrade
    MIN_CANDIDATES_FOR_ROAD = 3  # Min candidate actions before considering road building
    MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE = 5  # Don't buy knights if army size exceeds this
    START_VERTEX_EXPANSION_BONUS = 0.28169387753580094  # Bonus for high-expansion vertices
    ATTENTION_LR_VP_THRESHOLD = 7  # VP below which revealing Longest Road is considered "too early"

    # Knight evaluation
    KNIGHT_DEFICIT_THRESHOLD = 2  # Knight deficit for reduced value
    LOW_KNIGHT_VALUE = 0.2571382591709136  # Value when far from the largest army
    HIGH_KNIGHT_VALUE = 2.4553324046428946  # Value when claiming the largest army
    MEDIUM_KNIGHT_VALUE = 0.4478427439484143  # Value when maintaining the largest army
    MIN_EXPECTED_VP_FOR_KNIGHT = 0.19350416156068828  # Minimum expected VP to consider knight purchase

    # ETW (Estimated Time to Win) strategy
    ETW_NO_ACTION_PENALTY = 49.7205845700767  # Penalty added when no actions available
    ETW_MISSING_POINT_PENALTY = 9.953790870877215  # Penalty per missing victory point

    # Player Trades configuration
    LAMBDA_RISK_LEADER = 0.9438252157227857  # Trade risk weight against helping the leader
    LAMBDA_RISK_BASE = 0.6891581327736052  # Trade risk weight against helping opponents
    MAX_PLAYER_TRADE_GIVE_RATIO = 5  # Maximum cards we are willing to give for one in a player trade
    MIN_TRADE_ACCEPT_PROB = 0.3324369299988479  # Minimum estimated acceptance probability for proposing a trade
    ACCEPT_ETW_WEIGHT = 0.29012260538301715  # How strongly opponent benefit drives acceptance
    ACCEPT_COST_WEIGHT = 0.4525020535064614  # Penalty per card the opponent gives
    ACCEPT_HISTORY_WEIGHT = 0.24497757341489124  # Influence of past acceptance behaviour
    CLOSE_OPPONENT_VP_GAP = 3  # Opponent is considered close if within this VP gap of the agent
    TRADE_LEADER_PENALTY = 0.34258950128283605  # Small bias against trading with the current leader

    # Attention management
    ATTENTION_LR_EARLY_PENALTY = 15.276679632229282  # Penalty for claiming Longest Road too early
    DEV_CLOSE_THRESHOLD = -0.9715123961561473  # Dev card allowed if close in utility to best build.
    DIVERSION_BOOST = 1.1346294592642947  # Robber diversion boost when tied for the VP lead.
