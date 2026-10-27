import os
import struct
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from pythonbde.auth import AuthError, UserManager, timestamp, utcnow
from pythonbde.crypto import hash_password, verify_password
from pythonbde.dbf import DBFStore, FIELDS, HEADER_LEN, RECORD_LEN, make_dbf, parse_dbf


class TestCore(unittest.TestCase):
    def test_crypto(self):
        x = hash_password("GeheimesPasswort!1")
        self.assertEqual(16, len(bytes.fromhex(x["PWSALT"])))
        self.assertEqual(64, len(x["PWHASH"]))
        self.assertTrue(verify_password("GeheimesPasswort!1", x))
        self.assertFalse(verify_password("falsch", x))
        self.assertNotEqual(hash_password("GeheimesPasswort!1")["PWHASH"], x["PWHASH"])

    def test_dbf_roundtrip(self):
        row = dict(USERNAME="admin", PWHASH="a"*64, PWSALT="b"*32, PBKDFITER=310000,
                   ADMIN=True, READ=True, WRITE=False, ANSICHT=True, MODIFY=False,
                   LOCK=True, LOCKUSER=False, COUNTPASS=5, COUNTLIM=15,
                   FAILS=2, LOCKUNTIL="", EXPIRE="", CREATED="", UPDATED="")
        data = make_dbf({"admin": row})
        self.assertEqual(0x03, data[0])
        self.assertEqual(1, struct.unpack_from("<I", data, 4)[0])
        self.assertEqual(HEADER_LEN, struct.unpack_from("<H", data, 8)[0])
        self.assertEqual(RECORD_LEN, struct.unpack_from("<H", data, 10)[0])
        self.assertEqual(32+32*len(FIELDS)+1+RECORD_LEN+1, len(data))
        result = parse_dbf(data)["admin"]
        for key, value in row.items():
            self.assertEqual(value, result[key])
        self.assertIn("ACCTYPE", result)
        self.assertIn("FSROOT", result)
        with self.assertRaises(ValueError):
            parse_dbf(data[:-10])

    def test_auth_and_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            dbf = Path(td) / "users.dbf"
            with DBFStore(dbf) as store:
                mgr = UserManager(store)
                mgr.bootstrap("admin", "SecureAdmin!34")
                mgr.create("user1", "SecureUser!34", {"READ": True}, count_pass=2, count_limit=15)
                self.assertEqual(2, len(mgr.listing()))
                self.assertTrue(mgr.authenticate("user1", "SecureUser!34"))
                self.assertIsNone(mgr.authenticate("user1", "wrong"))
                self.assertIsNone(mgr.authenticate("user1", "wrong"))
                self.assertIsNotNone(mgr.get("user1")["LOCKUNTIL"])
                self.assertIsNone(mgr.authenticate("user1", "SecureUser!34"))
                mgr.unlock("user1")
                self.assertIsNotNone(mgr.authenticate("user1", "SecureUser!34"))
                mgr.edit("user1", rights={"MODIFY": True}, lock_user=True)
                self.assertIsNone(mgr.authenticate("user1", "SecureUser!34"))
                mgr.unlock("user1")
                mgr.edit("user1", expire=timestamp(utcnow() - timedelta(days=1)))
                self.assertIsNone(mgr.authenticate("user1", "SecureUser!34"))
                mgr.edit("user1", expire="")
                self.assertTrue(mgr.get("user1")["MODIFY"])
                with self.assertRaises(AuthError):
                    mgr.delete("admin")
                with self.assertRaises(AuthError):
                    mgr.edit("admin", expire=timestamp(utcnow() + timedelta(days=1)))
                self.assertFalse(mgr.get("admin")["LOCKUSER"])
                self.assertIn("PWHASH", mgr.get("user1"))
                self.assertNotIn("PWHASH", mgr.listing()[0])
            with DBFStore(dbf) as store:
                self.assertEqual(2, len(store.users))
                self.assertEqual("user1", store.users["user1"]["USERNAME"])

    def test_unlimited_attempts(self):
        with tempfile.TemporaryDirectory() as td, DBFStore(Path(td) / "test.dbf") as store:
            mgr = UserManager(store)
            mgr.bootstrap("admin", "SecureAdmin!34")
            mgr.create("noauto", "SecureUser!34", count_pass=0, count_limit=15)
            for _ in range(2):
                self.assertIsNone(mgr.authenticate("noauto", "wrong"))
            self.assertEqual("", mgr.get("noauto")["LOCKUNTIL"])
            self.assertTrue(mgr.authenticate("noauto", "SecureUser!34"))
            mgr.edit("noauto", count_pass=1, count_limit=0)
            self.assertIsNone(mgr.authenticate("noauto", "wrong"))
            self.assertTrue(mgr.authenticate("noauto", "SecureUser!34"))

    def test_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "users.dbf"
            with DBFStore(file):
                with self.assertRaises(OSError):
                    DBFStore(file)

if __name__ == "__main__":
    unittest.main()
