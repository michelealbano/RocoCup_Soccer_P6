import math
import geometry

from configurations import KICK_POWER_RATE, BALL_DECAY, \
    KICKABLE_MARGIN, FOV_NARROW, FOV_NORMAL, FOV_WIDE, PLAYER_SPEED_DECAY, PLAYER_MAX_SPEED, DASH_POWER_RATE, \
    WARNING_PREFIX, CATCHABLE_MARGIN
from geometry import calculate_full_origin_angle_radians, is_angle_in_range, smallest_angle_difference
from geometry import Vector2D
from player.player import PlayerState, ViewFrequency
from player.world_objects import Coordinate, ObservedPlayer, Ball, PrecariousData
from utils import clamp, debug_msg
from math import radians

_IDLE_ORIENTATION_INTERVAL = 4
_DRIBBLE_ORIENTATION_INTERVAL = 2
_POSSESSION_ORIENTATION_INTERVAL = 2

SET_FOV_NORMAL = "(change_view normal high)"
SET_FOV_NARROW = "(change_view narrow high)"
SET_FOV_WIDE = "(change_view wide high)"

_MAX_TICKS_PER_SEE_UPDATE = 4


class Command:
    def __init__(self, messages: [str] = None, urgent=False, on_execute=lambda: None) -> None:
        if messages is None:
            self.messages = []
        else:
            self.messages = messages
        self.urgent = urgent
        self._attached_functions = [on_execute]
        self.final = False

    def append_action(self, action: str):
        self.messages.append(action)

    def add_function(self, f):
        self._attached_functions.append(f)

    def mark_final(self):
        self.final = True

    def __repr__(self) -> str:
        return str(self.messages) + ", urgent: " + str(self.urgent)

    def execute_attached_functions(self):
        for f in self._attached_functions:
            f()


class CommandBuilder:
    def __init__(self) -> None:
        self.command_list: [Command] = [Command()]
        self.ticks = 0

    def _append_action(self, action, urgent=False):
        cmd = self.command_list[self.ticks]
        cmd.append_action(action)
        if urgent:
            cmd.urgent = True

    def append_turn_action(self, state: PlayerState, turn_moment, urgent=False):
        if abs(turn_moment) < 0.2:
            return
        self._append_action("(turn {0})".format(turn_moment), urgent)
        self.append_function(lambda: register_body_turn(state, turn_moment))

    def append_neck_turn(self, state, angle_to_turn, fov):
        if abs(angle_to_turn) < 0.2:
            return
        self._append_action("(turn_neck {0})".format(angle_to_turn))
        self.append_function(lambda: renew_angle(state, angle_to_turn, fov))
        self.append_function(lambda: register_neck_turn(state, angle_to_turn))

    def append_neck_body_turn(self, state, body_moment, neck_angle, fov):
        if abs(body_moment) > 0.1:
            self._append_action("(turn {0})".format(body_moment))
            self.append_function(lambda: register_body_turn(state, body_moment))

        if abs(neck_angle) > 0.1:
            self._append_action("(turn_neck {0})".format(neck_angle))
            self.append_function(lambda: register_neck_turn(state, neck_angle))

        if abs(neck_angle) > 0.1 or abs(body_moment) > 0.1:
            self.append_function(lambda: renew_angle(state, body_moment + neck_angle, fov))

    def append_dash_action(self, state, power, urgent=False):
        self._append_action("(dash {0})".format(power), urgent)
        self.current_command().add_function(lambda: project_dash(state, power))

    def append_catch_action(self, state, ball_pos: Coordinate, urgent=False):
        self._append_action("(catch {0})".format(int(_calculate_relative_angle(state, ball_pos))), urgent)

    def append_function(self, f):
        self.current_command().add_function(f)

    def append_fov_change(self, state, fov):
        if fov == 45:
            action = SET_FOV_NARROW
        elif fov == 90:
            action = SET_FOV_NORMAL
        elif fov == 180:
            action = SET_FOV_WIDE
        else:
            debug_msg(WARNING_PREFIX + " Turn angle not supported (append_fov_change): " + str(fov), "POSITIONAL")
            action = SET_FOV_NORMAL
        self.current_command().append_action(action)
        self.append_function(lambda: update_fov(state, fov))

    def next_tick(self, urgent=False):
        self.ticks += 1
        self.command_list.append(Command(urgent=urgent))

    def current_command(self):
        return self.command_list[self.ticks]

    def append_kick(self, state, power, direction, urgent=False):
        self._append_action("(kick {0} {1})".format(power, direction), urgent)

    def append_empty_actions(self, amount, urgent=False):
        for i in range(0, amount):
            self.next_tick(urgent)


def kick_if_collision(state: PlayerState, command: Command, speed=0.5, ball_dir: int = 0):
    now = state.now()
    ball = state.world_view.ball.get_value()

    if ball is not None and (
            state.now() - state.ball_collision_time) > 5 and not state.action_history.has_just_intercept_kicked:
        collision_time = ball.project_ball_collision_time()

        if state.is_test_player():
            debug_msg("{0} | Predicted collision time {1} | Distance history: {2} | Last collision time {3} "
                      .format(state.now(), collision_time, ball.dist_history, state.ball_collision_time)
                      , "INTERCEPTION")

        if collision_time is not None and collision_time <= now + 1:
            message = _kick_stop_ball_msg(state, ball_dir=ball_dir, speed=speed)
            command.messages.clear()
            command.messages.append(message)
            state.action_history.has_just_intercept_kicked = True


def _kick_stop_ball_msg(state, speed, ball_dir):
    kick_dir = (ball_dir + 180) % 360

    if state.action_history.turn_in_progress and state.action_history.expected_body_angle is not None:
        relative_dir = smallest_angle_difference(from_angle=state.action_history.expected_body_angle, to_angle=kick_dir)
    else:
        relative_dir = smallest_angle_difference(from_angle=state.body_angle.get_value(), to_angle=kick_dir)

    power = round(10 + 6 * speed)
    message = "(kick {0} {1})".format(str(power), str(relative_dir))
    if state.is_test_player():
        debug_msg(str(state.now()) + " | STOP BALL KICK. Relative Dir {0} | Power {1}".format(relative_dir, power)
                  , "INTERCEPTION")
    return message


