@echo off
REM Regenerate the projections page from current market prices.
REM Invoked by the "FantasyEFL-Refresh" scheduled task; safe to run by hand.
REM Costs 3 Odds API credits per run.
REM
REM The export writes nothing unless the odds fetch succeeds, so a failed run
REM leaves the previous good page in place rather than blanking it.

setlocal
set PROJECT=%~dp0..
set PYTHON=C:\Users\josh\AppData\Local\Python\pythoncore-3.14-64\python.exe
set LOG=%PROJECT%\data\refresh.log

if not exist "%PROJECT%\data" mkdir "%PROJECT%\data"

cd /d "%PROJECT%"
echo [%date% %time%] starting >> "%LOG%"

"%PYTHON%" scripts\export_app_data.py >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] FAILED at export - page left unchanged >> "%LOG%"
    exit /b 1
)

"%PYTHON%" scripts\build_app.py >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] FAILED at build >> "%LOG%"
    exit /b 1
)

"%PYTHON%" scripts\publish_page.py >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] FAILED at publish - built page not live >> "%LOG%"
    exit /b 1
)

echo [%date% %time%] ok >> "%LOG%"
endlocal
