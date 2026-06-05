@echo off
REM CutStock als Windows .exe bauen
REM Voraussetzung: Python 3.12+ installiert

cd /d "%~dp0"

if not exist venv (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt pyinstaller

pyinstaller cutstock_win.spec --noconfirm

echo.
echo ==> dist\CutStock\CutStock.exe ist bereit
pause
