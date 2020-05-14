import fnmatch
import re
from pathlib import Path
import os
from datetime import datetime
import math

from statisticsmodule.statistics import Game, Team, Stage, Player, Ball
from statisticsmodule import statistics
from parsing import _ROBOCUP_MSG_REGEX, _SIGNED_INT_REGEX, _REAL_NUM_REGEX
from geometry import get_distance_between_coords, Coordinate
from player import playerstrategy

SERVER_LOG_PATTERN = '*.rcg'
ACTION_LOG_PATTERN = '*.rcl'
__HEX_REGEX = "0[xX][0-9a-fA-F]+"

_LOWEST_STAMINA = 1000


# Main method
def parse_logs():
    game = statistics.Game()
    server_log_name = get_newest_server_log()
    action_log_name = get_newest_action_log()
    parse_log_name(server_log_name, game)

    # init number of players
    with open(Path(__file__).parent.parent / action_log_name, 'r') as file:
        for line in file:
            if "init" in line and "Coach" not in line:
                parse_init_action(line, game)
            else:
                continue

    # parsing server log file
    with open(Path(__file__).parent.parent / server_log_name, 'r') as file:
        for line in file:
            if line.startswith("(show "):
                parse_show_line(line, game)
            else:
                continue

    # parsing action log
    with open(Path(__file__).parent.parent / action_log_name, 'r') as file:
        for line in file:
            if "kick " in line:
                parse_kick_action(line, game)
            elif "goal_" in line and "kick" not in line:
                parse_goal_action(line, game)
            else:
                continue

    calculate_possession(game)
    calculate_stamina(game)

    log_directory = Path(__file__).parent.parent / game.gameID
    os.makedirs(log_directory)

    with open(os.path.join(log_directory, "game_goals.txt"), "w") as file:
        for goal in game.goals:
            file.write(goal + "\n")

    file_left = open(os.path.join(log_directory, "%s_leftkicks.txt" % game.teams[0].name), "w")
    file_right = open(os.path.join(log_directory, "%s_rightkicks.txt" % game.teams[1].name), "w")
    file_l_goalie_kicks = open(os.path.join(log_directory, "%s_left_goalie_kicks.txt" % game.teams[0].name), "w")
    file_r_goalie_kicks = open(os.path.join(log_directory, "%s_right_goalie_kicks.txt" % game.teams[1].name), "w")
    file_l_stamina = open(os.path.join(log_directory, "%s_left_stamina.txt" % game.teams[0].name), "w")
    file_r_stamina = open(os.path.join(log_directory, "%s_right_stamina.txt" % game.teams[1].name), "w")
    file_l_biptest = open(os.path.join(log_directory, "%s_biptest_rounds.txt" % game.teams[0].name), "w")
    file_r_biptest = open(os.path.join(log_directory, "%s_biptest_rounds.txt" % game.teams[1].name), "w")

    files = [file_left, file_l_goalie_kicks, file_right, file_r_goalie_kicks, file_l_stamina, file_r_stamina,
             file_l_biptest, file_r_biptest]

    write_possession_file(game)

    file_l_biptest.write(str(playerstrategy.__BIP_TEST_L))
    file_r_biptest.write(str(playerstrategy.__BIP_TEST_R))

    for t in game.teams:
        if t.side == "l":
            file_l_stamina.write(write_stamina_file(game, t))
        if t.side == "r":
            file_r_stamina.write(write_stamina_file(game, t))

    for stage in game.show_time:
        file_left.write(str(game.show_time.index(stage) + 1) + " " + str(stage.team_l_kicks) + "\n")
        file_right.write(str(game.show_time.index(stage) + 1) + " " + str(stage.team_r_kicks) + "\n")
        for player in stage.players:
            if player.no == 1:
                if player.side == "l":
                    file_l_goalie_kicks.write(str(game.show_time.index(stage) + 1) + " " + str(player.kicks) + "\n")
                if player.side == "r":
                    file_r_goalie_kicks.write(str(game.show_time.index(stage) + 1) + " " + str(player.kicks) + "\n")

    for file in files:
        file.close()


def write_stamina_file(game: Game, t: Team):
    return str("Time in ticks where stamina is under " + str(_LOWEST_STAMINA) + ": "
               + str(t.stamina_under) + " average: " + str(t.stamina_under / t.number_of_players)
               + "\nTime in ticks where stamina is over "
               + str(_LOWEST_STAMINA) + ": " + str(t.stamina_over) + " average: "
               + str(t.stamina_over / t.number_of_players) + "\n"
               + "Player with highest tick count under " + str(_LOWEST_STAMINA) + ": "
               + str(highest_stamina_under(game, t.side)) + "\n"
               + "Player with highest tick count over " + str(_LOWEST_STAMINA) + ": "
               + str(highest_stamina_over(game, t.side)))


