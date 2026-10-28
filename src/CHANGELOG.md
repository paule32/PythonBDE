## v0.6.6 (2026-10-28) – Qt5-Dock-Korrektur und konsolenloser Start

- `UserManagerDock`: nicht vorhandenes `QStyle.SP_DockWidgetFloatButton` durch unterstützte Qt5-Titelleistensymbole ersetzt, mit Aktualisierung beim Andocken/Abkoppeln.
- Watchdog-MinGW-Compilerprüfung/Autobuild (`g++`) laufen unter Windows mit `CREATE_NO_WINDOW` und `STARTF_USESHOWWINDOW/SW_HIDE`, damit kein Konsolenfenster aufblinkt.
- Watchdog-GUI-EXE wird ohne neues Konsolenfenster gestartet, ihre Crash-Dialoge bleiben sichtbar.
- Windows-`icacls`-Aufrufe in TLS- und VFS-Komponenten ebenfalls konsolenlos.
- `.pyw`-Startpunkte können eigene, privat zugewiesene Konsolen ganz früh verstecken; fremde Kommandozeilen-Fenster bleiben unangetastet.
- Tests für Qt5-Konstanten und Prozessstartoptionen erweitert. Nativer Win32-/PyQt5-Laufzeittest weiterhin erforderlich.

## v0.6.5 (2026-10-28) – MinGW32-/MinGW64-Compilerkorrektur

- `layout()` im C++-Watchdog: Win32-`LONG`-Werte der `RECT`-Breiten- und Höhendifferenz werden vor `std::max()` explizit in `int` umgewandelt. Korrigiert den gemeldeten GCC-16-Fehler `no matching function for call to max(int, LONG)`.
- Regressionstest stellt sicher, dass der Typkonflikt nicht erneut eingeführt wird.
- Alle Funktionen und Dateien aus v0.6.4 bleiben erhalten. Native MinGW-Builds müssen auf Windows verifiziert werden.

## v0.6.4 (2026-10-28) – Externer MinGW32/MinGW64 Crash Watchdog

- Eigenständiger Windows-C++-Watchdog (`watchdog/pythonbde_watchdog.cpp`): eigener Prozess, Win32-EDIT-Dialog mit Copy/Close, keine Python-/Qt-Abhängigkeit.
- Automatischer Start pro Server-/RPC-Client-PID **vor** PyQt5, Win32-Mutex gegen Duplikate, Ready-Event gegen frühen Prozessabbruch; normaler Exit erzeugt keinen Dialog.
- Python-`faulthandler` mit separatem PID-Log, Auswertung der letzten Fehlerlogeinträge durch den Watchdog nach unerwarteter Beendigung.
- Separate MinGW32-/MinGW64-Buildskripte und automatischer Best-Effort-Build mit richtigem MinGW-Compiler, wenn die EXE fehlt; der Anwendungsstart bleibt bei fehlendem Compiler möglich.
- Optionales WER-Minidump-Konfigurationsskript. Es erstellt keine Dumps nach dem Prozessende.
- README um bereits gezeigte Architektur-Grafik (PNG und SVG), Fehlerfalltabelle, Einschränkungen und Einrichtung ergänzt; bestehende Dokumentation vollständig erhalten.
- Statische Tests und Python-Regressionen, aber ohne native Win32-/MinGW-Kompilierung in dieser Linux-Testumgebung.

## v0.6.3 (2026-10-28) – GUI-Traceback und nativer Windows-EDIT-Fallback

