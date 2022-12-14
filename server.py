#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import select
import socketserver
import socket

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
    user_new: bool
    user: peers.MobilePeer | None
    users: users.MobileUserDatabase
    peers: peers.MobilePeers

    def setup(self):
        self.users = g_users
        self.peers = g_peers
        self.user = None
        self.user_new = False

    def finish(self):
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
            user = self.peers.connect()
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
            buffer += bytes.fromhex(self.user.get_token())
        self.request.send(buffer)

    def recv_call(self):
        number_len = self.request.recv(1)[0]
        number = self.request.recv(number_len).decode()
        return number

    def send_call(self, result: MobileRelayCallResult):
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.CALL])
        buffer.append(result)
        self.request.send(buffer)

    def handle_call(self) -> socket.socket | None:
        number = self.recv_call()
        self.log("Command: CALL %s" % number)
        peer = self.user.call(self.peers.dial(number))
        if isinstance(peer, int):
            if peer == 0:
                self.send_call(MobileRelayCallResult.UNAVAILABLE)
            if peer == 1:
                self.send_call(MobileRelayCallResult.BUSY)
            return None
        self.send_call(MobileRelayCallResult.ACCEPTED)
        return peer

    def send_wait(self, number: str) -> None:
        number = number.encode()
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.WAIT])
        buffer.append(len(number))
        buffer += number
        self.request.send(buffer)

    def handle_wait(self):
        self.log("Command: WAIT")
        poller = select.poll()
        poller.register(self.request, select.POLLIN | select.POLLPRI)
        while True:
            peer = self.user.wait()
            if peer is None:
                return None
            if peer != 0:
                break

            # Break out if any data or error is available in the socket
            if poller.poll(100):
                self.user.wait_stop()
                return None
        self.send_wait(self.user.get_pair_number())
        return peer

    def send_get_number(self):
        number = self.user.get_number().encode()
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.GET_NUMBER])
        buffer.append(len(number))
        buffer += number
        self.request.send(buffer)

    def handle_get_number(self):
        self.log("Command: GET_NUMBER")
        self.send_get_number()

    def handle_relay(self, pair: socket.socket):
        self.log("Starting relay")
        # TODO: Fork out a process, close sockets in parent
        #       This helps avoid the GIL and would reduce issues
        #        with many simultaneous clients (assuming no directed abuse).
        poller = select.poll()
        poller.register(self.request, select.POLLIN | select.POLLPRI)
        poller.register(pair, select.POLLRDHUP)
        try:
            run = True
            while run:
                events = poller.poll()

                for fd, event in events:
                    if fd == self.request.fileno():
                        data = self.request.recv(1024)
                        if not data:
                            run = False
                            break
                        pair.send(data)
                    elif fd == pair.fileno() and event & select.POLLRDHUP:
                        run = False
                        break
        except ConnectionResetError:
            pass
        self.log("QUIT: Disconnect")

    def handle(self):
        self.log("Connected")

        if not self.recv_handshake():
            self.log("QUIT: Login failed")
            return
        self.send_handshake()
        self.log("Logged in as %s" % self.user.get_number(),
                 "(new user)" if self.user_new else "")

        self.user.sock = self.request

        while True:
            data = self.request.recv(2)
            if len(data) < 2:
                self.log("QUIT: Disconnect")
                return

            version, command = data
            if version != PROTOCOL_VERSION:
                self.log("QUIT: Invalid command")
                return

            if command == MobileRelayCommand.CALL:
                pair = self.handle_call()
                if pair is not None:
                    return self.handle_relay(pair)
            elif command == MobileRelayCommand.WAIT:
                pair = self.handle_wait()
                if pair is not None:
                    return self.handle_relay(pair)
            elif command == MobileRelayCommand.GET_NUMBER:
                self.handle_get_number()
            else:
                self.log("QUIT: Invalid command")
                return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    HOST, PORT = "localhost", 1027
    g_users = users.MobileUserDatabase("users.json")
    g_peers = peers.MobilePeers(g_users)
    with Server((HOST, PORT), MobileRelay) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
    g_users.save()
