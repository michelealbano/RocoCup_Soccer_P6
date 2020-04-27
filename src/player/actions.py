import math
from logging import debug

from sympy import solve, Eq, Symbol

from constants import PLAYER_JOG_SPEED, PLAYER_RUN_SPEED, KICK_POWER_RATE, BALL_DECAY, \
    KICKABLE_MARGIN, FOV_NARROW, FOV_NORMAL, FOV_WIDE
from geometry import calculate_full_circle_origin_angle, is_angle_in_range

from player.player import PlayerState
from player.world_objects import Coordinate, ObservedPlayer, Ball

ORIENTATION_ACTIONS = ["(turn_neck 90)", "(turn_neck -180)", "(turn 180)", "(turn_neck 90)"]
NECK_ORIENTATION_ACTIONS = ["(turn_neck 90)", "(turn_neck -180)"]

SET_VIEW_NORMAL = "(change_view normal high)"
SET_VIEW_NARROW = "(change_view narrow high)"
SET_VIEW_WIDE = "(change_view wide high)"


def reset_neck(state):
    return ["(turn_neck " + str(-state.body_state.neck_angle) + ")"]


def dribble_towards(state: PlayerState, target_position: Coordinate):
    minimum_last_update_time = state.now() - 3
    angle_known = state.body_angle.is_value_known(minimum_last_update_time)
    position_known = state.position.is_value_known(minimum_last_update_time)

    if not angle_known or not position_known:
        return orient_self(state)

    if state.is_near_ball(KICKABLE_MARGIN):
        direction = calculate_relative_angle(state, target_position)
        actions: [] = ["(kick {0} {1})".format("20", direction), "(dash 70)"]
        return actions
    else:
        return jog_towards_ball(state)


def run_towards(state, target):
    return jog_towards(state, target, PLAYER_RUN_SPEED)


def jog_towards(state: PlayerState, target_position: Coordinate, speed=PLAYER_JOG_SPEED):
    actions = []
    history = state.action_history
    minimum_last_update_time = state.now() - 3
    angle_known = state.body_angle.is_value_known(minimum_last_update_time)
    position_known = state.position.is_value_known(minimum_last_update_time)

    if not angle_known or not position_known:
        return orient_self(state)

    if not state.body_facing(target_position, 15) and history.last_turn_time < state.body_angle.last_updated_time:
        rotation = calculate_relative_angle(state, target_position)
        history.last_turn_time = state.now()
        actions.append("(turn " + str(rotation) + ")")
    else:
        distance = state.position.get_value().euclidean_distance_from(target_position)
        actions.append("(dash {0})".format(str(calculate_dash_power(distance, speed))))

    actions.extend(orient_self_neck_only(state))
    return actions


def jog_towards_ball(state: PlayerState):
    minimum_last_update_time = state.now() - 10
    ball_known = state.world_view.ball.is_value_known(minimum_last_update_time)

    if not ball_known:
        return orient_self(state)

    return jog_towards(state, state.world_view.ball.get_value().coord)


def choose_rand_player(player_passing: PlayerState):
    if len(player_passing.world_view.other_players) != 0:
        return player_passing.world_view.other_players[0]
    return None


def pass_ball_to(target: ObservedPlayer, state: PlayerState):
    world = state.world_view

    if world.ball.is_value_known(world.ticks_ago(5)) and state.position.is_value_known(world.ticks_ago(5)):
        ball = world.ball.get_value()
        if state.is_near_ball(KICKABLE_MARGIN):
            if target is not None:
                print("Kicking from player {0} to player {1}".format(str(state.num), str(target.num)))
                direction = calculate_relative_angle(state, target.coord)
                distance = state.position.get_value().euclidean_distance_from(target.coord)
                return ["(kick " + str(calculate_kick_power(state, distance)) + " " + str(direction) + ")"]
            else:
                return orient_self(state)
        else:
            return jog_towards_ball(state)
    else:
        return orient_self(state)


def pass_ball_to_random(state: PlayerState):
    target: ObservedPlayer = choose_rand_player(state)
    if target is None:
        return orient_self(state)

    direction = target.direction
    power = calculate_kick_power(state, target.distance)

    return ["(kick " + str(power) + " " + str(direction) + ")"]


def kick_to_goal(player : PlayerState):
    if player.team_name == "Team1":
        target = Coordinate(53.0, 0)
    else:
        target = Coordinate(-53.0, 0)

    direction = calculate_relative_angle(player, target)

    return ["(kick " + str(160) + " " + str(direction) + ")"]


def require_see_update(function):
    def wrapper(*args, **kwargs):
        if args[0].action_history.has_turned_since_last_see:
            return []
        else:
            return function(*args, **kwargs)
    return wrapper


@require_see_update
def locate_ball(state: PlayerState):
    actions = [SET_VIEW_WIDE]
    if not state.body_angle.is_value_known(state.now() - 10):
        print("angle unknown")
        return actions

    turn_history = state.action_history.turn_history
    angle = turn_history.least_updated_angle(FOV_WIDE)
    actions.extend(look_direction(state, angle, FOV_WIDE))
    state.action_history.has_turned_since_last_see = True
    return actions