- Frühe Installation zentraler Exception-Hooks **vor dem PyQt5-Import** in `server.py` und `rpc_client.py`.
- Bei laufendem QApplication: Qt5-Fehlerdialog mit vollständig lesbarem, kopierbarem Traceback.
- Ohne QApplication oder bei kaputtem Qt: natives, mehrzeiliges Win32-EDIT-Fenster samt Scrollbars, Copy Traceback und Close; wenn die Win32-Fenstererzeugung scheitert, `MessageBoxW`.
- Auch Hintergrundthread-Ausnahmen und unraisable exceptions protokolliert; `SystemExit`/`KeyboardInterrupt` erzeugen keinen Fehlerdialog.
- `sys.stderr` wird parallel in eine Datei gespiegelt, selbst wenn `pythonw.exe` keine Konsole bereitstellt.
- Fehlerdatei im benutzerspezifischen Anwendungsdatenordner (`pythonbde_errors.log`), auf 5 MiB mit `.old`-Rotation begrenzt.
- Konsolenlose Einstiegsdateien: `server_gui.pyw` und `rpc_client_gui.pyw`.
- 297 Python-Tests erfolgreich, nativer Win32-UI-Laufzeittest ausstehend.

## v0.6.2 (2026-10-28) – Benutzeraktionen in Dock-Titelleiste

- Users-/Admins-Dock: `New User`, `Delete Account`, `Unlock`, `Refresh` befinden sich nun
  rechts neben dem Titel auf einer eigenen kompakten `QDockWidget`-Titelleiste.
- Separate Button-Zeile aus dem Hauptinhalt des Docks entfernt; zusätzlicher Platz
  steht für Benutzerbaum, Eigenschaften und Logging zur Verfügung.
- Float-/Dock- und Close-Schaltflächen explizit erhalten, da Qt bei einer benutzerdefinierten
  Titelleiste die bisherigen Standard-Dockbuttons nicht mehr selbst zeichnet.
- Vorhandene Kontooperationen, Sperrstatus-Rahmen, Kontextmenüs und Live-Status unverändert.
- Native visuelle Qt5-Validierung auf Windows/Linux noch ausstehend.

## v0.6.1 (2026-10-28) – Dock Settings & Time Windows

- Server Settings als QDockWidget mit horizontal teilbarem Netzwerk/TLS- und CA-Zertifikatspanel.
- Vier CA/Server-Zertifikatpfade in INI, Chain-Prüfung, Zertifikatsgenerierung nur bei Serverstopp,
  automatische Rotation der Server-UUID nach ausdrücklich bestätigter Neuerstellung.
- Neues Manager → Time Window: 7 Tage, 96 Slots pro Tag, 3 feste Kategorien und unzugewiesene Zeitbereiche,
  Maus-Ziehmarkierung und atomare JSON-Persistenz neben der Benutzer-DBF.
- Keine automatische Zeitfenster-Enforcement-Regel am Login; visuelle Windows/Qt5-Tests stehen aus.

## v0.6.0 (2026-10-28) – PythonBDE Sheets

- Neue Excel-ähnliche remote Qt5-Tabellenkalkulation als signiertes `.cpy`-Modul.
- Mehrere Arbeitsblätter, Formelleiste, Tabellenraster, Grundformeln und begrenzte Excel-Funktionsmenge, Dezimal-Rechenengine ohne eval.
- Zellstile, Zwischenablage, Formel-Fill, Undo/Redo, Sortieren, Suchen, AutoSumme, einfache Diagrammansicht.
- Remote-Open/Save/Save As über vorhandene VFS/TLS-Sitzung: `.pysheet`, CSV, TSV, begrenzte XLSX-Unterstützung.
- Neues Startmenü-Element unter Programs/Accessories, MDI-Startgröße angepasst.
- .cpy-Grenze 64 KiB komprimiert, JSONL-Nachrichtenlimit 128 KiB, max. entpackter Modulinhalt nun 256 KiB (mit ZIP-Bomb-Schutz).
- 279 automatische Tests bestanden (15 neue); nativer PyQt5-Sichttest noch offen.

## v0.5.9 TLS CA-Chain Fix
- Generierung einer privaten CA (`ca.crt`, `ca.key`) plus Serverzertifikat (`server.crt`, `server.key`).
- Client vertraut der CA, nicht dem Server-Leaf; prueft CA-Eignung und Hostname.
- Alte Zertifikate werden nicht automatisch geloescht/ueberschrieben.
- Bestehendes JSON-RPC-Protokoll bleibt unveraendert.

