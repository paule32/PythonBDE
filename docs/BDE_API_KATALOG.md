# Original-BDE-API – Funktionskatalog für PythonBDE

Stand: 24. Oktober 2026 · **179 unterschiedliche historisch benannte BDE-Funktionen**, thematisch sortiert.

## Einordnung

Der Katalog stellt die **historische C-API** der Borland Database Engine (`Dbi…`, `DBIResult`/`DBIFN`) dar, **nicht** Methoden von Delphi `TSession` und **nicht** den Implementierungsstand von PythonBDE. Zur Orientierung wurden kurze deutsche Funktionsbeschreibungen formuliert. Die Liste ist ein umfangreicher Arbeitskatalog aus der online dokumentierten API, erhebt aber **keinen Anspruch auf Vollständigkeit aller BDE-Versionen und DLL-Exporte**. Im Zweifel sind Original-Header (`IDAPI.H` / `BDE.INT`) und die jeweilige BDE-Referenz entscheidend.

**Spalten `Parameter / Hinweis`**: Bei **18** separat geprüften Funktionen werden die dokumentierten Argumentnamen in der Tabelle wiedergegeben; die übrigen Einträge enthalten lediglich **thematische Rollen/Beispiele**, **keine verifizierten C-Prototypen**. Alle BDE-Funktionen liefern üblicherweise `DBIResult`; Fehler werden über `DBIERR_...` signalisiert. Historische `TSession`-Methoden wie `AddPassword`, `Open` oder `OpenDatabase` sind eine separate, höherstufige Delphi-Schnittstelle.

**Priorität:** `P1` (Session, Database, Table, Cursor, Data), `P2` (Index, Lock, SQL), `P3` (Kompatibilitäts- und Erweiterungsfunktionen). Geplante PythonBDE-Implementierung benötigt kein idapi32.dll und ist kein 1:1-Binärklon.
## Initialisierung, Sessions und Passwörter

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAddPassword` | Registriert ein Tabellenpasswort für die Sitzung | Passwort/Session-Kontext *(Parameterrollen; Signatur offen)* |
| `DbiCheckRefresh` | Prüft auf Änderungen und aktualisiert Sitzungscursor | Sitzungskontext *(Parameterrollen; Signatur offen)* |
| `DbiCloseSession` | Schließt eine Sitzung und deren Datenbank-, Cursor- und Lock-Ressourcen | hSes **[Einzelsignatur geprüft]** |
| `DbiDllExit` | Bereitet die Freigabe der BDE innerhalb einer DLL vor | DLL/Client-Kontext *(Parameterrollen; Signatur offen)* |
| `DbiDropPassword` | Entfernt registrierte Tabellenpasswörter aus der Sitzung | Passwort-Kontext *(Parameterrollen; Signatur offen)* |
| `DbiExit` | Trennt den Client von der BDE und gibt dessen Ressourcen frei | Client-Kontext *(Parameterrollen; Signatur offen)* |
| `DbiGetCallBack` | Ermittelt eine vorher registrierte Callback-Funktion | Callback-Typ; Ausgabefunktion *(Parameterrollen; Signatur offen)* |
| `DbiGetCurrSession` | Ermittelt die aktuelle Sitzung | Ausgabe-Sitzungshandle *(Parameterrollen; Signatur offen)* |
| `DbiGetSesInfo` | Liefert Umgebungsinformationen der aktuellen Sitzung | Ausgabe-SessionInfo-Struktur *(Parameterrollen; Signatur offen)* |
| `DbiInit` | Initialisiert die BDE-Umgebung und legt die Standardsitzung an | DBIEnv-Zeiger (optional) **[Einzelsignatur geprüft]** |
| `DbiRegisterCallBack` | Registriert eine Callback-Funktion für Sitzung oder Cursor | hCursor; ecbType; iClientData; iCbBufLen; pCbBuf; pfCb **[Einzelsignatur geprüft]** |
| `DbiSetCurrSession` | Setzt eine vorhandene Sitzung als aktuelle Sitzung | Sitzungshandle *(Parameterrollen; Signatur offen)* |
| `DbiSetLockRetry` | Konfiguriert Wiederholungen bei Sperrkonflikten | Sitzung/Zeitangaben *(Parameterrollen; Signatur offen)* |
| `DbiSetPrivateDir` | Setzt das private Verzeichnis für temporäre Dateien | pszDir **[Einzelsignatur geprüft]** |
| `DbiStartSession` | Startet eine zusätzliche BDE-Sitzung | Sitzungsparameter; Ausgabehandle *(Parameterrollen; Signatur offen)* |

## Datenbanken, Aliase und Verzeichnisse

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAddAlias` | Legt einen BDE-Datenbankalias an | Aliasname; Treiber; Parameter; Persistenz *(Parameterrollen; Signatur offen)* |
| `DbiCloseDatabase` | Schließt Datenbank und zugehörige Tabellen | Datenbankhandle *(Parameterrollen; Signatur offen)* |
| `DbiDatabaseFlush` | Schreibt zwischengespeicherte Datenbankänderungen auf Datenträger | Datenbankhandle *(Parameterrollen; Signatur offen)* |
| `DbiDeleteAlias` | Entfernt einen Datenbankalias | Aliasname *(Parameterrollen; Signatur offen)* |
| `DbiGetDatabaseDesc` | Ermittelt den Deskriptor einer Datenbank | Alias/Handle; DBDesc *(Parameterrollen; Signatur offen)* |
| `DbiGetDirectory` | Liefert das aktuelle Arbeitsverzeichnis einer Datenbank | Datenbankhandle; Ausgabepuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetNetUserName` | Liefert den Netzwerkanmeldenamen des Benutzers | Ausgabepuffer *(Parameterrollen; Signatur offen)* |
| `DbiOpenDatabase` | Öffnet eine Datenbank und liefert deren Handle | pszDbName; pszDbType; eOpenMode; eShareMode; pszPassword; iOptFlds; pOptFldDesc; pOptParams; phDb **[Einzelsignatur geprüft]** |
| `DbiOpenDatabaseList` | Liefert eine virtuelle Tabelle verfügbarer Datenbanken | Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenFileList` | Listet zugängliche Dateien/Tabellen eines Verzeichnisses | Datenbank; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenIndexList` | Liefert die Indexliste einer Tabelle | Datenbank; Tabelle; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiSetDirectory` | Ändert das Arbeitsverzeichnis einer Datenbank | Datenbankhandle; Verzeichnispfad *(Parameterrollen; Signatur offen)* |

