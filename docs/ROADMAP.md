# PythonBDE – Entwicklungsplan

| Stufe | Ergebnis | Verifikationskriterium |
|---|---|---|
| 0 | Historischer BDE-API-Katalog, Anforderungen, eigenständiges Repository | Dokumentation geprüft, GitHub separat angelegt |
| 1 | Python-3.15-Paket, versioniertes IPC-Protokoll, Service-Host | Dienst startet/stoppbar ohne Qt GUI; Healthcheck |
| 2 | OS-gebundene Sessions, UUID und Cleanup | Verbindungsabbruch/Crash räumt alle Locks/Handles auf |
| 3 | Qt5-Login-Dialog, BDE/Windows/Linux/Custom Provider | Fehlanmeldungen, PAM/Windows-Logon, True/False erfolgreich getestet |
| 4 | DBF Lesezugriffe, dBASE-Feldtypen/Codepages | Vergleich mit unabhängig validierten DBF-Testdaten |
| 5 | Mehrbenutzer-Locks und Schreibzugriffe | Konsistenz und Crash-Fälle parallel getestet |
| 6 | SQL SELECT und parametrisierte Ausdrücke | Resultate stimmen mit Testreferenzdaten überein |
| 7 | Memo/Index, Migration/Alias-Tools | Externe Original-DBF-Dateien lesbar ohne Veränderung |
| 8 | Windows-SCM-Service und Qt5-Administration | Lokal-IPC und Remote-Reject, Rechte, Installation/Deinstallation |
| 9 | dBase2Many Client-/WFM-Integration | `__init__`, Session.Open/Close, Login und Eventhandling End-to-End |

## Nichtumfang der ersten Implementierung

Kein Netzwerk-/Internet-Dienst, kein BDE-kompatibler `IDAPI32.DLL` Drop-in, keine vollständige BDE-SQL-Emulation, keine Paradox-/Oracle-/ODBC-Kompatibilität und keine ungetestete native DBF-Transaktion.
