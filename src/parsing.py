import math
import re
import time

from geometry import angle_between, calculate_smallest_origin_angle_between, rotate_coordinate, get_object_position, \
    calculate_full_circle_origin_angle
from player import player, world
from math import sqrt, atan2

from player.player import PlayerState
from player.world import Coordinate
from player.world import Player
from player.world import PrecariousData

__REAL_NUM_REGEX = "[-0-9]*\\.?[0-9]*"
__SIGNED_INT_REGEX = "[-0-9]+"
__ROBOCUP_MSG_REGEX = "[-0-9a-zA-Z ().+*/?<>_]*"
__SEE_MSG_REGEX = "\\(\\([^\\)]*\\)[^\\)]*\\)"
__TEAM_NAME_REGEX = "(−|_|a-z|A−Z|0−9)+"

# Introduced to reduce calculation time
MAX_FLAGS_FOR_POSITION_ESTIMATE = 15

__FLAG_COORDS = {
    # perimiter flags
    "tl50": (-50, 39),
    "tl40": (-40, 39),
    "tl30": (-30, 39),
    "tl20": (-20, 39),
    "tl10": (-10, 39),
    "t0": (0, 40),
    "tr10": (10, 39),
    "tr20": (20, 39),
    "tr30": (30, 39),
    "tr40": (40, 39),
    "tr50": (50, 39),

    "rt30": (57.5, 30),
    "rt20": (57.5, 20),
    "rt10": (57.5, 10),
    "r0": (57.5, 0),
    "rb10": (57.5, -10),
    "rb20": (57.5, -20),
    "rb30": (57.5, -30),

    "bl50": (-50, -39),
    "bl40": (-40, -39),
    "bl30": (-30, -39),
    "bl20": (-20, -39),
    "bl10": (-10, -39),
    "b0": (0, -40),
    "br10": (10, -39),
    "br20": (20, -39),
    "br30": (30, -39),
    "br40": (40, -39),
    "br50": (50, -39),

    "lt30": (-57.5, 30),
    "lt20": (-57.5, 20),
    "lt10": (-57.5, 10),
    "l0": (-57.5, 0),
    "lb10": (-57.5, -10),
    "lb20": (-57.5, -20),
    "lb30": (-57.5, -30),

    # goal flags ('t' and 'b' flags can change based on server parameter
    # 'goal_width', but we leave their coords as the default values.
    "glt": (-52.5, 7.01),
    "gl": (-52.5, 0),
    "glb": (-52.5, -7.01),

    "grt": (52.5, 7.01),
    "gr": (52.5, 0),
    "grb": (52.5, -7.01),

    # penalty flags
    "plt": (-35, 20),
    "plc": (-35, 0),
    "plb": (-32, -20),

    "prt": (35, 20),
    "prc": (35, 0),
    "prb": (32, -20),

    # field boundary flags (on boundary lines)
    "lt": (-52.5, 34),
    "ct": (0, 34),
    "rt": (52.5, 34),

    "lb": (-52.5, -34),
    "cb": (0, -34),
    "rb": (52.5, -34),

    # center flag
    "c": (0, 0)
}


def _update_time(msg, state: PlayerState):
    comp_re = re.compile("\\([^(]* ({0})".format(__SIGNED_INT_REGEX))
    state.world_view.sim_time = int(re.match(comp_re, msg).group(1))


def parse_message_update_state(msg: str, ps: player):
    if msg.startswith("(error"):
        print(msg)
        return

    # The server_param and player_param files do not contain a time stamp
    # Can be used to get the configuration of the server and player
    # server_param: clang_mess_per_cycle, olcoach_port = 6002 etc.
    # player_param: General parameters of players, like max substitutions etc.
    # player_type: The current player type and its stats, like max_speed, kick power etc.
    if not (msg.startswith("(server_param") or msg.startswith("(player_param") or msg.startswith("(player_type")):
        _update_time(msg, ps)

    if msg.startswith("(hear"):
        _parse_hear(msg, ps)
    elif msg.startswith("(sense_body"):
        _parse_body_sense(msg, ps)
    elif msg.startswith("(init"):
        _parse_init(msg, ps)
    elif msg.startswith("(see "):
        _parse_see(msg, ps)