def calculate_highest_stamina(game: Game):
    for team in game.teams:
        if team.side == "l":
            for x in range(team.number_of_players):
                game.player_l_stamina_over.append(0)
                game.player_l_stamina_under.append(0)
        if team.side == "r":
            for x in range(team.number_of_players):
                game.player_r_stamina_over.append(0)
                game.player_r_stamina_under.append(0)

    for stage in game.show_time:
        for player in stage.players:
            if player.side == "l":
                game.player_l_stamina_under[player.no - 1] += player.stamina_under
                game.player_l_stamina_over[player.no - 1] += player.stamina_over
            if player.side == "r":
                game.player_r_stamina_under[player.no - 1] += player.stamina_under
                game.player_r_stamina_over[player.no - 1] += player.stamina_over


def highest_stamina_over(game: Game, side: str):
    if side == "l":
        return max(game.player_l_stamina_over)
    if side == "r":
        return max(game.player_r_stamina_over)


def highest_stamina_under(game: Game, side: str):
    if side == "l":
        return max(game.player_l_stamina_under)
    if side == "r":
        return max(game.player_r_stamina_under)


def calculate_stamina(game: Game):
    # for every tick in log file
    for stage in game.show_time:
        # for every player in the tick
        for p in stage.players:
            # for every team in tick
            for t in game.teams:
                # if players side is same as teams side.
                if p.side == t.side:
                    if p.stamina < _LOWEST_STAMINA:
                        t.stamina_under += 1
                        p.stamina_under += 1
                    elif p.stamina > _LOWEST_STAMINA:
                        t.stamina_over += 1
                        p.stamina_over += 1

    calculate_highest_stamina(game)


def calculate_possession(game: Game):
    last_ball = None
    counter = 0
    start_ball = None
    last_stage = game.show_time[0]

    # for all ticks in game
    for stage in game.show_time:
        # if the abs value of either x or y goes up, then the ball has been possessed.
        if abs(stage.ball.x_coord) > abs(last_stage.ball.x_coord) or \
                abs(stage.ball.y_coord) > abs(last_stage.ball.y_coord):

            # if the last kicker kicked in last tick, then it is the last possessor, else it is the closest player
            if game.show_time.index(stage) == game.last_kicker_tick:
                team = game.last_kicker.side
            else:
                team = stage.closest_player_team()

            # if it is our team, and it is the first time, set it as start ball. else set it as last ball.
            if team == "l":
                last_ball = stage.ball
                if counter == 0:
                    start_ball = last_stage.ball
                    counter += 1

            # if it is opposing team, and there is a last ball, then calculate our possess dist, else 0.
            if team == "r":
                if last_ball is not None:
                    game.possession_length = calculate_possession_length(start_ball, last_ball)
                else:
                    game.possession_length = 0


# Calculates the difference between the length to the goal from first possession to length of goal from last possession
def calculate_possession_length(start_ball: Ball, last_ball: Ball):
    # TODO very hard code of goal coords
    goal_x = 52.5
    goal_y = 0
    goal_coord = Coordinate(goal_x, goal_y)
    start_coord = Coordinate(start_ball.x_coord, start_ball.y_coord)
    last_coord = Coordinate(last_ball.x_coord, last_ball.y_coord)

    start_dist = get_distance_between_coords(start_coord, goal_coord)
    end_dist = get_distance_between_coords(last_coord, goal_coord)

    return start_dist - end_dist


def write_possession_file(game: Game):
    possession_dir = Path(__file__).parent.parent / "possessions"
    if not possession_dir.exists():
        os.makedirs(possession_dir)

    now = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = "possession_" + now
    file_possession = open(possession_dir / file_name, "w")
    file_possession.write(str(game.possession_length))


# Gets the newest server log ".rcg"
def get_newest_server_log():
    server_log_path = os.listdir('.')
    server_log_names = fnmatch.filter(server_log_path, SERVER_LOG_PATTERN)
    server_log_names.sort(reverse=True)
    return server_log_names[0]


# Gets the newest action log ".rcl"
def get_newest_action_log():
    actions_log_path = os.listdir('.')
    action_logs = fnmatch.filter(actions_log_path, ACTION_LOG_PATTERN)
    action_logs.sort(reverse=True)
    return action_logs[0]


def parse_init_action(txt, game: Game):
    init_regex = "{0},{0}\tRecv (.*)_{0}:".format(_SIGNED_INT_REGEX)
    init_re = re.compile(init_regex)
    matched = init_re.match(txt)

    for team in game.teams:
        if team.name == matched.group(1):
            team.number_of_players += 1


def parse_kick_action(txt, game: Game):
    kick_regex = "({0}),{0}\tRecv (.*)_{0}: \\(kick {1} {1}\\)".format(_SIGNED_INT_REGEX, _REAL_NUM_REGEX)
    kick_re = re.compile(kick_regex)
    matched = kick_re.match(txt)

    player = Player()

    for team in game.teams:
        if matched.group(2) == team.name:
            player.side = team.side

    # if ball has moved, then kick was success
    stage = game.show_time[int(matched.group(1))]
    last_stage = game.show_time[game.show_time.index(stage) - 1]
    if abs(stage.ball.x_coord) > abs(last_stage.ball.x_coord) or \
            abs(stage.ball.y_coord) > abs(last_stage.ball.y_coord):
        game.last_kicker = player
        game.last_kicker_tick = int(matched.group(1))