## Tabellen- und Strukturverwaltung

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiBatchMove` | Überträgt, aktualisiert oder ergänzt Datensätze zwischen Tabellen | Quell-/Zielcursor; Feldzuordnung; Modus *(Parameterrollen; Signatur offen)* |
| `DbiCopyTable` | Kopiert eine Tabelle | Quelle; Ziel; Optionen *(Parameterrollen; Signatur offen)* |
| `DbiCreateInMemTable` | Erstellt eine temporäre Speichertabelle | Tabellendefinition; Cursor *(Parameterrollen; Signatur offen)* |
| `DbiCreateTable` | Legt eine Tabelle mit Feld-/Indexbeschreibungen an | Datenbankhandle; Tabellendeskriptor *(Parameterrollen; Signatur offen)* |
| `DbiCreateTempTable` | Erstellt eine temporäre Tabelle, die mit dem Cursor geschlossen wird | Tabellendefinition; Cursor *(Parameterrollen; Signatur offen)* |
| `DbiDeleteTable` | Löscht eine Tabelle | Datenbank; Tabellenname *(Parameterrollen; Signatur offen)* |
| `DbiDoRestructure` | Ändert die Struktur einer bestehenden Tabelle | Tabellen-Restructure-Deskriptoren *(Parameterrollen; Signatur offen)* |
| `DbiEmptyTable` | Löscht alle Datensätze aus einer Tabelle | Datenbank/Tabellenname *(Parameterrollen; Signatur offen)* |
| `DbiFormFullName` | Ermittelt den vollständigen Tabellennamen | Datenbank; Name/Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetFieldDescs` | Ermittelt Deskriptoren sämtlicher Tabellenfelder | hCursor; Feldanzahl; FLDDesc-Array *(Parameterrollen; Signatur offen)* |
| `DbiGetFieldTypeDesc` | Liefert Beschreibung eines unterstützten Feldtyps | Feldtyp; Treiber *(Parameterrollen; Signatur offen)* |
| `DbiIsTableShared` | Prüft, ob eine Tabelle gemeinsam geöffnet ist | Cursor/Tabelle *(Parameterrollen; Signatur offen)* |
| `DbiMakePermanent` | Wandelt eine temporäre Tabelle in eine permanente um | Cursor; Tabellenziel *(Parameterrollen; Signatur offen)* |
| `DbiOpenFieldTypesList` | Listet unterstützte Feldtypen | Treiber; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenTableTypesList` | Listet unterstützte Tabellenformate | Treiber; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiRenameTable` | Benennt eine Tabelle samt zugehörigen Dateien um | Datenbank; alter/neuer Tabellenname *(Parameterrollen; Signatur offen)* |
| `DbiSortTable` | Sortiert Datensätze in eine Zieltabelle | Quell-/Zieltabelle; Sortierdeskriptor *(Parameterrollen; Signatur offen)* |

