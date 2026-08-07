@echo off
REM Capture a Fantasy EFL feed snapshot and append the outcome to a log.
REM Invoked by the "FantasyEFL-Snapshot" scheduled task; safe to run by hand.
REM Uses the real interpreter path, not the WindowsApps alias, which does not
REM resolve reliably under Task Scheduler.

setlocal
set PROJECT=%~dp0..
set PYTHON=C:\Users\josh\AppData\Local\Python\pythoncore-3.14-64\python.exe
set LOGDIR=%PROJECT%\data
set LOG=%LOGDIR%\snapshot.log

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

cd /d "%PROJECT%"
echo [%date% %time%] starting >> "%LOG%"
"%PYTHON%" -m fantasy_efl.snapshot >> "%LOG%" 2>&1

if errorlevel 1 (
    echo [%date% %time%] FAILED with exit code %errorlevel% >> "%LOG%"
    exit /b 1
)

echo [%date% %time%] ok >> "%LOG%"
endlocal
