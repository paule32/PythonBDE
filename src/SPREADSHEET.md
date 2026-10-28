# PythonBDE Sheets – Remote-Tabellenkalkulation (v0.6.0)

Das Modul `pythonbde/remote_apps/spreadsheet.py` ist eine Excel-ähnliche Qt5-Anwendung innerhalb des **bestehenden PythonBDE-RPC-Desktops**. Es wird wie Calculator, Notepad und WordPad über das vom Server signierte `.cpy`-Paket geladen. Der Server enthält weiterhin TLS und die eigene Zertifizierungsstelle aus v0.5.9.

## Start

1. Server und RPC-Client mit **demselben CPython-Minor-Release** starten und TLS wie in `TLS_SETUP.md` einrichten.
2. Den öffentlichen Modul-Signaturschlüssel unverändert auf dem Client vertrauenswürdig hinterlegen (`trusted_module_signing_public.pem`).
3. Mit einem RDP-Benutzer (Windows-95- oder XP-Desktop) anmelden.
4. **Start → Programs → Accessories → PythonBDE Sheets** öffnen. Der Server signiert das Modul und der Client startet es in einem normalen, minimierbaren `QMdiSubWindow` mit Taskleistenbutton.

## Oberfläche

- Excel-artige **Menüs** File/Edit/View/Insert/Format/Data/Formulas/Help, **Format-ToolBar**, Namenfeld (`A1`), **Formelleiste**, editierbares Zellraster mit Spalten A–BL und Zeilen 1–256 (bei Navigation erweiterbar) sowie mehrere **Sheet-Tabs**.
- Bis zu **4.096 Zeilen**, **256 Spalten**, **80.000 belegte Zellen** und **32 Arbeitsblätter** im Engine-Format. Dies sind bewusst kleinere Grenzen als bei Microsoft Excel.
- Editieren, AutoSumme, Undo/Redo, Suchen, Copy/Cut/Paste (TSV), Fill Down/Right (inkl. relativ/absoluter Bezüge wie `$A$1`), Sortierung, Fett/Kursiv/Unterstrichen, Schriftart, Schriftgröße, Ausrichtung, Text-/Füllfarbe, Zahlen-/Währungs-/Prozentdarstellung, einfaches Säulendiagramm.
- Formeln beginnen mit `=`. Zellbezüge wie `=A1*B2`, `=SUM(A1:A10)`, `=Sheet2!A1` oder `='Sales Data'!A1`; Fehlerausgaben `#DIV/0!`, `#REF!`, `#CYCLE!`, `#LIMIT!` usw.

### Implementierte Funktionen

`SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `IF`, `IFERROR`, `ROUND`, `ABS`, `INT`, `SQRT`, `LEN`, `LEFT`, `RIGHT`, `MID`, `CONCAT`, `CONCATENATE`, `AND`, `OR`, `NOT`, `TODAY`, `NOW`.

Operatoren: `+ - * / ^ & = <> < > <= >=`, Klammern, Prozentoperator. Dezimalberechnung nutzt `decimal.Decimal`. Es erfolgt **kein `eval()`** beim Auswerten von Zellformeln.

### Dateien

Alle Öffnen- und Speichern-Dialoge werden über `RemoteFiles.open_dialog()` im **RPC-Arbeitsfenster** geöffnet. Alle Lese-/Schreibzugriffe laufen über den benutzergebundenen virtuellen Dateiservice (`vfs_read`, `vfs_begin`/`vfs_chunk`/`vfs_commit`) und die TLS-Verbindung.

| Format | Import | Export | Hinweise |
|---|---|---|---|
| `.pysheet` | Ja | Ja | Native JSON-basierte Arbeitsmappe; erhält vorhandene Zell-Formatierungen zuverlässig |
| `.xlsx` | Teilweise | Teilweise | OOXML, mehrere Sheets und einfache Formeln; Formatierungsimport und komplexe Excel-Funktionen sind **nicht** vollständig unterstützt |
| `.csv` | Ja | Ja | Nur aktives Sheet, Unicode UTF-8 |
| `.tsv` | Ja | Ja | Nur aktives Sheet |

**Vorhandene komplexe Excel-Dateien niemals ohne Sicherheitskopie überschreiben**: Beim XLSX-Export gehen nicht unterstützte Excel-Merkmale wie VBA, Pivot-Tabellen, externe Datenverbindungen, Zeichnungen, eingebettete Grafiken und komplexe Zellstile verloren.

## Grenzen

Dies ist ein eigenständiger, funktionsfähiger Excel-artiger **erster Entwicklungsstand**, kein 1:1-Klon von Microsoft Excel. Nicht enthalten sind u. a. PivotTables, Makros/VBA, PowerQuery, Diagrammobjekte in XLSX, XLS-Binärdateien, kompletter Funktionskatalog, komplexe Formel-Arrays, kollaborative Bearbeitung und Excel-kompatible Drucklayouts. Grafische Qt5-Laufzeittests müssen auf dem Windows-/Linux-Zielrechner durchgeführt werden; die CI-Tests prüfen den Rechenkern und die signierte Paketübertragung ohne Qt.

**Sicherheit:** Die Module werden mit Ed25519 signiert und über TLS übertragen; signierter Python-Bytecode ist **keine Sandbox**. Nur ein vertrauenswürdiger Herausgeberschlüssel darf als signierende Autorität verwendet werden.

## Tests

```cmd
python3.15 -m unittest tests.test_spreadsheet_060 -v
python3.15 -m unittest discover -s tests
```