## Cursor, Filter und Navigation

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiActivateFilter` | Aktiviert einen registrierten Filter | Cursor; Filterhandle *(Parameterrollen; Signatur offen)* |
| `DbiAddFilter` | Registriert einen Tabellenfilter, noch ohne Aktivierung | Cursor; Filterausdruck *(Parameterrollen; Signatur offen)* |
| `DbiBeginLinkMode` | Aktiviert verknüpften Cursormodus | Cursor; neuer Cursor *(Parameterrollen; Signatur offen)* |
| `DbiCloneCursor` | Erzeugt einen zweiten Cursor mit derselben Ergebnismenge | Quellcursor; Zielhandle *(Parameterrollen; Signatur offen)* |
| `DbiCloseCursor` | Schließt einen Cursor und gibt dessen Ressourcen frei | hCursor *(Parameterrollen; Signatur offen)* |
| `DbiCompareBookMarks` | Vergleicht zwei Bookmark-Positionen | Cursor; zwei Bookmarks *(Parameterrollen; Signatur offen)* |
| `DbiDeactivateFilter` | Deaktiviert einen Filter temporär | Cursor; Filterhandle *(Parameterrollen; Signatur offen)* |
| `DbiDropFilter` | Entfernt einen Filter und gibt Ressourcen frei | Cursor; Filterhandle *(Parameterrollen; Signatur offen)* |
| `DbiEndLinkMode` | Beendet den verknüpften Cursormodus | Cursor; ursprünglicher Cursor *(Parameterrollen; Signatur offen)* |
| `DbiForceRecordReread` | Erzwingt erneutes Lesen eines einzelnen Datensatzes | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiForceReread` | Erzwingt Aktualisieren der Cursorpuffer | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiGetBookMark` | Speichert die aktuelle Cursorposition | Cursor; Bookmark-Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetCursorForTable` | Sucht einen Cursor für eine angegebene Tabelle | Tabelle; Cursorhandle *(Parameterrollen; Signatur offen)* |
| `DbiGetCursorProps` | Liefert Metadaten eines Cursors | Cursor; CURProps *(Parameterrollen; Signatur offen)* |
| `DbiGetExactRecordCount` | Ermittelt die exakte Anzahl der Sätze im Cursor | Cursor; Ausgabeanzahl *(Parameterrollen; Signatur offen)* |
| `DbiGetFilterInfo` | Liest Informationen über einen registrierten Cursorfilter | Cursor; Filterhandle; Info *(Parameterrollen; Signatur offen)* |
| `DbiGetLinkStatus` | Liefert Status einer Master/Detail-Verknüpfung | Cursor; Statuspuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetNextRecord` | Geht zum nächsten Datensatz und liest ihn | hCursor; eLock (optional); pRecBuf (optional); precProps (optional) **[Einzelsignatur geprüft]** |
| `DbiGetPriorRecord` | Geht zum vorigen Datensatz und liest ihn | Cursor; Sperrmodus; Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetProp` | Liest eine Objekt-Eigenschaft | Objekthandle; Property-ID; Ausgabepuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetRecord` | Liest den aktuellen Datensatz | Cursor; Sperrmodus; Datensatzpuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetRecordCount` | Ermittelt die Datensatzanzahl gemäß Cursorstatus | Cursor; Ausgabeanzahl *(Parameterrollen; Signatur offen)* |
| `DbiGetRecordForKey` | Sucht und liest einen Datensatz anhand eines Schlüssels | Cursor; Suchschlüssel; Datensatzpuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetRelativeRecord` | Navigiert um eine relative Datensatzanzahl | Cursor; Offset; Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetSeqNo` | Liefert die aktuelle Sequenznummer | Cursor; Ausgabewert *(Parameterrollen; Signatur offen)* |
| `DbiLinkDetail` | Richtet Master/Detail-Beziehung zwischen Cursorn ein | Master; Detail; Schlüssel *(Parameterrollen; Signatur offen)* |
| `DbiLinkDetailToExp` | Verknüpft Detailcursor mit Master per Ausdruck | Master; Detail; Ausdruck *(Parameterrollen; Signatur offen)* |
| `DbiOpenTable` | Öffnet eine Tabelle und liefert einen Cursor | hDb; pszTableName; pszDriverType; pszIndexName; pszIndexTagName; iIndexId; eOpenMode; eShareMode; exltMode; bUniDirectional; pOptParams; phCursor **[Einzelsignatur geprüft]** |
| `DbiReadBlock` | Liest mehrere aufeinanderfolgende Datensätze in einen Puffer | Cursor; Anzahl; Zielpuffer *(Parameterrollen; Signatur offen)* |
| `DbiResetRange` | Entfernt eine zuvor gesetzte Bereichsbeschränkung | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiSaveChanges` | Schreibt gepufferte Cursoränderungen | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiSetFieldMap` | Legt Feldabbildungen für den Cursor fest | Cursor; Feldmap *(Parameterrollen; Signatur offen)* |
| `DbiSetProp` | Setzt eine Objekt-Eigenschaft | Objekthandle; Property-ID; Wert *(Parameterrollen; Signatur offen)* |
| `DbiSetRange` | Begrenzt die Ergebnismenge auf einen Schlüsselbereich | Cursor; Start-/Endschlüssel *(Parameterrollen; Signatur offen)* |
| `DbiSetToBegin` | Positioniert den Cursor vor den ersten Datensatz | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiSetToBookMark` | Springt zu einer gesicherten Cursorposition | Cursor; Bookmark *(Parameterrollen; Signatur offen)* |
| `DbiSetToCursor` | Übernimmt die Position eines anderen Cursors | Quell-/Zielcursor *(Parameterrollen; Signatur offen)* |
| `DbiSetToEnd` | Positioniert den Cursor hinter den letzten Datensatz | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiSetToKey` | Positioniert mittels Index-Schlüssel | Cursor; Schlüsselbeschreibung *(Parameterrollen; Signatur offen)* |
| `DbiSetToRecordNo` | Positioniert dBASE/FoxPro nach physischer Satznummer | Cursor; Datensatznummer *(Parameterrollen; Signatur offen)* |
| `DbiSetToSeqNo` | Positioniert einen Paradox-Cursor nach Sequenznummer | Cursor; Sequenznummer *(Parameterrollen; Signatur offen)* |
| `DbiUnlinkDetail` | Entfernt eine Master/Detail-Verknüpfung | Cursor *(Parameterrollen; Signatur offen)* |