def renew_angle(state: PlayerState, angle_to_turn, fov):
    target_dir = (state.face_dir.get_value() + angle_to_turn) % 360
    state.action_history.turn_history.renew_angle(target_dir, fov)
    state.body_state.fov = fov


def update_fov(state: PlayerState, fov):
    state.body_state.fov = fov


def register_catch(state: PlayerState):
    state.action_history.last_catch = state.world_view.sim_time


def register_neck_turn(state: PlayerState, angle):
    state.action_history.expected_angle_change += angle
    state.action_history.turn_in_progress = True


def register_body_turn(state: PlayerState, body_turn_moment=0):
    turn_angle = _calculate_actual_turn_angle(state.body_state.speed, body_turn_moment)
    state.action_history.expected_angle_change += turn_angle
    state.action_history.expected_body_angle = state.body_angle.get_value() + turn_angle
    state.action_history.turn_in_progress = True


def project_dash(state: PlayerState, dash_power):
    actual_speed = _calculate_actual_speed(state.body_state.speed, dash_power)
    state.body_state.speed = actual_speed * PLAYER_SPEED_DECAY
    state.action_history.expected_speed = actual_speed * PLAYER_SPEED_DECAY
    """exp_angle = state.action_history.expected_angle

    if exp_angle is not None:
        projected_angle = exp_angle
    else:
        projected_angle = state.body_angle.get_value()
    
    projected_position = state.action_history.projected_position + geometry.get_xy_vector(direction=-projected_angle, length=actual_speed)
    """
    # print("PROJECTION : ", state.now() + 1, " | Position: ", projected_position, "Projected speed: ", actual_speed * PLAYER_SPEED_DECAY)
    # state.action_history.projected_position = projected_position


def orient_if_position_or_angle_unknown(function):
    def wrapper(*args, **kwargs):
        state: PlayerState = args[0]
        time_limit = state.action_history.two_see_updates_ago
        if (not state.position.is_value_known(time_limit)) or not state.body_angle.is_value_known(time_limit):
            debug_msg("Oriented instead of : " + str(function) + " because position or angle is unknown", "POSITIONAL")
            return blind_orient(state)
        else:
            return function(*args, **kwargs)

    return wrapper


def require_angle_update(function):
    def wrapper(*args, **kwargs):
        state: PlayerState = args[0]
        if state.action_history.turn_in_progress:
            return []
        else:
            return function(*args, **kwargs)

    return wrapper


def intercept(state: PlayerState, intercept_point: Coordinate):
    debug_msg(str(state.now()) + "intercepting at: " + str(intercept_point), "INTERCEPTION")

    state.action_history.has_just_intercept_kicked = False
    command_builder = CommandBuilder()
    delta: Coordinate = intercept_point - state.position.get_value()
    _append_rushed_position_adjustment(state, delta.pos_x, delta.pos_y, command_builder)

    """
    for com in command_builder.command_list:
        com.add_function(lambda c=com: kick_if_collision(state, com, speed=speed, ball_dir=direction))
    """
    return command_builder.command_list


def _gen_intercept_actions(state, target: geometry.Vector2D, arrival_tick, ball_velocity_at_impact: Vector2D,
                           stop_action="kick"):
    def advance(pos, vel):
        return pos + vel, vel.decayed(PLAYER_SPEED_DECAY, 1)

    command_builder = CommandBuilder()
    player_vel = state.get_y_north_velocity_vector()
    player_pos = Vector2D(0, 0)
    dist = target.magnitude()
    player_rotation = state.body_angle.get_value()

    if stop_action == "catch" and dist < CATCHABLE_MARGIN and arrival_tick == 1:
        urgent_catch = True
        append_catch(state, target.coord(), urgent_catch, command_builder)
        return Interception(target, command_builder.command_list, 0, arrival_tick)

    if stop_action == "kick" and dist < KICKABLE_MARGIN and arrival_tick == 1:
        urgent_Stop_kick = True
        append_stop_kick(state, player_pos, target, ball_velocity_at_impact, urgent_Stop_kick, player_rotation,
                         command_builder)
        append_neck_turn_to(state, player_rotation, player_pos, target, command_builder)
        return Interception(target, command_builder.command_list, 0, arrival_tick)

    if dist > arrival_tick * PLAYER_MAX_SPEED:
        return None  # todo: add extra checks to save computations

    # Face target point
    angle_dif = smallest_angle_difference(from_angle=player_rotation, to_angle=target.world_direction())
    while abs(angle_dif) > _allowed_angle_delta(dist) or dist < 0.3:
        moment = clamp(_calculate_turn_moment(player_vel.magnitude(), angle_dif), -180, 180)
        actual_turn = _calculate_actual_turn_angle(player_vel.magnitude(), moment)
        command_builder.append_turn_action(state, moment)
        append_look_at_ball_neck_only(state, command_builder, body_dir_change=actual_turn)
        command_builder.next_tick()
        player_vel = player_vel.rotated(radians(geometry.inverse_y_axis(actual_turn)))
        player_rotation += actual_turn
        player_pos, player_vel = advance(player_pos, player_vel)

        angle_dif = smallest_angle_difference(from_angle=player_rotation,
                                              to_angle=target.world_direction())
        # If we are beyond tick limit return nothing
        if command_builder.ticks > arrival_tick:
            return None

    # Move the player close to the target position and stop
    dist = player_pos.distance_from(target)
    braking = False
    while dist > 0.2 or player_vel.magnitude() > 0.2:
        target_dist = dist - 0.21

        if dist <= 0.31:
            # Brake if close
            target_speed = dist
            braking = True
        else:
            # Otherwise close remaining distance
            target_speed = min(target_dist, PLAYER_MAX_SPEED)

        dash_power, new_speed = _calculate_dash_power(player_vel.magnitude(), target_speed)

        # If braking is second action, make it urgent (to ensure that it happens)
        urgent = True if (braking and command_builder.ticks <= 1) or command_builder.ticks == 1 else False
        command_builder.append_dash_action(state, dash_power, urgent)
        command_builder.next_tick()

        # Update velocity vector prediction according to new dash speed
        if player_vel.magnitude() > 0:
            player_vel = player_vel.extend_length_to(new_speed)
        else:
            player_vel = Vector2D.velocity_to_xy(new_speed, geometry.inverse_y_axis(player_rotation))

        # Update prediction of player position and velocity for next tick
        player_pos, player_vel = advance(player_pos, player_vel)

        dist = player_pos.distance_from(target)
        if dist <= 0.3 and arrival_tick == command_builder.ticks:
            return Interception(target, command_builder.command_list, 0, arrival_tick)

        # If we are beyond tick limit return nothing
        if command_builder.ticks > arrival_tick:
            return None

    extra_ticks = (arrival_tick - 1) - command_builder.ticks

    if command_builder.ticks >= arrival_tick:
        return None

    while command_builder.ticks < arrival_tick - 1:
        command_builder.next_tick()

    if stop_action == "kick" and command_builder.ticks == arrival_tick - 1:
        urgent_Stop_kick = True if arrival_tick <= 3 else False
        append_stop_kick(state, player_pos, target, ball_velocity_at_impact, urgent_Stop_kick, player_rotation,
                         command_builder)
        append_neck_turn_to(state, player_rotation, player_pos, target, command_builder)
    if stop_action == "catch" and command_builder.ticks == arrival_tick - 1:
        urgent_catch = True if arrival_tick <= 3 else False
        append_catch(state, target.coord(), urgent_catch, command_builder)
        return Interception(target, command_builder.command_list, 0, arrival_tick)

    return Interception(target, command_builder.command_list, extra_ticks, arrival_tick)