## v0.5.8 (2026-10-27)

- Integrierter `TLSTcpServer` mit QSslSocket und Registrierung von Sitzungen erst nach TLS-Handshake (`encrypted`). Kein Klartext-Fallback bei aktiviertem TLS.
- SSL/TLS-Schutz für Login, CreateWindow, Startmenü, signierte `.cpy`-Module und virtuelle Dateiserver-RPCs.
- RPC-Client nutzt QSslSocket, verifiziert Zertifikatskette und Servername, verbindet über `connectToHostEncrypted`, prüft TLS vor Senden/Empfangen.
- Server-Settings: TLS Enable, PEM-Zertifikat/Key und Test Certificate; INI-Persistenz, TLS-Startvalidierung.
- Neues `generate_tls_certificate.py` mit RSA-3072, X.509 SAN und restriktiven Schlüsselrechten; Dokumentation in `TLS_SETUP.md`.
- Python-CLI-Beispielclient auf SSL umgestellt; TLS verpflichtend mit vorab vertrauenswürdigem Zertifikat.
- Tests: X.509, SSL-Handshake mit Hostname-Prüfung, kein RPC vor TLS; 258 automatische Tests. Kein nativer Qt-Socket-Test in dieser Umgebung.

## v0.5.7 (2026-10-27)

- Added mutually exclusive User Permissions `Use as RDP` and `Use as DB` radio buttons; ACCTYPE and FSROOT fields in dBASE III users table with backward-reading of old schema.
- Distinct `systemMode=db` login marker; DB users cannot start Win95/WinXP RDP sessions. RDP users cannot log in as DB.
- Server-side per-account virtual workspaces and JSON index, with read/list/new directory/chunked writes (16 MiB max).
- Remote MDI Open/Save As and print dialogs, per-application file filters, My Documents desktop icon and virtual explorer placeholder.
- Updated Notepad and WordPad signed `.cpy` modules to use session-authenticated virtual filesystem rather than native local QFileDialog in RDP mode.
- Added high-contrast check/radio indicators for the dark theme.
- 253 automated tests passing. Native Windows ACL, GUI and print testing outstanding.

## v0.5.6 (2026-10-27)

- Replaced sample Notepad with full client-side Qt5 plain text MDI editor, file save/open, encoding/BOM preservation, find/replace, status and printing.
- Added WordPad as signed `.cpy` remote MDI application: QTextEdit Rich Text, formatting toolbar, images, lists, HTML/TXT/partial RTF support, basic ODT import and Qt ODF export.
- Added `wordpad` to server allowlist, signed package mapping and Programs → Accessories JSON Start menu.
- Adjusted initial MDI sizes for editors; existing taskbar and minimize/restore support unchanged.
- 243 automatic tests passed (including 11 new editor/format/signature checks); Qt5 visual test remains outstanding.

## v0.5.5 (2026-10-27)

- Desktop icon and 48x48 snap grid now live in a dedicated transparent DesktopIconLayer beneath ALL QMdiSubWindow applications.
- Removed viewport-level icon/grid promotion that could draw desktop icons over application windows.
- Added nearest-free-cell drop placement: visible MDI window rectangles are avoided when snapping desktop icons.
- Layer stays below MDI subwindows through resize and subwindow activation; taskbar remains above work area.
- No server protocol, account database, or signed .cpy module changes.
- 232 automated tests (224 existing + 8 new) passed; native Qt5 visual verification pending.

## v0.5.4 (2026-10-27)

- Replaced basic two-number Calculator example with full classic-inspired Qt5 MDI Calculator.
- Standard/Scientific/Programmer modes with Decimal core, memory, repeat equals, trig/log/powers/factorial, and signed integer word sizes/bitwise operations.
- Calculator menus, keyboard shortcuts, copy/paste, history, mathematical error feedback, original Win95/XP-style palette.
- Kept signed server->client .cpy transfer and Ed25519 key pinning; separated compressed ZIP bound (32 KiB) from total uncompressed member bound (128 KiB).
- Adjusted calculator MDI initial geometry for visibility over the emulated taskbar.
- cryptography requirement now accepts v50 (e.g. Python 3.15 user installation) without downgrading.
- 224 automated tests passing; native Qt5 visual test remains outstanding.

