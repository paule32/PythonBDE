# PythonBDE v0.5.8 – TLS für Server und RPC-Client

Diese Version integriert TLS direkt in **`BDEServer`** und **`rpc_client.py`**.
Login, JSONL, `CreateWindow`, RDP-Startmenüs, signierte `.cpy`-Module,
Benachrichtigungen und VFS-Dateioperationen laufen über **einen** verschlüsselten
`QSslSocket`. Kein neues Protokoll und kein TLS-Proxy werden benötigt.

## 1. Vorbereitung (Windows und Linux)

Beide Rechner benötigen Python, PyQt5 mit funktionierender TLS/OpenSSL-Unterstützung
und `cryptography`:

```bash
python -m pip install -r requirements.txt
```

**Vor dem ersten Serverstart** brauchst du ein Zertifikat und den passenden
privaten Schlüssel. Für den Test auf `localhost`:

```bash
python generate_tls_certificate.py
```

Für einen Server im LAN z. B. unter `server1.local`/`192.168.1.10`:

```bash
python generate_tls_certificate.py --dns server1.local --ip 192.168.1.10
```

Das Test-Serverzertifikat wird mit RSA-3072/SHA-256, SAN und 365 Tagen Gültigkeit
erzeugt. Es ist von einer eigenen CA signiert. Die neue Datei `ca.crt` ist
**der Vertrauensanker für alle Clients**. Es wird **nicht** stillschweigend überschrieben. Unter Linux hat
`server.key` Rechte `0600`, unter Windows versucht das Skript eine
NTFS-ACL auf das aktuelle Konto und SYSTEM zu beschränken und bricht bei
ACL-Fehler ab.

**Sicherheitswichtig:** Das selbstsignierte CA-Zertifikat für den ersten Test
muss vor Nutzung auf dem Client über einen **vertrauenswürdigen Weg**
installiert werden. Vergleiche den Fingerprint unabhängig. Eine durch den
unbestätigten Netzwerkserver selbst gelieferte Zertifikatsdatei reicht nicht
für eine sichere Erstverbindung.

```bash
# Server: CA-Fingerprint ausgeben (Client muss genau dieser CA vertrauen)
openssl x509 -in certificates/ca.crt -noout -fingerprint -sha256
```

Kopiere **nur `ca.crt`**, **niemals `server.key` oder `ca.key`**, auf den Client. Der
Client erwartet die Datei standardmäßig im eigenen Verzeichnis
`certificates/ca.crt`; alternativ `--ca-cert PFAD` oder die TLS Certificate
Eingabe in der GUI nutzen. Ein DNS-Name/IP muss exakt einer SAN des Zertifikats
entsprechen.

Für öffentlich erreichbare Server verwende eine richtige CA-Zertifikatskette,
reguläre Zertifikatsrotation und einen privaten Schlüssel, der nur für den
Serverdienst lesbar ist. Das Hilfsskript erstellt ausschließlich Testzertifikate.

## 2. Server starten

```bash
python server.py
```

`Server → Settings` enthält jetzt:

- `Enable TLS` (standardmäßig aktiv),
- `Certificate (.crt)` (Standard: `certificates/server.crt`),
- `Private Key (.key)` (Standard: `certificates/server.key`),
- `Test Certificate`, `Test-Config`, `Save Config`.

Die Werte stehen in `pythonbde.ini` neben dem Programm:

```ini
[Server]
ip = 127.0.0.1
port = 43650

[TLS]
enabled = true
certificate = certificates/server.crt
private_key = certificates/server.key
```

Zum Aktivieren eines neuen Zertifikats muss der bereits laufende Server
**gestoppt und erneut gestartet** werden.

Ohne Zertifikat **verweigert der TLS-Server den Start**. TLS darf nur bei
**expliziter** Einstellung `enabled=false` und Bindung an `127.0.0.1`
deaktiviert werden; der mitgelieferte RPC-Client v0.5.8 verlangt selbst auf
Loopback TLS und fällt nie auf Klartext zurück.

## 3. RPC-Client und Remote Desktop

```bash
python rpc_client.py --host 127.0.0.1 --port 43650 \
    --ca-cert certificates/ca.crt
```

Unter Windows: `python3.15 rpc_client.py --host server1.local --port 43650
--ca-cert C:\\Pfad\\zum\\ca.crt` (der Server muss eine passende SAN besitzen).

