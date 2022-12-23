# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import socket
import threading
import select
import os

import users


class MobilePeerState(enum.Enum):
    CONNECTED = enum.auto()
    CALLING = enum.auto()
    WAITING = enum.auto()
    LINKING = enum.auto()
    LINKED = enum.auto()


class MobilePeer:
    _pair: "MobilePeer | None"
    _user: users.MobileUser
    _state: MobilePeerState
    _lock: threading.Lock
    sock: socket.socket | None

    def __init__(self, user: users.MobileUser):
        self._user = user
        self._pair = None
        self._state = MobilePeerState.CONNECTED
        self._lock = threading.Lock()
        self.rpipe, self.wpipe = os.pipe()
        self.sock = None

    def _pipe_recv(self, delay: int = 0) -> bytes:
        # Check if any data is available at all
        p = select.poll()
        p.register(self.rpipe, select.POLLIN)
        if not p.poll(delay):
            return b''

        # Read the data
        return os.read(self.rpipe, 1)

    def _pipe_send(self, value: int) -> None:
        os.write(self._pair.wpipe, bytes([value]))

    def get_number(self) -> str:
        return self._user.number

    def get_token(self) -> bytes:
        return self._user.token

    def set_pair(self, pair: "MobilePeer | None") -> None:
        self._pair = pair

    def get_pair_socket(self) -> socket.socket:
        return self._pair.sock

    def get_pair_number(self) -> str:
        return self._pair.get_number()

    def call(self, pair: "MobilePeer | None") -> int:
        # We've already connected, move along
        if self._pair is not None:
            return 1
        if self._state != MobilePeerState.CONNECTED:
            return 3  # internal

        # Make sure the pair is valid
        if pair is None:
            return 0

        # Lock to make sure no two threads can call the same number at once
        with pair._lock:
            if pair._state == MobilePeerState.CONNECTED:
                return 0
            if pair._state != MobilePeerState.WAITING:
                return 2  # busy
            if pair._pair is not None:
                return 2  # busy

            # Update states
            # Once past this barrier, the only way to back away is disconnecting
            self.set_pair(pair)
            pair.set_pair(self)
            self._pipe_send(MobilePeerState.WAITING.value)
            return 1

    def call_ready(self) -> None:
        # Signal readiness to start relaying
        if self._state == MobilePeerState.CONNECTED:
            self._state = MobilePeerState.LINKING
            self._pipe_send(MobilePeerState.LINKING.value)

    def wait(self, delay: int = 0) -> int:
        # If we've received the call, move on
        if self._pair is not None:
            b = self._pipe_recv(delay)
            if b:
                if b[0] == MobilePeerState.WAITING.value:
                    return 1

        if self._state == MobilePeerState.CONNECTED:
            self._state = MobilePeerState.WAITING
        if self._state != MobilePeerState.WAITING:
            return 2
        return 0

    def wait_ready(self) -> None:
        # Signal readiness to start relaying
        if self._state == MobilePeerState.WAITING:
            self._state = MobilePeerState.LINKING
            self._pipe_send(MobilePeerState.LINKING.value)

    def wait_stop(self) -> bool:
        # Lock to make sure call() isn't about to read and modify our state
        with self._lock:
            if self._pair is not None:
                return False
            if self._state == MobilePeerState.CONNECTED:
                return True
            if self._state == MobilePeerState.WAITING:
                self._state = MobilePeerState.CONNECTED
                return True
            return False

    def accept(self, delay: int = 0) -> int:
        # If we've linked, check if the pair is ready
        # We must do this to avoid writing to the pair's socket before
        #  the command reply can be sent.
        if self._state == MobilePeerState.LINKED:
            return 1
        if self._state != MobilePeerState.LINKING:
            return 2

        b = self._pipe_recv(delay)
        if not b:
            return 0
        if b[0] != MobilePeerState.LINKING.value:
            return 2
        if self._pair._state not in (MobilePeerState.LINKING,
                                     MobilePeerState.LINKED):
            return 2
        self._state = MobilePeerState.LINKED
        return 1


class MobilePeers:
    _users: users.MobileUserDatabase
    _connected: dict
    _connected_lock: threading.Lock

    def __init__(self, users_db: users.MobileUserDatabase):
        self._users = users_db
        self._connected = {}
        self._connected_lock = threading.Lock()

    def connect(self, token: bytes = b"") -> MobilePeer | None:
        self._users.connect()

        user = None
        if token:
            user = self._users.lookup_token(token)
            if user is None:
                return None

        # Lock includes user creation to avoid having a different thread log
        #  into a recently created user.
        with self._connected_lock:
            if user is None:
                user = self._users.new()
                if user is None:
                    return None

            if user.number in self._connected:
                return None

            self._users.update(user)
            peer = MobilePeer(user)
            self._connected[peer.get_number()] = peer
        return peer

    def disconnect(self, user: MobilePeer) -> None:
        del self._connected[user.get_number()]

    def dial(self, number: str) -> MobilePeer | None:
        return self._connected.get(number)
