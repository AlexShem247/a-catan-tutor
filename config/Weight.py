class Weight:
    INIT_PLACE_YIELD = 1.0  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY = 0.5  # Value of having diverse resources initially
    INIT_PLACE_BLOCK = 0.3  # Penalty if initial settlement doesn't block opponent expansion

    BUILD_SELF_UTILITY = 1.0  # Importance of advancing own plan (reducing ETW)
    BUILD_OPPONENT_UTILITY = 0.5  # Importance of delaying or interfering with opponents
    BUILD_SPECIAL_UTILITY = 0.3  # Importance of special objectives (Longest Road, Largest Army)

    LR_BASE = 0.2  # Baseline value of Longest Road progress
    LR_PHASE = 0.6  # Weight of game progress (early vs late)
    LR_DISTANCE = 1.0  # Weight of closeness to claiming Longest Road
    LR_CONTEST = 0.8  # Weight of competition for Longest Road