'''
Old protocol 3: 
(see 0 ((flag c) 50.4 -25) ((flag c b) 47 14) ((flag r t) 113.3 -29) ((flag r b) 98.5 7) ((flag g r b) " \
"99.5 -8) ((goal r) 100.5 -12) ((flag g r t) 102.5 -16) ((flag p r b) 81.5 -1) ((flag p r c) 84.8 -15) ((" \
"flag p r t) 91.8 -27) ((flag p l b) 9.7 -10 0 0) ((ball) 49.4 -25) ((player) 44.7 -24) ((player Team1 5) " \
"30 -41 0 0) ((player Team1) 33.1 -5) ((player Team1) 44.7 -28) ((player Team1) 44.7 -24) ((player Team1) " \
"40.4 -2) ((player) 60.3 7) ((player) 60.3 -16) ((player) 66.7 -20) ((player) 60.3 -31) ((player) 90 -39) (" \
"(player) 99.5 -9) ((player) 66.7 -10) ((player) 66.7 -21) ((player) 99.5 -19) ((player) 90 6) ((player) " \
"60.3 -27) ((line r) 98.5 90))

New protocol 7-16:
"(see 0 ((f r t) 55.7 3) ((f g r b) 70.8 38) ((g r) 66.7 34) ((f g r t) 62.8 28) ((f p r c) 53.5 43) ((f p " \
"r t) 42.5 23) ((f t 0) 3.6 -34 0 0) ((f t r 10) 13.2 -9 0 0) ((f t r 20) 23.1 -5 0 0) ((f t r 30) 33.1 -3 " \
"0 0) ((f t r 40) 42.9 -3) ((f t r 50) 53 -2) ((f r 0) 70.8 31) ((f r t 10) 66 24) ((f r t 20) 62.8 16) ((f " \
"r t 30) 60.9 7) ((f r b 10) 76.7 38) ((f r b 20) 83.1 43) ((p) 66.7 35) ((p \"Team2\" 2) 9 0 0 0 0 0) ((p " \
"\"Team2\" 3) 12.2 0 0 0 0 0) ((p \"Team2\" 4) 14.9 0 0 0 0 0) ((p \"Team2\" 5) 18.2 0 0 0 0 0) ((p " \
"\"Team2\" 6) 20.1 0 0 0 0 0) ((p \"Team2\" 7) 24.5 0 0 0 0 0) ((p \"Team2\") 27.1 0) ((p \"Team2\" 9) 30 0 " \
"0 0 0 0) ((p \"Team2\") 33.1 0) ((p \"Team2\") 36.6 0)) "
'''


def _parse_see(msg, ps: player.PlayerState):
    regex2 = re.compile(__SEE_MSG_REGEX)
    matches = regex2.findall(msg)

    flag_strings = []
    players = []
    goals = []
    lines = []
    ball = None
    for element in matches:
        if str(element).startswith("((f") or str(element).startswith("((F"):
            flag_strings.append(element)
        elif str(element).startswith("((g") or str(element).startswith("((G"):
            goals.append(element)
        elif str(element).startswith("((p") or str(element).startswith("((P"):
            players.append(element)
        elif str(element).startswith("((l") or str(element).startswith("((L"):
            lines.append(element)
        elif str(element).startswith("((b") or str(element).startswith("((B"):
            ball = element
        else:
            raise Exception("Unknown see element: " + str(element))

    flags = create_flags(flag_strings)

    _approx_position(flags, ps)
    _approx_glob_angle(flags, ps)
    _parse_players(players, ps)
    _parse_goals(goals, ps)
    _parse_ball(ball, ps)
    _parse_lines(lines, ps)

    '''
    if ps.team_name == "Team1" and ps.player_num == 1:
        if ps.position.is_value_known():
            print(ps.position.get_value())
        if ps.player_angle.is_value_known():
            print(ps.player_angle.get_value())
    '''


def _parse_lines(lines, ps):
    for line in lines:
        if str(line).startswith("((L"):
            continue
        else:
            _parse_line(line, ps)


