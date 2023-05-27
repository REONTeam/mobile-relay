# SPDX-License-Identifier: GPL-3.0-or-later

import typing
import secrets
import threading
import dataclasses
import contextlib
import configparser

import sqlite3
try:
    import MySQLdb
except ImportError as e:
    MySQLdb = e


@dataclasses.dataclass
class MobileUser:
    token: bytes
    number: str


class DatabaseSQLBase(threading.local):
    _args: dict

    def __init__(self):
        self._db = None
        self._module = None

    def __repr__(self):
        return self._module.__name__

    def _format(self, string):
        return string

    def init(self):
        self.connect()
        self.create()
        self.close()

    def create(self):
        with contextlib.closing(self._db.cursor()) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS relay_users (
                    token      BINARY(16) NOT NULL UNIQUE,
                    number     TEXT NOT NULL UNIQUE,
                    last_seen  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    registered INT
                )
            """)

    def connect(self):
        if self._db is None:
            self._db = self._module.connect(**self._args)

    def close(self):
        self._db.close()
        self._db = None

    def commit(self, *args, **kwargs):
        return self._db.commit(*args, **kwargs)

    def insert_user(self, token, number):
        with contextlib.closing(self._db.cursor()) as c:
            c.execute(self._format("""
                INSERT INTO relay_users(token, number) VALUES(?, ?)
            """), (token, number))

    def update_timestamp(self, token, number):
        with contextlib.closing(self._db.cursor()) as c:
            c.execute(self._format("""
                UPDATE relay_users SET last_seen = CURRENT_TIMESTAMP
                WHERE token = ? AND number = ?
            """), (token, number))

    def lookup_token(self, token):
        with contextlib.closing(self._db.cursor()) as c:
            c.execute(self._format("""
                SELECT token, number FROM relay_users WHERE token = ?
            """), (token,))
            return c.fetchone()

    def lookup_number(self, number):
        with contextlib.closing(self._db.cursor()) as c:
            c.execute(self._format("""
                SELECT token, number FROM relay_users WHERE number = ?
            """), (number,))
            return c.fetchone()


class DatabaseMySQL(DatabaseSQLBase):
    def __init__(self, **kwargs):
        if isinstance(MySQLdb, ImportError):
            raise MySQLdb

        super().__init__()
        self._module = MySQLdb
        self._args = kwargs

    def _format(self, string):
        return string.replace("?", "%s")


class DatabaseSQLite(DatabaseSQLBase):
    def __init__(self, **kwargs):
        super().__init__()
        self._module = sqlite3
        self._args = kwargs


class MobileUserDatabase:
    _db: typing.Union[DatabaseMySQL, DatabaseSQLite]
    _db_write_lock: threading.Lock

    def __init__(self, filename):
        dbconfig = configparser.ConfigParser()
        dbconfig.read(filename)
        if "mysql" in dbconfig:
            self._db = DatabaseMySQL(**dbconfig["mysql"])
        elif "sqlite" in dbconfig:
            self._db = DatabaseSQLite(**dbconfig["sqlite"])
        else:
            self._db = DatabaseSQLite(database="users.db")
        print("Database:", self._db)

        self._db.init()
        self._new_write_lock = threading.Lock()

    def __enter__(self):
        self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self) -> None:
        self._db.connect()

    def close(self) -> None:
        self._db.close()

    def _generate_token(self) -> typing.Optional[bytes]:
        for x in range(10):
            token = secrets.token_bytes(16)
            if self.lookup_token(token):
                continue
            return token
        return None

    def _generate_number(self) -> typing.Optional[str]:
        for x in range(10):
            number = "0" + "%09d" % secrets.randbelow(1000000000)
            if number.startswith("010"):
                continue
            if self.lookup_number(number):
                continue
            return number
        return None

    def new(self) -> typing.Optional[MobileUser]:
        with self._new_write_lock:
            token = self._generate_token()
            number = self._generate_number()
            if not token or not number:
                return None
            self._db.insert_user(token, number)
            self._db.commit()
        return MobileUser(token, number)

    def update(self, user: MobileUser) -> None:
        self._db.update_timestamp(user.token, user.number)
        self._db.commit()

    def lookup_token(self, token: bytes) -> typing.Optional[MobileUser]:
        row = self._db.lookup_token(token)
        if not row:
            return None
        return MobileUser(row[0], row[1])

    def lookup_number(self, number: str) -> typing.Optional[MobileUser]:
        row = self._db.lookup_number(number)
        if not row:
            return None
        return MobileUser(row[0], row[1])
