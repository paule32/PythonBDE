# PythonBDE Änderungsübersicht

## v0.4.1 (2026-10-25)

- Drei Statuslabels in das Users-/Admins-Dock verschoben; kein separates `centralWidget`/Logging-Dock, welches nach Minimieren links eine Spalte belegen könnte.
- User-Manager öffnet standardmäßig beim GUI-Start in voller Breite im oberen Dockbereich; Logging und Live-Status sind weiterhin im vertikalen Splitter integriert.
- Start Server direkt links neben Stop Server ergänzt; Buttons und Menüs folgen dem realen Listener-Zustand und blockieren Start-Doppelklicks/-Doppelaufrufe.
- Backup-Dock merkt zuvor sichtbare Docks vor dem Ausblenden und stellt sie beim Schließen wieder her.
- 42 automatisierte Tests erfolgreich; GUI visuell ohne installierte PyQt5-Laufzeit noch nicht geprüft.

## v0.4.0 (2026-10-25)

- Copyright im Fenstertitel/About und 940 × 650 px Startgröße.
- Live-Log mit 200/400 Statuscodes, 500 Zeilen, Save As/Clear Text, 5 MiB Rotation in python_bde.log neben DBF.
- GUI-Hide beim Schließen während Server läuft; File→Close fährt Server herunter.
- Windows systemweiter Single-Instance-Mutex und lokale GUI-Aktivierung.
- UserManager: Vertikalsplitter mit Logging/Server-Status, Kontextmenüs für User/Session, Admin-Selbstlöschschutz.
- Server: Client-Push-Nachrichten, Kick, Bann, Kick All; Clients erhalten asynchrone JSON-Events.
- Manager→Backup vorbereitet, vorherige Docks bei Schließen wieder sichtbar.

# Changelog

## 0.3.0 – Server-Steuerung und Benutzer-Manager

* Menüleiste File/Server/Manager/Help mit Start/Stop/Status/Settings/Users/About.
* Konfiguration als atomar gespeicherte `pythonbde.ini` neben Programm mit stabiler UUIDv4.
* Qt5 Netzwerkadapter-Auswahl, frei eingebbare IPv4 und TCP-Port-SpinBox (43650), Test-/Save-/Cancel-Buttons.
* Schnelle UDP-Discovery (43651) mit randomisiertem Probe-Nonce und Startverweigerung bei einem anderen erreichbaren PythonBDE-Server. Keine harte Multi-Subnetz-Garantie.
* `Users`-Dock mit QTreeWidget-Gruppen Users/Admins und eingebetteter Bearbeitungsmaske rechts im QSplitter; keine modalen Edit-Dialoge mehr.
* Live-Status mit Clientzahl, distinct angemeldeten Benutzern, Login-Zeiten und letzter Benutzer-DBF-Record-Operation.
* Client behält genau eine Loginantwort, unterstützt nun `--host`.
* DBF-/Hash-Schema der Version 0.2.0 unverändert.
* 24 reine Python-Tests erfolgreich unter Linux, native Windows-/Qt5-GUI-Tests offen.


## 0.2.0 – Gemeinsame Windows-/Linux-Codebasis

* Windows CNG (`BCryptDeriveKeyPBKDF2`) und Linux OpenSSL (`hashlib.pbkdf2_hmac`) über `platform.system()` zentral ausgewählt.
* DBF-Passwortformat (PBKDF2-HMAC-SHA256, Salz/Hash/Rundenzahl) unverändert: kein Datenbank-Migrationsbedarf.
* Linux: `fcntl.flock(LOCK_EX | LOCK_NB)` zur Vermeidung paralleler **kooperativer** Serverstarts, Berechtigungen `0600`, Schutz gegen Dateisymlinks.
* Default-Datenpfade nach Windows `LOCALAPPDATA` / Linux XDG Data Home, `--dbf` weiterhin möglich.
* `start_linux.sh` und `server.py --check-platform` hinzugefügt.
* Qt5-Verwaltungsfenster zeigt das aktive OS und Passwort-Backend an.
* Tests erweitert: 18 erfolgreich auf Linux, Windows-Auswahl über Mock getestet; native Win32-API/Qt5-GUI nicht in dieser Umgebung getestet.
* Client-Verhalten von 0.1.1 (eine sichtbare Login-Antwort) beibehalten.

**Sicherheitsgrenze Linux:** `flock` ist advisory; Programme unter derselben UID können die Sperre ignorieren. Dateirechte `0600` schützen vor anderen UIDs; für produktiven Betrieb dediziertes Dienstkonto und Verzeichnis `0700` verwenden. Kein direkter gleichwertiger Linux-Ersatz für Windows `CreateFileW(..., shareMode=0, ...)`.

## v0.3.1 – Kontostatusrahmen im User-Manager
- Das gesamte rechte Benutzer-Detailpanel besitzt einen 3 Pixel breiten Statusrahmen.
- Administratoren: rot; normale Benutzer: grün; manuell oder aktuell zeitlich gesperrte Accounts: gelb (hat Vorrang).
- Während kein Datensatz ausgewählt ist, bleibt der Rahmen transparent.
- Admin- und Lock-User-Checkbox aktualisieren die Vorschaufarbe sofort; gespeichert wird weiterhin erst mit "Save User".
- Eine zeitliche Sperre wird im laufenden Betrieb neu geprüft (1 Sekunde), ohne ungespeicherte Formularfelder zurückzusetzen.
- Automatisierte Tests der Statusfarbenauswahl hinzugefügt.
