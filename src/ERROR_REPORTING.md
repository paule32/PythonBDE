# PythonBDE: Fehlerdiagnose ohne Konsole

Für Windows **PythonBDE Server v0.6.3**. Dieselbe Fehlerbehandlung ist im
`rpc_client.py` aktiv.

## Start vor dem Qt-Import

Beide Python-Einstiege importieren `pythonbde.gui_errors` vor den
PyQt5-Modulen und rufen `install_exception_handler(...)` auf.
`sys.excepthook`, `threading.excepthook` und (falls vorhanden)
`sys.unraisablehook` übernehmen unbehandelte Python-Ausnahmen.
Zusätzlich bleibt Python-`sys.stderr` im Fehlerlog erhalten.

## Fallback-Reihenfolge

1. Wenn `QApplication` vorhanden ist **und der aktuelle Thread der GUI-Thread**
   ist: Qt5-Dialog (`QPlainTextEdit`, Copy Traceback, Close).
2. Windows ohne nutzbare Qt-Oberfläche: **natives Win32-Fenster** mit einem
   mehrzeiligen, schreibgeschützten EDIT-Control, vertikaler/horizontaler
   Scrollbar, Copy-Button und Close-Button. Keine Qt-Abhängigkeit.
3. Wenn selbst das scheitert: native `MessageBoxW` (kurzer Text).
4. Ohne native GUI: Fehlerdatei und eventuell vorhandenes stderr.

Der *vollständige* Python-Traceback wird **vor jedem Dialogversuch** in
`pythonbde_errors.log` geschrieben. Darum geht nichts verloren, auch wenn der
Dialog selbst nicht geöffnet werden kann.

## Datei

Windows: `%LOCALAPPDATA%\PythonBDE\pythonbde_errors.log`
Linux: `~/.local/state/PythonBDE/pythonbde_errors.log`

Bei fehlenden Dateirechten wird das temporäre Systemverzeichnis als Fallback
verwendet. Die Fehlerdatei rotiert ab 5 MiB zu `.log.old`.

## Start ohne Konsole

Starte `server_gui.pyw` oder `rpc_client_gui.pyw` mit `pythonw.exe` oder
verknüpfe `.pyw` in Windows mit Pythonw. Alternativ:

```cmd
pythonw.exe server.py
pythonw.exe rpc_client.py
```

Wenn die Installation andere Python-Versionen verwendet, explizit den
korrekten Interpreter wählen, z.B. dessen vollständigen `pythonw.exe`-Pfad.

## Grenzen

Keine Garantie bei harten Abstürzen (Access Violation in nativer Bibliothek,
`os._exit`, Kill, Bluescreen). Ausnahmen aus Hintergrundthreads werden nicht
auf einem fremden Qt-Thread durch Qt angezeigt, sondern unter Windows über
den Win32-Fallback, um GUI-Thread-Verstöße zu vermeiden.

## Ab v0.6.4: eigenständiger Crash-Watchdog

Unter Windows kann vor dem Qt-Import ein separater C++-Watchdog (MinGW32/MinGW64) gestartet werden, der einen unerwartet beendeten PythonBDE-Prozess überwacht und im eigenen Win32-EDIT-Fenster Status sowie die letzten Traceback-Logzeilen anzeigt. Die native `faulthandler`-Ausgabe wird unter `%LOCALAPPDATA%\PythonBDE\pythonbde_fatal_<PID>.log` gespeichert. Der Watchdog kann den beendeten Prozess nicht wiederherstellen. Bei normalem Beenden gibt es keine Meldung.

Die bestehende Python-Exception-Behandlung bleibt unverändert. Build, Einrichtung und WER-Minidumps: siehe [watchdog/README.md](watchdog/README.md) und die neue Sektion v0.6.4 in [README.md](README.md).
