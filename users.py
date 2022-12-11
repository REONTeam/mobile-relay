# SPDX-License-Identifier: GPL-3.0-or-later

import json
import secrets

class MobileUserDatabase():
    def __init__(self, filename: str):
        self.filename = filename
        self.dirty = False
        if not self._load():
            self.users = []
            self._apply()
            self.save()
        else:
            self._lookup_refresh()

    def _load(self):
        try:
            with open(self.filename, "r") as f:
                self.users = json.load(f)
        except FileNotFoundError:
            return False
        return True

    def _lookup_refresh(self):
        self.lookup_token = {}
        self.lookup_number = {}
        for user in self.users:
            self.lookup_token[user["token"]] = user
            self.lookup_number[user["number"]] = user

    def _apply(self):
        self.dirty = True
        self._lookup_refresh()

    def _generate_token(self) -> str:
        # TODO: What to do if we run out of tokens?
        while True:
            token = secrets.token_hex(16)
            if token not in self.lookup_token:
                return token

    def _generate_number(self) -> str:
        # TODO: What to do if we run out of numbers?
        num = secrets.randbelow(10000000)
        while True:
            string = "%07d" % num
            if string not in self.lookup_number:
                return string
            num += 1
            if num >= 10000000:
                num = 0

    def save(self):
        if not self.dirty:
            return
        with open(self.filename, "w") as f:
            json.dump(self.users, f, indent=4)

    def user_new(self):
        token = self._generate_token()
        number = self._generate_number()
        user = {
            "token": token,
            "number": number,
        }
        self.users.append(user)
        self._apply()
        return user

    def user_lookup_token(self, token: str):
        return self.lookup_token.get(token)

    def user_lookup_number(self, number: str):
        return self.lookup_number.get(number)