## v0.5.3 (2026-10-26)

- WinXP GUI workspace with an original painter-generated blue sky and green hill background; Win95 teal unchanged.
- Icon graphics 48×48 pixels, centered caption, press overlay, visible 48×48 snap grid during dragging.
- Qt QMdiArea hosts individually movable, minimizable and restorable signed remote Python module windows.
- Taskbar adds an application button at module launch; button toggles minimize/restore; removed on close.
- New `load_module` JSON RPC exchanges signed `.cpy` Python bytecode packages; authentication and session-binding are mandatory.
- Ed25519 signature and independently pinned publisher key, SHA-256 integrity, CPython bytecode magic/version validation, strict server allowlist.
- Server publisher keys persisted beside users.dbf (Windows DPAPI private key; Linux 0600); `module_keys.py` generates/exposes the public identity for trusted distribution.
- Two sample modules Notepad and Calculator; remaining enabled Start items use no-shell placeholder modules.
- Existing protocol and platform checks retained; no arbitrary path execution.
- 208 automatic tests passed including new signature, replay, ABI, grid and MDI structure regression tests; Qt5 visual runtime not yet checked.

# PythonBDE Änderungsübersicht

## v0.5.2 (2026-10-26)

- Windows-95-Desktop im RPC-Arbeitsfenster mit klassischem Petrolgrün `#008080` gezeichnet.
- Hintergrund bleibt auch beim Umschalten des Client-Light-/Dark-Themes erhalten.
- Graue Taskleiste und Startmenü unverändert; Windows XP/Console bleiben unverändert.
- Weitere Regressionstests für den Windows-95-Arbeitsfenster-Hintergrund.

## v0.5.1 (2026-10-26)

- Server versendet nach Login und CreateWindow ein sitzungsgebundenes JSONL-Startmenü (`menu_config`) an Win95-/WinXP-Clients.
- Die JSON-Datei existiert nur für die Übertragung in privatem Temporärverzeichnis und wird sofort entfernt. Windows: Win32-NTFS-DACL für aktuelles Benutzerkonto und SYSTEM, fail-closed bei Fehlern. Linux: 0700/0600.
- Windows95/XP Start-Schaltfläche anklickbar; Windows-95-Logo, klassischer Menü-Stil mit vertikalem Band, Untermenüs, sichere Icon-Nachbildungen.
- Taskleiste bleibt oberhalb des Arbeitsbereichs; Menü öffnet oberhalb der Taskleiste.
- Keine beliebige Befehlsausführung aus JSON; Menüeinträge sind vorerst protokollierte Platzhalter.
- 186 automatisierte Tests erfolgreich. Visueller Qt5-/Windows-DACL-Test weiterhin ausstehend.


## v0.5.0 (2026-10-26)

- Common-Tab in zwei Bereiche geteilt: Verbindung links, System Emulation rechts (Windows 95 / Windows XP / Console).
- Display-Tab mit GUI Geometry (sieben Pixelauflösungen) und TUI Geometry (80 x 25 / 80 x 50) als Radio/Combo-Zeilen.
- Modi synchronisieren die Geometrie-Auswahl. Full Screen bleibt Dummy.
- Qt5-Taskleisten für Win95 (klassisches Grau) und WinXP (blau/grüner Startbereich); Console als 80-spaltige monochrome Textansicht.
- JSONL-Login trägt geprüften `systemMode` (`win95`, `winXP`, `con`) und `display` (`pixels`/`cells`) mit sich.
- Modus/Geometrie pro Sitzung gespeichert und im `CreateWindow`-RPC zurückgegeben; Client prüft Übereinstimmung.
- TCP-RPC-, Passwort- und Account-Sperrverhalten bleibt erhalten. Alte Clients ohne Profil erhalten WinXP als Fallback.
- 170 automatisierte Tests erfolgreich; tatsächliche Qt5-Anzeige unter Windows/Linux noch nicht geprüft.