def append_catch(state, ball_pos, urgent_catch, command_builder):
    command_builder.append_catch_action(state, ball_pos, urgent_catch)


def append_stop_kick(state, player_pos, ball_pos, ball_velocity_at_impact, urgent, player_rotation, command_builder):
    opposite_ball_angle = (ball_velocity_at_impact.world_direction() + 180) % 360
    kick_angle = smallest_angle_difference(from_angle=player_rotation, to_angle=opposite_ball_angle)
    kick_power = _calculate_stop_kick_power(player_pos, ball_pos, player_rotation, ball_velocity_at_impact)
    command_builder.append_kick(state, kick_power, kick_angle, urgent)


def append_neck_turn_to(state, player_rotation, player_position: Vector2D, target: Vector2D, command_builder):
    ball_angle = (target - player_position).world_direction()
    target_neck_angle = smallest_angle_difference(player_rotation, ball_angle)
    target_neck_angle = clamp(target_neck_angle, -90, 90)
    turn_amount = smallest_angle_difference(from_angle=state.body_state.neck_angle, to_angle=target_neck_angle)
    command_builder.append_neck_turn(state, turn_amount, state.body_state.fov)


class Interception:

    def __init__(self, position, actions, extra_ticks, deadline) -> None:
        self.extra_ticks = extra_ticks
        self.actions = actions
        self.position = position
        self.deadline = deadline

    def contains_urgent_commands(self):
        for a in self.actions:
            if a.urgent:
                return True
        return False

    def __repr__(self) -> str:
        return "(Position : {0}, Extra ticks: {1}, Deadline: {2} Actions: {3})" \
            .format(self.position, self.extra_ticks, self.deadline, self.actions)


def intercept_2(state: PlayerState, stop_action="kick"):
    ball = state.world_view.ball.get_value()
    if state.get_y_north_velocity_vector() is None or ball is None or ball.absolute_velocity is None or ball.distance > 20:
        return None

    def project(position_vec, vel_vec, ticks):
        positions = []
        for t in range(0, ticks):
            position_vec = position_vec + vel_vec
            positions.append(position_vec)
            vel_vec = vel_vec.decayed(BALL_DECAY)
        return positions

    ball: Ball = state.world_view.ball.get_value()
    rel_ball_positions = project(ball.relative_ball_position_vector(), ball.absolute_velocity, 15)

    # Find possible interceptions
    interceptions: [Interception] = []
    for i, relative_pos in enumerate(rel_ball_positions):
        tick_limit = i + 1
        new_intercept = _gen_intercept_actions(state, relative_pos, tick_limit,
                                               ball.absolute_velocity.decayed(BALL_DECAY, tick_limit), stop_action)
        if new_intercept is not None:
            interceptions.append(new_intercept)
            if new_intercept.extra_ticks > 3:
                break  # Performance measure

    # Filter out invalid interceptions
    interceptions = list(filter(lambda interception: interception is not None, interceptions))

    # No valid interceptions
    if len(interceptions) == 0:
        return None

    best_interception = None
    for i in interceptions:  # If already standing at intercept point, just return that intercept point
        if i.contains_urgent_commands or (i.position.magnitude() < KICKABLE_MARGIN / 2 and i.extra_ticks < 3):
            best_interception = i
            break

    if best_interception is None and state.action_history.intercepting:
        for i in interceptions:
            turn_angle = _calculate_relative_angle(state, i.position.coord())
            if turn_angle < 5:
                best_interception = i.actions
                break

    if best_interception is None:  # Prioritize interceptions that can be reached with a bit of overhead
        interceptions = list(sorted(interceptions, key=lambda interception: abs(3 - interception.extra_ticks)))
        best_interception = interceptions[0]
        if best_interception.extra_ticks < 2 and ball.distance > 5:
            return None

    state.action_history.intercepting = True

    # DEBUG
    player_pos = Vector2D(state.position.get_value().pos_x, state.position.get_value().pos_y)
    """print(state.now(), " | Intercept pos: ", best_interception.position + player_pos)
    print(state.now(), " | Interception: ", best_interception)
    print(state.now(), " | Chosen from: ", list(map(lambda rel: rel + player_pos, rel_ball_positions)))
    print(state.now(), " | Chosen from: ", interceptions)
    print(state.now(), " | Ball velocity: ", ball.absolute_velocity)
    print(state.now(), " | Ball positions: ", list(
        map(lambda v: v + Vector2D(state.position.get_value().pos_x, state.position.get_value().pos_y),
            rel_ball_positions)))
    print(state.now(), ball.absolute_velocity, "| dist chng: ", ball.dist_change, " | dir chng: ",
          ball.dir_change, " | ball dir: ", ball.global_dir, "| ball dist: ", ball.distance)
    print(state.now(), " | Actions : ", best_interception.actions)"""

    return best_interception.actions