## Datensätze, Felder und BLOB

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAppendRecord` | Fügt einen Datensatz am Ende der Tabelle an | Cursor; Datensatzpuffer *(Parameterrollen; Signatur offen)* |
| `DbiDeleteRecord` | Löscht/markiert den aktuellen Datensatz als gelöscht | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiFreeBlob` | Gibt BLOB-Handle/Ressourcen frei | Cursor; Blobfeld **[Einzelsignatur geprüft]** |
| `DbiGetBlob` | Liest Daten aus einem BLOB-Feld | Cursor; Blobfeld; Offset; Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetBlobHeading` | Liest die Kopf-/Metadaten eines BLOB-Feldes | Cursor; Blobfeld; Ergebnis *(Parameterrollen; Signatur offen)* |
| `DbiGetBlobSize` | Ermittelt die Größe eines BLOBs in Bytes | Cursor; Blobfeld; Größe *(Parameterrollen; Signatur offen)* |
| `DbiGetField` | Extrahiert einen Feldwert aus dem Datensatzpuffer | Cursor; Feldnummer; Datensatzpuffer; Zielpuffer *(Parameterrollen; Signatur offen)* |
| `DbiInitRecord` | Initialisiert einen Datensatzpuffer mit typgerechten Leerwerten | Cursor; Puffer *(Parameterrollen; Signatur offen)* |
| `DbiInsertRecord` | Fügt einen Datensatz in eine Tabelle ein | Cursor; Datensatzpuffer *(Parameterrollen; Signatur offen)* |
| `DbiModifyRecord` | Schreibt den bearbeiteten Datensatz zurück | Cursor; Datensatzpuffer *(Parameterrollen; Signatur offen)* |
| `DbiOpenBlob` | Öffnet BLOB zur Bearbeitung oder zum Lesen | Cursor; Blobfeld; Modus **[Einzelsignatur geprüft]** |
| `DbiPutBlob` | Schreibt Daten in ein BLOB-Feld | Cursor; Blobfeld; Offset; Daten *(Parameterrollen; Signatur offen)* |
| `DbiPutField` | Setzt einen Feldwert im Datensatzpuffer | Cursor; Feldnummer; Quelle; Datensatzpuffer *(Parameterrollen; Signatur offen)* |
| `DbiTruncateBlob` | Verkürzt einen BLOB-Inhalt | Cursor; Blobfeld; Größe **[Einzelsignatur geprüft]** |
| `DbiUndeleteRecord` | Stellt einen als gelöscht markierten dBASE-/FoxPro-Satz wieder her | Cursor; Datensatzkontext *(Parameterrollen; Signatur offen)* |
| `DbiVerifyField` | Prüft Feldinhalt und Datentyp auf Gültigkeit | Cursor; Feldnummer; Wert *(Parameterrollen; Signatur offen)* |

## Indizes und Schlüssel

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAddIndex` | Erstellt einen neuen Tabellenindex | Datenbank/Tabelle; Indexdefinition *(Parameterrollen; Signatur offen)* |
| `DbiCloseIndex` | Schließt einen Index | Cursor; Indexkennung *(Parameterrollen; Signatur offen)* |
| `DbiCompareKeys` | Vergleicht zwei Schlüssel gemäß aktueller Indexordnung | Cursor; zwei Schlüssel *(Parameterrollen; Signatur offen)* |
| `DbiDeleteIndex` | Entfernt einen Tabellenindex | Datenbank/Tabelle; Indexname *(Parameterrollen; Signatur offen)* |
| `DbiExtractKey` | Ermittelt einen Schlüsselwert aus Satz oder Puffer | Cursor; Puffer; Zielschlüssel *(Parameterrollen; Signatur offen)* |
| `DbiGetIndexDesc` | Liest einen Indexdeskriptor | Cursor; Indexkennung; Deskriptor *(Parameterrollen; Signatur offen)* |
| `DbiGetIndexDescs` | Liefert mehrere Indexdeskriptoren | Cursor; Deskriptorarray *(Parameterrollen; Signatur offen)* |
| `DbiGetIndexForField` | Sucht geeigneten Index für ein Feld | Cursor; Feldnummer *(Parameterrollen; Signatur offen)* |
| `DbiGetIndexSeqNo` | Liefert Indexposition innerhalb einer Liste | Cursor; Indexkennung *(Parameterrollen; Signatur offen)* |
| `DbiGetIndexTypeDesc` | Liefert Beschreibung eines Indextyps | Treiber/Typ *(Parameterrollen; Signatur offen)* |
| `DbiOpenIndex` | Öffnet einen Index zu einem Cursor | Cursor; Indexkennung *(Parameterrollen; Signatur offen)* |
| `DbiOpenIndexTypesList` | Listet unterstützte Indextypen | Treiber; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiRegenIndex` | Baut einen Index neu auf | Cursor; Indexkennung *(Parameterrollen; Signatur offen)* |
| `DbiRegenIndexes` | Reorganisiert veraltete Tabellenindizes | Cursor/Tabelle *(Parameterrollen; Signatur offen)* |
| `DbiSwitchToIndex` | Wählt einen anderen aktiven Index | Cursor; Indexkennung *(Parameterrollen; Signatur offen)* |

## Sperren und Mehrbenutzerbetrieb

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAcqPersistTableLock` | Fordert eine persistente exklusive Tabellensperre an | Datenbank/Tabelle; Lock-Kontext *(Parameterrollen; Signatur offen)* |
| `DbiAcqTableLock` | Fordert eine Tabellensperre an | Cursor; Sperrtyp *(Parameterrollen; Signatur offen)* |
| `DbiIsRecordLocked` | Prüft den Lock-Status des aktuellen Datensatzes | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiIsTableLocked` | Ermittelt aktive Tabellensperren eines Typs | Tabelle; Sperrtyp; Ausgabe *(Parameterrollen; Signatur offen)* |
| `DbiOpenLockList` | Liefert einen Cursor mit vorhandenen Sperren | Cursor/Tabelle *(Parameterrollen; Signatur offen)* |
| `DbiOpenUserList` | Listet Benutzer, die dieselbe Netzwerkdatei nutzen | Datenbank; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiRelPersistTableLock` | Hebt eine persistente Tabellensperre auf | Datenbank/Tabelle *(Parameterrollen; Signatur offen)* |
| `DbiRelRecordLock` | Gibt eine Satzsperre oder alle Sitzungssatzsperren frei | Cursor; Modus *(Parameterrollen; Signatur offen)* |
| `DbiRelTableLock` | Gibt Tabellensperren der Sitzung frei | Cursor; Sperrtyp *(Parameterrollen; Signatur offen)* |

