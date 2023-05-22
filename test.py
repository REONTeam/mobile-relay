#!/usr/bin/env python3

import time
import typing
import unittest
import socket
from server import PROTOCOL_VERSION, handshake_magic, MobileRelayCommand, \
    MobileRelayCallResult, MobileRelayWaitResult


class MobileRelayClient:
    sock: typing.Optional[socket.socket]

    def __init__(self, token: typing.Optional[bytes] = None):
        self.sock = None
        self.token = token
        self.connect()

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(("127.0.0.1", 31227))

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_handshake(self) -> None:
        buffer = bytearray(handshake_magic)
        if self.token is not None:
            buffer.append(1)
            buffer += self.token
        else:
            buffer.append(0)
        self.sock.send(buffer)

    def recv_handshake(self) -> typing.Optional[bytes]:
        handshake = self.sock.recv(len(handshake_magic))
        assert handshake == handshake_magic
        new_token, = self.sock.recv(1)
        if new_token == 1:
            token = self.sock.recv(16)
            assert len(token) == 16
            self.token = token
            return token
        assert new_token == 0
        return None

    def send_call(self, number: str) -> None:
        encnum = number.encode()
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.CALL])
        buffer.append(len(encnum))
        buffer += encnum
        self.sock.send(buffer)

    def recv_call(self) -> MobileRelayCallResult:
        recv = self.sock.recv(3)
        assert recv[0] == PROTOCOL_VERSION
        assert recv[1] == MobileRelayCommand.CALL
        return MobileRelayCallResult(recv[2])

    def send_wait(self) -> None:
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.WAIT])
        self.sock.send(buffer)

    def recv_wait(self) -> tuple[MobileRelayWaitResult, str]:
        recv = self.sock.recv(4)
        assert recv[0] == PROTOCOL_VERSION
        assert recv[1] == MobileRelayCommand.WAIT
        assert recv[3] != 0
        number = self.sock.recv(recv[3])
        assert len(number) == recv[3]
        return MobileRelayWaitResult(recv[2]), number.decode()

    def send_get_number(self) -> None:
        buffer = bytearray([PROTOCOL_VERSION, MobileRelayCommand.GET_NUMBER])
        self.sock.send(buffer)

    def recv_get_number(self) -> str:
        recv = self.sock.recv(3)
        assert recv[0] == PROTOCOL_VERSION
        assert recv[1] == MobileRelayCommand.GET_NUMBER
        assert recv[2] != 0
        number = self.sock.recv(recv[2])
        assert len(number) == recv[2]
        return number.decode()


class Tests(unittest.TestCase):
    def test_token(self):
        c = MobileRelayClient()
        c.send_handshake()
        token = c.recv_handshake()
        self.assertIsNot(token, None)
        c.close()

        c = MobileRelayClient(token)
        c.send_handshake()
        token = c.recv_handshake()
        self.assertIs(token, None)
        c.close()

    def test_conn(self):
        c1 = MobileRelayClient()
        c1.send_handshake()
        self.assertIsNot(c1.recv_handshake(), None)
        c2 = MobileRelayClient()
        c2.send_handshake()
        self.assertIsNot(c2.recv_handshake(), None)

        c1.send_get_number()
        num = c1.recv_get_number()
        c2.send_call(num)
        c1.send_wait()
        self.assertEqual(c2.recv_call(), MobileRelayCallResult.ACCEPTED)
        self.assertEqual(c1.recv_wait()[0], MobileRelayWaitResult.ACCEPTED)

        msg = b"hello"
        c1.sock.send(msg)
        c2.sock.send(msg)
        self.assertEqual(c2.sock.recv(16), msg)
        self.assertEqual(c1.sock.recv(16), msg)

        c1.close()
        c2.close()

    def test_disconnect_call(self):
        c = MobileRelayClient()
        c.send_handshake()
        self.assertIsNot(c.recv_handshake(), None)
        c.send_call("1234")
        time.sleep(0.1)
        c.close()

    def test_disconnect_wait(self):
        c = MobileRelayClient()
        c.send_handshake()
        self.assertIsNot(c.recv_handshake(), None)
        c.send_wait()
        time.sleep(0.1)
        c.close()

    def test_connerr(self):
        c = MobileRelayClient()
        c.send_handshake()
        c.close()

    def test_connerr_relay(self):
        c1 = MobileRelayClient()
        c1.send_handshake()
        self.assertIsNot(c1.recv_handshake(), None)
        c1.send_get_number()
        num = c1.recv_get_number()

        c2 = MobileRelayClient()
        c2.send_handshake()
        self.assertIsNot(c2.recv_handshake(), None)

        c2.send_call(num)
        c1.send_wait()
        time.sleep(0.2)
        c1.close()
        c2.recv_call()
        c2.close()

if __name__ == '__main__':
    unittest.main(verbosity=2)
