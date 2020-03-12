import math
import re
from player import player_state
from math import sqrt, atan2

from world import Coordinate

REAL_NUM_REGEX = "[0-9]*\\.?[0-9]*"
SIGNED_INT_REGEX = "[-0-9]*"
ROBOCUP_MSG_REGEX = "[-0-9a-zA-Z ().+*/?<>_]*"


def parse_message_update_state(msg: str, ps: player_state):
    if msg.startswith("(hear"):
        __parse_hear(msg, ps)
    elif msg.startswith("(sense_body"):
        __parse_body_sense(msg, ps)
    elif msg.startswith("(init"):
        __parse_init(msg, ps)


def __parse_init(msg, ps: player_state.PlayerState):
    regex = re.compile("\\(init ([lr]) ([0-9]*)")
    matched = regex.match(msg.__str__())
    ps.side = matched.group(1)
    ps.player_num = matched.group(2)


# Three different modes
# example: (hear 0 referee kick_off_l)
# example: (hear 0 self *msg*)
# Pattern: (hear *time* *degrees* *msg*)
def __parse_hear(text: str, ps: player_state):
    split_by_whitespaces = re.split('\\s+', text)
    time = split_by_whitespaces[1]
    ps.sim_time = time  # Update players understanding of time

    sender = split_by_whitespaces[2]
    if sender == "referee":
        regex_string = "\\(hear ({0}) referee ({1})\\)".format(SIGNED_INT_REGEX, ROBOCUP_MSG_REGEX)

        regular_expression = re.compile(regex_string)
        matched = regular_expression.match(text)

        ps.game_state = matched.group(2)

        return
    elif sender == "self":
        return
    else:
        regex_string = "\\(hear ({0}) ({0}) ({1})\\)".format(SIGNED_INT_REGEX, ROBOCUP_MSG_REGEX)

        regular_expression = re.compile(regex_string)
        matched = regular_expression.match(text)

        return


# example : (sense_body 0 (view_mode high normal) (stamina 8000 1) (speed 0) (kick 0) (dash 0) (turn 0) (say 0))
# Group [1] = time, [2] = stamina, [3] = effort, [4] = speed, [5] = kick count, [6] = dash, [7] = turn
def __parse_body_sense(text: str, ps: player_state):
    # Will view_mode ever change from "high normal"?
    regex_string = ".*sense_body ({1}).*stamina ({0}) ({0})\\).*speed ({0})\\).*kick ({0})\\)"
    regex_string += ".*dash ({0})\\).*turn ({1})\\)"
    regex_string = regex_string.format(REAL_NUM_REGEX, SIGNED_INT_REGEX)

    regular_expression = re.compile(regex_string)
    matched = regular_expression.match(text)

    return matched


# Example : (see 0 ((flag r b) 48.9 29) ((flag g r b) 42.5 -4) ((goal r) 43.8 -13) ((flag g r t) 45.6 -21)
#           ((flag p r b) 27.9 21) ((flag p r c) 27.9 -21 0 0) ((Player) 1 -179) ((player Team2 2) 1 0 0 0)
#           ((Player) 0.5 151) ((player Team2 4) 0.5 -28 0 0) ((line r) 42.5 90))
def __parse_flags(text):
    flag_regex = "\\(flag [^)]*\\) {0} {0}".format(REAL_NUM_REGEX)
    return re.findall(flag_regex, text)


def __parse_players(text):
    flag_regex = " [^)]*".format(REAL_NUM_REGEX, SIGNED_INT_REGEX)
    return re.findall(flag_regex, text)


def __match(regex_string, text):
    regular_expression = re.compile(regex_string)
    regex_match = regular_expression.match(text)
    return regex_match


def __flag_position(pos_x, pos_y):
    return None


# for m in reg_str.groups():
#    print(m)