def _parse_line(text: str, ps: PlayerState):
    line_regex = "\\(\\(l (r|l|b|t)\\)\\s({0}) ({1})".format(__REAL_NUM_REGEX, __SIGNED_INT_REGEX)
    regular_expression = re.compile(line_regex)
    matched = regular_expression.match(text)

    line_side = matched.group(1)
    line_distance = matched.group(2)
    line_relative_angle = matched.group(3)

    # Add information to WorldView
    new_line = world.Line(line_side=line_side, distance=line_distance, relative_angle=line_relative_angle)
    ps.world_view.lines.append(new_line)
    return matched


def _parse_goals(goals, ps):
    for goal in goals:
        _parse_goal(goal, ps)


def _parse_goal(text: str, ps: PlayerState):
    # Unknown see object (out of field of view)
    if text.startswith("((G"):
        return world.Goal(None, None, None)

    goal_regex = "\\(\\(g (r|l)\\)\\s({0}) ({1})".format(__REAL_NUM_REGEX, __SIGNED_INT_REGEX)
    regular_expression = re.compile(goal_regex)
    matched = regular_expression.match(text)

    goal_side = matched.group(1)
    goal_distance = matched.group(2)
    goal_relative_angle = matched.group(3)

    # Add information to WorldView
    new_goal = world.Goal(goal_side=goal_side, distance=goal_distance, relative_angle=goal_relative_angle)
    ps.world_view.goals.append(new_goal)
    return matched


class Flag:

    def __init__(self, identifier, coordinate, distance, direction) -> None:
        self.identifier = identifier
        self.coordinate = coordinate
        self.relative_distance = distance
        self.relative_direction = direction

    def __repr__(self) -> str:
        return "Flag " + self.identifier + " : " + str(self.coordinate) + ", dist: " + str(self.relative_distance) + \
               ", direction: " + str(self.relative_direction)


def create_flags(flag_strings):
    known_flags_strings = []

    # Remove flags out of field of view
    for flag in flag_strings:
        if not str(flag).startswith("((F)"):
            known_flags_strings.append(flag)

    ids = _extract_flag_identifiers(known_flags_strings)
    coords = _extract_flag_coordinates(ids)
    distances = _extract_flag_distances(known_flags_strings)
    directions = _extract_flag_directions(known_flags_strings)

    flags = []
    for i in range(0, len(known_flags_strings)):
        flags.append(Flag(ids[i], coords[i], float(distances[i]), float(directions[i])))

    return flags


# Note that the mean value of angles is not well defined (fx. what is the mean angle of (0, 90, 180, 270)?)
# This function averages angles that are close together.
def average(numbers):
    return sum(numbers) / len(numbers)


def find_mean_angle(angles):
    if len(angles) == 0:
        return None

    if len(angles) == 1:
        return angles[0]

    # We expect more than half of the angles to be close together (eliminate outliers)
    expected_close_angles = int(len(angles) / 2 + 1)
    acceptable_variance = 3.0
    cluster_size_best_solution = 0
    best_cluster = []

    for i in range(0, len(angles) - 1):
        first_angle = angles[i]
        cluster = [angles[i]]
        for j in range(i + 1, len(angles)):
            other_angle = angles[j]
            # Handle wrap-around 360 degrees
            if first_angle < 0 + acceptable_variance:
                if other_angle > 360 - acceptable_variance:
                    other_angle = -(360 - other_angle)
            # Handle other case of wrap-around 360 degrees
            elif first_angle > 360 - acceptable_variance:
                if other_angle < acceptable_variance:
                    other_angle = 360 + other_angle

            if abs(first_angle - other_angle) <= acceptable_variance:
                cluster.append(other_angle)

        if len(cluster) >= expected_close_angles:
            return average(cluster)

        if len(cluster) > cluster_size_best_solution:
            cluster_size_best_solution = len(cluster)
            best_cluster = cluster

    # No angles were close enough to provide a non-ambiguous solution
    if len(best_cluster) <= 1:
        return None
    return average(best_cluster) % 360


def _approx_glob_angle(flags: [Flag], ps):
    if not ps.position.is_value_known():  # todo Make time dependent? (Magnus)
        return

    estimated_angles = []
    # angle between c1 and c2, with c3 offsetting to make 0 degrees in some direction
    # For this purpose x+ = east, -x = west etc.
    player_coord = ps.position.get_value()
    for flag in flags:
        radians_between_flag_player = calculate_full_circle_origin_angle(flag.coordinate, player_coord)
        player_angle = float(radians_between_flag_player) - math.radians(float(flag.relative_direction))
        estimated_player_angle = math.degrees(player_angle) % 360

        estimated_angles.append(estimated_player_angle)

    mean_angle = find_mean_angle(estimated_angles)
    if mean_angle is not None:
        ps.player_angle.set_value(mean_angle, ps.now())


