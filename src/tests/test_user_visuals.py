"""Kontorahmen ohne Qt testen – identisch unter Windows und Linux."""
import unittest
from datetime import datetime, timedelta, timezone

from pythonbde.user_visuals import account_border, ADMIN_RED, USER_GREEN, LOCKED_YELLOW, EMPTY_TRANSPARENT


class TestAccountBorders(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)

    def test_none_is_transparent(self):
        self.assertEqual(EMPTY_TRANSPARENT, account_border(None, now=self.now)[0])

    def test_regular_user_is_green(self):
        self.assertEqual(USER_GREEN, account_border({"ADMIN": False}, now=self.now)[0])

    def test_admin_is_red(self):
        self.assertEqual(ADMIN_RED, account_border({"ADMIN": True}, now=self.now)[0])

    def test_locked_user_and_admin_are_yellow(self):
        for is_admin in (False, True):
            with self.subTest(admin=is_admin):
                self.assertEqual(LOCKED_YELLOW, account_border({"ADMIN": is_admin, "LOCKUSER": True}, now=self.now)[0])

    def test_active_auto_lock_is_yellow_even_when_not_manually_locked(self):
        for is_admin in (False, True):
            user = {"ADMIN": is_admin, "LOCKUSER": False,
                    "LOCKUNTIL": (self.now + timedelta(minutes=15)).isoformat()}
            self.assertEqual(LOCKED_YELLOW, account_border(user, now=self.now)[0])

    def test_expired_temporary_lock_restores_normal_color(self):
        past = (self.now - timedelta(seconds=1)).isoformat()
        for is_admin, expected in ((False, USER_GREEN), (True, ADMIN_RED)):
            user = {"ADMIN": is_admin, "LOCKUSER": False, "LOCKUNTIL": past}
            self.assertEqual(expected, account_border(user, now=self.now)[0])

    def test_expire_is_not_a_manual_lock(self):
        user = {"ADMIN": False, "LOCKUSER": False,
                "EXPIRE": (self.now - timedelta(days=1)).isoformat()}
        self.assertEqual(USER_GREEN, account_border(user, now=self.now)[0])


if __name__ == "__main__":
    unittest.main()
