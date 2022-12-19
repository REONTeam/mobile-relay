# SPDX-License-Identifier: GPL-3.0-or-later

import secrets
import threading
import dataclasses
import sqlite3


@dataclasses.dataclass
class MobileUser:
    token: bytes
    number: str


class MobileUserDatabase:
    _db: sqlite3.Connection
    _db_write_lock: threading.Lock

    def __init__(self, filename: str):
        self._db = sqlite3.connect(filename, check_same_thread=False)
        self._db_write_lock = threading.Lock()
        self._create()

    def save(self):
        pass

    def _create(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS "relay_users" (
                "token"      BLOB NOT NULL UNIQUE,
                "number"     TEXT NOT NULL UNIQUE,
                "last_seen"  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                "registered" INTEGER
            )
        """)

    def _generate_token(self) -> bytes:
        # TODO: What to do if we run out of tokens?
        while True:
            token = secrets.token_bytes(16)
            if not self.lookup_token(token):
                return token

    def _generate_number(self) -> str:
        # TODO: What to do if we run out of numbers?
        while True:
            number = "%07d" % secrets.randbelow(10000000)
            if not self.lookup_number(number):
                return number

    def new(self) -> MobileUser | None:
        with self._db_write_lock:
            token = self._generate_token()
            number = self._generate_number()
            self._db.execute("""
                INSERT INTO relay_users("token", "number") VALUES(?, ?)
            """, (token, number))
            self._db.commit()
        return MobileUser(token, number)

    def lookup_token(self, token: bytes) -> MobileUser | None:
        res = self._db.execute("""
            SELECT "token", "number" FROM "relay_users" WHERE "token" = ?
        """, (token,))
        row = res.fetchone()
        if not row:
            return None
        return MobileUser(row[0], row[1])

    def lookup_number(self, number: str) -> MobileUser | None:
        res = self._db.execute("""
            SELECT "token", "number" FROM "relay_users" WHERE "number" = ?
        """, (number,))
        row = res.fetchone()
        if not row:
            return None
        return MobileUser(row[0], row[1])
