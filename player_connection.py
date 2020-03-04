import socket
import re
import threading
import time
from queue import Queue

import player_state


class PlayerConnection(threading.Thread):
    BUFFER_SIZE = 1024

    # default constructor
    def __init__(self, port, ip, player_state: player_state.PlayerState):
        super().__init__()
        self.player_state = player_state
        self.port = port
        self.server_ip = ip
        self.client_socket = ""
        self.action_queue: Queue = Queue()

    def connect_to_server(self):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.__send_message("(init " + self.player_state.team_name + ")")

        player_info = self.__receive_message()  # buffer size is 1024 bytes
        regex = re.compile("\\(init ([lr]) ([0-9]*)")
        match = regex.match(player_info.__str__())
        self.player_state.side = match.group(1)
        self.player_state.player_num = match.group(2)

        # Move to a position
        self.__send_message("(move -" + self.player_state.player_num + "0 -" + self.player_state.player_num + "0)")

        while True:
            data = self.__receive_message()  # buffer size is 1024 bytes
            self.__update_state(data)
            while not self.action_queue.empty():
                self.__send_message(self.action_queue.get())

    def __send_message(self, msg: str):
        bytes_to_send = str.encode(msg)
        self.client_socket.sendto(bytes_to_send, (self.server_ip, self.port))

    def __receive_message(self):
        player_info = self.client_socket.recv(self.BUFFER_SIZE).decode()
        return player_info  # Temporary, should be done through player_state

    def __update_state(self, msg: str):
        # TODO Update player state
        return

    def request_action(self, action_list: [str]):
        for elem in action_list:
            self.action_queue.put(elem)
