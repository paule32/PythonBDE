# PythonBDE Win32 Crash Watchdog (MinGW32 / MinGW64)

Der Watchdog ist ein **eigenständiger C++-Prozess**, kein Qt-Fenster und keine Python-C-Erweiterung. Server und RPC-Client starten ihn unter Windows **vor dem ersten PyQt5-Import**. Er überwacht ausschließlich die PID der ihn gestarteten Anwendung. Mehrere PythonBDE-Instanzen können parallel jeweils einen eigenen Watchdog haben. Derselbe PID wird durch einen Win32-Mutex nicht mehrfach überwacht.

## Konsolenloser GUI-Start in v0.6.6

Beim automatischen MinGW-Build startet PythonBDE die externen `g++`-Aufrufe mit `CREATE_NO_WINDOW` und versteckter Startkonsole. Die GUI-EXE des Watchdogs erhält dagegen kein `SW_HIDE`, damit sie ihren Win32-EDIT-Fehlerdialog nach einem Absturz weiterhin anzeigen kann. Zum vollständigen konsolenlosen GUI-Start `pythonw.exe server_gui.pyw` bzw. `pythonw.exe rpc_client_gui.pyw` verwenden.

## Korrektur v0.6.5 (GCC 16, MinGW32/MinGW64)

`RECT`-Koordinaten verwenden den Windows-Typ `LONG`. Die vorherigen Aufrufe `std::max(100, rc.right - rc.left)` und `std::max(100, rc.bottom - rc.top)` konnten nicht kompiliert werden, weil `int` und `LONG` unterschiedliche C++-Typen sind. Die Differenzen werden jetzt explizit in `int` umgewandelt.

## Kompilieren

In der **MSYS2 MINGW32**-Umgebung `watchdog\build_mingw32.bat` starten, in der **MSYS2 MINGW64**-Umgebung `watchdog\build_mingw64.bat` starten (aus `cmd.exe` mit der entsprechenden MinGW-`bin` im `PATH` oder direkt mit `cmd.exe /c ...` in der Shell). Alternativ:

```sh
# MINGW32
 g++ -std=c++17 -O2 -municode -mwindows -static -static-libgcc -static-libstdc++ \
    -o bin/pythonbde_watchdog_x86.exe pythonbde_watchdog.cpp -lshell32 -luser32

# MINGW64
 g++ -std=c++17 -O2 -municode -mwindows -static -static-libgcc -static-libstdc++ \
    -o bin/pythonbde_watchdog_x64.exe pythonbde_watchdog.cpp -lshell32 -luser32
```

Der Build muss jeweils mit einem Compiler der **richtigen Zielarchitektur** erfolgen. Der Startcode bestimmt die passende EXE anhand des laufenden Python-Interpreters (32 oder 64 Bit), nicht anhand des Betriebssystems.

### Automatischer Build beim Start

Wenn die passende `watchdog/bin/pythonbde_watchdog_x86.exe` bzw. `_x64.exe` fehlt, versucht PythonBDE die C++-Quelle bei Programmstart mit dem im `PATH` verfügbaren MinGW-Compiler zu bauen. Das Ergebnis wird unter `%LOCALAPPDATA%\PythonBDE\watchdog\` gespeichert. Falls MinGW nicht installiert ist, läuft PythonBDE weiter und schreibt eine verständliche Meldung ins Fehlerlog. **Ein nicht gebauter Watchdog kann selbstverständlich noch keine Abstürze anzeigen.** Für Installationen ohne Compiler sollten die EXE-Dateien vorab erzeugt und mit ausgeliefert werden.

## Kontrollierter Funktionstest auf Windows

Ohne Serverstart, mit einem separaten Testprozess:

```cmd
python3.15 watchdog\smoke_test.py
```

Der Testprozess beendet sich absichtlich mit Code 33; der Watchdog sollte das EDIT-Fenster anzeigen. Für einen echten nativen Abbruch **nur im separaten Testprozess**:

```cmd
python3.15 watchdog\smoke_test.py --native-abort
```

Bei `--native-abort` wird das Testprogramm absichtlich hart beendet. **Nicht im produktiven PythonBDE-Server ausführen.**

## Überwachung und Fehleranzeige

- Der Python-Prozess installiert Python-`faulthandler` und öffnet vor dem Qt-Import `%LOCALAPPDATA%\PythonBDE\pythonbde_fatal_<PID>.log`.
- Ein Win32-Event bestätigt beim Start, dass der separate Watchdog den Prozess geöffnet hat.
- Der Watchdog wartet mit `WaitForSingleObject()` auf das Prozessende und liest danach den Exit-Code.
- Bei einem unerwarteten Prozessende öffnet er ein natives, mehrzeiliges Win32-EDIT-Fenster mit Scrollbars, Copy Traceback und Close. Python und Qt müssen hierfür **nicht** mehr laufen.
- Exit 0 ist eine normale Beendigung. PythonBDE verwendet 1/2 unter anderem beim abgebrochenen Login; diese Codes werden ohne vorhandenen Fatal-Traceback nicht als nativer Absturz gemeldet. Andere unerwartete Nicht-Null-Codes werden angezeigt.
- Neben dem Fatal-Log werden bis zu 48 KiB vom Ende des normalen `pythonbde_errors.log` angezeigt. Das ist ein Diagnoseauszug, nicht zwingend die auslösende Fehlermeldung.
- Optional kann Windows Error Reporting (WER) einen Minidump **während** des Absturzes schreiben; der Watchdog selbst erzeugt **nach** dem Prozessende keinen nachträglichen Dump. Dafür liegt `enable_wer_dumps.ps1` bei.

## Windows Error Reporting (optional)

`watchdog\enable_wer_dumps.ps1` als Administrator ausführen. Die Einrichtung gilt für alle `python.exe`-/`pythonw.exe`-Prozesse des Rechners, **nicht nur** für PythonBDE. Dump-Dateien liegen standardmäßig unter `%LOCALAPPDATA%\CrashDumps` und können Passwörter oder andere vertrauliche Prozessdaten enthalten. Zum Analysieren eignet sich WinDbg.

## Grenzen

Ein separates Programm kann oft den ungewöhnlichen Exit-Code, einen gespeicherten Python/C-Stack oder einen WER-Dump erkennen. Es kann keinen laufenden, bereits beschädigten Python-Prozess zuverlässig reparieren und keine Garantie bei plötzlichem Stromausfall, Betriebssystemabsturz oder fehlenden Schreibrechten geben. Diese Fassung überwacht Prozessbeendigung, **keine Hänger per Heartbeat**. Der Watchdog zeigt die Diagnose **nach** dem Prozessende und versucht keinen automatischen Neustart.

Zum temporären Deaktivieren (beispielsweise für Tests): `PYTHONBDE_DISABLE_WATCHDOG=1`.
