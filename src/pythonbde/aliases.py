"""Persistenter Katalog der BDE-Aliase (Aliasname -> Verzeichnis).

Ein Alias reserviert einen Verzeichnispfad für spätere DBF-Tabellenzugriffe.
Das Modul öffnet noch keine beliebigen DBF-Tabellen.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

ALIAS_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z", re.ASCII)


class AliasError(ValueError):
    pass


class AliasInUse(AliasError):
    def __init__(self, name: str, sessions: list[dict]):
        self.name = name
        self.sessions = sessions
        super().__init__(f"Alias '{name}' wird noch von {len(sessions)} Sitzung(en) verwendet")


def validate_alias_name(name: str) -> str:
    if not isinstance(name, str) or not ALIAS_NAME.fullmatch(name):
        raise AliasError("Aliasname: 1–48 Zeichen, beginnend mit Buchstabe; danach Buchstaben, Ziffern, _ oder -")
    return name


class AliasRegistry:
    """Sicher gespeicherte Alias-Definitionen neben der users.dbf.

    Schreibvorgänge sind atomar. Ein schreibgeschütztes Serverdateisystem
    verursacht einen Fehler und keine stillschweigende Änderung im Speicher.
    """

    def __init__(self, dbf_path, path=None):
        self.path = Path(path) if path is not None else Path(dbf_path).absolute().parent / "aliases.json"
        self._items: dict[str, dict[str, str]] = {}
        self.load()

    @staticmethod
    def _key(name):
        return validate_alias_name(name).casefold()

    @staticmethod
    def _folder(folder):
        if not isinstance(folder, str) or not folder.strip():
            raise AliasError("Ein existierendes Datenverzeichnis ist erforderlich")
        path = Path(folder).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise AliasError("Der Alias muss auf ein Verzeichnis verweisen")
        return str(path)

    def load(self):
        if not self.path.exists():
            return
        with self.path.open('r', encoding='utf-8') as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("aliases"), list):
            raise AliasError("Ungültiger Alias-Katalog")
        items = {}
        for item in raw["aliases"]:
            if not isinstance(item, dict):
                raise AliasError("Ungültiger Eintrag im Alias-Katalog")
            name = validate_alias_name(item.get("name"))
            path = item.get("path")
            if not isinstance(path, str) or not path:
                raise AliasError("Ungültiger Alias-Pfad")
            key = name.casefold()
            if key in items:
                raise AliasError("Doppelter Aliasname im Katalog")
            items[key] = {"name": name, "path": path}
        self._items = items

    def _commit(self, changed: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "aliases": sorted(changed.values(), key=lambda x: x["name"].casefold())}
        fd, temporary = tempfile.mkstemp(prefix=".pythonbde-alias-", dir=str(self.path.parent))
        try:
            if os.name == 'posix':
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._items = changed

    def listing(self):
        return [dict(v) for v in sorted(self._items.values(), key=lambda x: x['name'].casefold())]

    def get(self, name):
        item = self._items.get(self._key(name))
        return dict(item) if item else None

    def create(self, name, folder):
        key = self._key(name)
        if key in self._items:
            raise AliasError("Alias existiert bereits")
        changed = dict(self._items)
        changed[key] = {"name": name, "path": self._folder(folder)}
        self._commit(changed)
        return dict(changed[key])

    def rename(self, old_name, new_name):
        old_key = self._key(old_name)
        new_key = self._key(new_name)
        if old_key not in self._items:
            raise AliasError("Alias nicht vorhanden")
        if new_key != old_key and new_key in self._items:
            raise AliasError("Alias existiert bereits")
        changed = dict(self._items)
        entry = dict(changed.pop(old_key))
        entry['name'] = new_name
        changed[new_key] = entry
        self._commit(changed)
        return dict(entry)

    def set_path(self, name, folder):
        key = self._key(name)
        if key not in self._items:
            raise AliasError("Alias nicht vorhanden")
        changed = dict(self._items)
        changed[key] = {"name": changed[key]["name"], "path": self._folder(folder)}
        self._commit(changed)
        return dict(changed[key])

    def delete(self, name):
        key = self._key(name)
        if key not in self._items:
            raise AliasError("Alias nicht vorhanden")
        changed = dict(self._items)
        removed = changed.pop(key)
        self._commit(changed)
        return dict(removed)