def parse_goal_action(txt, game: Game):
    goal_regex = "({0}),{0}\t\\(referee goal_(r|l)_{0}\\)".format(_SIGNED_INT_REGEX)
    goal_re = re.compile(goal_regex)
    matched = goal_re.match(txt)

    # It may seem like it is not suicide, but last that tried to kick could be opposing team.
    if game.last_kicker.side == matched.group(2):
        game.goals.append("%s goal to %s" % (matched.group(1), matched.group(2)))
    else:
        game.goals.append("%s goal to %s by suicide" % (matched.group(1), matched.group(2)))


# Parses log name (game id, team names and goals)
def parse_log_name(log_name, game: Game):
    id_regex = "({1})\\-({0})\\_({1})\\-.*\\-({0})\\_?({1})?\\.".format(_ROBOCUP_MSG_REGEX, _SIGNED_INT_REGEX)
    regular_expression = re.compile(id_regex)
    matched = regular_expression.match(log_name)

    team2_regex = "({0})\\_({1})".format(_ROBOCUP_MSG_REGEX, _SIGNED_INT_REGEX)
    team2_re = re.compile(team2_regex)
    team2_matched = team2_re.match(matched.group(4))

    team1 = Team()
    team2 = Team()

    team1.side = "l"
    team2.side = "r"

    game.gameID = matched.group(1)
    team1.name = matched.group(2)
    team1.goals = matched.group(3)

    if matched.group(4) == "null":
        team2.name = "null"
    else:
        team2.name = team2_matched.group(1)
        team2.goals = team2_matched.group(2)

    game.teams.append(team1)
    game.teams.append(team2)


# Parses the lines of the server log starting with "((show"
def parse_show_line(txt, game: Game):
    regex_string = "\\(show ({0}) (\\(\\([^\\)]*\\)[^\\)]*\\)) (.*)".format(_SIGNED_INT_REGEX)
    regular_expression = re.compile(regex_string)
    matched = regular_expression.match(txt)

    stage = Stage()
    tick = int(matched.group(1))
    if len(game.show_time) == tick:
        return

    ball_txt = matched.group(2)
    parse_ball(ball_txt, stage)

    # log file always has 22 players, even the ones not initiated
    players = re.findall(r'\(\([^)]*\)[^)]*\)[^)]*\)[^)]*\)', matched.group(3))
    for p in players:
        player = parse_player(p)
        # check if the parsed player is initiated
        for team in game.teams:
            if player.side == team.side and player.no in range(team.number_of_players + 1):
                stage.players.append(player)

    distance_to_ball(stage)
    insert_kicks(stage)

    # Inserts the stage in the correct array slot (tick)
    game.show_time.insert(tick, stage)


# Parses ball from show msg
def parse_ball(txt, stage: Stage):
    regex_string = "\\(\\(b\\) ({0}) ({0}) ({0}) ({0})".format(_REAL_NUM_REGEX)
    regular_expression = re.compile(regex_string)
    matched = regular_expression.match(txt)

    stage.ball.x_coord = float(matched.group(1))
    stage.ball.y_coord = float(matched.group(2))
    stage.ball.delta_x = float(matched.group(3))
    stage.ball.delta_y = float(matched.group(4))


def distance_to_ball(stage: Stage):
    for player in stage.players:
        player.distance_to_ball = math.sqrt(math.pow((player.x_coord - stage.ball.x_coord), 2)
                                            + math.pow((player.y_coord - stage.ball.y_coord), 2))


def insert_kicks(stage: Stage):
    for player in stage.players:
        if player.side == "l" and player.kicks != 0:
            stage.team_l_kicks = stage.team_l_kicks + player.kicks


# Examples:
# ((Side unum) playertype goalkeeper_bool x_coord y_coord delta_x delta_y body_angle neck_angle
# (view high narrow/normal(90)/wide) stamina (etc etc) counts ? dash turn ? move turn_neck ? ? ? ?

# ((l 1) 0 0x9 -50 0 0 0 35.618 -90 (v h 90) (s 8000 1 1 130300) (c 0 5 4 0 1 17 0 0 0 0 0))
# ((r 10) 0 0 30 -37 0 0 0 0 (v h 90) (s 8000 1 1 130600) (c 0 0 0 0 0 0 0 0 0 0 0))

# Parses a player from show msg
def parse_player(txt):
    regex_string = "\\(\\((l|r) ({0})\\) ({0}) ({2}|0) ({1}) ({1}) ({1}) ({1}) ({1}) ({1}) \\(v [h|l] {0}\\) \\(s " \
                   "({1}) {1} {1} {1}\\) \\(c ({0}) ".format(_SIGNED_INT_REGEX, _REAL_NUM_REGEX, __HEX_REGEX)
    regular_expression = re.compile(regex_string)
    matched = regular_expression.match(txt)

    player = Player()
    player.side = matched.group(1)
    player.no = int(matched.group(2))
    player.x_coord = float(matched.group(5))
    player.y_coord = float(matched.group(6))
    player.stamina = float(matched.group(11))
    player.kicks = int(matched.group(12))

    return player