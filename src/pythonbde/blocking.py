"""Persistente serverseitige Sperrregeln. Nur vertrauenswürdige Socket-Metadaten.

Port = TCP-Quellport des Clients (NICHT Server-Listen-Port). Domain-Regeln
werden ausschließlich gegen im Hintergrund aufgelöste IP-Adressen geprüft.
"""
from __future__ import annotations

import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import tempfile
import time
import uuid

TYPES = (
    'IP Range Blocking', 'Port Range Blocking', 'IP Blocking',
    'Port Blocking', 'Domain Blocking', 'User Blocking',
)
FIELDS = {
    TYPES[0]: ('start', 'end'), TYPES[1]: ('start', 'end'),
    TYPES[2]: ('ip',), TYPES[3]: ('port',),
    TYPES[4]: ('domain',), TYPES[5]: ('username',),
}
DOMAIN_RE = re.compile(r'(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
USER_RE = re.compile(r'[A-Za-z0-9_.-]{1,48}\Z')
MAX_RULES = 2000


class BlockingError(ValueError):
    pass


def ipv4(value):
    try:
        ip = ipaddress.ip_address(value)
        if ip.version != 4:
            raise ValueError('IPv6 nicht unterstützt')
        return str(ip)
    except (ValueError, TypeError) as exc:
        raise BlockingError('Gültige IPv4-Adresse erforderlich') from exc


def port(value):
    if isinstance(value, bool):
        raise BlockingError('Port muss eine Zahl zwischen 1 und 65535 sein')
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise BlockingError('Port muss eine Zahl zwischen 1 und 65535 sein') from exc
    if not 1 <= number <= 65535:
        raise BlockingError('Port muss zwischen 1 und 65535 liegen')
    return number


def validate_rule(category, values):
    if category not in FIELDS or not isinstance(values, dict):
        raise BlockingError('Ungültiger Blocking-Typ')
    if category == TYPES[0]:
        a, b = ipv4(values.get('start')), ipv4(values.get('end'))
        if int(ipaddress.IPv4Address(a)) > int(ipaddress.IPv4Address(b)):
            raise BlockingError('IP-Range: Anfang darf nicht größer als Ende sein')
        return {'start': a, 'end': b}
    if category == TYPES[1]:
        a, b = port(values.get('start')), port(values.get('end'))
        if a > b:
            raise BlockingError('Port-Range: Anfang darf nicht größer als Ende sein')
        return {'start': a, 'end': b}
    if category == TYPES[2]:
        return {'ip': ipv4(values.get('ip'))}
    if category == TYPES[3]:
        return {'port': port(values.get('port'))}
    if category == TYPES[4]:
        domain = values.get('domain')
        if not isinstance(domain, str) or not DOMAIN_RE.fullmatch(domain.lower().strip('.')):
            raise BlockingError('Gültiger DNS-Domainname erforderlich')
        return {'domain': domain.lower().strip('.')}
    username = values.get('username')
    if not isinstance(username, str) or not USER_RE.fullmatch(username):
        raise BlockingError('Ungültiger Benutzername')
    return {'username': username.casefold()}


def rule_label(rule):
    values = rule['values']
    category = rule['type']
    if category in (TYPES[0], TYPES[1]):
        return f"{values['start']} – {values['end']}"
    return str(next(iter(values.values())))


def resolve_domains(domains):
    """Für background executor: DNS niemals beim Login im Qt-GUI-Thread auflösen."""
    result = {}
    for domain in domains:
        addresses = set()
        try:
            for item in socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM):
                addresses.add(ipv4(item[4][0]))
        except (socket.gaierror, OSError, BlockingError):
            pass
        result[domain] = addresses
    return result


