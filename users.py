# SPDX-License-Identifier: GPL-3.0-or-later

import json
import secrets

class MobileUserDatabase():
    def __init__(self, filename: str):
        self.filename = filename
        self.dirty = False
        if not self.load():
            self.users = []
            self.apply()
            self.save()
        else:
            self.lookup_refresh()

    def load(self):
        try:
            with open(self.filename, "r") as f:
                self.users = json.load(f)
        except FileNotFoundError:
            return False
        return True

    def save(self):
        if not self.dirty:
            return
        with open(self.filename, "w") as f:
            json.dump(self.users, f, indent=4)

    def lookup_refresh(self):
        self.lookup_token = {}
        self.lookup_number = {}
        for user in self.users:
            self.lookup_token[user["token"]] = user
            self.lookup_number[user["number"]] = user

    def apply(self):
        self.dirty = True
        self.lookup_refresh()

    def generate_token(self):
        # TODO: What to do if we run out of tokens?
        while True:
            token = secrets.token_hex(16)
            if token not in self.lookup_token:
                return token

    def generate_number(self):
        # TODO: What to do if we run out of numbers?
        while True:
            number = "%07d" % secrets.randbelow(10000000)
            if number not in self.lookup_number:
                return number

    def user_new(self):
        token = self.generate_token()
        number = self.generate_number()
        user = {
            "token": token,
            "number": number,
        }
        self.users.append(user)
        self.apply()
        return user

    def user_lookup_token(self, token: str):
        return self.lookup_token.get(token)

    def user_lookup_number(self, number: str):
        return self.lookup_number.get(number)
