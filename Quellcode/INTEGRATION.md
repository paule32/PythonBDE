# Übernahme in PythonBDE v0.5.7 (Implementierungshinweise)

Die vorliegenden Beispiele sind ein **Startpunkt**, kein vollständiger Patch für
die Qt5-Hauptanwendung. In `pythonbde/protocol.py` und `rpc_client.py` ist
weiterhin die folgende Integration vorzunehmen:

1. `BDEServer.listener = QTcpServer(self)` durch einen Listener ersetzen, der
   jede neue TCP-Verbindung in einem `QSslSocket` annimmt und erst nach dem
   `encrypted`-Signal zur bestehenden `BDEServer`-Sitzungsliste hinzufügt.
   Dafür `BDEServer._accepted()` in den eigentlichen Verbindungs-Registrierer
   und die Listener-Akzeptanz aufteilen.
2. Bestehende `readyRead`-Verarbeitung und JSON-RPC-Protokoll beibehalten,
   aber **ausschließlich** für `isEncrypted() == True` aktivieren.
3. Im RPC-Client `QTcpSocket` durch `QSslSocket` ersetzen und
   `connectToHostEncrypted()` aufrufen. Den bisherigen Callback am Signal
   `connected` entfernen; stattdessen die bestehende `_connected()`-Methode
   erst am Signal `encrypted` ausführen. Danach erst `hello` senden.
4. Im Client das vertrauenswürdige CA-/Serverzertifikat und Hostname/SAN
   korrekt prüfen; **niemals** `ignoreSslErrors()` verwenden.
5. `pythonbde.ini` optional um `[TLS] enabled`, `certificate`, `private_key`
   ergänzen. Fehlende/ungültige Schlüssel müssen beim aktiven TLS-Betrieb
   zu einem sicheren Startabbruch führen.
6. Alle sonstigen Verbindungen wie Discovery/UDP separat bewerten:
   UDP-Discovery bleibt damit **nicht TLS-geschützt**. Für untrusted LANs
   sind zusätzliche Authentifizierung und Einschränkungen erforderlich.
7. Tests mit echten Qt5-Sockets durchführen: gültiges Zertifikat, abgelaufenes
   Zertifikat, falscher Hostname, unbekannte CA, TLS-Ausfall, Client-Abbruch,
   2 Clients gleichzeitig, RPC-Anmeldung, Dateiübertragung und Modultransport.

**Wichtig:** PythonBDE verwendet für Remote-Module bereits eigene Signaturen;
diese sind unabhängig von TLS und müssen erhalten bleiben. Eine reine
Transportverschlüsselung ersetzt weder Authentifizierung noch Berechtigungen.