# ((flag g r b) 99.5 -5)
# ((flag p l c) 27.1 10 -0 0)
# distance, direction, dist_change, dir_change
def _extract_flag_directions(flag_strings):
    flag_directions = []
    for flag_string in flag_strings:
        # Remove the first part of the string *((flag p l c)*
        removed_flag_name = flag_string.split(') ', 1)[1]
        # Remove ) from the items
        cur_flag = str(removed_flag_name).replace(")", "")
        cur_flag = str(cur_flag).replace("(", "")

        split_by_whitespaces = []
        split_by_whitespaces = re.split('\\s+', cur_flag)

        # We now have a list of elements like this:
        # ['13.5', '-31', '2', '-5']

        direction = split_by_whitespaces[1]
        flag_directions.append(direction)

    return flag_directions


# Input ((b) 13.5 -31 0 0)
# or ((b) 44.7 -20)
# Or B
# distance, direction, dist_change, dir_change
def _parse_ball(ball: str, ps: player.PlayerState):
    # If ball is not present at all
    if ball is None:
        return
    # Unknown see object (out of field of view)
    if ball.startswith("((B"):
        return world.Ball(None, None, None, None, None)

    # Remove ) from the items
    ball = str(ball).replace(")", "")
    ball = str(ball).replace("(", "")

    split_by_whitespaces = []
    split_by_whitespaces = re.split('\\s+', ball)

    # We now have a list of elements like this:
    # ['b', '13.5', '-31', '2', '-5']

    # These are always included
    distance = split_by_whitespaces[1]
    direction = split_by_whitespaces[2]
    # These might be included depending on the distance and view of the player
    distance_chng = None
    dir_chng = None

    # If we also know dist_change and dir_change
    if len(split_by_whitespaces) > 3:
        distance_chng = split_by_whitespaces[3]
        dir_chng = split_by_whitespaces[4]

    # print("Pretty: Distance ({0}), Direction ({1}), distance_chng ({2}), dir_chng ({3})".format(distance, direction,
    #                                                                                            distance_chng,
    #                                                                                            dir_chng))
    ball_coord = None
    # The position of the ball can only be calculated, if the position of the player is known
    if ps.position.is_value_known():
        pos: Coordinate = ps.position.get_value()
        ball_coord: Coordinate = get_object_position(object_rel_angle=int(direction), dist_to_obj=float(distance),
                                                     my_x=pos.pos_x,
                                                     my_y=pos.pos_y,
                                                     my_global_angle=ps.player_angle.get_value())

    new_ball = world.Ball(distance=distance, direction=direction, dist_chng=distance_chng, dir_chng=dir_chng,
                          coord=ball_coord)

    ps.world_view.ball.set_value(new_ball, ps.world_view.sim_time)


# Parse this: (p "team"? num? goalie?)
# Returns arguments in this order: team, num, is_goalie
def _parse_player_obj_name(obj_name, ps: player.PlayerState):
    # Remove "noise" in form of " and ( from the object name
    obj_name = str(obj_name).replace("(", "")
    obj_name = str(obj_name).replace("\"", "")

    # Split by whitespaces to get a divided list like so:
    # ['p', '"Team2"', '7']
    split_by_whitespaces = re.split('\\s+', obj_name)

    # If we have no info on who the player is
    if len(split_by_whitespaces) == 1:
        return None, None, None

    # If we know the team of the player
    if len(split_by_whitespaces) == 2:
        return split_by_whitespaces[1], None, None

    # If we know both team and player_num
    if len(split_by_whitespaces) == 3:
        return split_by_whitespaces[1], split_by_whitespaces[2], None

    # If we know both the team, player_num and that the player is the goalie
    if len(split_by_whitespaces) == 4:
        return split_by_whitespaces[1], split_by_whitespaces[2], True