"""if intercept_actions is not None:
    player_pos = Vector2D(state.position.get_value().pos_x, state.position.get_value().pos_y)
    print(state.now(), " | Intercepting at: ", relative_pos + player_pos)
    print(state.now(), " | Ball velocity: ", ball.absolute_velocity)
    print(state.now(), " | Ball relative positions: ", list(
        map(lambda v: v + Vector2D(state.position.get_value().pos_x, state.position.get_value().pos_y),
            rel_ball_positions)))
    print(state.now(), ball.absolute_velocity, "| dist chng: ", ball.dist_change, " | dir chng: ",
          ball.dir_change, " | ball dir: ", ball.global_dir, "| ball dist: ", ball.distance)
    print(state.now(), "actions : ", intercept_actions)
    state.action_history.intercepting = True"""


def receive_ball(state: PlayerState):
    debug_msg(str(state.now()) + " | Receiving ball", "ACTIONS")
    command_builder = CommandBuilder()
    if not state.action_history.turn_in_progress:
        append_look_at_ball(state, command_builder)
    ball: Ball = state.world_view.ball.get_value()

    command_builder.append_empty_actions(4, False)
    """
    for com in command_builder.command_list:
        com.add_function(lambda c=com: kick_if_collision(state, c, speed=ball.absolute_velocity.magnitude(),
                                                         ball_dir=ball.absolute_velocity.world_direction()))
    """
    return command_builder.command_list


# Calculates urgent actions to quickly reposition player at the cost of precision
def _append_rushed_position_adjustment(state: PlayerState, delta_x, delta_y, command_builder: CommandBuilder,
                                       focus_ball=True):
    target = Coordinate(delta_x, delta_y)
    distance = Coordinate(0, 0).euclidean_distance_from(target)

    target_body_angle = math.degrees(calculate_full_origin_angle_radians(target, Coordinate(0, 0)))
    turn_angle = smallest_angle_difference(from_angle=state.body_angle.get_value(), to_angle=target_body_angle)
    projected_speed = state.body_state.speed

    if abs(turn_angle) > _allowed_angle_delta(distance):  # Need to turn body first
        if _calculate_turn_moment(projected_speed, turn_angle) >= 180:  # Stop moving if necessary
            dash_power, projected_speed = _calculate_dash_power(state.body_state.speed, 0)
            command_builder.append_dash_action(state, dash_power)
            command_builder.next_tick()
            projected_speed *= PLAYER_SPEED_DECAY

        moment = _calculate_turn_moment(projected_speed, turn_angle)
        command_builder.append_turn_action(state, moment, True)
        actual_turn_angle = _calculate_actual_turn_angle(projected_speed, moment)
        append_look_at_ball_neck_only(state, command_builder, body_dir_change=actual_turn_angle)
        command_builder.next_tick()
        projected_speed *= PLAYER_SPEED_DECAY

    append_last_dash_actions(state, projected_speed, distance, command_builder, urgent=True)
    debug_msg("distance: " + str(distance) + "| speed : " + str(state.body_state.speed) + " | target body direction: "
              + str(target_body_angle) + " | current body angle: " + str(state.body_angle.get_value())
              + str(command_builder.command_list), "INTERCEPTION")

    return


def rush_to(state: PlayerState, target: Coordinate):
    return go_to(state, target, dash_power_limit=state.body_state.max_dash_power)


def rush_to_ball(state: PlayerState):
    debug_msg(str(state.now()) + "RUSH TO BALL", "ACTIONS")

    if not state.world_view.ball.is_value_known(state.action_history.three_see_updates_ago) or state.is_ball_missing():
        debug_msg("ACTION: LOCATE BALL", "INTERCEPTION")
        return locate_ball(state)

    ball: Ball = state.world_view.ball.get_value()
    ball_vel = ball.absolute_velocity
    player_vel = state.get_y_north_velocity_vector()
    if ball_vel is not None and player_vel is not None and ball_vel.magnitude() > 0.1 \
            and abs(ball_vel.world_direction() - state.body_angle.get_value()) < 10:
        if state.is_test_player():
            debug_msg(str(state.now()) + " Running after ball ", "ORIENTATION")

        ball_dist = ball.distance
        command_builder = CommandBuilder()

        """if state.world_view.ball.last_updated_time == state.action_history.last_see_update:
            angle_to_turn = smallest_angle_difference(from_angle=0, to_angle=(ball.direction
                                                                              + state.body_state.neck_angle) % 360)"""
        if ball.absolute_velocity is not None:
            ticks = state.now() - state.world_view.ball.last_updated_time + 1
            angle_to_turn = _calculate_relative_angle(state, ball.project_position_in_n_ticks(ticks))
        else:
            angle_to_turn = _calculate_relative_angle(state, ball.coord)

        if abs(angle_to_turn) >= 5:
            if state.is_test_player():
                debug_msg(str(state.now()) + " Turning " + str(angle_to_turn) + " degrees to face ball", "ORIENTATION")

            moment = _calculate_turn_moment(state.body_state.speed, angle_to_turn)
            command_builder.append_turn_action(state, moment)
            append_look_at_ball_neck_only(state, command_builder, _calculate_actual_turn_angle(player_vel.magnitude(),
                                                                                               moment))
            command_builder.next_tick()
            ball_dist += ball_vel.magnitude() - player_vel.magnitude()
            ball_vel = ball_vel.decayed(BALL_DECAY, 1)
            player_vel = player_vel.decayed(PLAYER_SPEED_DECAY, 1)
        elif not state.action_history.turn_in_progress:
            _append_neck_orientation(state, command_builder)

        player_speed = player_vel.magnitude()
        while ball_dist > 0 and command_builder.ticks < 4:
            target_speed = ball_dist + ball_vel.magnitude()
            dash_power, new_speed = _calculate_dash_power(player_speed, target_speed)
            command_builder.append_dash_action(state, dash_power)
            command_builder.next_tick()

            ball_dist = ball_dist - new_speed + ball_vel.magnitude()
            player_speed *= PLAYER_SPEED_DECAY
            ball_vel = ball_vel.decayed(BALL_DECAY, 1)

        return command_builder.command_list

    locations = ball.project_ball_position(5, state.now() - state.world_view.ball.last_updated_time)

    if locations is not None and False:
        debug_msg("Using prediction point: " + str(locations[4]), "ACTIONS")
        return go_to(state, locations[4], dash_power_limit=state.body_state.max_dash_power)
    else:
        return go_to(state, state.world_view.ball.get_value().coord, dash_power_limit=state.body_state.max_dash_power)