# Creates turn commands (both neck and body)
# to face the total angle of the player in the target direction
@require_see_update
def look_direction(state: PlayerState, target_direction, fov):
    actions = []
    current_total_direction = state.body_angle.get_value() + state.body_state.neck_angle

    body_angle = state.body_angle.get_value()
    # Case where it is enough to turn neck
    if is_angle_in_range(target_direction, from_angle=(body_angle - 90) % 360, to_angle=(body_angle + 90) % 360):
        angle_to_turn = target_direction - current_total_direction
        actions.append("(turn_neck {0})".format(angle_to_turn))
    # Case where it is necessary to turn body
    else:
        angle_to_turn_body = target_direction - state.body_angle.get_value()
        actions.extend(reset_neck(state))
        actions.append("(turn {0})".format(angle_to_turn_body))

    # Update state to show that this angle has now been viewed
    state.action_history.turn_history.renew_angle(target_direction, fov)
    state.action_history.has_turned_since_last_see = True
    return actions


def orient_self(state: PlayerState):
    actions = []
    view = adjust_view(state)
    viewable_range = (state.body_angle.get_value() - 90, state.body_angle.get_value() + 90)
    viewable_indices = ()
    if state.is_near_ball():
        view = SET_VIEW_NARROW
    elif state.is_near_ball(20):
        view = SET_VIEW_NARROW
    else:
        view = SET_VIEW_NORMAL

    if state.action_history.last_orientation_time >= state.last_see_update:
        return ""

    history = state.action_history
    action = ORIENTATION_ACTIONS[history.last_orientation_action]
    actions.append(action)

    history.last_orientation_action += 1
    history.last_orientation_action %= len(ORIENTATION_ACTIONS)
    history.last_orientation_time = state.now()

    return actions


def adjust_view(state: PlayerState):
    if state.world_view.ball.is_value_known(state.now() - 6) and state.position.is_value_known(state.now() - 6):
        dist_to_ball = state.world_view.ball.get_value().coord.euclidean_distance_from( state.position.get_value())
        if dist_to_ball < 15:
            return SET_VIEW_NARROW
        else:
            return SET_VIEW_NORMAL
    return SET_VIEW_WIDE


def orient_self_neck_only(state: PlayerState):
    actions = [adjust_view(state)]
    history = state.action_history
    if history.last_orientation_time >= state.last_see_update:
        return [None]  # Don't do anything if no vision update has been received from the server since last turn command
    history.last_orientation_time = state.now()

    if history.last_orientation_action >= len(NECK_ORIENTATION_ACTIONS):
        # Reset neck position
        history.last_orientation_action = 0
        actions.extend(reset_neck(state))
        return actions

    action = NECK_ORIENTATION_ACTIONS[history.last_orientation_action]
    history.last_orientation_action += 1
    actions.append(action)
    return actions


def calculate_relative_angle(player_state, target_position):
    rotation = calculate_full_circle_origin_angle(target_position, player_state.position.get_value())
    rotation = math.degrees(rotation)
    rotation -= player_state.body_angle.get_value()

    # Pick the short way around (<180 degrees)
    if rotation > 180:
        rotation -= 360
    elif rotation < -180:
        rotation += 360

    return rotation


# TODO: find out how to calculate power from distance
def calculate_power(distance):
    return 15 + float(distance) * 3


def calculate_dash_power(distance, speed):
    if distance < 2:
        return 15 + distance * 10
    return speed


def calculate_kick_power(state: PlayerState, distance: float) -> int:
    ball: Ball = state.world_view.ball.get_value()
    dir_diff = abs(ball.direction)
    dist_ball = ball.distance

    # voodoo parameters
    if distance > 40:
        time_to_target = int(distance * 1.4)
    elif distance >= 30:
        time_to_target = int(distance * 1.35)
    elif distance >= 20:
        time_to_target = int(distance * 1.25)
    elif distance >= 10:
        time_to_target = int(distance * 1.15)
    else:
        time_to_target = 3

    # Solve for the initial kick power needed to get to the distance after time_to_target ticks
    # x = kickpower (0-100)
    x = Symbol('x', real=True)
    eqn = Eq(sum([(((x * KICK_POWER_RATE) * (1 - 0.25 * (dir_diff / 180) - 0.25 * (dist_ball / KICKABLE_MARGIN)))
                   * BALL_DECAY ** i) for i in range(0, time_to_target)]), distance)
    solution = solve(eqn)
    if len(solution) == 0:
        print(solution)
        print("Time_to_target: {0}, dist_ball: {1}, dir_diff: {2}, player: {3}".format(time_to_target, dist_ball, dir_diff, state))
    needed_kick_power = solve(eqn)[0]

    if needed_kick_power < 0:
        raise Exception("Should not be able to be negative. What the hell - Philip")
    elif needed_kick_power > 100:
        pass
        # print("Tried to kick with higher than 100 power: ", str(needed_kick_power), ", player: ", state)

    return needed_kick_power



