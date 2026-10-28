@echo off
setlocal
cd /d "%~dp0"
if not exist "bin" mkdir "bin"
where g++ >nul 2>&1
if errorlevel 1 (
    echo MinGW64 g++ nicht gefunden. In MSYS2 MINGW64-Shell ausfuehren.
    exit /b 1
)
for /f "delims=" %%T in ('g++ -dumpmachine') do set "TARGET=%%T"
echo Target: %TARGET%
echo %TARGET% | findstr /i "x86_64" >nul
if errorlevel 1 (
    echo Falscher Compiler: bitte die passende MSYS2 MinGW-Shell verwenden.
    exit /b 1
)
g++ -std=c++17 -O2 -Wall -Wextra -municode -mwindows -D_WIN32_WINNT=0x0601 -static -static-libgcc -static-libstdc++ -o "bin\pythonbde_watchdog_x64.exe" "pythonbde_watchdog.cpp" -lshell32 -luser32
if errorlevel 1 exit /b 1
echo Fertig: bin\pythonbde_watchdog_x64.exe