# ((p "team"? num?) Distance Direction DistChng? DirChng? BodyFacingDir? HeadFacingDir? [PointDir]?)
# ((p "Team1" 5) 30 -41 0 0)
def _parse_players(players: [], ps: player.PlayerState):
    for cur_player in players:
        # Unknown see object (out of field of view)
        if cur_player.startswith("((P"):
            continue
        # Default values
        team = None
        num = None
        is_goalie = None
        distance = None
        direction = None
        dist_chng = None
        dir_chng = None
        body_dir = None
        head_dir = None

        # Get object name like (player Team1 5) or (player Team1 5 goalie)
        obj_name = re.split('\\)+', cur_player)[0]
        team, num, is_goalie = _parse_player_obj_name(obj_name, ps)

        # The rest of the player like 9 0 0 0 0 0
        # Start from index 1 to remove a white space
        cur_player = re.split('\\)+', cur_player)[1][1:]

        # Remove ),( and " from the items
        cur_player = str(cur_player).replace(")", "")
        cur_player = str(cur_player).replace("(", "")
        cur_player = str(cur_player).replace("\"", "")

        split_by_whitespaces = re.split('\\s+', cur_player)

        # We now have a list of elements like this:
        # Diretion DistChange DirChange BodyFacingDir HeadFacingDir [PointDir]
        # ['30', '-41', '0', '0' ]

        # If only direction
        if len(split_by_whitespaces) == 1:
            direction = split_by_whitespaces[0]
        # If only distance and direction
        elif len(split_by_whitespaces) == 2:
            distance = split_by_whitespaces[0]
            direction = split_by_whitespaces[1]
        # If Distance Direction DistChange DirChange
        elif len(split_by_whitespaces) == 4:
            distance = split_by_whitespaces[0]
            direction = split_by_whitespaces[1]
            dist_chng = split_by_whitespaces[2]
            dir_chng = split_by_whitespaces[3]
        # If Distance Direction DistChange DirChange BodyFacingDir HeadFacingDir [PointDir]
        # Todo should we include pointdir? - Philip
        elif len(split_by_whitespaces) >= 6:
            distance = split_by_whitespaces[0]
            direction = split_by_whitespaces[1]
            dist_chng = split_by_whitespaces[2]
            dir_chng = split_by_whitespaces[3]
            body_dir = split_by_whitespaces[4]
            head_dir = split_by_whitespaces[5]

        my_pos: Coordinate = ps.position.get_value()
        other_player_coord = PrecariousData.unknown()
        if ps.position.is_value_known():
            other_player_coord = get_object_position(object_rel_angle=float(direction), dist_to_obj=float(distance),
                                                     my_x=my_pos.pos_x, my_y=my_pos.pos_y,
                                                     my_global_angle=float(ps.player_angle.get_value()))

        new_player = Player(team=team, num=num, distance=distance, direction=direction, dist_chng=dist_chng
                            , dir_chng=dir_chng, body_dir=body_dir, head_dir=head_dir, is_goalie=is_goalie
                            , coord=other_player_coord)

        ps.world_view.other_players.append(new_player)


def _parse_init(msg, ps: player.PlayerState):
    regex = re.compile("\\(init ([lr]) ([0-9]*)")
    matched = regex.match(msg)
    ps.side = matched.group(1)
    ps.player_num = int(matched.group(2))


# Three different modes
# example: (hear 0 referee kick_off_l)
# example: (hear 0 self *msg*)
# Pattern: (hear *time* *degrees* *msg*)
def _parse_hear(text: str, ps: player):
    split_by_whitespaces = re.split('\\s+', text)
    time = split_by_whitespaces[1]
    ps.sim_time = time  # Update players understanding of time

    sender = split_by_whitespaces[2]
    if sender == "referee":
        regex_string = "\\(hear ({0}) referee ({1})\\)".format(__SIGNED_INT_REGEX, __ROBOCUP_MSG_REGEX)

        regular_expression = re.compile(regex_string)
        matched = regular_expression.match(text)

        ps.game_state = matched.group(2)

        return
    elif sender == "self":
        return
    elif sender == "online_coach_left":
        return  # todo Handle incoming messages from online coach
    elif sender == "online_coach_right":
        return  # todo handle incoming messages from online coach
    elif sender == "coach":
        return  # todo handle trainer input
    else:
        regex_string = "\\(hear ({0}) ({0}) ({1})\\)".format(__SIGNED_INT_REGEX, __ROBOCUP_MSG_REGEX)

        regular_expression = re.compile(regex_string)
        matched = regular_expression.match(text)

        return


