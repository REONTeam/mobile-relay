#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import enum
import time
import select
import socketserver

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
    INTERNAL = enum.auto()
    BUSY = enum.auto()
    UNAVAILABLE = enum.auto()


class MobileRelayWaitResult(enum.IntEnum):
    ACCEPTED = 0
    INTERNAL = enum.auto()


class MobileRelay(socketserver.BaseRequestHandler):
    user_new: bool
    user: peers.MobilePeer | None
    users: users.MobileUserDatabase
    peers: peers.MobilePeers

    def setup(self) -> None:
        self.users = g_users
        self.peers = g_peers
        self.user = None
        self.user_new = False

    def finish(self) -> None:
        if self.user:
            self.peers.disconnect(self.user)
        self.users.close()

    def log(self, *args) -> None:
        print(self.client_address, *args)

    def recv_handshake(self) -> bool:
        handshake = self.request.recv(len(handshake_magic))
        if handshake != handshake_magic:
            return False

        has_token, = self.request.recv(1)
        self.user_new = False
        if has_token == 0:
            user = self.peers.connect()
            self.user_new = True
        elif has_token == 1:
            token = self.request.recv(16)
            user = self.peers.connect(token)
        else:
            return False
        if user is None:
            return False

        self.user = user
        return True

    def send_handshake(self) -> None:
        buffer = bytearray(handshake_magic)
        buffer.append(self.user_new)
        if self.user_new:
            buffer += self.user.get_token()
        self.request.send(buffer)

    def recv_call(self) -> str | None:
        number_len, = self.request.recv(1)
        number = self.request.recv(number_len).decode()
        return number

    def send_call(self, result: MobileRelayCallResult) -> None:
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.CALL])
        buffer.append(result)
        self.request.send(buffer)

    def handle_call(self) -> bool:
        number = self.recv_call()
        self.log("Command: CALL %s" % number)

        poller = select.poll()
        poller.register(self.request, select.POLLIN | select.POLLPRI)

        # Find an available peer with the correct phone number
        user = None
        timer = time.time()
        while True:
            # Get peer attached to number
            if user is None:
                user = self.peers.dial(number)

            # Try to call the peer
            if user is not None:
                res = self.user.call(user)
                if res == 1:
                    break
                elif res == 2:
                    self.send_call(MobileRelayCallResult.BUSY)
                    return False
                elif res == 3:
                    self.send_call(MobileRelayCallResult.INTERNAL)
                    raise ConnectionResetError
                elif res != 0:
                    self.send_call(MobileRelayCallResult.INTERNAL)
                    raise ConnectionResetError

            # Time out after a while
            if (time.time() - timer) >= 30:
                if user is not None:
                    self.send_call(MobileRelayCallResult.BUSY)
                else:
                    self.send_call(MobileRelayCallResult.UNAVAILABLE)
                return False

            # If the client sends anything, we can still back out
            if poller.poll(100):
                return False
        self.send_call(MobileRelayCallResult.ACCEPTED)
        self.user.call_ready()
        return True

    def send_wait(self, result: MobileRelayWaitResult,
                  number: str = "") -> None:
        number = number.encode()
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.WAIT])
        buffer.append(result)
        buffer.append(len(number))
        buffer += number
        self.request.send(buffer)

    def handle_wait(self) -> bool:
        self.log("Command: WAIT")

        poller = select.poll()
        poller.register(self.request, select.POLLIN | select.POLLPRI)

        # Set self into waiting state, break out when called
        while True:
            res = self.user.wait()
            if res == 1:
                break
            elif res != 0:
                self.send_wait(MobileRelayWaitResult.INTERNAL)
                raise ConnectionResetError

            # Break out if any data or error is available in the socket
            if poller.poll(100):
                if self.user.wait_stop():
                    return False
                time.sleep(0.1)
        self.send_wait(MobileRelayWaitResult.ACCEPTED,
                       self.user.get_pair_number())
        self.user.wait_ready()
        return True

    def send_get_number(self) -> None:
        number = self.user.get_number().encode()
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.GET_NUMBER])
        buffer.append(len(number))
        buffer += number
        self.request.send(buffer)

    def handle_get_number(self) -> None:
        self.log("Command: GET_NUMBER")
        self.send_get_number()

    def handle_relay(self) -> None:
        # Wait until peer is ready to receive data
        timer = time.time()
        while True:
            res = self.user.accept()
            if res == 1:
                break
            if res != 0:
                raise ConnectionResetError
            if (time.time() - timer) >= 5:
                raise ConnectionResetError
            time.sleep(0.1)

        self.log("Starting relay")
        # TODO: Fork out a process, close sockets in parent
        #       This helps avoid the GIL and would reduce issues
        #        with many simultaneous clients (assuming no directed abuse).
        try:
            pair = self.user.get_pair_socket()
            poller = select.poll()
            poller.register(self.request, select.POLLIN | select.POLLPRI)
            poller.register(pair, select.POLLRDHUP)
            while True:
                events = poller.poll()

                for fd, event in events:
                    if fd == self.request.fileno():
                        data = self.request.recv(1024)
                        if not data:
                            return
                        pair.send(data)
                    elif fd == pair.fileno() and event & select.POLLRDHUP:
                        return
        finally:
            self.log("Quit: Disconnect")

    def handle(self) -> None:
        self.log("Connected")

        if not self.recv_handshake():
            self.log("Quit: Login failed")
            return
        self.send_handshake()
        self.log("Logged in as %s" % self.user.get_number(),
                 "(new user)" if self.user_new else "")

        self.user.sock = self.request

        while True:
            data = self.request.recv(2)
            if len(data) < 2:
                self.log("Quit: Disconnect")
                return

            version, command = data
            if version != PROTOCOL_VERSION:
                self.log("Quit: Invalid command")
                return

            if command == MobileRelayCommand.CALL:
                if self.handle_call():
                    return self.handle_relay()
            elif command == MobileRelayCommand.WAIT:
                if self.handle_wait():
                    return self.handle_relay()
            elif command == MobileRelayCommand.GET_NUMBER:
                self.handle_get_number()
            else:
                self.log("Quit: Invalid command")
                return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    HOST, PORT = "localhost", 1027
    g_users = users.MobileUserDatabase()
    g_peers = peers.MobilePeers(g_users)
    with Server((HOST, PORT), MobileRelay) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
