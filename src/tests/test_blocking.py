"""Tests der persistierten Login-Sperrregeln und 20-Sekunden-Regel ohne Qt."""
import ipaddress
import json
from pathlib import Path
import tempfile
import unittest

from pythonbde.blocking import (
    TYPES, BlockingRegistry, BlockingError, DuplicateLoginGuard,
    resolve_domains, validate_rule, ipv4,
)


class BlockingPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'users.dbf'
        self.registry = BlockingRegistry(self.path)

    def test_ipv4_range_inclusive_edges(self):
        self.registry.upsert(TYPES[0], {'start':'192.168.1.10', 'end':'192.168.1.25'})
        for address in ('192.168.1.10','192.168.1.19','192.168.1.25'):
            self.assertEqual(TYPES[0], self.registry.blocked(address)['type'])
        self.assertIsNone(self.registry.blocked('192.168.1.26'))
        self.assertIsNone(self.registry.blocked('192.168.1.9'))

    def test_exact_ip_and_ipv4_mapped_v6(self):
        self.registry.upsert(TYPES[2], {'ip':'10.0.0.1'})
        self.assertEqual(TYPES[2], self.registry.blocked('10.0.0.1')['type'])
        self.assertEqual(TYPES[2], self.registry.blocked('::ffff:10.0.0.1')['type'])
        self.assertIsNone(self.registry.blocked('10.0.0.2'))

    def test_ports_refer_to_client_source_port(self):
        self.registry.upsert(TYPES[1], {'start':5000, 'end':5010})
        self.assertTrue(self.registry.blocked('10.0.0.2', 5005))
        self.assertIsNone(self.registry.blocked('10.0.0.2', 4999))
        self.registry.upsert(TYPES[3], {'port':'2222'})
        self.assertEqual(TYPES[3], self.registry.blocked('10.0.0.2', 2222)['type'])

    def test_domain_resolution_uses_cached_address_not_untrusted_client_text(self):
        item = self.registry.upsert(TYPES[4], {'domain':'Example.NET'})
        self.assertIsNone(self.registry.blocked('203.0.113.12'))
        self.registry.update_domain_ips({'example.net': {'203.0.113.12'}})
        self.assertEqual(item['id'], self.registry.blocked('203.0.113.12')['id'])
        self.assertIsNone(self.registry.blocked('203.0.113.13'))

    def test_user_blocking_is_case_insensitive(self):
        self.registry.upsert(TYPES[5], {'username':'Martha'})
        self.assertEqual(TYPES[5], self.registry.blocked('127.0.0.1', 0, 'MARTHA')['type'])
        self.assertIsNone(self.registry.blocked('127.0.0.1', 0, 'Berta'))

    def test_persistence_update_and_remove(self):
        rule = self.registry.upsert(TYPES[2], {'ip':'192.0.2.10'})
        again = BlockingRegistry(self.path)
        self.assertEqual(rule, again.rules[rule['id']])
        modified = again.upsert(TYPES[2], {'ip':'192.0.2.11'}, rule['id'])
        self.assertEqual(rule['id'], modified['id'])
        again.delete(rule['id'])
        self.assertFalse(BlockingRegistry(self.path).rules)

    def test_no_duplicates_or_invalid_ranges(self):
        self.registry.upsert(TYPES[2], {'ip':'192.0.2.11'})
        with self.assertRaises(BlockingError):
            self.registry.upsert(TYPES[2], {'ip':'192.0.2.11'})
        for a,b in [('192.0.2.255','192.0.2.1'), ('bad','192.0.2.3')]:
            with self.assertRaises(BlockingError):
                self.registry.upsert(TYPES[0], {'start':a,'end':b})
        with self.assertRaises(BlockingError):
            self.registry.upsert(TYPES[1], {'start':20000,'end':2000})
        with self.assertRaises(BlockingError):
            self.registry.upsert(TYPES[3], {'port':65536})

    def test_invalid_domains_and_json(self):
        for value in ['bad_domain', 'http://server.local', '', '.']:
            with self.subTest(value=value), self.assertRaises(BlockingError):
                self.registry.upsert(TYPES[4], {'domain':value})
        self.registry.path.write_text('{"schema":2,"rules":[]}', encoding='utf-8')
        with self.assertRaises(BlockingError):
            BlockingRegistry(self.path)

    def test_rule_file_permissions_on_linux(self):
        self.registry.upsert(TYPES[2], {'ip':'192.0.2.3'})
        if __import__('os').name == 'posix':
            self.assertEqual(0o600, self.registry.path.stat().st_mode & 0o777)


class LoginGuardTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.guard = DuplicateLoginGuard(20, lambda: self.clock[0])
        self.original = {'username': 'john', 'logged_at': 99.0}
        self.second = {'username': None, 'logged_at': 0.0}

    def test_duplicate_rejected_for_twenty_seconds_and_original_untouched(self):
        self.assertEqual(('duplicate',20), self.guard.check('john', self.second,
                          [self.original, self.second], 3600))
        self.assertEqual('john', self.original['username'])
        self.clock[0] += 5
        self.original['username'] = None  # bereits bestehende Sitzung abgemeldet
        self.assertEqual(('cooldown',15), self.guard.check('john', self.second,
                          [self.original, self.second], 3600))
        self.clock[0] += 15
        self.assertEqual((None,0), self.guard.check('john', self.second,
                         [self.original, self.second], 3600))

    def test_other_users_not_affected(self):
        self.guard.check('john', self.second,[self.original,self.second],3600)
        self.assertEqual((None,0), self.guard.check('alice',self.second,[self.original,self.second],3600))

    def test_expired_sessions_not_counted_as_logged_in(self):
        self.clock[0] = 5000
        self.assertEqual((None,0), self.guard.check('john',self.second,[self.original,self.second],3600))

    def test_same_connection_can_reauthenticate(self):
        self.assertEqual((None,0), self.guard.check('john',self.original,[self.original],3600))


if __name__ == '__main__':
    unittest.main()
