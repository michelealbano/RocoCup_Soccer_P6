import math
import re
import threading
import queue

from configurations import GOALIE_MODEL_TEAMS
from player import player
import client_connection
from player.player import PlayerState
import time
import parsing
from player.playerstrategy import determine_objective
from player.startup_positions import goalie_pos, defenders_pos, midfielders_pos, strikers_pos
from player.world_objects import Coordinate
from statisticsmodule import statistics
from uppaal import strategy, goalie_strategy
from utils import debug_msg


class Thinker(threading.Thread):

    def __init__(self, team_name: str, player_type: str):
        super().__init__()
        self._stop_event = threading.Event()
        self.player_state: PlayerState = player.PlayerState()
        self.player_state.team_name = team_name
        self.player_state.player_type = player_type

        # Connection with the server
        self.player_conn: client_connection.Connection = None

        # Messages from the server that has not yet been processed
        self.input_queue = queue.Queue()
        self.is_positioned = False

    def start(self) -> None:
        # Send init messages to the server
        super().start()
        if self.player_state.player_type == "goalie":
            init_string = "(init " + self.player_state.team_name + "(goalie)" + "(version 16))"
        else:
            init_string = "(init " + self.player_state.team_name + " (version 16))"

        self.player_conn.action_queue.put(init_string)
        init_msg: str = self.input_queue.get()
        parsing.parse_message_update_state(init_msg, self.player_state)
        self.player_conn.action_queue.put("(synch_see)")
        self.position_player()

    def run(self) -> None:
        super().run()
        # Wait for client connection thread to receive the correct new port
        time.sleep(1.5)
        # Set accepted coach language versions
        self.player_conn.action_queue.put("(clang (ver 8 8))")

        if self.player_state.player_type == "goalie" and self.player_state.team_name in GOALIE_MODEL_TEAMS:
            self.player_state.goalie_position_dict = goalie_strategy.get_result_dict()

        self.think()

    def stop(self) -> None:
        self._stop_event.set()

    def think(self):
        self.player_state.current_objective = determine_objective(self.player_state)
        time_since_action = 0
        last_time = time.time()

        # Enter loop until player client is terminated
        while not self._stop_event.is_set():
            while not self.input_queue.empty():
                # Parse message and update player state / world view
                msg: str = self.input_queue.get()
                if msg.startswith("(sense_body"):
                    can_send = True
                parsing.parse_message_update_state(msg, self.player_state)

                # Move player back to starting positions after goal.
                if self.player_state.should_reset_to_start_position:
                    self.move_back_to_start_pos()

            # Check if some strategy has been provided by UPPAAL
            if len(self.player_state.strategy_result_list) > 0:
                parsing.parse_strat_player(self.player_state)
                self.player_state.statistics.register_finished_strategy_generation()

            # Evaluate the current state of the game to see if any of the strategy models can be used:
            if not self.player_state.is_generating_strategy and strategy.has_applicable_strat_player(self.player_state):
                self.player_state.is_generating_strategy = True
                threading.Thread(target=generate_strategy, args=(self.player_state, )).start()

            # Ensure that server action messages are sent at a fixed interval of 100ms
            current_time = time.time()
            time_since_action += current_time - last_time
            last_time = current_time
            if time_since_action >= 0.1:
                # Gathering statistics about the amount of ticks spent generating a strategy
                if self.player_state.is_generating_strategy:
                    self.player_state.statistics.register_missed_tick()
                if self.player_state.now() == 5900:
                    statistics.print_to_file(self.player_state.statistics.missed_ticks_text(),
                                             "missed_ticks_" + str(self.player_state.num)
                                             + str(self.player_state.world_view.side))
                    
                time_since_action -= 0.1
                time_since_action %= 0.08  # discard queued updates if more than 80 ms behind
                self.perform_action()

            time.sleep(0.05)

    # Called every 100ms
    def perform_action(self):
        if self.player_state.current_objective.should_recalculate(self.player_state):
            self.player_state.current_objective = determine_objective(self.player_state)

        if self.player_state.is_test_player():  # Debugging
            debug_msg(str(self.player_state.now()) + " Mode : " + str(self.player_state.mode), "MODE")

        commands = self.player_state.current_objective.get_next_commands(self.player_state)

        if self.player_state.is_test_player():  # Debugging
            debug_msg(str(self.player_state.now()) + " Sending commands : " + str(commands), "SENT_COMMANDS")
            debug_msg(str(self.player_state.now()) + "Position : {0} | Speed : {1} | BodyDir : {2} | NeckDir : {3} | "
                                                     "TurnInProgress : {4}".format(
                self.player_state.position.get_value(), self.player_state.body_state.speed,
                self.player_state.body_angle.get_value(), self.player_state.body_state.neck_angle,
                self.player_state.action_history.turn_in_progress), "STATUS")

        if self.player_state.is_test_player():  # Debugging
            debug_msg("{0} Commands: {1}".format(self.player_state.world_view.sim_time, commands), "MESSAGES")

        for command in commands:
            if command is not None:
                self.player_conn.action_queue.put(command)

    def move_back_to_start_pos(self):
        move_action = "(move {0} {1})".format(self.player_state.starting_position.pos_x
                                              , self.player_state.starting_position.pos_y)
        self.player_conn.action_queue.put(move_action)
        self.player_state.should_reset_to_start_position = False

    def position_player(self):
        if (len(goalie_pos) + len(defenders_pos) + len(midfielders_pos) + len(strikers_pos)) > 11:
            raise Exception("Too many startup positions given. Expected < 12, got: " + str(len(goalie_pos)
                                                                                           + len(defenders_pos)
                                                                                           + len(midfielders_pos)
                                                                                           + len(strikers_pos)))

        self.assign_position()
        if self.player_state.player_type == "goalie":
            if len(goalie_pos) > 1:
                raise Exception("Only 1 goalie / goalie position allowed")
            pos = goalie_pos[0]
            move_action = "(move {0} {1})".format(pos[0], pos[1])
            self.player_state.playing_position = Coordinate(pos[0], pos[1])
        elif self.player_state.player_type == "defender":
            index = self.player_state.num - 1 - len(goalie_pos)
            pos = defenders_pos[index]
            self.player_state.playing_position = Coordinate(pos[0], pos[1])
            move_action = "(move {0} {1})".format(pos[0], pos[1])
        elif self.player_state.player_type == "midfield":
            index = self.player_state.num - 1 - len(goalie_pos) - len(defenders_pos)
            pos = midfielders_pos[index]
            self.player_state.playing_position = Coordinate(pos[0] + 10, pos[1])
            move_action = "(move {0} {1})".format(pos[0], pos[1])
        elif self.player_state.player_type == "striker":
            index = self.player_state.num - 1 - len(goalie_pos) - len(defenders_pos) - len(midfielders_pos)
            pos = strikers_pos[index]
            self.player_state.playing_position = Coordinate(pos[0] + 10, pos[1])
            move_action = "(move {0} {1})".format(pos[0], pos[1])
        else:
            raise Exception("Could not position player: " + str(self.player_state))
        self.player_state.starting_position = Coordinate(pos[0], pos[1])
        self.player_state.objective_behaviour = pos[2]
        self.player_conn.action_queue.put(move_action)
        self.is_positioned = True

    def assign_position(self):
        if self.player_state.num == 1:
            if self.player_state.player_type != "goalie":
                raise Exception("Goalie is not player num 1")
            else:
                return
        if 1 < self.player_state.num <= 1 + len(defenders_pos):
            self.player_state.player_type = "defender"
        elif 1 + len(defenders_pos) < self.player_state.num <= 1 + len(defenders_pos) + len(midfielders_pos):
            self.player_state.player_type = "midfield"
        elif 1 + len(defenders_pos) + len(midfielders_pos) < self.player_state.num <= 1 + len(defenders_pos) \
                + len(midfielders_pos) + len(strikers_pos):
            self.player_state.player_type = "striker"
        else:
            raise Exception("Could not assign position. Unum unknown. Expected unum between 1-11, got: "
                            + str(self.player_state.num) + " for player " + str(self.player_state))


def generate_strategy(state: PlayerState):
    result = strategy.generate_strategy_player(state)
    state.strategy_result_list.append(result)
    state.is_generating_strategy = False
