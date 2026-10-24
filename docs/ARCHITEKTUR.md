# PythonBDE – Architekturentwurf

## Prozessübersicht

```text
+---------------------------+  lokale IPC  +------------------------------------+
| Programm A (.prg/.wfm)    |<----------->| PythonBDE Dienst (Windows/Linux)  |
| Qt5 Login UI + BDE client |             | Sessions / ACL / Lock Manager      |
+---------------------------+             | DBF Reader/Writer + SQL Engine     |
                                          | Whitelisted DBF-Verzeichnisse      |
+---------------------------+  lokale IPC |                                    |
| Programm B (.prg/.wfm)    |<----------->|                                    |
+---------------------------+             +------------------------------------+

+---------------------------+  Admin IPC              |
| Qt5 PythonBDE Verwaltung |<-------------------------+
+---------------------------+
```

## Lokales Protokoll, Entwurf v1

- Framing: feste Längenangabe + UTF-8 JSON/MessagePack, Maximalgröße, Protokollversion und Request-ID; Binärdaten als separater Block.
- Alle Clientbefehle binden `session_id` und pro Verbindung authentifizierte Betriebssystemidentität; kein bloßes Vertrauen auf übertragene User-ID/PID.
- Befehle: `HELLO`, `OPEN_SESSION`, `LOGIN`, `CLOSE_SESSION`, `OPEN_DATABASE`, `OPEN_TABLE`, `FETCH`, `LOCK_RECORD`, `UNLOCK_RECORD`, `SQL_PREPARE`, `SQL_EXEC`, `CLOSE_HANDLE`, `PING`, `STATUS`.
- Antworten: `ok`, `error_code`, `message`, `request_id`, Daten; standardisierte BDE-kompatible Fehlerzuordnung in späterem Entwurf.
- Autorisierung auf jeder Ressource (Database/Path/Session/Cursor), nicht nur beim Login; Pfade kanonisieren, Symbolic-Link-/Reparse-Point-Escape verhindern.

## Vorgeschlagenes Session-Datenmodell (nur Spezifikation)

```json
{
  "id": "uuidv4",
  "created_at_utc": "2026-10-24T14:00:00Z",
  "application_id": "example.Form1",
  "process_id": 1234,
  "user_id": "os-specific-identity",
  "login_method": "Windows",
  "status": "ACTIVE",
  "opened_databases": [],
  "opened_tables": [],
  "last_activity_utc": "2026-10-24T14:00:00Z"
}
```

Eine tatsächliche Session-ID muss kryptografisch erzeugt werden. Das JSON ist **nur ein Datenmodell-Beispiel**, keine Implementierung.

## Lebenszyklus

`NEW → AUTH_PENDING → ACTIVE → CLOSING → CLOSED` bzw. `AUTH_FAILED`, `EXPIRED`, `ABORTED`. DB-Operationen nur im Zustand `ACTIVE`. Bei Crash Locks über Service-internen Ownership-Graph freigeben und offene Handles schließen.

## Modulaufteilung (geplant)

```text
pythonbde/
  service/           # Windows SCM und Linux systemd
  sessions/          # ID, Authentifizierung, Lifetime, Ownership
  security/          # Windows LogonUser / PAM / ACL
  ipc/               # Named Pipes / Unix-Domain-Socket
  storage/dbf/       # DBF Parser, Writer, Memo, Indizes
  locking/           # Locks, Deadlocks, Leases
  query/             # SQL Parser, Planner, Execution
  adminqt/           # Qt5-Verwaltung (eigener Prozess)
  client/            # dBase2Many IPC Client und ABI
```

## Technische Risiken

- Python-3.15-Unterstützung der gewählten Qt5-Bindings und pywin32 vor Implementierung mit Smoke-Test nachweisen.
- GUI unter Service Session 0 kann nicht zuverlässig angezeigt werden; strikt Prozess-Trennung.
- Keine Passwörter in JSON-Protokoll-Logs, Environment-Variablen oder Kommandozeilen.
- Windows-Prozessrechte/Impersonation nur nach expliziter Autorisierung des Clients.
- BDE-Originaldateiformate und Indexkompatibilität benötigen Testkorpus mit legal beschafften Daten.
