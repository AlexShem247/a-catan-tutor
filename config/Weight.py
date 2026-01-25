class Weight:
    # Initial placement weights
    INIT_PLACE_YIELD = 1.0  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY = 0.5  # Value of having diverse resources initially
    INIT_PLACE_BLOCK = 0.3  # Penalty if initial settlement doesn't block opponent expansion

    # Building action utility weights
    BUILD_SELF_UTILITY = 1.0  # Importance of advancing own plan (reducing ETW)
    BUILD_OPPONENT_UTILITY = 0.5  # Importance of delaying or interfering with opponents
    BUILD_SPECIAL_UTILITY = 0.3  # Importance of special objectives (Longest Road, Largest Army)

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

    # Performance optimization limits
    MAX_EVALUATIONS = 5  # Maximum number of candidate actions to evaluate per turn
    MAX_CANDIDATES_GENERATE = 8  # Maximum number of candidate actions to generate per turn
    MAX_ETW_SIMULATION_DEPTH_SHALLOW = 5  # ETW simulation depth for candidate evaluation
    MAX_ETW_SIMULATION_DEPTH_DEEP = 8  # ETW simulation depth for main planning
    MAX_ETB_THRESHOLD = 15.0  # Maximum ETB value to consider an action (higher = ignore)
