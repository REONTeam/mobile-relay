#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import json
import socketserver
import time

import users
import peers

PROTOCOL_VERSION = 0
handshake_magic = bytes([PROTOCOL_VERSION]) + b"MOBILE"

class MobileRelayCommand(enum.IntEnum):
    CALL = 0
    WAIT = enum.auto()
    GET_NUMBER = enum.auto()

class MobileRelayCallResult(enum.IntEnum):
    ACCEPTED = 0
    UNAVAILABLE = enum.auto()
    BUSY = enum.auto()

class MobileRelay(socketserver.BaseRequestHandler):
    def setup(self):
        self.users = g_users
        self.peers = g_peers
        self.user = None
        self.user_new = False

    def finish(self):
        self.log("Disconnected")
        if self.user:
            self.peers.disconnect(self.user)
        self.users.save()

    def log(self, *args):
        print(self.client_address, *args)

    def recv_handshake(self):
        handshake = self.request.recv(len(handshake_magic))
        if handshake != handshake_magic:
            return False

        has_token = self.request.recv(1)[0]
        self.user_new = False
        if has_token == 0:
            user = self.peers.connect(None)
            self.user_new = True
        elif has_token == 1:
            token = self.request.recv(16).hex()
            user = self.peers.connect(token)
        else:
            return False
        if user is None:
            return False

        self.user = user
        return True

    def send_handshake(self):
        buffer = bytearray(handshake_magic)
        buffer.append(self.user_new)
        if self.user_new:
            buffer += bytes.fromhex(self.user["token"])
        self.request.send(buffer)

    def recv_call(self):
        number_len = self.request.recv(1)[0]
        number = self.request.recv(number_len).decode()
        return number

    def send_call(self, result: MobileRelayCallResult):
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.CALL])
        buffer.append(result)
        self.request.send(buffer)

    def handle_call(self):
        number = self.recv_call()
        self.log("Command: CALL %s" % number)
        peer = self.peers.call(self.user, number)
        if isinstance(peer, int):
            if peer == 0:
                self.send_call(MobileRelayCallResult.UNAVAILABLE)
            if peer == 1:
                self.send_call(MobileRelayCallResult.BUSY)
            return None
        self.send_call(MobileRelayCallResult.ACCEPTED)
        return peer

    def send_wait(self, number: str):
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.WAIT])
        buffer.append(len(number))
        buffer += number.encode()
        self.request.send(buffer)

    def handle_wait(self):
        self.log("Command: WAIT")
        while True:
            # TODO: Detect client disconnect
            peer = self.peers.wait(self.user)
            if peer is None:
                return None
            if peer != False:
                break
            time.sleep(0.5)
        self.send_wait(peer)
        return peer

    def send_get_number(self):
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.GET_NUMBER])
        buffer.append(len(self.user["number"]))
        buffer.append(self.user["number"].encode())
        self.request.send(buffer)

    def handle_get_number(self):
        self.log("Command: GET_NUMBER")
        self.send_get_number()

    def handle_relay(self, number: str):
        self.log("Starting relay")
        peer = self.peers.get_socket(number)
        try:
            while True:
                data = self.request.recv(1024)
                if not data:
                    break
                peer.send(data)
        except ConnectionResetError:
            pass

    def handle(self):
        self.log("Connected")

        if not self.recv_handshake():
            self.log("QUIT: Login failed")
            return
        self.send_handshake()
        self.log("Logged in as %s" % self.user["number"],
            "(new user)" if self.user_new else "")

        self.peers.set_socket(self.user, self.request)

        peer = None
        while peer is None:
            version = self.request.recv(1)[0]
            if version != PROTOCOL_VERSION:
                self.log("QUIT: Invalid command")
                return
            command = self.request.recv(1)[0]
            if command == MobileRelayCommand.CALL:
                peer = self.handle_call()
            elif command == MobileRelayCommand.WAIT:
                peer = self.handle_wait()
            elif command == MobileRelayCommand.GET_NUMBER:
                self.handle_get_number()
            else:
                self.log("QUIT: Invalid command")
                break

        return self.handle_relay(peer)

class MobileRelayServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

if __name__ == "__main__":
    HOST, PORT = "localhost", 1027
    g_users = users.MobileUserDatabase("users.json")
    g_peers = peers.MobilePeers(g_users)
    with MobileRelayServer((HOST, PORT), MobileRelay) as server:
        server.serve_forever()
    g_users.save()