def jog_to_ball(state: PlayerState):
    debug_msg(str(state.now()) + "JOG TO BALL", "ACTIONS")
    if not state.world_view.ball.is_value_known(state.action_history.three_see_updates_ago) or state.is_ball_missing():
        debug_msg("ACTION: LOCATE BALL", "INTERCEPTION")
        return locate_ball(state)

    ball: Ball = state.world_view.ball.get_value()
    locations = ball.project_ball_position(5, state.now() - state.world_view.ball.last_updated_time)
    if locations is not None and False:
        return go_to(state, locations[4], dash_power_limit=state.body_state.jog)
    else:
        return go_to(state, state.world_view.ball.get_value().coord, dash_power_limit=state.body_state.jog_dash_power)


def rush_collide_ball(state: PlayerState):
    pass
    """ball: Ball = state.world_view.ball.get_value()

    angle_dif = smallest_angle_difference(from_angle=state.body_angle.get_value(), to_angle=state.body_angle)
    if state.body_angle.get_value

    locations = ball.project_ball_position(5, state.now() - state.world_view.ball.last_updated_time)
    if locations is not None:
        return go_to(state, locations[4], dash_power_limit=PLAYER_RUSH_POWER)
    else:
        return go_to(state, state.world_view.ball.get_value().coord, dash_power_limit=PLAYER_RUSH_POWER)"""


def jog_to(state: PlayerState, target: Coordinate):
    return go_to(state, target, dash_power_limit=state.body_state.jog_dash_power)


@orient_if_position_or_angle_unknown
def go_to(state: PlayerState, target: Coordinate, dash_power_limit=100):
    command_builder = CommandBuilder()
    projected_dir = state.body_angle.get_value()
    projected_speed = state.body_state.speed
    dist = target.euclidean_distance_from(state.position.get_value())
    projected_pos = state.position.get_value()

    if not state.body_facing(target, _allowed_angle_delta(dist)) and not state.action_history.turn_in_progress:
        rotation = _calculate_relative_angle(state, target)

        # Stop moving if necessary to turn completely towards target
        if _calculate_turn_moment(projected_speed, rotation) >= 180:
            dash_power, projected_speed = _calculate_dash_power(state.body_state.speed, 0)
            command_builder.append_dash_action(state, dash_power)
            command_builder.next_tick()
            projected_speed *= PLAYER_SPEED_DECAY

        turn_moment = round(_calculate_turn_moment(projected_speed, rotation), 2)
        if state.is_test_player():
            debug_msg(str(state.now()) + " global angle: " + str(state.body_angle.get_value())
                      + " off by: " + str(rotation), "ACTIONS")

        if turn_moment < 0:
            first_turn_moment = max(turn_moment, -180)
        else:
            first_turn_moment = min(turn_moment, 180)
        command_builder.append_turn_action(state, first_turn_moment)
        _append_neck_orientation(state, command_builder,
                                 _calculate_actual_turn_angle(projected_speed, first_turn_moment))
        command_builder.next_tick()

        # Update projections
        projected_dir += _calculate_actual_turn_angle(state.body_state.speed, first_turn_moment)
        projected_pos = project_position(projected_pos, projected_speed, projected_dir)
        projected_speed *= PLAYER_SPEED_DECAY

    elif not state.action_history.turn_in_progress:
        _append_neck_orientation(state, command_builder, 0)

    # Add dash commands for remaining amount of ticks
    for i in range(command_builder.ticks, _MAX_TICKS_PER_SEE_UPDATE):
        projected_dist = target.euclidean_distance_from(projected_pos)

        if projected_dist < 1.5:
            append_last_dash_actions(state, projected_speed, projected_dist, command_builder, False)
            return command_builder.command_list

        possible_speed = _calculate_actual_speed(projected_speed, dash_power_limit)
        target_speed = min(projected_dist, possible_speed)
        power, projected_speed = _calculate_dash_power(projected_speed, target_speed)
        command_builder.append_dash_action(state, power)
        command_builder.next_tick()

        projected_pos = project_position(projected_pos, projected_speed, projected_dir)

        # Predict new dist to target and speed
        projected_dist -= projected_speed
        projected_speed *= PLAYER_SPEED_DECAY

    return command_builder.command_list


def project_position(current_pos, current_speed, current_dir):
    return current_pos + geometry.get_xy_vector(direction=-current_dir, length=current_speed)


def distance_in_three_ticks(speed):
    return speed + speed * PLAYER_SPEED_DECAY + speed * PLAYER_SPEED_DECAY * PLAYER_SPEED_DECAY