class BlockingRegistry:
    def __init__(self, dbf_path, path=None):
        self.path = Path(path) if path is not None else Path(dbf_path).absolute().parent / 'blocking.json'
        self.rules = {}
        self.domain_ips = {}
        self.load()

    def load(self):
        if not self.path.exists():
            return
        if self.path.is_symlink() or self.path.stat().st_size > 2 * 1024 * 1024:
            raise BlockingError('Blocking-Datei unsicher oder zu groß')
        with self.path.open(encoding='utf-8') as stream:
            source = json.load(stream)
        if not isinstance(source, dict) or source.get('schema') != 1 or not isinstance(source.get('rules'), list):
            raise BlockingError('Ungültiges Blocking-Dateiformat')
        if len(source['rules']) > MAX_RULES:
            raise BlockingError('Zu viele Blocking-Regeln')
        loaded = {}
        for entry in source['rules']:
            if not isinstance(entry, dict):
                raise BlockingError('Ungültiger Regel-Eintrag')
            try:
                ident = str(uuid.UUID(entry['id']))
            except (ValueError, KeyError, TypeError) as exc:
                raise BlockingError('Ungültige Regel-ID') from exc
            if ident in loaded:
                raise BlockingError('Doppelte Regel-ID')
            loaded[ident] = {'id': ident, 'type': entry['type'],
                             'values': validate_rule(entry['type'], entry['values'])}
        self.rules = loaded

    def _save(self, changed):
        if self.path.is_symlink():
            raise BlockingError('Keine symbolischen Links als Blocking-Datei zulässig')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'schema': 1, 'rules': list(changed.values())}, ensure_ascii=False, indent=2)
        fd, temp = tempfile.mkstemp(dir=str(self.path.parent), prefix='.blocking-')
        try:
            if os.name == 'posix':
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.rules = changed
        valid_domains = {r['values']['domain'] for r in changed.values() if r['type'] == TYPES[4]}
        self.domain_ips = {d: ips for d, ips in self.domain_ips.items() if d in valid_domains}

    def listing(self):
        return sorted(self.rules.values(), key=lambda r: (TYPES.index(r['type']), rule_label(r), r['id']))

    def upsert(self, category, values, ident=None):
        clean = validate_rule(category, values)
        if ident is None:
            ident = str(uuid.uuid4())
        elif ident not in self.rules:
            raise BlockingError('Regel nicht vorhanden')
        updated = self.rules.copy()
        if ident not in updated and len(updated) >= MAX_RULES:
            raise BlockingError('Maximale Anzahl Blocking-Regeln erreicht')
        # Einträge nicht stillschweigend doppelt anlegen.
        for key, entry in updated.items():
            if key != ident and entry['type'] == category and entry['values'] == clean:
                raise BlockingError('Blocking-Regel existiert bereits')
        result = {'id': ident, 'type': category, 'values': clean}
        updated[ident] = result
        self._save(updated)
        return result

    def delete(self, ident):
        if ident not in self.rules:
            raise BlockingError('Regel nicht vorhanden')
        updated = self.rules.copy()
        deleted = updated.pop(ident)
        self._save(updated)
        return deleted

    def domains(self):
        return sorted({r['values']['domain'] for r in self.rules.values() if r['type'] == TYPES[4]})

    def update_domain_ips(self, resolved):
        active = set(self.domains())
        self.domain_ips = {d: set(ips) for d, ips in resolved.items() if d in active}

    def blocked(self, peer_ip, peer_port=0, username=''):
        """Keine Client-Header als Peer-IP verwenden, nur sock.peerAddress()."""
        ip = ipaddress.ip_address(peer_ip) if peer_ip else None
        if ip is not None and ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        p = int(peer_port or 0)
        name = username.casefold() if isinstance(username, str) else ''
        for rule in self.listing():
            cat, val = rule['type'], rule['values']
            if cat == TYPES[0] and ip and ip.version == 4 and (int(ipaddress.IPv4Address(val['start'])) <= int(ip) <= int(ipaddress.IPv4Address(val['end']))):
                return rule
            if cat == TYPES[1] and val['start'] <= p <= val['end']:
                return rule
            if cat == TYPES[2] and ip and str(ip) == val['ip']:
                return rule
            if cat == TYPES[3] and p == val['port']:
                return rule
            if cat == TYPES[4] and ip and str(ip) in self.domain_ips.get(val['domain'], set()):
                return rule
            if cat == TYPES[5] and name and name == val['username']:
                return rule
        return None


class DuplicateLoginGuard:
    """20 Sekunden temporäre Sperre; die bereits eingeloggte Sitzung bleibt aktiv."""
    def __init__(self, seconds=20.0, clock=None):
        self.seconds = seconds
        self.clock = clock or time.monotonic
        self.until = {}

    def check(self, name, current, states, session_ttl):
        now = self.clock()
        key = name.casefold()
        self.until = {k: deadline for k, deadline in self.until.items() if deadline > now}
        # Bestehende Sitzung wird nicht verändert oder gekickt.
        other_active = any(s is not current and s.get('username') == key and
                           now - s.get('logged_at', 0) <= session_ttl
                           for s in states)
        if other_active:
            if key not in self.until:
                self.until[key] = now + self.seconds
            return 'duplicate', max(1, int(self.until[key] - now + .999))
        if key in self.until:
            return 'cooldown', max(1, int(self.until[key] - now + .999))
        return None, 0


class ReLoginIntervalGuard:
    """Minimum interval between *successful* logins for the same account.

    The deadline starts when a login succeeds, not on logout, TCP FIN, or a
    failed attempt. Thus a brief connection cannot immediately re-login.
    Monotonic deadlines are local to this running server process.
    """

    def __init__(self, seconds=60.0, clock=None):
        self.seconds = float(seconds)
        self.clock = clock or time.monotonic
        self.until = {}

    def remaining(self, username):
        now = self.clock()
        self.until = {key: deadline for key, deadline in self.until.items()
                      if deadline > now}
        deadline = self.until.get(username.casefold(), 0.0)
        return max(0, int(math.ceil(deadline - now)))

    def record_success(self, username):
        self.until[username.casefold()] = self.clock() + self.seconds
