@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=.qbank-venv"
set "PYTHON_CMD="

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    )
)

if "%PYTHON_CMD%"=="" (
    echo Python 3 was not found.
    echo Please install Python 3 from https://www.python.org/downloads/
    echo Make sure "Add python.exe to PATH" is selected during installation.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating local Python environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Could not create the Python environment.
        pause
        exit /b 1
    )
)

echo Installing required packages...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Could not upgrade pip.
    pause
    exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Could not install required packages.
    pause
    exit /b 1
)

echo Starting 9618 QBank...
echo If the browser does not open automatically, go to http://127.0.0.1:5001
"%VENV_DIR%\Scripts\python.exe" launch_qbank.py

pause
