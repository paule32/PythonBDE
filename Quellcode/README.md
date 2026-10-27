# PythonBDE – TLS-Quellcodebeispiele für PyQt5

Diese ZIP enthält **ausführbare, eigenständige Beispiele**, keine bereits
vollständig in PythonBDE v0.5.7 integrierte TLS-Version. Der eigentliche
Benutzer-, DBF- und RPC-Server wurde bewusst nicht geändert.

## Inhalte

- `tls_server_demo.py`: Qt5 `QTcpServer` + `QSslSocket`, TLS-Handshake vor RPC-Empfang.
- `tls_client_demo.py`: verifizierender `QSslSocket`-Client mit Zertifikat-/Hostnamenprüfung.
- `framing.py`: JSON-Lines-Begrenzer mit Größenlimit.
- `tests/test_framing.py`: Unit-Tests ohne Qt5.
- `create_test_certificate_windows.bat`, `create_test_certificate_linux.sh`.
- `INTEGRATION.md`: Hinweise zur Übernahme in PythonBDE.

## Windows – Schnellstart

```cmd
py -3 -m pip install -r requirements.txt
create_test_certificate_windows.bat
py -3 tls_server_demo.py --host 127.0.0.1 --port 43650
```

Ein zweites Terminal:

```cmd
py -3 tls_client_demo.py --host 127.0.0.1 --port 43650 --cafile certificates/server.crt
```

## Linux – Schnellstart

```bash
python3 -m pip install -r requirements.txt
bash create_test_certificate_linux.sh
python3 tls_server_demo.py --host 127.0.0.1 --port 43650
# Neues Terminal
python3 tls_client_demo.py --host 127.0.0.1 --port 43650 --cafile certificates/server.crt
```

Test der Zertifikatsprüfung:

```bash
openssl s_client -connect 127.0.0.1:43650 \
  -CAfile certificates/server.crt -verify_ip 127.0.0.1 -verify_return_error
```

Unit-Tests:

```bash
python -m unittest discover -s tests -v
```

## Sicherheit

- **Demo, keine produktive Anwendung**: nur `ping`, keine Anmeldung.
- TLS-Handshake muss abgeschlossen sein, bevor RPC-Daten gesendet werden.
- Zertifikatsfehler werden abgewiesen (`ignoreSslErrors()` wird **nicht** verwendet).
- Die privaten Schlüssel werden niemals in die ZIP aufgenommen.
- Bei anderen Hostnamen oder LAN-IP muss das Testzertifikat mit passendem SAN
  neu erstellt werden. Der private Schlüssel darf nicht an Clients gelangen.
- Die Zertifikatsdatei muss vor dem ersten Kontakt über einen vertrauenswürdigen
  Kanal auf den Client gelangen; sonst ist Vertrauen nicht gesichert.
- Für produktiven Einsatz: echte CA/PKI, Zertifikatsrotation, Firewall und
  mTLS nach Bedarf, TLS auf **allen** Pfaden erzwingen, keine Klartext-Fallbacks.

Das Beispiel benötigt PyQt5 plus eine von PyQt5 unterstützte OpenSSL-Bibliothek.
PyQt5 kann auf manchen Systemen ohne passende OpenSSL-Runtime installiert sein;
dann meldet `QSslSocket.supportsSsl()` `False`.
