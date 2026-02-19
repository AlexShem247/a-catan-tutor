# Toggle: fast (cheap) vs full (strong)
FAST_MODE = True

# Settlement candidate search limits
MAX_EXTRA_ROADS_FOR_SETTLEMENT = 2 if FAST_MODE else 3  # Max extra roads to reach settlement
MAX_POTENTIAL_VERTICES = 10 if FAST_MODE else 40        # Max vertices in pre-filter
MAX_SETTLEMENT_CANDIDATES = 3 if FAST_MODE else 8      # Max settlement actions kept
MAX_BEAM_PER_DEPTH = 20 if FAST_MODE else 80           # Beam width per depth
MAX_EXPANSIONS_PER_STATE = 3 if FAST_MODE else 8       # Branch cap per state
MAX_CANDIDATES_TOTAL = 40 if FAST_MODE else 180        # Hard cap on sequences

START_LIMIT = 6 if FAST_MODE else 16                    # Expand from top-N starts
MAX_CHEAP_CANDIDATES_TOTAL = 40 if FAST_MODE else 160  # Cheap pool cap pre-ETB
K_ETB_EVAL = 12 if FAST_MODE else 50                    # ETB-eval top-K cheap
DIRECT_LIMIT = 8 if FAST_MODE else 30                   # ETB-eval top-N direct spots
ROAD_LEN_PENALTY = 0.18 if FAST_MODE else 0.12          # Bias against long roads

# Candidate action generation thresholds
ROAD_ETB_THRESHOLD = 10.0 if FAST_MODE else 14.0        # Road allowed if ETB ≤ this
DEV_CARD_ETB_THRESHOLD = 15.0 if FAST_MODE else 22.0    # Dev card allowed if ETB ≤ this

# ETW simulation limits
ETW_SIMULATION_MAX_CANDIDATES = 5 if FAST_MODE else 20  # Max candidates in ETW sim
ETW_ETB_THRESHOLD = 20.0 if FAST_MODE else 30.0         # Abort ETW if ETB > this
ETW_MAX_DEPTH_OFFSET = 5 if FAST_MODE else 9            # Extra depth over WIN_POINTS
MAX_EVALUATIONS = 5 if FAST_MODE else 18                # Max evals per turn
MAX_ETB_THRESHOLD = 15.0 if FAST_MODE else 25.0         # Ignore if ETB > this
EVAL_UTIL_MAX_DEPTH = 3 if FAST_MODE else 5             # Utility eval depth cap

# Trade limits
TRADE_ETW_SHORTLIST_K = 6 if FAST_MODE else 14          # Trades: top-K for full ETW
CHECK_INVALID_TRADES_EARLY = True                       # Early reject invalid trades

# Small value to avoid division by zero
EPSILON = 1e-6                                          # Tiny constant