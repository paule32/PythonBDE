"""Serverseitige Benutzerrechte und Login-/Lockout-Regeln."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets

from .crypto import hash_password, verify_password
from .dbf import DBFStore

RIGHTS = ("ADMIN", "READ", "WRITE", "ANSICHT", "MODIFY", "LOCK")
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,48}\Z")


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(date: datetime) -> str:
    return date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def public_user(user: dict) -> dict:
    """Nie PWHASH/PWSALT und keine PBKDF-Konfiguration an UI/API ausgeben."""
    fields = ("USERNAME", *RIGHTS, "LOCKUSER", "COUNTPASS", "COUNTLIM", "FAILS", "LOCKUNTIL", "EXPIRE", "CREATED", "UPDATED")
    return {k: user[k] for k in fields}


class AuthError(Exception):
    pass


class UserManager:
    def __init__(self, store: DBFStore):
        self.store = store

    def get(self, username: str):
        return self.store.users.get(username.casefold()) if isinstance(username, str) else None

    def _ensure_admin_remains(self, new_users):
        if new_users and not any(u["ADMIN"] and not u["LOCKUSER"] and not u["EXPIRE"]
                                 for u in new_users.values()):
            raise AuthError("Mindestens ein nicht gesperrter Administrator ohne Ablaufdatum muss bestehen bleiben.")

    def bootstrap(self, username: str, password: str):
        if self.store.users:
            raise AuthError("Initialer Administrator existiert bereits")
        return self.create(username, password, {"ADMIN": True, "READ": True, "WRITE": True,
                                               "ANSICHT": True, "MODIFY": True, "LOCK": True})

    @staticmethod
    def _validate(name, count_pass, count_limit, expire):
        if not isinstance(name, str) or not USERNAME_PATTERN.fullmatch(name):
            raise AuthError("Benutzername: 1–48 Zeichen (a-z, 0-9, _, ., -)")
        if not isinstance(count_pass, int) or not 0 <= count_pass <= 99999:
            raise AuthError("Count Pass muss zwischen 0 und 99999 liegen")
        if not isinstance(count_limit, int) or not 0 <= count_limit <= 99999:
            raise AuthError("Count Pass Limit muss zwischen 0 und 99999 Minuten liegen")
        if expire:
            value = parse_time(expire)
            if not value or value.utcoffset() is None:
                raise AuthError("Expire muss ein ISO-8601-UTC-Zeitpunkt sein")

    def create(self, name: str, password: str, rights: dict | None = None,
               *, lock_user=False, count_pass=5, count_limit=15, expire=""):
        self._validate(name, count_pass, count_limit, expire)
        pw = hash_password(password)
        def write(users):
            if name.casefold() in users:
                raise AuthError("Benutzer existiert bereits")
            now = timestamp(utcnow())
            row = dict(USERNAME=name, **pw, **{k: bool((rights or {}).get(k, False)) for k in RIGHTS},
                       LOCKUSER=bool(lock_user), COUNTPASS=count_pass, COUNTLIM=count_limit,
                       FAILS=0, LOCKUNTIL="", EXPIRE=expire or "", CREATED=now, UPDATED=now)
            users[name.casefold()] = row
            self._ensure_admin_remains(users)
        self.store.change(write)
        return public_user(self.get(name))

    def edit(self, name: str, *, password=None, rights=None, lock_user=None,
             count_pass=None, count_limit=None, expire=None):
        pw = hash_password(password) if password else None
        def write(users):
            if name.casefold() not in users:
                raise AuthError("Benutzer unbekannt")
            row = users[name.casefold()]
            if rights is not None:
                if not isinstance(rights, dict):
                    raise AuthError("Rechte müssen ein Objekt sein")
                for k in RIGHTS:
                    if k in rights:
                        if not isinstance(rights[k], bool):
                            raise AuthError(f"Recht {k} muss true oder false sein")
                        row[k] = rights[k]
            if lock_user is not None:
                if not isinstance(lock_user, bool):
                    raise AuthError("Lock User muss bool sein")
                row["LOCKUSER"] = lock_user
            cp = row["COUNTPASS"] if count_pass is None else count_pass
            cl = row["COUNTLIM"] if count_limit is None else count_limit
            ex = row["EXPIRE"] if expire is None else expire
            self._validate(name, cp, cl, ex)
            row.update(COUNTPASS=cp, COUNTLIM=cl, EXPIRE=ex, UPDATED=timestamp(utcnow()))
            if pw:
                row.update(pw)
                row.update(FAILS=0, LOCKUNTIL="")
            self._ensure_admin_remains(users)
        self.store.change(write)
        return public_user(self.get(name))

    def delete(self, username: str):
        def write(users):
            if username.casefold() not in users:
                raise AuthError("Benutzer unbekannt")
            del users[username.casefold()]
            self._ensure_admin_remains(users)
        self.store.change(write)

    def unlock(self, name: str):
        def write(users):
            if name.casefold() not in users:
                raise AuthError("Benutzer unbekannt")
            row = users[name.casefold()]
            row.update(LOCKUSER=False, LOCKUNTIL="", FAILS=0, UPDATED=timestamp(utcnow()))
            self._ensure_admin_remains(users)
        self.store.change(write)

    def authenticate(self, name: str, password: str, *, require_admin=False) -> dict | None:
        user = self.get(name)
        if user is None:
            # Dummy KDF gegen schnelle Benutzer-Enumeration; keine Usernamen aus Fehler ableiten.
            from .crypto import derive, ITERATIONS
            derive(password if isinstance(password, str) else "", b"\x00"*16, ITERATIONS)
            return None
        now = utcnow()
        if user["LOCKUSER"] or (parse_time(user["EXPIRE"]) and now > parse_time(user["EXPIRE"])):
            return None
        until = parse_time(user["LOCKUNTIL"])
        if until and now < until:
            return None
        if until and now >= until:
            self.store.change(lambda _: user.update(FAILS=0, LOCKUNTIL=""))
        ok = isinstance(password, str) and verify_password(password, user)
        if ok:
            if require_admin and not user["ADMIN"]:
                return None
            if user["FAILS"]:
                self.store.change(lambda _: user.update(FAILS=0, LOCKUNTIL=""))
            return public_user(user)
        def failed(_):
            user["FAILS"] = min(99999, user["FAILS"] + 1)
            if user["COUNTPASS"] > 0 and user["COUNTLIM"] > 0 and user["FAILS"] >= user["COUNTPASS"]:
                user["LOCKUNTIL"] = timestamp(now + timedelta(minutes=user["COUNTLIM"]))
                user["FAILS"] = 0
            user["UPDATED"] = timestamp(now)
        self.store.change(failed)
        return None

    def has_permission(self, name: str, permission: str):
        user = self.get(name)
        return bool(user and permission in RIGHTS and user[permission] and
                    not user["LOCKUSER"] and not (parse_time(user["EXPIRE"]) and utcnow() > parse_time(user["EXPIRE"])))

    def listing(self):
        return [public_user(u) for u in sorted(self.store.users.values(), key=lambda v: v["USERNAME"].casefold())]