# example : (sense_body 0 (view_mode high normal) (stamina 8000 1 130600) (speed 0 0) (head_angle 0) (kick 0)
# (dash 0) (turn 0) (say 0) (turn_neck 0) (catch 0) (move 0) (change_view 0) (arm (movable 0) (expires 0) (target 0 0)
# (count 0)) (focus (target none) (count 0)) (tackle (expires 0) (count 0)) (collision none) (foul  (charged 0)
# (card none)))

# ALL COUNT COMMANDS MEAN: HOW MANY TIMES THE COMMAND HAS BEEN EXECUTED BY THE PLAYER SO FAR
# Group [1] = time,
# [2] = view mode,
# [3] = stamina, [4] = effort, [5] = capacity,
# [6] = speed, [7] = direction of speed,
# [8] = kick count,
# [9] = dash count,
# [10] = turn count,
# [11] = say count,
# [12] = turn neck count,
# [13] = catch count,
# [14] = move count,
# [15] = change view count,
# [16] = movable cycles, [17] = expire cycles, [18] = point to count,
# [19] = target, [20] = Unum, [21] = count,
# [22] = expire cycles, [23] count, [24] = collision,
# [25] = charged, [26] = card

def _parse_body_sense(text: str, ps: player):
    regex_string = ".*sense_body ({1}).*view_mode ({2})\\).*stamina ({0}) ({0}) ({1})\\).*speed ({0}) ({1})\\)"
    regex_string += ".*head_angle ({1})\\).*kick ({1})\\).*dash ({1})\\).*turn ({1})\\)"
    regex_string += ".*say ({1})\\).*turn_neck ({1})\\).*catch ({1})\\).*move ({1})\\).*change_view ({1})\\)"
    regex_string += ".*movable ({1})\\).*expires ({1})\\).*target ({1}) ({1})\\).*count ({1})\\)\\)"
    regex_string += ".*target (none|l|r)( {1})?\\).*count ({1})\\)\\)"
    regex_string += ".*expires ({1})\\).*count ({1})\\)"
    regex_string += ".*collision (none|{2})\\).*charged ({1})\\).*card (red|yellow|none)\\)\\)\\)"
    regex_string = regex_string.format(__REAL_NUM_REGEX, __SIGNED_INT_REGEX, __ROBOCUP_MSG_REGEX)

    regular_expression = re.compile(regex_string)
    matched = regular_expression.match(text)

    return matched


# Example : (see 0 ((f r b) 48.9 29) ((f g r b) 42.5 -4) ((g r) 43.8 -13) ((f g r t) 45.6 -21)
#           ((f p r b) 27.9 21) ((f p r c) 27.9 -21 0 0) ((P) 1 -179) ((p Team2 2) 1 0 0 0)
#           ((P) 0.5 151) ((p Team2 4) 0.5 -28 0 0) ((l r) 42.5 90))
def _parse_flags(text):
    flag_regex = "\\(f [^)]*\\) {0} {0}".format(__REAL_NUM_REGEX)
    return re.findall(flag_regex, text)


def _match(regex_string, text):
    regular_expression = re.compile(regex_string)
    regex_match = regular_expression.match(text)
    return regex_match


def _flag_position(pos_x, pos_y):
    return None


def _extract_flag_identifiers(flags):
    flag_identifiers_regex = ".*\\(f ([^\\)]*)\\)"
    flag_identifiers = []
    for flag in flags:
        m = _match(flag_identifiers_regex, flag)
        flag_identifiers.append(m.group(1).replace(" ", ""))
    return flag_identifiers


def _extract_flag_distances(flags):
    flag_distance_regex = ".*\\(f [^\\)]*\\) ({0}) ".format(__REAL_NUM_REGEX)
    flag_distances = []
    for flag in flags:
        m = _match(flag_distance_regex, flag)
        flag_distances.append(m.group(1).replace(" ", ""))
    return flag_distances


