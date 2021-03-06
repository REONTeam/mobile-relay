# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import socket

class MobilePeerState(enum.Enum):
    CONNECTED = enum.auto()
    CALLING = enum.auto()
    WAITING = enum.auto()
    LINKED = enum.auto()

class MobilePeers():
    def __init__(self, users):
        self.users = users
        self.connected = {}

    def connect(self, token: str):
        if token is None:
            user = self.users.user_new()
        else:
            user = self.users.user_lookup_token(token)
            if user is None:
                return None
        if user["number"] in self.connected:
            return None
        self.connected[user["number"]] = {
            "user": user,
            "state": MobilePeerState.CONNECTED,
            "peer": None,
            "socket": None,
        }
        return user

    def disconnect(self, user: dict):
        del self.connected[user["number"]]

    def set_socket(self, user: dict, socket: socket.socket):
        me = self.connected[user["number"]]
        me["socket"] = socket

    def get_socket(self, number: str):
        peer = self.connected[number]
        if peer["state"] != MobilePeerState.LINKED:
            return None
        return peer["socket"]

    def call(self, user: dict, number: str):
        me = self.connected[user["number"]]
        if me["state"] != MobilePeerState.CONNECTED:
            return 0
        peer = self.connected.get(number)
        if peer is None:
            return 0
        if peer["state"] != MobilePeerState.WAITING:
            return 1
        me["state"] = MobilePeerState.LINKED
        me["peer"] = peer["user"]["number"]
        peer["state"] = MobilePeerState.LINKED
        peer["peer"] = me["user"]["number"]
        return me["peer"]

    def wait(self, user: dict):
        me = self.connected[user["number"]]
        if me["state"] == MobilePeerState.LINKED:
            return me["peer"]
        if me["state"] not in (
                MobilePeerState.CONNECTED, MobilePeerState.WAITING):
            return None
        me["state"] = MobilePeerState.WAITING
        return False
