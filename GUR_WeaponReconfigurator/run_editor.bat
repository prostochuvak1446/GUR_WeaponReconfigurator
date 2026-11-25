@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0GUR_WeaponEditor.exe" (
    start "" "%~dp0GUR_WeaponEditor.exe" %*
    exit /b 0
)

set "PYEXE="

rem 1) py launcher
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import tkinter" >nul 2>nul
    if not errorlevel 1 set "PYEXE=py"
)

rem 2) common user/system install locations
if not defined PYEXE (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%ProgramFiles%\Python313\python.exe"
        "%ProgramFiles%\Python312\python.exe"
        "%ProgramFiles%\Python311\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if not defined PYEXE if exist "%%~fP" set "PYEXE=%%~fP"
    )
)

rem 3) python on PATH (the Microsoft Store stub fails the import check)
if not defined PYEXE (
    python -c "import tkinter" >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo Python 3 with tkinter was not found.
    echo Install it from https://www.python.org/downloads/ or run:
    echo     winget install -e --id Python.Python.3.12
    echo Then start this file again.
    echo.
    pause
    exit /b 1
)

if /i "%PYEXE%"=="py" (
    py -3 "%~dp0GUR_WeaponEditor.py" %*
) else (
    "%PYEXE%" "%~dp0GUR_WeaponEditor.py" %*
)
if errorlevel 1 pause