def _extract_flag_coordinates(flag_ids):
    coords = []
    for flag_id in flag_ids:
        coord_pair = __FLAG_COORDS.get(flag_id)
        coords.append(Coordinate(coord_pair[0], coord_pair[1]))
    return coords


def _zip_flag_coords_distance(flags):
    coords_zipped_distance = []
    flag_ids = _extract_flag_identifiers(flags)
    flag_coords = _extract_flag_coordinates(flag_ids)
    flag_distances = _extract_flag_distances(flags)

    for i in range(0, len(flag_ids)):
        coords_zipped_distance.append((flag_coords[i], flag_distances[i]))

    return coords_zipped_distance


def _calculate_distance(coord1, coord2):
    x_dist = abs(coord1.pos_x - coord2.pos_x)
    y_dist = abs(coord1.pos_y - coord2.pos_y)
    return sqrt(pow(float(x_dist), 2) + pow(float(y_dist), 2))


# Calculates position as two possible offsets from flag_one
def _trilaterate_offset(flag_one, flag_two):
    distance_between_flags = _calculate_distance(flag_one.coordinate, flag_two.coordinate)

    x = (((flag_one.relative_distance ** 2) - (flag_two.relative_distance ** 2)) + (distance_between_flags ** 2)) \
        / (2.0 * distance_between_flags)

    # Not sure if this is a correct solution
    if abs(flag_one.relative_distance) > abs(x):
        y = sqrt((flag_one.relative_distance ** 2) - (x ** 2))
    else:
        y = sqrt(pow(x, 2.0) - pow(flag_one.relative_distance, 2.0))

    # This calculation provides two possible offset solutions (x, y) and (x, -y)
    return Coordinate(x, y), Coordinate(x, -y)


def _solve_trilateration(flag_1, flag_2):
    (possible_offset_1, possible_offset_2) = _trilaterate_offset(flag_1, flag_2)
    # The trilateration algorithm assumes horizontally aligned flags
    # To resolve this, the solution is calculated as if the flags were horizontally aligned
    # and is then rotated to match the actual angle
    radians_to_rotate = calculate_smallest_origin_angle_between(flag_1.coordinate, flag_2.coordinate)
    corrected_offset_from_flag_one_1 = rotate_coordinate(possible_offset_1, radians_to_rotate)
    corrected_offset_from_flag_one_2 = rotate_coordinate(possible_offset_2, radians_to_rotate)

    return flag_1.coordinate - corrected_offset_from_flag_one_1, flag_1.coordinate - corrected_offset_from_flag_one_2


def _get_all_combinations(original_list):
    combinations = []

    for i in range(0, len(original_list) - 1):
        for j in range(i + 1, len(original_list)):
            combinations.append((original_list[i], original_list[j]))

    return combinations


def _find_all_solutions(flags: [Flag]):
    solutions = []
    flag_combinations = _get_all_combinations(flags)
    for combination in flag_combinations:
        possible_solutions = _solve_trilateration(combination[0], combination[1])
        solutions.append(possible_solutions[0])
        solutions.append(possible_solutions[1])
    return solutions


def _average_point(cluster):
    amount_of_clusters = len(cluster)
    total_x = 0
    total_y = 0

    for point in cluster:
        total_x += point.pos_x
        total_y += point.pos_y

    return Coordinate(total_x / amount_of_clusters, total_y / amount_of_clusters)


def _find_mean_solution(all_solutions, state):
    amount_of_correct_solutions = (len(all_solutions) * (len(all_solutions) - 1)) / 2
    acceptable_distance = 3.0
    cluster_size_best_solution = 0
    best_cluster = []

    for solution1 in all_solutions:
        if not is_possible_position(solution1, state):
            continue
        cluster = [solution1]

        for solution2 in all_solutions:
            if solution1 == solution2:
                continue

            if solution1.euclidean_distance_from(solution2) < acceptable_distance:
                cluster.append(solution2)

            if len(cluster) >= amount_of_correct_solutions:
                return _average_point(cluster)

        if len(cluster) > cluster_size_best_solution:
            cluster_size_best_solution = len(cluster)
            best_cluster = cluster

    if len(best_cluster) == 0:
        return None
    return _average_point(best_cluster)