FLAG_COORDS = {
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


# example : (sense_body 0 (view_mode high normal) (stamina 8000 1) (speed 0) (kick 0) (dash 0) (turn 0) (say 0))
# Group [1] = time, [2] = stamina, [3] = effort, [4] = speed, [5] = kick count, [6] = dash, [7] = turn
def parse_body_sense(text):
    # Will view_mode ever change from "high normal"?
    regex_string = ".*sense_body ({1}).*stamina ({0}) ({0})\\).*speed ({0})\\).*kick ({0})\\)"
    regex_string += ".*dash ({0})\\).*turn ({1})\\)".format(REAL_NUM_REGEX, SIGNED_INT_REGEX)
    regex_string = regex_string.format(REAL_NUM_REGEX, SIGNED_INT_REGEX)

    regular_expression = re.compile(regex_string)
    matched = regular_expression.match(text)

    return matched


# Example : (see 0 ((flag r b) 48.9 29) ((flag g r b) 42.5 -4) ((goal r) 43.8 -13) ((flag g r t) 45.6 -21)
#           ((flag p r b) 27.9 21) ((flag p r c) 27.9 -21 0 0) ((Player) 1 -179) ((player Team2 2) 1 0 0 0)
#           ((Player) 0.5 151) ((player Team2 4) 0.5 -28 0 0) ((line r) 42.5 90))
def parse_flags(text):
    flag_regex = "\\(flag [^\\)]*\\) {0} {0}".format(REAL_NUM_REGEX)
    return re.findall(flag_regex, text)


def parse_goal(text):
    # todo
    flag_regex = "\\(flag [^\\)]*\\) {0} {0}".format(REAL_NUM_REGEX)
    return re.findall(flag_regex, text)


def parse_players(text):
    flag_regex = "\\(\\(".format(REAL_NUM_REGEX, SIGNED_INT_REGEX)
    return re.findall(flag_regex, text)


def match(regex_string, text):
    regular_expression = re.compile(regex_string)
    regex_match = regular_expression.match(text)
    return regex_match


def extract_flag_identifiers(flags):
    flag_identifiers_regex = ".*\\(flag ([^\\)]*)\\)"
    flag_identifiers = []
    for flag in flags:
        m = match(flag_identifiers_regex, flag)
        flag_identifiers.append(m.group(1).replace(" ", ""))
    return flag_identifiers


def extract_flag_distances(flags):
    flag_distance_regex = ".*\\(flag [^\\)]*\\) ({0}) ".format(REAL_NUM_REGEX)
    flag_distances = []
    for flag in flags:
        m = match(flag_distance_regex, flag)
        flag_distances.append(m.group(1).replace(" ", ""))
    return flag_distances


def extract_flag_coordinates(flag_ids):
    coords = []
    for flag_id in flag_ids:
        coordpair = FLAG_COORDS.get(flag_id)
        coords.append(Coordinate(coordpair[0], coordpair[1]))
    return coords


def zip_flag_coords_distance(flags):
    coords_zipped_distance = []
    flag_ids = extract_flag_identifiers(flags)
    flag_coords = extract_flag_coordinates(flag_ids)
    flag_distances = extract_flag_distances(flags)

    for i in range(0, len(flag_ids)):
        coords_zipped_distance.append((flag_coords[i], flag_distances[i]))

    return coords_zipped_distance


def calculate_distance(coord1, coord2):
    x_dist = abs(coord1.pos_x - coord2.pos_x)
    y_dist = abs(coord1.pos_y - coord2.pos_y)
    return sqrt(pow(float(x_dist), 2) + pow(float(y_dist), 2))


# Calculates position as two possible offsets from flag_one
def trilaterate_offset(flag_one, flag_two):
    coord1 = flag_one[0]
    coord2 = flag_two[0]
    distance_between_flags = calculate_distance(coord1, coord2)
    distance_to_flag1 = float(flag_one[1])
    distance_to_flag2 = float(flag_two[1])

    x = (((distance_to_flag1 ** 2) - (distance_to_flag2 ** 2)) + (distance_between_flags ** 2)) \
        / (2.0 * distance_between_flags)

    # Not sure if this is a correct solution
    if abs(distance_to_flag1) > abs(x):
        y = sqrt((distance_to_flag1 ** 2) - (x ** 2))
    else:
        y = sqrt(pow(x, 2.0) - pow(distance_to_flag1, 2.0))

    # This calculation provides two possible offset solutions (x, y) and (x, -y)
    return Coordinate(x, y), Coordinate(x, -y)


# Calculates angle between two points (relative to the origin (0, 0))
def calculate_angle_between(coordinate1, coordinate2):
    return atan2(coordinate1.pos_y - coordinate2.pos_y, coordinate1.pos_x - coordinate2.pos_x)


def rotate_coordinate(coord, radians_to_rotate):
    new_x = math.cos(radians_to_rotate) * coord.pos_x - math.sin(radians_to_rotate) * coord.pos_y
    new_y = math.sin(radians_to_rotate) * coord.pos_x + math.cos(radians_to_rotate) * coord.pos_y
    return Coordinate(new_x, new_y)


def solve_trilateration(flag_1, flag_2):
    (possible_offset_1, possible_offset_2) = trilaterate_offset(flag_1, flag_2)
    # The trilateration algorithm assumes horizontally aligned flags
    # To resolve this, the solution is calculated as if the flags were horizontally aligned
    # and is then rotated to match the actual angle
    radians_to_rotate = calculate_angle_between(flag_1[0], flag_2[0])
    corrected_offset_from_flag_one_1 = rotate_coordinate(possible_offset_1, radians_to_rotate)
    corrected_offset_from_flag_one_2 = rotate_coordinate(possible_offset_2, radians_to_rotate)

    return flag_1[0] - corrected_offset_from_flag_one_1, flag_1[0] - corrected_offset_from_flag_one_2


# Trilateration function from 101computing.net (DOES NOT WORK WHEN FLAGS ARE PERFECTLY ALIGNED!)
'''def solve_trilateration(flag_1, flag_2, flag_3):
    r1 = float(flag_1[1])
    r2 = float(flag_2[1])
    r3 = float(flag_3[1])
    c1 = flag_1[0]
    c2 = flag_2[0]
    c3 = flag_3[0]

    print(str(c1) + str(r1) + " - " + str(c2) + str(r2) + " - " + str(c3) + str(r3))

    A = 2 * c2.pos_x - 2 * c1.pos_x
    B = 2 * c2.pos_y - 2 * c1.pos_y
    C = r1 ** 2 - r2 ** 2 - c1.pos_x ** 2 + c2.pos_x ** 2 - c1.pos_y ** 2 + c2.pos_y ** 2
    D = 2 * c3.pos_x - 2 * c2.pos_x
    E = 2 * c3.pos_y - 2 * c2.pos_y
    F = r2 ** 2 - r3 ** 2 - c2.pos_x ** 2 + c3.pos_x ** 2 - c2.pos_y ** 2 + c3.pos_y ** 2


    x = (C * E - F * B) / (E * A - B * D)
    y = (C * D - A * F) / (B * D - A * E)

    return Coordinate(x, y)'''


def get_all_combinations(original_list):
    combinations = []

    for i in range(0, len(original_list) - 1):
        for j in range(i + 1, len(original_list)):
            combinations.append((original_list[i], original_list[j]))

    return combinations


def find_all_solutions(coords_and_distance):
    solutions = []
    flag_combinations = get_all_combinations(coords_and_distance)
    for combination in flag_combinations:
        possible_solutions = solve_trilateration(combination[0], combination[1])
        solutions.append(possible_solutions[0])
        solutions.append(possible_solutions[1])
    return solutions


def average_point(cluster):
    amount_of_clusters = len(cluster)
    total_x = 0
    total_y = 0

    for point in cluster:
        total_x += point.pos_x
        total_y += point.pos_y

    return Coordinate(total_x / amount_of_clusters, total_y / amount_of_clusters)


def find_mean_solution(all_solutions):
    amount_of_correct_solutions = len(all_solutions) * (len(all_solutions) - 1)
    acceptable_distance = 3.0
    cluster_size_best_solution = 0
    best_cluster = []

    for solution1 in all_solutions:
        cluster = []
        for solution2 in all_solutions:
            if solution1 == solution2:
                continue

            if solution1.euclidean_distance_from(solution2) < acceptable_distance:
                cluster.append(solution2)

            if len(cluster) >= amount_of_correct_solutions:
                return average_point(cluster)

        if len(cluster) > cluster_size_best_solution:
            cluster_size_best_solution = len(cluster)
            best_cluster = cluster

    return average_point(best_cluster)

def approx_position(txt: str):
    if not txt.startswith("(see"):
        return

    parsed_flags = zip_flag_coords_distance(parse_flags(txt))
    if len(parsed_flags) < 2:
        return  # TODO : maybe return none or return last known position

    all_solutions = find_all_solutions(parsed_flags)
    print(find_mean_solution(all_solutions))
    # print(txt)


'''
- Returns the position of an object.
object_rel_angle is the relative angle to the observer (-180 to 180)
distance is the distance from the observer to the object
my_x, my_y are the coordinates of the observer
my_angle is the global angle of the observer

Formular:
X= distance*cos(angle) +x0
Y= distance*sin(angle) +y0

example: 
My pos: x: -19,  y: -16 my_angle 0
(player Team1 9) 14.9 -7 0 0) = x:-4, y:-17,5
'''
def get_object_position(object_rel_angle, distance, my_x, my_y, my_angle):
    actual_angle = my_angle + object_rel_angle
    x = distance * math.cos(math.radians(actual_angle)) + my_x
    y = distance * math.sin(math.radians(actual_angle)) + my_y
    return x, y