def append_last_dash_actions(state, projected_speed, distance, command_builder: CommandBuilder, urgent, max_power=100):
    # print("distance", distance, "speed:", projected_speed)
    if distance >= distance_in_three_ticks(_calculate_actual_speed(projected_speed, max_power)):
        command_builder.append_dash_action(state, max_power)
        command_builder.next_tick()
        projected_speed = _calculate_actual_speed(projected_speed, max_power)
        distance -= projected_speed
        projected_speed *= PLAYER_SPEED_DECAY
        append_last_dash_actions(state, projected_speed, distance, command_builder, urgent)
        return

    # one dash + two empty commands
    # dash:
    target_speed = projected_speed + (25.0 * distance - 39.0 * projected_speed) / 39.0
    dash_power, projected_speed = _calculate_dash_power(projected_speed, target_speed)
    command_builder.append_dash_action(state, dash_power, urgent)
    projected_speed *= PLAYER_SPEED_DECAY

    # deceleration 1
    command_builder.next_tick(urgent)  # idle deceleration tick 1
    projected_speed *= PLAYER_SPEED_DECAY

    # deceleration 2
    command_builder.next_tick(urgent)  # idle deceleration tick 2
    projected_speed *= PLAYER_SPEED_DECAY


@require_angle_update
@orient_if_position_or_angle_unknown
def locate_ball(state: PlayerState):
    commandBuilder = CommandBuilder()
    commandBuilder.append_fov_change(state, FOV_WIDE)

    turn_history = state.action_history.turn_history
    angle = turn_history.least_updated_angle(FOV_WIDE)
    turn_history.renew_angle(angle, FOV_WIDE)
    _append_look_direction(state, angle, FOV_WIDE, commandBuilder)

    if state.is_test_player():
        debug_msg(str(state.now()) + " locate_ball. Looking towards : " + str(angle), "ORIENTATION")
    return commandBuilder.command_list


def catch_ball(state: PlayerState, ball_pos_1_tick: Coordinate):
    commandBuilder = CommandBuilder()
    if state.world_view.sim_time - state.action_history.last_catch < 5:
        debug_msg("Can't catch due to penalty: ", "GOALIE")
        return commandBuilder.command_list
    commandBuilder.append_catch_action(state, ball_pos_1_tick, urgent=True)
    commandBuilder.current_command().add_function(lambda: register_catch_action(state))

    return commandBuilder.command_list


def register_catch_action(state: PlayerState):
    state.action_history.last_catch = state.world_view.sim_time


def face_ball(state: PlayerState):
    command_builder = CommandBuilder()
    rel_angle = _calculate_relative_angle(state, state.world_view.ball.get_value().coord)

    command_builder.append_turn_action(state, _calculate_turn_moment(state.body_state.speed, rel_angle))
    append_look_at_ball_neck_only(state, command_builder, int(rel_angle))
    return command_builder.command_list


# Used to reorient self in case of not knowing position or body angle
def blind_orient(state):
    if state.is_test_player():
        debug_msg(str(state.now()) + "blind_orient", "ORIENTATION")

    command_builder = CommandBuilder()
    command_builder.append_fov_change(state, FOV_WIDE)
    command_builder.append_turn_action(state, 160)
    return command_builder.command_list


# Creates turn commands (both neck and body)
# to face the total angle of the player in the target direction
def _append_look_direction(state: PlayerState, target_direction, fov, command_builder: CommandBuilder):
    if state.is_test_player():
        debug_msg(str(state.now()) + "_append_look_direction : " + str(target_direction) + " Current angle: "
                  + str(state.body_angle.get_value() + state.body_state.neck_angle), "ORIENTATION")

    current_total_direction = state.body_angle.get_value() + state.body_state.neck_angle

    body_angle = state.body_angle.get_value()
    # Case where it is enough to turn neck
    if is_angle_in_range(target_direction, from_angle=(body_angle - 90) % 360, to_angle=(body_angle + 90) % 360):
        angle_to_turn = round(smallest_angle_difference(target_direction, current_total_direction), 2)
        command_builder.append_neck_turn(state, angle_to_turn, fov)
    else:  # Case where it is necessary to turn body
        body_turn_angle = smallest_angle_difference(target_direction, state.body_angle.get_value())
        neck_turn_angle = state.body_state.neck_angle
        command_builder.append_neck_body_turn(state, body_turn_angle, neck_turn_angle, fov)


@require_angle_update
def idle_neck_orientation(state):
    command_builder = CommandBuilder()
    _append_neck_orientation(state, command_builder)
    if state.is_test_player():
        debug_msg("inside idle neck orient : " + str(command_builder.command_list), "POSITIONAL")
    return command_builder.command_list


def _append_neck_orientation(state: PlayerState, command_builder, body_dir_change=0):
    if state.is_test_player():
        debug_msg(str(state.now()) + " _append_neck_orientation", "ORIENTATION")
    ball = state.world_view.ball.get_value()

    if state.is_dribbling() and state.action_history.ball_focus_actions > _DRIBBLE_ORIENTATION_INTERVAL \
            and ball.distance > 1.0:
        # Look 180 degrees to one side
        _append_wide_neck_orientation(state, command_builder, body_dir_change)
        state.action_history.ball_focus_actions = 0
    elif state.action_history.ball_focus_actions > _IDLE_ORIENTATION_INTERVAL \
            and state.world_view.ball.is_value_known(state.action_history.last_see_update):
        # Orient to least updated place within neck angle
        _append_orient(state, neck_movement_only=True, command_builder=command_builder, body_dir_change=body_dir_change)
        state.action_history.ball_focus_actions = 0
    else:
        # Look towards ball as far as possible
        append_look_at_ball_neck_only(state, command_builder, body_dir_change)
        state.action_history.ball_focus_actions += 1


def _append_wide_neck_orientation(state, command_builder, body_dir_change=0):
    fov = FOV_WIDE
    command_builder.append_fov_change(state, fov)
    if state.action_history.turn_in_progress and state.action_history.expected_body_angle is not None:
        current_body_angle = state.action_history.expected_body_angle + body_dir_change
    else:
        current_body_angle = state.body_angle.get_value() + body_dir_change

    target_angle = state.action_history.turn_history.least_updated_angle(fov, (current_body_angle - 80) % 360
                                                                            , (current_body_angle + 80) % 360)
    target_neck_angle = smallest_angle_difference(from_angle=current_body_angle, to_angle=target_angle)
    turn_angle = target_neck_angle - state.body_state.neck_angle
    state.action_history.turn_history.renew_angle(target_angle, fov)

    command_builder.append_neck_turn(state, turn_angle, fov)