def is_possible_position(new_position: Coordinate, state: PlayerState):
    if not world.is_inside_field_bounds(new_position):
        return False

    # If no information on previous state exists, then all positions inside the field are possible positions
    if not state.position.is_value_known(state.world_view.sim_time - 5):
        return True

    ticks_since_update = state.world_view.sim_time - state.position.last_updated_time
    possible_travel_distance = player.MAX_MOVE_DISTANCE_PER_TICK * ticks_since_update
    return possible_travel_distance >= new_position.euclidean_distance_from(state.position.get_value())


def furthest_flag_distance_and_index(flags: [Flag]):
    furthest_flag = flags[0]
    furthest_dist = furthest_flag.relative_distance
    furthest_index = 0

    for index in range(1, len(flags)):
        flag = flags[index]
        dist = flag.relative_distance
        if dist > furthest_dist:
            furthest_index = index
            furthest_dist = dist
    return furthest_dist, furthest_index


def find_closest_flags(flags, amount):
    closest_flags = flags[0:amount]
    furthest_dist_closest_flags, furthest_index = furthest_flag_distance_and_index(closest_flags)

    i = amount
    while i < len(flags):
        f = flags[i]
        f_dist = f.relative_distance
        if f_dist < furthest_dist_closest_flags:
            closest_flags[furthest_index] = f
            # Find new furthest flag in closest_flags list
            furthest_dist_closest_flags, furthest_index = furthest_flag_distance_and_index(closest_flags)
        i += 1

    return closest_flags


def _approx_position(flags: [Flag], state):
    if len(flags) < 2:
        # print("No flag can be seen - Position unknown")
        return

    if len(flags) > MAX_FLAGS_FOR_POSITION_ESTIMATE:
        flags = find_closest_flags(flags, MAX_FLAGS_FOR_POSITION_ESTIMATE)

    all_solutions = _find_all_solutions(flags)

    if len(all_solutions) == 2:
        # print("only two flags visible")
        solution_1_plausible = is_possible_position(all_solutions[0], state)
        solution_2_plausible = is_possible_position(all_solutions[1], state)

        if solution_1_plausible and solution_2_plausible:
            # print("both solutions match")
            return

        if solution_1_plausible:
            state.position.set_value(all_solutions[0], state.world_view.sim_time)
            # print(all_solutions[0])
            return
        if solution_2_plausible:
            state.position.set_value(all_solutions[1], state.world_view.sim_time)
            # print(all_solutions[1])
            return

        # print("no position trilaterations match previous positions")
    else:
        # handle case where this return an uncertain result
        solution = _find_mean_solution(all_solutions, state)
        if solution is not None and is_possible_position(solution, state):
            state.position.set_value(solution, state.world_view.sim_time)


# PHILIPS - DO NOT REMOVE
my_str4 = "(see 0 ((f r t) 55.7 3) ((f g r b) 70.8 38) ((g r) 66.7 34) ((f g r t) 62.8 28) ((f p r c) 53.5 43) ((f p " \
          "r t) 42.5 23) ((f t 0) 3.6 -34 0 0) ((f t r 10) 13.2 -9 0 0) ((f t r 20) 23.1 -5 0 0) ((f t r 30) 33.1 -3 " \
          "0 0) ((f t r 40) 42.9 -3) ((f t r 50) 53 -2) ((f r 0) 70.8 31) ((f r t 10) 66 24) ((f r t 20) 62.8 16) ((f " \
          "r t 30) 60.9 7) ((f r b 10) 76.7 38) ((f r b 20) 83.1 43) ((p) 66.7 35) ((p \"Team2\" 2) 9 0 0 0 0 0) ((p " \
          "\"Team2\" 3) 12.2 0 0 0 0 0) ((p \"Team2\" 4) 14.9 0 0 0 0 0) ((p \"Team2\" 5) 18.2 0 0 0 0 0) ((p " \
          "\"Team2\" 6) 20.1 0 0 0 0 0) ((p \"Team2\" 7) 24.5 0 0 0 0 0) ((p \"Team2\") 27.1 0) ((p \"Team2\" 9) 30 0 " \
          "0 0 0 0) ((p \"Team2\") 33.1 0) ((p \"Team2\") 36.6 0)) "
# parse_message_update_state(my_str4, player.PlayerState())
