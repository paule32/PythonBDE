# Sicherheitsleitlinien

- Standardmäßig **nur lokale IPC**, kein TCP-/UDP-Listener.
- Windows: Named Pipe mit DACL und `PIPE_REJECT_REMOTE_CLIENTS`; Identität mit geschütztem Client-Token prüfen, niemals Client-Angaben über Benutzername/PID unbesehen vertrauen.
- Linux: Unix-Domain-Socket mit restriktiven Zugriffsrechten, Peer-Credentials, PAM zur Passwortprüfung; `/etc/passwd` allein authentifiziert keine Benutzer.
- Der Dienst läuft unter minimal erforderlichen Dateisystemrechten. Zugelassene DBF-Wurzelverzeichnisse durch Admin konfigurieren.
- Keine Passwörter, SID-Geheimnisse oder Session-Token in Logdateien, Konfiguration, Quellcode oder Git.
- Session-IDs zufällig und nicht als alleinige Berechtigung verwenden. Handle-Zugriffe an Authentisierung und Sitzung binden.
- Qt5-Anmeldedialog gehört in den interaktiven Benutzerprozess, nicht in den Windows-Service.
- `Custom __login__`: `TRUE`/`FALSE` entscheidet über die Anwendungsanmeldung; der Server erzwingt trotzdem seine ACLs. Keine beliebige Codeausführung im Dienst.
- Versionierte IPC-Nachrichten, harte Größen-/Zeitlimits, Input-Validierung, Audit und Rate-Limit von Fehlanmeldungen.
- GitHub-Repository zuerst privat erstellen und erst nach Review öffentlich schalten, wenn gewünscht.