@require_angle_update
def idle_orientation(state: PlayerState):
    command_builder = CommandBuilder()
    if not state.world_view.ball.is_value_known(state.action_history.three_see_updates_ago):
        return blind_orient(state)

    # Perform an orientation with boundaries of neck movement
    if state.action_history.ball_focus_actions > _IDLE_ORIENTATION_INTERVAL:
        _append_orient(state, False, command_builder)
        state.action_history.ball_focus_actions = 0
    else:
        append_look_at_ball(state, command_builder)
        state.action_history.ball_focus_actions += 1

    return command_builder.command_list


def _append_orient(state, neck_movement_only, command_builder: CommandBuilder, body_dir_change=0, fov=None):
    if state.is_test_player():
        debug_msg(str(state.now()) + " _append_orient", "ORIENTATION")

    if fov is None:
        fov_size = _determine_fov(state)
        command_builder.append_fov_change(state, fov_size)
    else:
        fov_size = fov
        command_builder.append_fov_change(state, fov)

    body_angle = state.body_angle.get_value() + body_dir_change
    turn_history = state.action_history.turn_history

    if neck_movement_only:  # Limit movement to within neck range
        lower_bound = (body_angle - 90) % 360
        upper_bound = (body_angle + 90) % 360
    else:  # Allow any turn movement (both body and neck)
        lower_bound = 0
        upper_bound = 360

    angle = turn_history.least_updated_angle(fov_size, lower_bound, upper_bound)
    _append_look_direction(state, angle, fov_size, command_builder)
    state.action_history.ball_focus_actions = 0


def append_look_at_ball(state: PlayerState, command_builder):
    ball_position = state.world_view.ball.get_value().coord
    ball_angle = math.degrees(calculate_full_origin_angle_radians(ball_position, state.position.get_value()))
    angle_difference = abs((state.body_angle.get_value() + state.body_state.neck_angle) - ball_angle)
    if angle_difference > 0.9:
        fov = _determine_fov(state)
        command_builder.append_fov_change(state, fov)
        _append_look_direction(state, ball_angle, fov, command_builder)


def append_look_at_ball_body_only(state: PlayerState, command_builder):
    ball_position = state.world_view.ball.get_value().coord
    ball_angle = math.degrees(calculate_full_origin_angle_radians(ball_position, state.position.get_value()))
    angle_difference = abs((state.body_angle.get_value()) - ball_angle)
    if angle_difference > 0.1:
        _append_orient(state, False, command_builder, angle_difference)


def append_look_at_ball_neck_only(state: PlayerState, command_builder, body_dir_change=0):
    # Look towards ball as far as possible
    ball = state.world_view.ball.get_value()
    ball_projection = state.world_view.ball.get_value().project_ball_position(1,
                                                                              state.now() - state.world_view.ball.last_updated_time)
    if ball_projection is None:
        ball_position = ball.coord
    else:
        ball_position = ball_projection[0]

    append_look_towards_neck_only(state, ball_position, command_builder, body_dir_change)


def append_look_towards_neck_only(state: PlayerState, coord, command_builder, body_dir_change=0):
    # Look towards ball as far as possible
    body_angle = (state.body_angle.get_value() + body_dir_change) % 360

    global_target_angle = math.degrees(calculate_full_origin_angle_radians(coord, state.position.get_value()))
    angle_difference = smallest_angle_difference((body_angle + state.body_state.neck_angle) % 360, global_target_angle)

    if abs(angle_difference) > 0.9:
        target_neck_angle = smallest_angle_difference(from_angle=body_angle, to_angle=global_target_angle)
        # Adjust to be within range of neck turn
        target_neck_angle = clamp(target_neck_angle, lower_bound=-90, upper_bound=90)
        new_total_angle = (body_angle + target_neck_angle) % 360

        # Calculate which fov to use based on what is required to see the ball
        preferred_fov = _determine_fov(state)
        required_view_angle = abs(smallest_angle_difference(new_total_angle, global_target_angle) * 2.1)
        minimum_fov = FOV_NARROW
        if required_view_angle >= FOV_NARROW:
            minimum_fov = FOV_NORMAL
        if required_view_angle >= FOV_NORMAL:
            minimum_fov = FOV_WIDE

        fov = max(minimum_fov, preferred_fov)
        command_builder.append_fov_change(state, fov)
        if state.is_test_player():
            debug_msg("global ball:" + str(global_target_angle) + "global neck:" + str(
                    new_total_angle) + "required fov: " + str(minimum_fov) +
                      "view angle: " + str(required_view_angle), "POSITIONAL")

        neck_turn_angle = smallest_angle_difference(from_angle=state.body_state.neck_angle, to_angle=target_neck_angle)
        if state.body_state.neck_angle + neck_turn_angle > 90 or state.body_state.neck_angle + neck_turn_angle < -90:
            # The smallest angle difference between 90 and -90 has two solutions: 180 and -180
            # If the wrong one is chosen, then switch sign
            neck_turn_angle *= -1

        command_builder.append_neck_turn(state, neck_turn_angle, state.body_state.fov)
        if state.is_test_player():
            debug_msg(str(state.now()) + " _look_at_ball_neck_only. New body angle=" + str(body_angle)
                      + " | Current neck angle : " + str(state.body_state.neck_angle)
                      + " | target neck angle : " + str(target_neck_angle)
                      + " | Global ball angle : " + str(global_target_angle)
                      + " | Ball position : " + str(coord)
                      + " | Player position : " + str(state.position.get_value()),
                      "ORIENTATION")


def shoot_to(state: PlayerState, target: Coordinate, power=None):
    command_builder = CommandBuilder()
    distance_to_target = target.euclidean_distance_from(state.position.get_value())
    direction = _calculate_relative_angle(state, target)
    if power is None:
        power = _calculate_kick_power(state, distance_to_target)
    command_builder.append_kick(state, power, direction)
    return command_builder.command_list


