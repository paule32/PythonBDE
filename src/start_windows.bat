@echo off
cd /d "%~dp0"
::py -3 -m pip install -r requirements.txt
::if errorlevel 1 pause & exit /b 1
python3.15 -m compileall server.py
pythonw3.15 server.py
if errorlevel 1 pause
