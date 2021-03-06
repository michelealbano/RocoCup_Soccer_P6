TEAM_1_NAME = "Team_1"
TEAM_2_NAME = "Team_2"

PLAYER_MAX_SPEED = 1.05
PLAYER_SPEED_DECAY = 0.4

DASH_POWER_RATE = 0.006

FOV_NARROW = 45
FOV_NORMAL = 90
FOV_WIDE = 180

BALL_DECAY = 0.94  # per tick
BALL_MAX_SPEED = 3
KICKABLE_MARGIN = 0.7
KICK_POWER_RATE = 0.027
CATCHABLE_MARGIN = 1

MINIMUM_TEAMMATES_FOR_PASS = 5

WARNING_PREFIX = '\033[93m'

QUANTIZE_STEP_LANDMARKS = 0.01
QUANTIZE_STEP_OBJECTS = 0.1
QUANTIZE_STEP_LINES = 0.01

EPSILON = 1.0e-10

# -----------------  Uppaal Strategies --------------------- #
# Make team use strategies by adding the team name to these lists
# For example DRIBBLE_OR_PASS_TEAMS = [TEAM_1_NAME] would make team one use possession model.
DRIBBLE_OR_PASS_TEAMS = []
STAMINA_MODEL_TEAMS = []
GOALIE_MODEL_TEAMS = []

DRIBBLE_OR_PASS_STRAT_PREFIX = "DRIBBLE_PASS:"
DRIBBLE_INDICATOR = "DRIBBLE_FORWARD"
PASS_INDICATOR = "PASS_TO:"

USING_PASS_CHAIN_STRAT = False
