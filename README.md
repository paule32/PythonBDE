# PythonBDE – Qt5-BDE-Server mit DBF-Benutzerverwaltung

**Version 0.4.3** · eigenständige Erweiterung zu [paule32/PythonBDE](https://github.com/paule32/PythonBDE).
Der beim Abruf verfügbare Repository-Text beschreibt das Projekt als „python based BDE server“.
Die hier enthaltene Implementierung ist ein **neues, separates Grundmodul**; es wurde **nichts nach GitHub gepusht**.

## Neuerungen v0.4.3 – Toolbar mit Light-/Dark-Umschaltung

- Das Hauptmenü heißt ab sofort **Help** statt **Hilfe**. Die bisherigen Einträge **Informations** und **About ...** bleiben erhalten.
- Über der Docking-Fläche befindet sich nun eine **Appearance-ToolBar** mit genau einem Button. **Mond = aktuell Light-Mode**; ein Klick aktiviert den Dark-Mode und tauscht den Mond gegen die **Sonne** aus. Klick auf die Sonne schaltet wieder in den Light-Mode mit Mondsymbol.
- Die Umschaltung betrifft die gesamte `QApplication`: Hauptfenster, Docking-Fenster, Menüs, Tabellen, Baumansichten, Eingabefelder, Statusleiste, Log-Editoren und danach geöffnete Dialoge. Als plattformübergreifende Basis dient Qt5 **Fusion** mit eigenen `QPalette`-Farben und einem globalen Qt Style Sheet.
- Vertikale und horizontale Scrollbars besitzen **navyblauen Hintergrund**, blau abgesetzte Griffe sowie **gelbe Richtungspfeile** in beiden Themes. Die PNG-Ressourcen befinden sich in `pythonbde/assets/` und benötigen kein QtSvg-Plugin.
- Die Toolbar-Icons für Sonne und Mond entstehen **zur Laufzeit mit `QPainter`** und benötigen keine externen Icon-Pakete. Die roten, grünen und gelben 3-Pixel-Rahmen der Account-Details werden nach dem Theme-Wechsel unmittelbar erneut angewendet.
- Der Serverbetrieb sowie DBF-, Alias- und Protokollformate bleiben unverändert. **Das Design startet bei jedem Programmstart bewusst im Light-Mode**; eine dauerhafte Speicherung der Theme-Auswahl war nicht angefordert.
- Teststand: **66 automatisierte Tests unter Linux erfolgreich** (davon 6 neue Theme-/GUI-Strukturtests ohne PyQt5). Ein tatsächlicher visueller PyQt5-Test unter Windows und Linux steht noch aus.

## Neuerungen v0.4.2 – Informationsdialog, Statusbar und Aliases

- Das Hauptmenü **Help → Informations** enthält jetzt den **ersten Eintrag** „Informations“. Ein Dialog enthält ausschließlich **Passwortschutz** sowie die Pfade zu **users.dbf** und **python_bde.log**. Die bisherigen drei Statuslabels sind aus dem Users-/Admins-Dock entfernt.
- Zwei dauerhafte Statusbar-Panels zeigen **`Server: Stopped` / `Server: Started`** sowie **`Logged-In: n`**. Die Zahl zählt verschiedene angemeldete Benutzernamen; die bestehende Server-Statusansicht zeigt darüber hinaus einzelne TCP-Sitzungen.
- **Manager → Aliases** öffnet ein Dock, blendet andere Docks aus und stellt sie beim Schließen wieder her. Oberhalb: **New**, **Delete**, **Rename**; darunter links der Aliasbaum und rechts Aliasname/Verzeichnispfad mit Browse/Save Directory. Ein **vertikaler Splitter** trennt diesen Bereich vom unteren QPlainTextEdit-Logging (gleicher 500-Zeilen-Puffer und dieselbe 5-MiB-Datei wie der User-Manager).
- Aliasdefinitionen werden atomar in **`aliases.json`** neben der DBF gespeichert (Linux: `0600`). Aliasnamen sind unabhängig von Groß-/Kleinschreibung eindeutig. **New** benötigt einen existierenden Ordner; **Rename** und **Save Directory** sind bei aktiver Aliasnutzung gesperrt.
- Neue, authentisierte JSONL-Aktionen: `list_aliases`, `select_alias`, `release_alias`. `list_aliases` liefert **nur die Namen** (keine Serverpfade). `select_alias` registriert einen Alias für die konkrete TCP-Sitzung, `release_alias` hebt diese Registrierung auf; Logout, Re-Login und Verbindungsschluss beenden die Zuordnung.
- **Löschschutz bei aktiver Verwendung:** Vor jeder Aliaslöschung überprüft der Server seine Sitzungsliste. Ohne ausdrückliche Bestätigung wirft er `AliasInUse`; die GUI listet die betroffenen Sitzungen und verlangt eine zweite, deutliche Zustimmung. Angemeldete Admin-Clients bekommen außerdem ein `admin_notice`-Ereignis. Nach bestätigtem Löschen erhalten betroffene Clients `alias_removed` und die Alias-Reservierungen werden freigegeben. Diese Prüfung erfolgt **serverseitig**, nicht nur in der GUI.
- Die vorhandenen Kontorechte, die DBF-Benutzertabelle und die Start-/Stop-Steuerung bleiben unverändert.

**Umfang:** Ein Alias ist derzeit eine **Verzeichniszuordnung und Sitzungsreservierung**, keine vollständige BDE-Tabellenengine. Allgemeines Öffnen/Ändern von DBF-Dateien über Aliase, Transaktionen, tatsächliche Datensatzsperren und Indexmanagement sind noch **nicht** implementiert. Ein Client kann den Alias auswählen, aber noch keine Tabellendatensätze darüber lesen oder ändern. Bereits außerhalb dieses Servers geöffnete DBF-Dateien werden durch die neue Sitzungsprüfung nicht erkannt. Für einen produktiven LAN-Einsatz ist das bestehende unverschlüsselte JSONL-Protokoll weiterhin nur über TLS/VPN geeignet.

Beispiele nach Anmeldung (eine JSON-Zeile pro Aktion):

```json
{"action":"list_aliases"}
{"action":"select_alias","alias":"Archiv"}
{"action":"release_alias","alias":"Archiv"}
```

Beispielclient:

```bash
python client_example.py --list-aliases
python client_example.py --select-alias Archiv --listen
```

**Prüfstand:** Automatisierte Tests auf Linux (ohne native Qt5-GUI). Die echte Qt5-Ansicht und ihre Splitter/Buttons müssen auf Windows/Linux noch visuell getestet werden.

## Neuerungen v0.4.1 – Statuslabels im User-Manager, Server-Startbutton

- Die drei Labels `Server`, `Passwortschutz` und `DBF-/Log-Pfade` sind jetzt **im Users-/Admins-Dock** direkt über der Benutzerverwaltung. Das frühere eigenständige `centralWidget` mit den Labels entfällt, da es beim Minimieren/Wiederherstellen eine unerwünschte linke Spalte erzeugen konnte. Das Dock liegt beim Start über die gesamte verfügbare Fensterbreite und bleibt verschiebbar.
- Beim Start wird **Manager → Users automatisch angezeigt**; in diesem Dock liegen sowohl der Account-Bereich als auch Logging und Serverstatus. Ein zweites, separates Logging-Dock wird nicht mehr erzeugt. `Server → Status` navigiert zum eingebetteten Statusbereich des User-Managers.
- Die Steuerleiste unter `Logged-in User / Login Time (UTC)` enthält jetzt `Send Message To All`, `Kick All with Message`, **`Start Server`** und `Stop Server` in dieser Reihenfolge.
- Ist der TCP-Listener erfolgreich gestartet, wird **Start Server deaktiviert und Stop Server aktiviert**. Im gestoppten Zustand ist es umgekehrt. Während eines laufenden Startversuchs sind beide Schaltflächen deaktiviert; schlägt der Start fehl, bleibt Start Server wieder verfügbar. Menüaktionen folgen dem identischen Listener-Zustand. Auch direkte Doppelaufrufe von `start_server()` werden abgefangen.
- Das Backup-Dock blendet den User-Manager beim Öffnen aus und stellt ihn nach dem Schließen wieder her (die sichtbaren Docks werden jetzt vor dem Ausblenden erfasst).
- Automatisierte Tests: **42 erfolgreich** (37 bestehende + 5 neue GUI-Struktur-/Startlogik-Regressionstests). Die visuellen Docking- und Wiederherstellungsabläufe müssen weiterhin mit einer tatsächlichen PyQt5-Installation unter Windows/Linux geprüft werden.

## Neuerungen v0.4.0 – Logging, Sitzungssteuerung und Fensterzustände

Der Titel der Anwendung und der About-Dialog enthalten jetzt **` (c) 2026 by Jens Kallup - paule32`**.
Die Startgröße beträgt **940 × 650 Pixel**; das Hauptfenster bleibt in beide Richtungen frei skalierbar.

### Fenster und Splitter

- Ab v0.4.2 stehen `Server` und `Logged-In` **in der Statusbar**; Passwortschutz und DBF-/Log-Pfade werden über **Help → Informations** angezeigt. Ein separates Dashboard und Logging-Dock gibt es weiterhin nicht.
- Unter **Manager → Users** ersetzt das neue Benutzer-Dock die bisherige einfache Zweispaltenansicht durch einen **vertikalen Splitter**: oben das horizontal gesplittete Benutzerbaum-/Eigenschaftenpanel, unten die protokollierte Live-Aktivität und Serverstatus.
- Im unteren Bereich gibt es einen zweiten **vertikalen Splitter** zwischen dem QPlainTextEdit-Logging (mit **Save As ...** / **Clear Text**) und den aktiven Verbindungen (mit **Send Message To All**, **Kick All with Message**, **Stop Server**).
- Das Menü **Server → Status** navigiert in das eingebettete Statuspanel anstelle eines neuen Dialogs.
- **Manager → Backup** öffnet ein vorbereitetes Dock. Andere Docks werden ausgeblendet und bei Schließen wiederhergestellt. **Es enthält absichtlich noch kein funktionierendes Backup/Restore**.
- Das Konto-Detailpanel behält die **3px-Rahmenfarben** rot (Admin), grün (User), gelb (gesperrt).

### Audit-/Logging-Ausgabe

Ein Log-Eintrag hat die Form `YYYY-MM-DD HH:MM:SS | STATUSCODE | kurzer Text`.
Beispiele: `200 | GUI started`, `200 | GUI hidden`, `200 | GUI closed.`, `200 | User successfully created: name`, `400 | User can not be created: name (...)`.

Die QPlainTextEdit-Ansicht im User-Manager zeigt die Session-Historie, **neueste Meldung zuerst**. Beim nächsten Eintrag nach 500 Zeilen wird der sichtbare Puffer geleert und neu begonnen. **Clear Text** löscht ausschließlich diesen Puffer, nicht das Audit-Protokoll auf der Festplatte. **Save As ...** exportiert die derzeit sichtbaren Zeilen.

Die **`python_bde.log`** liegt neben der jeweils tatsächlich verwendeten Benutzer-DBF (auch bei `--dbf`). Sie ist **nicht gesperrt** und kann während des Betriebs durch andere Programme gelesen werden. Die Datei hat eine Obergrenze von **5 MiB**; beim Überschreiten werden die ältesten Logzeilen entfernt. Anders als der Editor ist die Datei **chronologisch** für `tail` und externe Log-Reader sortiert. Die Datei kann Kontonamen, IP-Adressen und Metadaten enthalten; die Zugriffsrechte auf das Datenverzeichnis sind daher wichtig. Passwörter, Hashes und Salts werden nicht in das Audit-Protokoll geschrieben.

### GUI schließen / Windows Single Instance

- **X bei laufendem Listener**: Fenster verstecken und `200 | GUI hidden` protokollieren. Der Server bleibt aktiv.
- **X bei gestopptem Server**: Fenster schließen und `200 | GUI closed.` protokollieren.
- **File → Close**: unabhängig vom Serverstatus Server stoppen, `200 | GUI closed.` schreiben und die Anwendung beenden.
- Unter **Windows** wird vor dem Öffnen der DBF ein systemweiter benannter Mutex `Global\PythonBDE_Server_PythonBDE_v1` geprüft. Eine zweite Instanz öffnet die DBF nicht, sondern sendet ein `SHOW` an den laufenden Qt-LocalServer. Das vorhandene Hauptfenster wird sichtbar und die Doppelstart-Meldung angezeigt. Das ist eine **lokale Betriebssystem-Einzelinstanz**, unabhängig von IP-/DNS-Namen. Unter Linux gilt weiterhin die DBF-Sperre gegen gleichzeitig geöffnete Server.
- Falls die bestehende Windows-Instanz noch im Anmeldedialog steht oder der lokale Aktivierungskanal nicht erreichbar ist, kann der zweite Prozess die GUI nicht zuverlässig nach vorne bringen; er weist darauf hin. Ein native-Windows-Test ist weiterhin notwendig.

### Live-Sitzungsaktionen (Rechtsklick in `Logged-in User`)

`Send Message`, `Kick`, `Bann`, `Status`, Trennlinie, `Send Message To All`, `Kick All`.

- **Send Message** sendet an die ausgewählte **Sitzung** ein asynchrones JSON-Ereignis.
- **Kick** beendet die ausgewählte TCP-Verbindung nach Ausgabe eines Kick-Ereignisses.
- **Bann** setzt `LOCKUSER=True` in der DBF und trennt alle Sitzungen dieses Kontos. Der letzte nicht gesperrte permanente Administrator bleibt durch die vorhandene Datenbankinvariante geschützt.
- **Send Message To All** sendet an alle angemeldeten Sitzungen. **Kick All with Message** lässt zuerst einen Text eingeben, sendet ihn und trennt danach alle Sitzungen. `Kick All` im Kontextmenü benötigt keine Nachricht.
- Das rechte Maustastenmenü des Kontobaums bietet **New User**, **New Admin**, Trennlinie und **Delete Account**. Das **lokal angemeldete Administratorkonto kann nicht gelöscht werden**; die netzwerkseitige Benutzer-API schützt ebenfalls das jeweils dort angemeldete Admin-Konto vor Selbstlöschung.

Eine Push-Nachricht ist **keine weitere Antwort auf die vorherige Clientanfrage**, sondern eine eigenständige JSON-Zeile:

```json
{"event":"server_message","text":"Wartung um 20:00 Uhr"}
{"event":"kicked","reason":"Sitzung durch Administrator beendet"}
```

Clients müssen solche `event`-Zeilen neben gewöhnlichen `{ "ok": true|false, ... }`-Antworten verarbeiten und während der Sitzung den TCP-Kanal offen halten. Der Beispielclient `client_example.py --listen` zeigt Push-Nachrichten live an; ohne `--listen` bleibt sein bisheriges kurzes Login-Verhalten erhalten. Der Beispielclient verwendet **keine System-Notifications**. In der GUI kann für die Statusaktionen jede der aktuell angemeldeten **TCP-Sitzungen** unabhängig ausgewählt werden, auch wenn derselbe Username mehrfach vorkommt.

**Sicherheit:** Die erweiterten Session-Aktionen sind gegenwärtig **nur über die lokale Administrator-GUI** verfügbar. Das JSON-Lines-Netzwerkprotokoll erhält hier keine neue Remote-Kick-/Ban-API. Für produktive LAN-Nutzung wird weiterhin TLS/VPN benötigt. Die Linux-Log-Datei wird standardmäßig mit `0600` erstellt; unter Windows den Datenordner per NTFS-ACL absichern.

**Testhinweis:** Kernlogik und neue Logdateibegrenzung sind automatisiert geprüft. Die tatsächliche Qt5-GUI, Windows-Mutex/Named-Pipe-Aktivierung und Netzwerk-Sessions sollten unter Windows/Linux funktional geprüft werden; PyQt5 war in der Ausführungsumgebung nicht installiert.

## Neuerungen v0.3.1 – farbige Kontostatusrahmen

Im Manager-Dock ist das **gesamte rechte Detailpanel** 3 Pixel farbig umrandet: **rot** bei Admins, **grün** bei normalen Benutzern, **gelb** bei manueller oder aktuell zeitlicher Kontosperre (mit Vorrang vor Rot/Grün). Der Status wird beim Auswählen, bei Änderungen an der Admin- oder Lock-User-Checkbox sowie während einer automatischen Sperre aktualisiert.

## Neuerungen v0.3.0 – Menü, Status, Einstellungen, Dock-Manager

Der Server wird über **eine einzige gemeinsame Windows-/Linux-Codebasis** gestartet. Die GUI besitzt diese Menüs:

| Menü | Funktion |
| --- | --- |
| `File -> Close` | Server stoppen, Verbindungen schließen, Anwendung beenden |
| `Server -> Start` / `Server -> Stop` | Listener/UDP-Discovery einschalten bzw. stoppen |
| `Server -> Status` | Laufzeitstatus, verbundene Clients, Anzahl **verschiedener** angemeldeter Benutzer, Login-Zeiten pro TCP-Sitzung und letzte DBF-Änderung anzeigen |
| `Server -> Settings` | NIC-Auswahl, IPv4-Adresse, TCP-Port einstellen, testen und speichern |
| `Manager -> Users` | Dock-Fenster mit `Users` und `Admins`, rechts Eingabefelder statt modaler Bearbeitungsmaske |
| `Help -> About ...` | Programm- und Versionsinformationen |

Im User-Manager links einen Benutzer auswählen. Rechts lassen sich Username (nur beim Anlegen), Passwort, Admin/Read/Write/Ansicht/Modify/Lock, Lock User, Count Pass, Count Pass Limit und Expire direkt ändern. Der Passwort-Hash wird nie angezeigt. `FAILS`, `LOCKUNTIL`, `CREATED`, `UPDATED` sind nur lesbar. Aktionen **New User**, **Delete User**, **Unlock**, **Refresh** befinden sich oben, **Save User** im rechten Panel. Ein administratives Anlegen/Bearbeiten/Entsperren wird im Status als `Insert Record`, `Modify Record` bzw. `Update Record` für `users.dbf` protokolliert. Das ersetzt **keine vollständige allgemeine DBF-Record-API**.

### INI-Konfiguration

Die Datei `pythonbde.ini` wird beim ersten Start **neben `server.py`**, bei einer gepackten EXE **neben der EXE**, angelegt. Das Verzeichnis muss also beschreibbar sein. Beispiel:

```ini
[Server]
id = 8e784661-f203-44c1-8ff6-cbe8264b6b74
ip = 127.0.0.1
port = 43650
nic =
```

Die angezeigte UUID ist hier **nur ein Beispiel**. Tatsächlich generiert PythonBDE pro Installation eine neue UUIDv4, die bei Neustarts erhalten bleibt. **Beim Kopieren einer Installation inklusive INI wird auch die ID kopiert**; PythonBDE erkennt eine solche doppelte ID in erreichbaren Netzsegmenten und verweigert den Start. Änderungen in `Settings` gelten bei laufendem Server erst nach `Server -> Stop` und erneutem `Server -> Start`. `Cancel` schreibt nichts. `Test-Config` reserviert die gewünschte Bind-Adresse und den TCP-Port nur kurz; ein späterer Start kann trotzdem scheitern, falls inzwischen ein anderes Programm den Port belegt.

CLI optional (ohne Speicherung): `python server.py --ip 192.168.1.15 --port 43650`. Für Clients außerhalb von localhost unterstützt der Testclient `python client_example.py --host 192.168.1.15 --port 43650`; nur mit sicherem Transport nutzen.

### Netzwerk-Discovery / Ein-Server-Regel

Beim Start sendet PythonBDE innerhalb von circa 300 ms ein **UDP-Discovery-Probe mit zufälliger Anfragekennung** auf den festen **UDP-Port 43651**, über Loopback und die Broadcast-Adressen der lokalen IPv4-Interfaces. Bereits laufende PythonBDE-v0.3-Server antworten mit Produkt-ID, UUID und TCP-Port. Wenn ein fremder Server antwortet, verweigert PythonBDE den Start und zeigt Adresse, Port und ID an. Der Discovery-Port wird anschließend **exklusiv lokal reserviert**. Der eigentliche TCP-Port bleibt getrennt (standardmäßig 43650).

Ein **breiter Portscan oder eine zentrale Netz-/Port-Datenbank wird nicht benötigt**. Namen wie `server1.local` umgehen diese Erkennung nicht, solange sich die beteiligten Hosts in derselben erreichbaren Broadcast-Domain befinden. **Wichtige Grenze:** Broadcast-Discovery ist _best effort_, keine globale Eindeutigkeitsgarantie. VLANs, Router, Firewalls, deaktivierter UDP-Verkehr, unterschiedliche Softwareversionen und annähernd gleichzeitige Starts können zwei Server unentdeckt lassen. Für harte Ein-Server-Garantien über mehrere Teilnetze hinweg ist ein zentraler Registry-/Lease-Dienst mit atomarer Registrierung nötig. UDP-Discovery ist keine authentifizierte Vertrauens- oder Sicherheitsgrenze.

### Prüfstatus

Die rein Python-basierten Tests prüfen INI, UUID, Plattform, Kryptografie, DBF, Sperrregeln, Netzwerk-Discovery auf Loopback und das JSON-Lines-Clientverhalten. **Die GUI/Qt5-Sockets und die Windows-Laufzeit konnten in dieser Umgebung nicht nativ geprüft werden**. Für einen produktiven Netzeinsatz sind außerdem Authentisierung, TLS, Firewall-Regeln, automatisierte Neustart-/Crash-Tests und eine transaktionssichere DBF-Speicherung notwendig.

## Voraussetzungen / Start (Windows 10/11 und Linux)

```powershell
py -3 -m pip install -r requirements.txt
py -3 server.py
# optional:
py -3 server.py --port 43650 --dbf "C:\ProgramData\PythonBDE\users.dbf"
```

Alternativ unter Windows `start_windows.bat` starten.

### Linux (mit grafischer Desktop-Sitzung)

```bash
sudo apt install python3 python3-venv python3-pip  # Debian/Ubuntu-Beispiel
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start_linux.sh
# oder direkt:
.venv/bin/python server.py
```

Es muss eine laufende grafische Sitzung vorhanden sein, damit die **PyQt5-GUI** angezeigt werden kann (X11 bzw. Qt5-fähige Wayland/XWayland-Umgebung). Auf Headless-Servern ohne GUI ist diese Version kein eigenständiger Hintergrunddienst.

**Plattformprüfung ohne Qt5:**

```bash
python3 server.py --check-platform
```

Die Ausgabe enthält erkannte Plattform, Kryptografie-Backend, Dateisperrverfahren und DBF-Pfad.

Beim ersten Start ein Admin-Konto mit eigenem Passwort anlegen. Danach ist eine Administratoranmeldung erforderlich. **Der Server startet nun zunächst gestoppt** und wird über `Server -> Start` aktiviert. `Manager -> Users` öffnet den andockbaren Manager mit Benutzergruppen und eingebettetem Editor. Beim Schließen wird die DBF freigegeben.

Die Datenbank liegt unter Windows standardmäßig in `%LOCALAPPDATA%\PythonBDE\users.dbf`, unter Linux in `$XDG_DATA_HOME/PythonBDE/users.dbf` bzw. `~/.local/share/PythonBDE/users.dbf`. Mit `--dbf` kann jederzeit ein eigener Pfad angegeben werden.
Im Serverprozess wird die DBF unter Windows mit `CreateFileW(GENERIC_READ|GENERIC_WRITE, shareMode=0, OPEN_ALWAYS)` geöffnet: **solange der Server läuft**, verhindert Windows, dass andere Prozesse die Datei erneut öffnen, auch lesend. Die Verwaltungsoberfläche und die Netzwerk-API arbeiten auf demselben bereits geöffneten Handle. Die Datei selbst hat keinen Dateisystem-Read-Only-Flag, da der Server sie aktualisieren können muss. Außerhalb der Laufzeit schützen **NTFS-Datei-ACLs** vor unbefugtem Zugriff; für eine systemweite Installation Verzeichnis und ACLs entsprechend einrichten. **Ein Windows-Administrator mit entsprechenden Privilegien kann auch diese Schutzmechanismen umgehen.**

Unter Linux wird die DBF mit `fcntl.flock(LOCK_EX|LOCK_NB)` **kooperativ (advisory)** gegen andere Prozesse geschützt. Die Datei selbst erhält die Berechtigung `0600` (nur der Eigentümer darf lesen und schreiben). Ein anderes Benutzerkonto kann dann normalerweise nicht zugreifen. Anwendungen, die unter **derselben UID** laufen und eine `flock`-Sperre ignorieren, können die DBF trotzdem öffnen und verändern: Linux bietet mit `flock` **nicht** dieselbe zwingende Öffnungssperre wie `CreateFileW` unter Windows. Daher für produktive Installationen ein separates Linux-Dienstkonto und ein privates Datenverzeichnis verwenden. Bei gleichem Benutzerkonto schützt die Sperre vor allem gegen einen zweiten kooperierenden PythonBDE-Server.

## Kennwörter / Kontosperre

* Keine reversible Verschlüsselung: aus Sicherheitsgründen werden **gesalzene, nicht rückrechenbare PBKDF2-HMAC-SHA256-Hashes** gespeichert.
  * **Windows:** native Windows CNG / `BCryptDeriveKeyPBKDF2` aus `bcrypt.dll`.
  * **Linux:** `hashlib.pbkdf2_hmac("sha256", ...)` aus CPython, das OpenSSL verwendet (Python 3.12+ setzt dafür OpenSSL voraus).
  * **Beide Backends:** UTF-8-Passwortbytes, 16 zufällige Salt-Bytes, 310000 Runden, 32 Hash-Bytes. Die gespeicherten DBF-Felder `PWSALT`, `PWHASH`, `PBKDFITER` bleiben **unverändert**; bestehende Benutzer werden ohne Migration weiterverwendet. Es findet **keine** reversible Passwortverschlüsselung statt. Der Backend-Selektor nutzt zentral `platform.system()` und unterstützt nur `Windows` / `Linux`.

* `Lock User`: unabhängig von Netzwerk-Sitzungen manuell gesperrtes Konto. Über `Entsperren` wird auch der Fehlversuchszähler zurückgesetzt.
* `Count Pass`: erlaubte Anzahl aufeinanderfolgender falscher Anmeldeversuche. **0 = unbegrenzt** (kein automatischer Lockout).
* `Count Pass Limit`: Wartezeit **in Minuten** nach Erreichen der Schwelle. Beispiel **15 = 15 Minuten Sperre**. Bei **0** erfolgt keine automatische Sperre, auch wenn Count Pass gesetzt ist.
* `Expire`: optionaler UTC-Zeitpunkt, **bis zu dem** das Konto genutzt werden darf. Danach wird jeder Login verweigert; ein Admin kann die Frist ändern oder deaktivieren.
* Rechte: `Admin`, `Read`, `Write`, `Ansicht`, `Modify`, `Lock`. Nur `Admin` hat in diesem Grundmodul Zugriff auf Benutzeroperationen. Die restlichen Berechtigungen werden gespeichert und als Schnittstelle für spätere DBF-Tabellenoperationen angeboten. `Lock` (**Recht**) ist unabhängig von `Lock User` (**Kontosperre**).
* Mindestens ein nicht gesperrtes Administratorkonto **ohne Ablaufdatum** muss bleiben; das letzte solche Konto kann nicht gelöscht oder deaktiviert werden.

## DBF-Aufbau

Native dBASE-III-Datei ohne Memo-Seitendatei, Standardheader, Feld-Deskriptoren, gelöschtes-Flag je Datensatz und Dateiende `0x1A`.
Feldnamen maximal 10 Zeichen (dBASE III). Alle Passwörter werden als Hash (`PWHASH`), Salz (`PWSALT`) und Iterationszahl (`PBKDFITER`) gespeichert; **niemals** als Klartext.

| DBF-Felder | Typ | Bedeutung |
| --- | --- | --- |
| USERNAME | C(48) | Benutzername |
| PWSALT, PWHASH | C(32), C(64) | Hex-kodiertes Salz/Passworthash |
| PBKDFITER | N(9) | PBKDF2-Runden |
| ADMIN, READ, WRITE, ANSICHT, MODIFY, LOCK | L | Einzelrechte |
| LOCKUSER | L | manuell gesperrt |
| COUNTPASS, COUNTLIM, FAILS | N(5) | Schwelle, Sperrminuten, laufende Fehlversuche |
| LOCKUNTIL, EXPIRE | C(20) | UTC ISO-8601-Zeitpunkte (oder leer) |
| CREATED, UPDATED | C(20) | UTC ISO-8601-Zeitpunkte |

Benutzernamen sind bewusst auf ASCII-Buchstaben, Ziffern, `_.-` beschränkt; das Schema ist mit normalen DBF-Werkzeugen lesbar, **wenn der Server gestoppt ist**. Keine automatische Migration bereits vorhandener DBFs mit fremdem Schema – sie werden sicherheitshalber abgelehnt.

## Lokales Serverprotokoll

Der Qt5-Server lauscht **standardmäßig** auf `127.0.0.1:43650`; die Adresse ist über `Server -> Settings` konfigurierbar. Das Protokoll ist **eine UTF-8-JSON-Anfrage und eine UTF-8-JSON-Antwort pro Zeile** (`\n`). Authentifizierung ist **an die TCP-Verbindung gebunden**, keine im Klartext übertragene Session-ID. Sitzungen laufen nach 1 Stunde ab. Maximal 64 KiB je Anfrage, Verbindungspuffer 128 KiB.

```json
{"action":"ping"}
{"action":"login","username":"admin","password":"IHR_PASSWORT"}
{"action":"whoami"}
{"action":"list_users"}
{"action":"create_user","username":"gast","password":"GeheimPasswort123","rights":{"READ":true,"ANSICHT":true},"count_pass":5,"count_limit":15,"expire":"2027-12-31T23:59:59Z"}
{"action":"edit_user","username":"gast","lock_user":true}
{"action":"unlock_user","username":"gast"}
{"action":"delete_user","username":"gast"}
{"action":"logout"}
```

Antworten haben die Form `{"ok":true,"data":...}` bzw. `{"ok":false,"error":"..."}`.
`ping` und `login` benötigen keine Anmeldung; alle Änderungen und `list_users` erfordern `ADMIN`. In sämtlichen Antworten werden Salz/Passworthash ausgelassen.

**Sicherheitshinweis:** Das lokale JSON-Protokoll verwendet **keine TLS-Verschlüsselung**. Bei Bindung an eine LAN-Adresse kann das Passwort beim Login unverschlüsselt über das Netz übertragen werden. Für externe Verbindungen ist ein **TLS-Proxy oder VPN mit geeigneter Zugriffskontrolle** zwingend zu empfehlen; eine integrierte TLS-Authentifizierung ist noch nicht implementiert. Es ist noch **kein vollwertiger Borland-BDE-Protokollserver**: DBF-Tabellenfreigaben, Transaktionen, SQL, Indizes und Record Locks für externe Tabellen sind nicht implementiert. Die Berechtigungen sind vorbereitet, müssen aber bei künftigen DBF-Operationen serverseitig durchgesetzt werden.

## Testen

```powershell
py -3 -m unittest discover -s tests -v
py -3 client_example.py
```

Die Kernlogik läuft ohne Qt5 unter Linux. Mit Version 0.2.0 wurden Linux-PBKDF2, DBF-Dateirechte, ein zweiter konkurrierender Linux-Prozess, die Plattformauswahl und das Kommando `--check-platform` getestet. Die Windows-Bcrypt-API und die Qt5-GUI unter beiden Betriebssystemen müssen zusätzlich **auf den Zielsystemen** getestet werden. Tests eines Windows-Backends mit Mocks ersetzen keinen nativen Windows-Test.

## Plattformübersicht (v0.2.0)

| Merkmal | Windows | Linux |
| --- | --- | --- |
| OS-Erkennung | `platform.system()` → `Windows` | `platform.system()` → `Linux` |
| Passwort-API | `bcrypt.dll` / Windows CNG | OpenSSL über `hashlib.pbkdf2_hmac` |
| PBKDF2-Ausgabe | SHA256 / UTF-8 / 16-Byte-Salz / 32-Byte-Hash | identisch |
| DBF-Format | dBASE III | identisch |
| DBF-Handle | `CreateFileW`, ShareMode=0 (erzwungen) | `fcntl.flock` (advisory) |
| Linux-Dateirechte | – | `0600` / neue Zielordner `0700` |
| Verwaltung | PyQt5 | PyQt5 |
| Standardordner | `%LOCALAPPDATA%` | `$XDG_DATA_HOME` oder `~/.local/share` |

**Migration:** Es ist keine Datenkonvertierung erforderlich. Für eine Übernahme die `users.dbf` bei **gestopptem** Quellserver sichern und beim gestoppten Zielserver im gewünschten Datenverzeichnis ablegen. Erst danach den Zielserver starten. Eine gleichzeitig von mehreren Systemen verwendete DBF-Datei (Netzlaufwerk/NFS/SMB) ist **nicht unterstützt**; beide Betriebssysteme verwenden unterschiedliche Sperrmechanismen.

## Wichtige Betriebsgrenzen

* Das Format ist dBASE-III-kompatibel, die Speicherung erfolgt direkt in derselben exklusiv geöffneten Datei. **Bei Stromausfall während einer DBF-Aktualisierung besteht Beschädigungsrisiko**; gesicherte Backups im Ruhezustand erstellen. Journal / Crash-Recovery wären ein nächster Schritt.
* Die DBF ist **nicht vollständig verschlüsselt**: Rechte, Benutzernamen und Hashes sind für Berechtigte bei abgeschaltetem Server lesbar. Unter Windows den Zielordner durch restriktive NTFS-ACLs absichern; unter Linux mittels dediziertem Benutzerkonto und Verzeichnisrechten `0700`.
* Dies ist eine erste, nicht gehärtete Implementierung. Für produktiven Mehrbenutzer- oder Netzwerkbetrieb: Windows-Service mit separatem Dienstkonto, ACLs, TLS/mTLS oder Named Pipes mit Authentisierung, Protokoll-Audit, Datenbank-Journaling und Rechteprüfung auf jede Tabellenoperation ergänzen.

## Client-Ausgabe (v0.1.1)

`client_example.py` gibt bei normaler Anmeldung **nur die `login`-Antwort** aus.
Die früher direkt anschließende `whoami`-Abfrage gab dieselben Benutzerdaten nochmals aus.
`ping`, `whoami` und `list_users` werden jetzt **nur auf Anforderung** gesendet und angezeigt:

```powershell
py -3 client_example.py
py -3 client_example.py --ping
py -3 client_example.py --whoami
py -3 client_example.py --list-users
```

Der Server selbst antwortet weiterhin mit genau einer JSON-Zeile je gültiger Anfrage.
Auch ein `logout` wird beantwortet, die Antwort wird im Beispielclient jedoch nicht ausgegeben.
Dies ist eine Änderung **nur am Testclient**, das Serverprotokoll und vorhandene Clients bleiben kompatibel.

## Änderungen v0.2.0 (Windows + Linux)

* Neue zentrale OS-Auswahl in `pythonbde/platform_support.py` über `platform.system()`.
* Linux ist ein explizit unterstützter Kryptografie-Backend-Pfad, nicht mehr nur Entwicklungs-Fallback.
* Linux-DBF: `flock` (nonblocking), `chmod 0600`, symbolische Datei-Links bei Öffnung abweisen.
* Plattformabhängige Standardpfade, `start_linux.sh`, CLI `--check-platform`.
* Qt5-Fenstertitel zeigt die aktive Plattform und das Passwort-Backend.
* JSON-Lines-Protokoll, Benutzerrechte, Felder, Ports und Client-Ausgaben aus v0.1.1 bleiben unverändert.


### User-Manager: Statusrahmen (Version 0.3.1)

Das rechte Eigenschaftspanel hat einen **3 Pixel** breiten farbigen Rahmen:
- **Rot:** Administrator (`ADMIN=True`).
- **Grün:** Normaler Benutzer (`ADMIN=False`).
- **Gelb:** `LOCKUSER=True` oder eine noch aktive automatische Sperre (`LOCKUNTIL` in der Zukunft), **auch bei Administratoren**. Gelb besitzt Vorrang.

Ein nicht ausgewählter Datensatz verwendet einen transparenten Rahmen. Beim
Bearbeiten der beiden Checkboxen `Admin` bzw. `Lock User` ändert sich die
Rahmenfarbe sofort als **Vorschau**. Erst `Save User` übernimmt die Änderungen.
Eine abgelaufene `LOCKUNTIL`-Sperre schaltet automatisch zurück auf Rot bzw.
Grün. `EXPIRE` wird unverändert als eigene Kontogültigkeitsregel behandelt
und stellt keine `LOCKUSER`-Sperre dar.
