# PythonBDE – Anforderungen v0.1

Stand: **24. Oktober 2026**. Dies ist eine **Spezifikation**, keine Behauptung einer fertigen Implementierung.

## 1. Repository und Produkte

- Separates GitHub-Repository: **`paule32/PythonBDE`**, unabhängig von d64_dism/dBase2Many.
- Python **3.15**, Qt **5** für die Administrationsanwendung und Login-Dialoge; Abhängigkeiten auf Python-3.15-Kompatibilität prüfen. Qt-Widgets nicht innerhalb von Windows Session 0 als Desktop-Anwendung betreiben.
- `pythonbde-service`: lokaler Broker, Sessionverwaltung, DBF-Zugriffe, Locks, SQL und Audit.
- `pythonbde-admin`: separate Qt5-Oberfläche für Betrieb, Diagnose, aktive Sessions und Benutzer-/Zugriffsregeln; Verknüpfung in der Windows-Systemsteuerung oder im Startmenü ist ein späterer Integrationsschritt.
- `pythonbde-client`: lokaler Python-/C-ABI-Client für zukünftige dBASE-Programme und die WFM-Runtime.

## 2. Session-Objekt

- **Nur** automatisch erzeugen, wenn das jeweilige Programm DBF-/Tabellen-/SQL-Funktionalität nutzt oder `Session.Open()` explizit ausführt; nicht für reine Formulare ohne DB-Zugriff.
- Einzigartige, kryptografisch zufällige **Session-ID** (z. B. UUIDv4 oder Token); UTC-Erstellungszeit `created_at` mit Zeitzone und monotone Laufzeit-Referenz; optional `closed_at` im Audit.
- Identität: `application_id`, `process_id`, `process_start_time`, `os_user`, `authenticated_user`, `login_method`, `last_activity`, `open_tables`, `locks`, `transactions`.
- Pro Anwendung/Prozess isoliert; keine automatische Übertragung zwischen Programmen. Mehrere Benutzer können denselben lokalen BDE-Dienst über getrennte Sessions nutzen.
- Reguläres Programmende: Session schließen, Handles/DBF-Dateien und Locks freigeben. Prozessabbruch: Prozess-Handle/IPC-Verbindungsabbruch und Lease/Heartbeat zur Bereinigung; PID allein reicht wegen Wiederverwendung nicht aus.
- Die zentrale Windows-Instanz hält **aktive Sessions im Dienstprozess**; nur notwendige, bereinigte Metadaten/Audit dürfen persistent gespeichert werden. Keine Passwörter, Sitzungsschlüssel oder offenen DB-Handles persistent speichern.
- Beendete Sessions dürfen zu Diagnosezwecken **anonymisiert protokolliert**, aber nicht als aktive Sessions weitergeführt werden.

## 3. Projekteigenschaft `Session.Login Methode`

Auswahlliste (ComboBox): **BDE**, **Windows**, **Linux**, **Custom**. Werte werden im Projekt gespeichert; OS-ungeeignete Verfahren liefern verständliche Diagnosen (kein stilles Fallback). Zusätzlich konfigurierbar: `Login beim Formularanzeigen`, `Login beim __init__`, `Nur bei erster DB-Nutzung` (empfohlener Default), `Timeout`, `MaxVersuche`. Für ein und dieselbe Session darf der Dialog nicht gleichzeitig mehrfach aufgehen.

| Login-Methode | Vorgabe | Sicherheitsverhalten |
|---|---|---|
| BDE | Lokale, später einzuführende PythonBDE-Konten-/Rechteverwaltung | Keine Abhängigkeit von der historischen Borland-BDE; eigener Dienst und eigene Zugangsdaten |
| Windows | Lokale Windows-Konten über dokumentierte Windows-Anmelde-APIs prüfen | Benutzername/ggf. Rechnerdomäne, Passwort ausschließlich transient; Dienst authentifiziert den Aufruf zusätzlich über IPC-Clientidentität |
| Linux | Vorhandene Benutzer über NSS/`pwd` auflisten (darunter lokale `/etc/passwd`-Einträge) | `/etc/passwd` ist **keine Passwortdatenbank**; Passwortprüfung über PAM, Benutzer-/Gruppenrichtlinie zusätzlich prüfen |
| Custom | WFM-/dBASE-Funktion `__login__` | Rückgabe muss logisch `TRUE`/`FALSE` sein; kein impliziter Adminzugriff; serverseitige Berechtigungen gelten weiter |

### Custom-Login

```dbase
FUNCTION __login__(UserName, Password)
    /* benutzerdefinierte Pruefung */
    RETURN .F.  && oder .T.
```

Dies ist die **vorgeschlagene** Aufrufsignatur; als kompatible Kurzform kann `FUNCTION __login__()` ohne Argumente unterstützt werden, wenn Anmeldedaten über eine Session-API bereitgestellt werden. Der Compiler muss Signatur, Rückgabetyp und tatsächliche Ausführung zuerst implementieren. Der serverseitige Zugriff wird niemals nur durch ein beliebiges `.T.` vertrauenswürdig; die Policy ist getrennt.