## SQL, QBE und Statement-Handles

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiQAlloc` | Erzeugt ein Statement-Handle | hDb; eQryLang; phStmt **[Einzelsignatur geprüft]** |
| `DbiQExec` | Führt vorbereitete Abfrage aus | hStmt; phCur **[Einzelsignatur geprüft]** |
| `DbiQExecDirect` | Bereitet Abfrage vor und führt sie unmittelbar aus | hDb; eQryLang; pszQuery; phCur **[Einzelsignatur geprüft]** |
| `DbiQFree` | Gibt ein Statement-Handle und dessen Ressourcen frei | hStmt/Zeiger *(Parameterrollen; Signatur offen)* |
| `DbiQGetBaseDescs` | Liefert Quelltabellen/-felder des Resultsets | hStmt; Metadatenpuffer *(Parameterrollen; Signatur offen)* |
| `DbiQInstantiateAnswer` | Persistiert Resultset als Antworttabelle | hStmt; Cursor; Tabellenname; Treiber; Optionen *(Parameterrollen; Signatur offen)* |
| `DbiQPrepare` | Bereitet SQL-/QBE-Abfrage vor | hStmt; pszQuery **[Einzelsignatur geprüft]** |
| `DbiQPrepareProc` | Bereitet einen gespeicherten SQL-Server-Prozeduraufruf vor | Statement; Prozedur *(Parameterrollen; Signatur offen)* |
| `DbiQSetParams` | Bindet Werte an Query-Parameter | hStmt; uFldDescs; paFldDescs; pRecBuf **[Einzelsignatur geprüft]** |
| `DbiQSetProcParams` | Bindet Parameter an gespeicherte SQL-Prozedur | Statement; Parameterdefinition *(Parameterrollen; Signatur offen)* |

## Transaktionen und zwischengespeicherte Updates

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiApplyDelayedUpdates` | Schreibt gesammelte Änderungen in die Datenbank | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiBeginDelayedUpdates` | Schaltet zwischengespeicherte Datensatzänderungen ein | Cursor; Status *(Parameterrollen; Signatur offen)* |
| `DbiBeginTran` | Beginnt eine Datenbanktransaktion | Datenbank; Isolationsmodus; Transaktionshandle *(Parameterrollen; Signatur offen)* |
| `DbiEndDelayedUpdates` | Beendet den Modus verzögerter Aktualisierungen | Cursor *(Parameterrollen; Signatur offen)* |
| `DbiEndTran` | Schließt eine Transaktion ab oder führt Rollback aus | hDb; hXact; eEnd **[Einzelsignatur geprüft]** |
| `DbiGetTranInfo` | Ermittelt Transaktionsstatus und Isolationsniveau | hDb; hXact; pxInfo **[Einzelsignatur geprüft]** |

## Datum, Zeit, Zahlen und Übersetzungen

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAnsiToNative` | Übersetzt ANSI-Text in Treiber-Codepage | Quell-/Zielpuffer; Sprachantreiber *(Parameterrollen; Signatur offen)* |
| `DbiBcdFromFloat` | Konvertiert Fließkommazahl zu BCD | Fließkommazahl; BCD-Ziel *(Parameterrollen; Signatur offen)* |
| `DbiBcdToFloat` | Konvertiert BCD zu Fließkommazahl | BCD-Wert; Ziel *(Parameterrollen; Signatur offen)* |
| `DbiDateDecode` | Zerlegt BDE-Datum in Tag, Monat und Jahr | Datum; Tag; Monat; Jahr *(Parameterrollen; Signatur offen)* |
| `DbiDateEncode` | Kodiert Datumsbestandteile in DBIDATE | Tag; Monat; Jahr; Ausgabedatum *(Parameterrollen; Signatur offen)* |
| `DbiGetDateFormat` | Liest Datumsformat der Sitzung | Session; Formatpuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetNumberFormat` | Liest Zahlenformat der Sitzung | Session; Formatpuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetTimeFormat` | Liest Zeitformat der Sitzung | Session; Formatpuffer *(Parameterrollen; Signatur offen)* |
| `DbiNativeToAnsi` | Übersetzt native Treiberzeichen in ANSI | Quell-/Zielpuffer; Sprachantreiber *(Parameterrollen; Signatur offen)* |
| `DbiSetDateFormat` | Setzt Datumsformat der Sitzung | Session; Formateinstellungen *(Parameterrollen; Signatur offen)* |
| `DbiSetNumberFormat` | Setzt Zahlenformat der Sitzung | Session; Formateinstellungen *(Parameterrollen; Signatur offen)* |
| `DbiSetTimeFormat` | Setzt Zeitformat der Sitzung | Session; Formateinstellungen *(Parameterrollen; Signatur offen)* |
| `DbiTimeDecode` | Zerlegt BDE-Zeit in Komponenten | Zeit; Ausgabekomponenten *(Parameterrollen; Signatur offen)* |
| `DbiTimeEncode` | Kodiert Zeitkomponenten als BDE-Zeitwert | Zeitkomponenten; Ausgabe *(Parameterrollen; Signatur offen)* |
| `DbiTimeStampDecode` | Zerlegt Zeitstempel in Datum und Zeit | Zeitstempel; Ausgabe *(Parameterrollen; Signatur offen)* |
| `DbiTimeStampEncode` | Erzeugt Zeitstempel aus Datum und Zeit | Datum; Zeit; Ergebnis *(Parameterrollen; Signatur offen)* |

