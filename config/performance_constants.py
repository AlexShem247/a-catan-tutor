# Settlement candidate search limits
MAX_EXTRA_ROADS_FOR_SETTLEMENT = 2     # Max roads to build to reach a settlement location
MAX_POTENTIAL_VERTICES = 10            # Max vertices to consider in heuristic pre-filtering
MAX_SETTLEMENT_CANDIDATES = 3          # Max settlement candidates to include in action list
MAX_BEAM_PER_DEPTH = 20          # how many partial paths to keep per depth
MAX_EXPANSIONS_PER_STATE = 3     # limit branching from any one state
MAX_CANDIDATES_TOTAL = 40        # cap returned candidate action sequences

START_LIMIT = 6  # expand only from the best few start vertices
MAX_CHEAP_CANDIDATES_TOTAL = 40  # cap cheap candidate pool before ETB
K_ETB_EVAL = 12  # compute ETB only for top-K cheap candidates
DIRECT_LIMIT = 8  # only ETB-evaluate top-N direct-on-network settlement spots
ROAD_LEN_PENALTY = 0.18  # cheap preference for shorter road paths

# Candidate action generation thresholds
ROAD_ETB_THRESHOLD = 10.0              # Max ETB to consider building a road
DEV_CARD_ETB_THRESHOLD = 15.0          # Max ETB to consider buying development cards

# ETW simulation limits
ETW_SIMULATION_MAX_CANDIDATES = 5      # Max candidates to evaluate during ETW simulation
ETW_ETB_THRESHOLD = 20.0               # ETB threshold to abort ETW simulation
ETW_MAX_DEPTH_OFFSET = 5               # Offset added to WIN_POINTS for simulation depth limit
MAX_EVALUATIONS = 5                    # Maximum number of candidate actions to evaluate per turn
MAX_ETB_THRESHOLD = 15.0               # Maximum ETB value to consider an action (higher = ignore)
EVAL_UTIL_MAX_DEPTH = 3                # Maximum depth for evaluating utilities

# Trade limits
TRADE_ETW_SHORTLIST_K = 6              # Number of top-ranked trade offers to evaluate with full ETW.
CHECK_INVALID_TRADES_EARLY = True      # Reads opponents hand to see if the trade will be invalid for opponents

# Small value to avoid division by zero
EPSILON = 1e-6
