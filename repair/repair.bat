@echo off
rem ==========================================================
rem  Galgame Memoir - repair and fallback launcher
rem  This file lives in  repair\  , the project root is its parent.
rem  It checks Python 3.9+ and the deps, installs what is missing,
rem  then starts the app. Normally just run Galgame Manager.exe .
rem  ASCII-only on purpose, and no parentheses inside echo lines
rem  of an if-block, so the cmd parser never chokes.
rem ==========================================================
setlocal
title Galgame Memoir - Repair
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

rem ----- step 1: python exists ? -----
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found. Please install Python 3.9 or newer.
    echo Download: https://www.python.org/downloads/
    echo Important: check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

rem ----- step 2: python version >= 3.9 ? -----
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 9)" >nul 2>nul
if errorlevel 9 (
    echo.
    echo [ERROR] Your Python is older than 3.9, or it is only the Microsoft
    echo Store shortcut, which does not run Python at all. Please upgrade it.
    echo.
    pause
    exit /b 1
)

rem ----- step 3: deps present ? install if missing -----
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
echo Checking runtime environment. First run needs internet, please wait...
python -c "import PySide6, requests, PIL" >nul 2>nul
if errorlevel 1 (
    echo Dependencies missing. Installing PySide6-Essentials / requests / pillow ...
    echo Using Tsinghua mirror for a much faster download...
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install -i %MIRROR% --timeout 30 --retries 5 PySide6-Essentials requests pillow
    if errorlevel 1 (
        echo Mirror failed, trying the default index...
        python -m pip install --timeout 30 --retries 5 PySide6-Essentials requests pillow
    )
    python -c "import PySide6, requests, PIL" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [ERROR] Dependency installation failed. Check your network,
        echo then double-click this file again.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed successfully.
)

rem ----- step 4: launch. pythonw first so no console stays open -----
set "PYW=pythonw.exe"
where pythonw.exe >nul 2>nul
if errorlevel 1 set "PYW=python.exe"
echo Starting the program...
start "" /D "%ROOT%" %PYW% "%ROOT%\src\main.py"
exit /b 0