def pass_to_player(state, player: ObservedPlayer):
    target: Coordinate = player.coord
    command_builder = CommandBuilder()
    distance_to_target = target.euclidean_distance_from(state.position.get_value())
    direction = _calculate_relative_angle(state, target)
    power = _calculate_kick_power(state, distance_to_target)
    command_builder.append_kick(state, power, direction)
    return command_builder.command_list


def positional_adjustment(state, adjustment: Coordinate):
    command_builder = CommandBuilder()

    max_power = state.body_state.jog_dash_power
    distance = Coordinate(0, 0).euclidean_distance_from(adjustment)

    target_body_angle = math.degrees(calculate_full_origin_angle_radians(adjustment, Coordinate(0, 0)))
    turn_angle = smallest_angle_difference(from_angle=state.body_angle.get_value(), to_angle=target_body_angle)

    if abs(turn_angle) >= _allowed_angle_delta(distance):
        turn_moment = _calculate_turn_moment(state.body_state.speed, turn_angle)
        command_builder.append_turn_action(state, _calculate_turn_moment(state.body_state.speed, turn_angle))
        _append_neck_orientation(state, command_builder,
                                 _calculate_actual_turn_angle(state.body_state.speed, turn_moment))
        command_builder.next_tick(_calculate_actual_turn_angle(state.body_state.speed, turn_moment))
    else:
        _append_neck_orientation(state, command_builder)

    append_last_dash_actions(state, state.body_state.speed, distance, command_builder, False, max_power)

    return command_builder.command_list


def find_dribble_direction(state, optimal_dir):
    target_dir = smallest_angle_difference(from_angle=state.body_angle.get_value(), to_angle=optimal_dir)
    return target_dir


def dribble(state: PlayerState, optimal_dir: int, dribble_kick_power=None):
    command_builder = CommandBuilder()
    dribble_dir = find_dribble_direction(state, optimal_dir)
    if dribble_kick_power is not None:
        command_builder.append_kick(state, dribble_kick_power, dribble_dir)
    else:
        command_builder.append_kick(state, state.body_state.dribble_kick_power, dribble_dir)
    command_builder.next_tick()
    command_builder.append_turn_action(state, _calculate_turn_moment(state.body_state.speed, dribble_dir))
    command_builder.next_tick()
    command_builder.append_dash_action(state, state.body_state.dribble_dash_power, urgent=True)

    return command_builder.command_list


@require_angle_update
def look_for_pass_target(state: PlayerState):
    state.action_history.last_look_for_pass_targets = state.world_view.sim_time
    command_builder = CommandBuilder()
    # Perform an orientation with boundaries of neck movement
    _append_orient(state, neck_movement_only=False, command_builder=command_builder, fov=FOV_NORMAL)
    state.action_history.ball_focus_actions = 0
    return command_builder.command_list


def _determine_fov(state: PlayerState):
    if state.world_view.ball.is_value_known(state.now() - 6) and state.position.is_value_known(state.now() - 6):
        dist_to_ball = state.world_view.ball.get_value().coord.euclidean_distance_from(state.position.get_value())

        if dist_to_ball < 25:
            return FOV_NARROW
        elif dist_to_ball < 35:
            return FOV_NORMAL
        else:
            return FOV_WIDE

    return FOV_WIDE


def _calculate_relative_angle(state, target_position):
    rotation = calculate_full_origin_angle_radians(target_position, state.position.get_value())
    rotation = math.degrees(rotation)

    if state.action_history.turn_in_progress and state.action_history.expected_body_angle is not None:
        rotation -= state.action_history.expected_body_angle
    else:
        rotation -= state.body_angle.get_value()

    # Pick the short way around (<180 degrees)
    if rotation > 180:
        rotation -= 360
    elif rotation < -180:
        rotation += 360

    return rotation


def _calculate_stop_kick_power(player_pos, ball_pos, player_rotation, ball_velocity: Vector2D):
    dist_ball = (ball_pos - player_pos).magnitude()
    dir_diff = abs(player_rotation - (ball_pos - player_pos).world_direction())
    start_velocity = ball_velocity.magnitude() * 0.6
    power = start_velocity / (KICK_POWER_RATE * (1 - 0.25 * (dir_diff / 180) - 0.25 * (dist_ball / KICKABLE_MARGIN)))
    return min(power, 100)


def _calculate_kick_power(state: PlayerState, distance: float) -> int:
    ball: Ball = state.world_view.ball.get_value()

    current_vel = 0
    if ball.absolute_velocity is not None:
        current_vel = ball.absolute_velocity.magnitude()

    dir_diff = abs(ball.direction)
    dist_ball = ball.distance
    target_delivery_velocity = 0.5  # The velocity of the ball after traveling the given distance

    time_to_travel_distance = 50 * math.log(
        (3 * distance + 50 * target_delivery_velocity) / (50 * target_delivery_velocity)) / 3
    start_velocity = target_delivery_velocity / math.exp(-0.06 * time_to_travel_distance)

    power = (start_velocity - current_vel) / (KICK_POWER_RATE * (1 - 0.25 * (dir_diff / 180) - 0.25 * (dist_ball / KICKABLE_MARGIN)))
    return min(power, 100)


def _calculate_turn_moment(projected_speed, target_angle):
    return target_angle * (1 + 5 * projected_speed)


def _calculate_actual_turn_angle(projected_speed, moment):
    return moment / (1 + 5 * projected_speed)


def _calculate_dash_power(current_speed, target_speed):
    delta = target_speed - current_speed
    power = delta / DASH_POWER_RATE
    power = clamp(power, -100, 100)
    projected_speed = current_speed + power * DASH_POWER_RATE
    return power, projected_speed


def _calculate_actual_speed(current_speed, dash_power):
    return current_speed + dash_power * DASH_POWER_RATE


def _allowed_angle_delta(distance, max_distance_deviation=0.5):
    if distance > 5:
        return 5
    else:
        return math.degrees(math.acos(distance / math.sqrt(pow(max_distance_deviation, 2) + pow(distance, 2))))

    """if distance < 0.1:
        return 90
    return math.degrees(math.acos(distance / math.sqrt(pow(max_distance_deviation, 2) + pow(distance, 2))))"""