### Login-Ablauf

1. `Session.Open()` oder erster Zugriff bzw. expliziter Formular-Hook; blockiert nur die betreffende Anwendung, nicht den Dienst.
2. Qt5-Dialog zeigt Benutzername, verdeckte Passworteingabe, OK/Abbrechen und konkrete Login-Methode.
3. IPC-Client prüft Benutzer- und Prozesskontext und sendet nur erforderliche Authentifizierungsdaten über **lokal geschützte IPC**.
4. Dienst authentifiziert und ordnet eine gültige Session zu; fehlgeschlagener Login gibt eine neutrale Fehlermeldung, kein Datenbank-Handle.
5. Beim Formularabschluss oder Prozessende `Session.Close()`; bei Absturz automatische Bereinigung.

## 4. BDE-inspirierter lokaler Datenbankserver

- Lokaler DBF-v3/v4-/dBASE-Kompatibilitätsmodus als erste Stufe; genaue Varianten und Codepages in Tests definieren.
- Zugriff auf `.dbf`, zugehörige `.dbt` (Memo) sowie `.ndx`/`.mdx` Indizes in weiteren Stufen; **kein** vorgetäuschter Schreib-/Transaktionssupport für unbekannte Varianten.
- Mehrbenutzerzugriff durch zentralen Dienst mit Cursor-/Tabellen-/Datensatzsperren; Lock-Reihenfolge, Fairness, Timeouts, Deadlocks, Prozessabbruch und Konfliktmeldung spezifizieren.
- Aliasverwaltung (`STANDARD`/Verzeichnispfade), Table.Open/Close, Navigation, Lesen, Schreiben, Indexverwaltung, DBF-Reparatur nur nach expliziter Datensicherung.
- SQL auf DBF: zuerst **SELECT, WHERE, ORDER BY, LIMIT, parametrisierte Queries**; spätere JOIN, UPDATE, INSERT, DELETE, Transaktionen/Undo. SQL-Unterstützung ist neu zu implementieren, nicht automatisch vorhanden.
- Wiederanlauf: Journal/WAL oder sichere Copy-on-Write-/Transaktionsstrategie vor gleichzeitigen Schreibzugriffen. DBF ist keine vollwertige transaktionale Datenbank; Atomicität muss eigens geschaffen und getestet werden.
- Logging/Audit: Anmeldung, Session Start/Ende, Zugriffe und Konflikte ohne Passwörter oder sensible Datensatzinhalte.

## 5. Windows-Dienst und Management

- Hintergrundprozess mit **Windows Service Control Manager**: automatischer/manueller Start, Stop, Restart, Recovery, Eventlog.
- Dienst mit dediziertem, möglichst niedrig privilegiertem Konto; DBF-Verzeichnisse und IPC-Rechte administrativ begrenzt.
- **Keine Qt5-Dialoge aus dem Dienstprozess**. Separater Qt5-Admin-Client für Systemsteuerung/Startmenü sowie Login-Dialog im Benutzerprozess.
- Lokale Netzwerkverbindungen verschiedener Programme auf demselben Rechner sind erlaubt; **keine Verbindung über LAN/Internet**.
- Lokalität muss technisch erzwungen werden: Windows Named Pipe mit `PIPE_REJECT_REMOTE_CLIENTS` und expliziten DACLs (oder lokalem RPC); kein TCP-Listener, auch nicht `127.0.0.1` als alleiniger Sicherheitsbeweis.
- Linux-Variante: Unix-Domain-Socket in restriktivem Laufzeitverzeichnis mit Dateirechten und Peer-Credentials; optional systemd-Dienst, nicht PAM-Passwörter selbst verwalten.
- Betriebszugriff: nur Admins dürfen Dienstparameter, zugelassene DBF-Stammverzeichnisse, Aliasdefinitionen und Benutzer-Rollen ändern.

## 6. Meilenstein und Abnahme

- Architektur/Katalog (diese Phase) → Dienstgrundgerüst → sichere IPC/Auth → Sessionmanager → DBF-Read-only → Locks und Schreiben → SQL-Subset → Qt5-Admin → Windows-Dienstinstallation und End-to-End-Tests → IDE-Anbindung.
- Testfälle: mehrere lokale Benutzer, zwei parallele `.prg`-Prozesse, unberechtigter Tabellenzugriff, abgebrochene Anwendung, ID-Wiederverwendung ausgeschlossen, DBF-Lock-Konflikt, Remote-Pipe abgelehnt, falsches Passwort, `Custom` TRUE/FALSE, sauberer Dienst-Restart.

## 7. Begriffsabgrenzung

`TSession` in Delphi/BDE ist nicht dasselbe wie eine serverseitig zentral verwaltete Session über sichere IPC. Die PythonBDE-Session ist eine eigenständige Erweiterung. Bei Original-BDE wurden lokale ISAM-Tabellen nicht generell durch einen eigenständigen Python-Dienst verwaltet.