## Treiber, Umgebung und Metadaten

| Originalfunktion | Aufgabe | Parameterrollen bzw. original belegte Parameter |
|---|---|---|
| `DbiAddDriver` | Fügt einen Treibereintrag zur BDE-Konfiguration hinzu | Treiber; Konfiguration *(Parameterrollen; Signatur offen)* |
| `DbiDeleteDriver` | Entfernt einen Treibereintrag | Treibername *(Parameterrollen; Signatur offen)* |
| `DbiGetClientInfo` | Liest Informationen zum BDE-Client | Client; Info-Struktur *(Parameterrollen; Signatur offen)* |
| `DbiGetDriverDesc` | Liefert Treibereigenschaften | Treiber; Deskriptor *(Parameterrollen; Signatur offen)* |
| `DbiGetErrorContext` | Liefert erweiterten Kontext zum letzten BDE-Fehler | Fehler-Kontextpuffer *(Parameterrollen; Signatur offen)* |
| `DbiGetErrorEntry` | Liest einen Eintrag aus dem BDE-Fehlerkontext | Fehler-Kontextindex; Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetErrorInfo` | Liefert detaillierte BDE-Fehlerinformationen | Fehler-Infostruktur *(Parameterrollen; Signatur offen)* |
| `DbiGetErrorString` | Wandelt BDE-Fehlercode in Beschreibungstext um | DBIResult-Fehlercode; Ausgabetext *(Parameterrollen; Signatur offen)* |
| `DbiGetLdName` | Liest Codepage-/Sprachantreibernamen der Tabelle | Objektname; Ausgabename *(Parameterrollen; Signatur offen)* |
| `DbiGetLdNameFromDb` | Liest Sprachantreiber zu einer Datenbank | Datenbank; Ausgabename *(Parameterrollen; Signatur offen)* |
| `DbiGetLdObj` | Liefert ein Sprachantreiberobjekt | Cursor; Objekt *(Parameterrollen; Signatur offen)* |
| `DbiGetSysConfig` | Liest BDE-Konfiguration | Konfigurationseintrag *(Parameterrollen; Signatur offen)* |
| `DbiGetSysInfo` | Liest Systemstatus und BDE-Informationen | Systeminfo-Puffer *(Parameterrollen; Signatur offen)* |
| `DbiGetSysVersion` | Liest BDE-Version und Schnittstellenversion | Versionspuffer *(Parameterrollen; Signatur offen)* |
| `DbiLoadDriver` | Lädt den angeforderten Datenbanktreiber | Treibername *(Parameterrollen; Signatur offen)* |
| `DbiOpenCfgInfoList` | Liest Konfigurationsknoten als Cursor | Konfigurationspfad; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenDriverList` | Listet verfügbare Treiber | Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenFunctionArgList` | Listet Parameter einer Datenquellenfunktion | Datenbank; Funktion; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenFunctionList` | Listet Datenquellenfunktionen | Datenbank; Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenLdList` | Listet Sprach-/Sortiertreiber | Listen-Cursor *(Parameterrollen; Signatur offen)* |
| `DbiOpenTableList` | Listet Tabellen einer Datenbank | hDb; bExtended; bSystem; pszWild; phCur **[Einzelsignatur geprüft]** |

## Wichtige, separat geprüfte Originalsignaturen

Dies sind **BDE-Originalargumentnamen** (historische C-Syntax in Kurzform, keine Python-API):

```c
DBIResult DBIFN DbiInit(pEnv);
DBIResult DBIFN DbiOpenDatabase(pszDbName, pszDbType, eOpenMode,
    eShareMode, pszPassword, iOptFlds, pOptFldDesc, pOptParams, phDb);