## v0.4.9 (2026-10-26)

- RPC-Login mit blau-weißem Qt-gemaltem Remote-Desktop-Header, Beschriftung Remotedesktop/Connection und Tabs Common/Display.
- Common: Host, Port-SpinBox (43650), Benutzername, Passwort, Connect und Disconnect.
- Display: Windowed, Full Screen (weiterhin Dummy) und sieben neue Auflösungen, von 640x480 bis 1280x1024.
- Arbeitsfenster öffnet beim Login in der eingestellten Größe, lässt sich nur verkleinern oder bis zur maximal gewählten Größe zurückvergrößern.
- Altes Settings-Menü und Client Settings-Dock entfernt; Verbindungszustand in QStatusBar verschoben.
- 154 automatisierte Tests erfolgreich; native PyQt5-Anzeigetests auf Windows/Linux noch offen.

## v0.4.8 (2026-10-26)

- RPC-Client Display GroupBox zweispaltig: links Windowed/Full Screen, rechts Geometrie-Label/ComboBox.
- Client-Theme-ToolBar: Mond/Sonne, Light/Dark, einheitliches Qt5-QSS inkl. navyblauen Scrollbars.
- Nach Login freies Arbeitsfenster mit selbst gezeichnetem, verschiebbarem Schließen-Icon; Mausklick schließt und trennt die Clientverbindung.
- Windows/Windows JSONL-Handshake mit DPAPI-geschützter Server-RSA-3072-Identität, SHA256-Fingerprint-Pinning und Challenge-gebundenem RSA-OAEP/AES-256-GCM-Passwortpaket.
- Mixed/Linux-Plattformen erhalten vor dem Login die geforderte OK/Cancel-Klartextwarnung. Kein stillschweigender Downgrade bei bereits gepinnten Windows-Servern.
- Nur Login-Passwort geschützt; TLS/VPN bleibt für Schutz des gesamten RPC-Verkehrs nötig. Native Qt5-/DPAPI-Prüfung noch offen.
- 147 Unit-Tests und 22 Subtests erfolgreich; ZIP-Integrität und Syntax geprüft.

## v0.4.7 (2026-10-26)

- Per-Account-Wiederanmeldeintervall 60 Sekunden ab letztem erfolgreichem Login, auch nach Logout oder Disconnect; JSONL-Fehler 429 mit Restsekunden.
- Vorhandene 20-Sekunden-Konfliktsperre bei parallel aktiver Sitzung unverändert, erste Sitzung wird nicht verdrängt.
- RPC Client mit File/Settings/Help Menü, zentriertem About-Dialog, Anzeigeoptionen (Windowed / Full Screen Dummy / Geometrie).
- Login-Screen wechselt nach Login zum einzigen Kommunikationsfenster, RPC CreateWindow wird darin verarbeitet; Fenster schließen stellt Login-Screen wieder her und trennt TCP.
- QPlainTextEdit-Protokoll mit Lokalzeit, Statuscode, einzeiligem Text, neueste Einträge zuerst, maximal 500 Zeilen.
- 136 automatisierte Tests erfolgreich; native Qt5-Oberfläche ungetestet.


## v0.4.6 (2026-10-26)

- Login auf einer zweiten TCP-Verbindung mit einem bereits aktiven Benutzernamen wird abgewiesen (`errorCode=409`, 20 Sekunden Wartefrist); bestehende Sitzung bleibt unangetastet.
- Vor dem Login serverseitige Sperrregelprüfung (`errorCode=403`) für IPv4-Adressen und IP-Bereiche, TCP-Quellports und Port-Bereiche, DNS→IP-Zuordnungen sowie Benutzernamen.
- Neuer Hauptmenüpunkt `Block` und exklusives Blocking-Dock mit sechs Baumknoten, horizontalem/vertikalem Splitter, Save/Delete und gemeinsamem Log.
- Atomare Speicherung `blocking.json` neben der DBF; Login-/Blocking-Ablehnungen im Audit-Log.
- Domain-DNS-Abfragen asynchron und periodisch; bestehendes JSONL-RPC-Protokoll ansonsten unverändert.
- RPC-Testclient zeigt Blockierungsfehler mit Countdown in einer MessageBox.

