# Quellen und Prüfbasis

Historische BDE-Funktionsnamen und Beschreibungen dienen als Referenz; PythonBDE implementiert sie in diesem Stand **nicht**.

1. BDE-API Alphabetische Liste: https://www.nknabe.dk/database/bde32help/functionreferencealphabetical.htm
2. Einführung und C-/Delphi-Syntax: https://www.nknabe.dk/database/bde32help/bdeapifunctions.htm
3. Cursor-Funktionen: https://nknabe.dk/database/bde32help/cursorfunctions.htm
4. Tabellen-Funktionen: https://www.nknabe.dk/database/bde32help/tablefunctions.htm
5. Index-Funktionen: https://www.nknabe.dk/database/bde32help/indexfunctions.htm
6. Datenzugriff: https://www.nknabe.dk/database/bde32help/dataaccessfunctions.htm
7. Environment: https://nknabe.dk/database/bde32help/environmentfunctions.htm
8. Locks: https://www.nknabe.dk/database/bde32help/lockingfunctions.htm
9. Datum/Zeit/Numerik: https://nknabe.dk/database/bde32help/datetimenumberfunctions.htm
10. Historische Schritte: https://www.nknabe.dk/database/bde32help/accessingandupdatingtables.htm
11. DbiInit: https://nknabe.dk/database/bde32help/dbiinit.htm
12. DbiOpenDatabase: https://www.nknabe.dk/database/bde32help/dbiopendatabase.htm
13. DbiOpenTable: https://nknabe.dk/database/bde32help/dbiopentable.htm
14. DbiGetNextRecord: https://nknabe.dk/database/bde32help/dbigetnextrecord.htm
15. DbiCloseSession: https://www.nknabe.dk/database/bde32help/dbiclosesession.htm
16. DbiQAlloc, DbiQPrepare, DbiQExec, DbiQExecDirect, DbiQSetParams: https://nknabe.dk/database/bde32help/dbiqalloc.htm ; https://www.nknabe.dk/database/bde32help/dbiqprepare.htm ; https://nknabe.dk/database/bde32help/dbiqexec.htm ; https://nknabe.dk/database/bde32help/dbiqexecdirect.htm ; https://www.nknabe.dk/database/bde32help/dbiqsetparams.htm
17. Windows `LogonUserW`: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-logonuserw
18. Windows Named Pipes: https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipes
19. Named Pipe Remote-Rejection: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea
20. Delphi BDE-TSession: https://docwiki.embarcadero.com/Libraries/Alexandria/de/Bde.DBTables.TSession_Methods
21. BDE Abkündigung: https://docwiki.embarcadero.com/RADStudio/Sydney/en/Working_with_BDE_Aliases
22. Python 3.15: https://www.python.org/downloads/release/python-3150/

## Präzision

`Dbi...` und `TSession` sind **zwei verschiedene API-Oberflächen**. In der Funktionsliste unten werden nur C-API-Namen mit `Dbi` gesammelt. Wo Originalparameter nicht anhand der Einzelreferenz abgeglichen wurden, werden ausdrücklich nur semantische Parameterklassen oder `noch zu verifizieren` genannt; daraus darf keine binärkompatible Signatur abgeleitet werden.
