# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import socket
import threading


class MobilePeerState(enum.Enum):
    CONNECTED = enum.auto()
    CALLING = enum.auto()
    WAITING = enum.auto()
    LINKED = enum.auto()


class MobilePeer:
    _pair: "MobilePeer | None"
    _user: dict
    _state: MobilePeerState
    sock: socket.socket | None

    def __init__(self, user: dict):
        self._user = user
        self._pair = None
        self._state = MobilePeerState.CONNECTED
        self.sock = None

    def get_number(self) -> str:
        return self._user["number"]

    def get_token(self) -> str:
        return self._user["token"]

    def set_pair(self, pair: "MobilePeer | None") -> None:
        self._pair = pair

    def get_pair_socket(self) -> socket.socket:
        return self._pair.sock

    def get_pair_number(self) -> str:
        return self._pair.get_number()

    def call(self, pair: "MobilePeer | None") -> socket.socket | int:
        if self._state != MobilePeerState.CONNECTED:
            return 0

        # Make sure the pair is valid
        if pair is None:
            return 0
        if pair._state != MobilePeerState.WAITING:
            return 1

        # Update states
        self.set_pair(pair)
        self._state = MobilePeerState.LINKED
        pair.set_pair(self)
        # TODO: Wait for pair to indicate readiness through pair._state
        return self.get_pair_socket()

    def wait(self) -> socket.socket | int:
        # If we've received the call, we're linked
        if self._pair is not None:
            self._state = MobilePeerState.LINKED
        if self._state == MobilePeerState.LINKED:
            return self.get_pair_socket()

        # Invalid states
        if self._state not in (
                MobilePeerState.CONNECTED, MobilePeerState.WAITING):
            return 1

        self._state = MobilePeerState.WAITING
        return 0

    def wait_stop(self):
        if self._state == MobilePeerState.WAITING:
            self._state = MobilePeerState.CONNECTED


class MobilePeers:
    def __init__(self, users):
        self.users = users
        self.connected = {}
        self.connected_lock = threading.Lock()

    def connect(self, token: str = "") -> MobilePeer | None:
        user = None
        if token:
            user = self.users.user_lookup_token(token)
            if user is None:
                return None

        # Lock includes user creation to avoid having a different thread log
        #  into a recently created user.
        with self.connected_lock:
            if user is None:
                user = self.users.user_new()
                if user is None:
                    return None

            if user["number"] in self.connected:
                return None

            peer = MobilePeer(user)
            self.connected[peer.get_number()] = peer
        return peer

    def disconnect(self, user: MobilePeer) -> None:
        del self.connected[user.get_number()]

    def dial(self, number: str) -> MobilePeer | None:
        return self.connected.get(number)