## v0.4.5 (2026-10-26)

- Ein zentraler Disconnect-Audit-Eintrag pro TCP-Sitzung bei Clientfenster-/Programmende und Netzwerktrennung.
- Logzeile mit Benutzername (auch nach Logout), Session-ID, Client-IP und Ursache.
- Ursachen `connection closed`, `logout`, `kicked by administrator`, `account banned by administrator`, `server stopped`.
- Logging im vorhandenen Qt5-Loggingfenster und in `python_bde.log`; keine Änderungen am DBF-Schema.
- Schutz vor doppelten Disconnect-Einträgen, auch wenn Qt beim Serverstopp sofort `disconnected` signalisiert.


## v0.4.4 (2026-10-25)

- Bidirektionaler RPC über bestehende JSON-Lines-Verbindung: nach Login `rpc_request` mit `CreateWindow`.
- Sitzungsgebundene Rückmeldung `rpc_result` mit `client`, `rpcId`, `lastErrorCode`; 0=Erfolg, >0=Fehler.
- Replay-/Routing-Prüfung und 15-Sekunden-Timeout für nicht bestätigte RPCs.
- Neuer Qt5-GUI-Testclient (`rpc_client.py`) erstellt ein sichtbares Fenster und bestätigt danach den Server.
- RPC-Status und Fehlercode pro eingeloggter Sitzung in der Serverstatus-Ansicht.
- Testclient-Startskripte für Windows und Linux; Benutzer-/Alias-DBF-Schema unverändert.


## v0.4.3 (2026-10-25)

- Hauptmenü `Hilfe` in `Help` umbenannt; `Informations` und `About ...` beibehalten.
- Neue `Appearance`-ToolBar (ein Icon-Button): Light zeigt Mond, Dark zeigt Sonne; ein Klick tauscht Theme und Symbol.
- Einheitliche Qt5-Fusion-Palette plus globales QSS für Fenster, Docks, Dialoge, Menüs, Editor-/Baumansichten und Statusleiste.
- Navyblaue Scrollbars mit gelben Pfeilen (4 kleine PNG-Ressourcen in `pythonbde/assets`), senkrecht und waagerecht.
- Bestehende rot/grün/gelbe 3px-Account-Rahmen nach Themewechsel sofort nachgezogen.
- 66 automatisierte Tests bestanden; native Qt5-Anzeige noch visuell zu prüfen.

## v0.4.2 (2026-10-25)

- Hilfe → Informations vor About, mit Passwortschutz und Pfaden; drei Labels aus User-Manager entfernt.
- Statusbar rechts um „Server: Started/Stopped“ und „Logged-In: n“ erweitert.
- Manager → Aliases: exklusiv sichtbares Dock mit horizontalem Aliasbaum-/Detail-Splitter und vertikalem Log-Splitter; New, Delete, Rename, Browse, Save Directory.
- Persistenter Alias-Katalog (`aliases.json`) neben der users.dbf, atomar geschrieben; keine Änderung am Benutzer-DBF-Schema.
- Server-Protokoll um `list_aliases`, `select_alias`, `release_alias` erweitert; aktive Sitzungsauswahl wird verfolgt.
- Serverseitige Löschblockade bei verwendeten Aliassen, Admin-Hinweis (`admin_notice`), GUI-Bestätigung und `alias_removed`-Ereignisse.
- Vorhandene Aliasdefinitionen entsprechen Verzeichnis-Registrierungen; die volle DBF-Tabellenengine bleibt geplant.

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