Der Client benutzt **nur `QSslSocket`**, prüft die gesamte Zertifikatskette
und den Hostnamen (`VerifyPeer`, `setPeerVerifyName`). Ein `sslErrors` führt
zum Abbruch; `ignoreSslErrors()` wird niemals aufgerufen.

Statusbar: `TLS: Negotiating` → `TLS: TLS 1.2+/TLS 1.3 (Cipher)`; erst danach
wird `hello` gesendet. Nach einer positiven Server-Antwort geht das Passwort
als JSON über die bereits geschützte TLS-Verbindung. Windows Secrets ist für
diesen Weg nicht erforderlich. Der Server behält die Windows-Secrets-Logik
für ältere, ausdrücklich auf Loopback beschränkte Betriebsarten.

`login` → `CreateWindow` → `menu_config` → `load_module` / VFS funktionieren
unverändert. Ein Zertifikatsfehler oder Timeout unterbindet die Anmeldung.

Auch der CLI-Beispielclient **`client_example.py`** benutzt jetzt Python
`ssl` mit Hostname-Prüfung und erfordert `--ca-cert`.

## 4. TLS-Check mit OpenSSL

```bash
openssl s_client -connect 127.0.0.1:43650 \
  -CAfile certificates/ca.crt -verify_ip 127.0.0.1 -verify_return_error
```

Prüfe `Verify return code: 0 (ok)` **und** den Zertifikatnamen, sowie
Fehlschläge mit einem absichtlich falschen Host oder CA-Zertifikat.

**Nicht zur Verschlüsselung gehörend:** UDP-Discovery-Port 43651 sendet
öffentliche Metadaten und ist selbst nicht TLS-geschützt. Signierte `.cpy`
Module behalten ihre separate Ed25519-Verifikation; TLS macht Python-Bytecode
nicht sicher zu einer Sandbox. Der Server speichert Datensätze weiterhin lokal
und muss Dateirechte/Backups gesondert absichern.

## 5. Tests und Grenzen

```bash
python -m unittest discover -s tests -v
```

Die automatisierten Tests laufen ohne Qt: X.509-/Schlüsselprüfung, eine reale
Python-`ssl`-Client/Server-Verbindung inklusive Hostname-Reject, neue TLS-INI,
und die bisherige Server-/RPC-Logik. **Dies ist kein nativer Qt-End-to-End-Test.**
Den tatsächlichen `QSslSocket`-Handshake, die Windows-Zertifikats-ACL und die
Qt5-RDP-Oberfläche musst du auf Windows bzw. Linux zusätzlich prüfen.


## Zertifikatskettenfehler in v0.5.8 beheben (v0.5.9)

Der alte Generator erzeugte ein selbstsigniertes **Server-Leaf** mit `CA=False`,
das der Client irrtuemlich als CA importierte. Qt/OpenSSL kann dies mit
`UnableToGetLocalIssuerCertificate` / "issuer certificate ... not found" ablehnen.

1. Server stoppen. Alten Ordner `certificates` **sicher sichern**; niemals
   existierende Server- oder CA-Schluessel unbemerkt ueberschreiben.
2. Die alten `server.crt` und `server.key` aus dem aktiven Zertifikatsordner
   entfernen (beziehungsweise nach einem sicheren Backup umbenennen).
3. `python generate_tls_certificate.py --dns localhost --ip 127.0.0.1`
   ausfuehren (fuer das LAN stattdessen richtige `--dns`/`--ip` SAN nutzen).
4. Serverkonfiguration weiter auf `certificates/server.crt` und `server.key`
   zeigen lassen. Server neu starten.
5. **Nur `certificates/ca.crt`** zum RPC-Client uebertragen und den CA-Fingerprint
   auf getrenntem vertrauenswuerdigem Kanal bestaetigen. In der GUI
   `TLS Certificate` auf die **CA-Datei**, nicht die Server-Datei setzen.
6. `openssl verify -CAfile certificates/ca.crt certificates/server.crt`
   sowie `openssl s_client -connect 127.0.0.1:43650 -CAfile certificates/ca.crt
   -verify_ip 127.0.0.1 -verify_return_error` testen.

**Schutz:** `ca.key` ist ein CA-Signaturschluessel! Nach Ausstellung vom
Serverrechner entfernen und offline lagern. `ca.crt` darf verteilt werden.
Keine Ausnahmen mit `ignoreSslErrors()` und keine unverschluesselte Fallback-Verbindung.