DBIResult DBIFN DbiOpenTable(hDb, pszTableName, pszDriverType,
    pszIndexName, pszIndexTagName, iIndexId, eOpenMode, eShareMode,
    exltMode, bUniDirectional, pOptParams, phCursor);
DBIResult DBIFN DbiGetNextRecord(hCursor, eLock, pRecBuf, precProps);
DBIResult DBIFN DbiCloseSession(hSes);
DBIResult DBIFN DbiQAlloc(hDb, eQryLang, phStmt);
DBIResult DBIFN DbiQPrepare(hStmt, pszQuery);
DBIResult DBIFN DbiQSetParams(hStmt, uFldDescs, paFldDescs, pRecBuf);
DBIResult DBIFN DbiQExec(hStmt, phCur);
DBIResult DBIFN DbiQExecDirect(hDb, eQryLang, pszQuery, phCur);
DBIResult DBIFN DbiEndTran(hDb, hXact, eEnd);
```

**Hinweis:** Die Referenz verwendet `DBIFN` und Typen wie `hDBIDb`, `hDBICur`, `hDBIStmt`, `DBIOpenMode`, `DBIShareMode`, `XLTMode`; aus diesen schematischen Kurzsignaturen dürfen **keine konkreten ctypes-ABI-Bindings** ohne Headerabgleich erstellt werden.

## Typischer Originalablauf

1. `DbiInit` → Umgebung initialisieren.
2. `DbiOpenDatabase` → Datenbank/Verzeichnis bzw. Alias öffnen.
3. `DbiOpenTable` → Tabellen-Cursor öffnen.
4. `DbiGetCursorProps` + `DbiGetFieldDescs` → Puffer/Felder ermitteln.
5. `DbiGetNextRecord` + `DbiGetField` → Sätze/Felder lesen.
6. Optional: `DbiPutField`/`DbiModifyRecord`, `DbiAcqTableLock`, `DbiBeginTran` und `DbiEndTran`.
7. `DbiCloseCursor` → `DbiCloseDatabase` → `DbiExit`.

Für SQL stattdessen oder zusätzlich: `DbiQAlloc` → `DbiQPrepare` → `DbiQSetParams` → `DbiQExec` → `DbiQFree`; für direkte SQL-Queries `DbiQExecDirect`.

## PythonBDE-Priorisierung

- **MVP:** Session anlegen/beenden, lokale DBF-Tabelle öffnen, Cursor navigieren, Feld lesen, eingeschränkte Benutzerrechte, Fehlercodes.
- **Danach:** Sperren, Schreiben, Indexe, SQL-SELECT, sichere Mehrbenutzerverwaltung.
- **Später:** BLOB/Memo/Transaktionen, Kompatibilität weiterer dBASE-/Paradox-Varianten, zusätzliche Originalfunktionen.

## Referenzen

Siehe [QUELLEN.md](QUELLEN.md). Primäre historische Funktionsliste: https://www.nknabe.dk/database/bde32help/functionreferencealphabetical.htm
